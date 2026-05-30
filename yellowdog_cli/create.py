#!/usr/bin/env python3

"""
A script to create or update YellowDog resources.
"""

import dataclasses
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import cast

import yellowdog_client.model as model
from dateparser import parse as date_parse
from requests import post, put
from requests.exceptions import HTTPError
from yellowdog_client.common.json import Json
from yellowdog_client.model import (
    AddApplicationResponse,
    AddConfiguredWorkerPoolResponse,
    AddGroupRequest,
    ApiKey,
    Application,
    CreateNamespaceRequest,
    Group,
    GroupRole,
    ImageOsType,
    InternalUser,
    MachineImage,
    MachineImageFamily,
    MachineImageGroup,
    NamespacePolicy,
    RoleScope,
    UpdateGroupRequest,
    User,
)
from yellowdog_client.model.exceptions import InvalidRequestException

from yellowdog_cli.utils.entity_utils import (
    clear_application_caches,
    clear_compute_requirement_template_cache,
    clear_compute_source_template_cache,
    clear_group_caches,
    clear_image_caches,
    get_application_group_summaries,
    get_application_id_by_name,
    get_compute_requirement_template_id_by_name,
    get_compute_source_template_id_by_name,
    get_group_id_by_name,
    get_group_name_by_id,
    get_image_name_or_id,
    get_role_id_by_name,
    get_role_name_by_id,
    get_user_by_name_or_id,
    get_user_groups,
    remove_allowances_matching_description,
)
from yellowdog_cli.utils.interactive import confirmed
from yellowdog_cli.utils.load_resources import load_resource_specifications
from yellowdog_cli.utils.printing import (
    print_error,
    print_info,
    print_json,
    print_warning,
)
from yellowdog_cli.utils.settings import (
    NAMESPACE_PREFIX_SEPARATOR,
    PROP_AUTOSCALING_MAX_NODES,
    PROP_CREDENTIAL,
    PROP_CST_ID,
    PROP_DEFAULT_RANK_ORDER,
    PROP_DESCRIPTION,
    PROP_EFFECTIVE_FROM,
    PROP_EFFECTIVE_UNTIL,
    PROP_GLOBAL,
    PROP_GROUPS,
    PROP_ID,
    PROP_IMAGE,
    PROP_IMAGE_ID,
    PROP_IMAGES_ID,
    PROP_KEYRING_NAME,
    PROP_KEYRINGS,
    PROP_NAME,
    PROP_NAMESPACE,
    PROP_NAMESPACES,
    PROP_OPTIONS,
    PROP_OS_TYPE,
    PROP_RANGE,
    PROP_REQUIREMENT_CREATED_FROM,
    PROP_RESOURCE,
    PROP_ROLE,
    PROP_ROLES,
    PROP_SCOPE,
    PROP_SOURCE,
    PROP_SOURCE_CREATED_FROM,
    PROP_SOURCES,
    PROP_TITLE,
    PROP_TYPE,
    PROP_UNITS,
    PROP_USERNAME,
    RN_ADD_APPLICATION_REQUEST,
    RN_ALLOWANCE,
    RN_APPLICATION,
    RN_CONFIGURED_POOL,
    RN_CREDENTIAL,
    RN_EXTERNAL_USER,
    RN_GROUP,
    RN_IMAGE_FAMILY,
    RN_INTERNAL_USER,
    RN_KEYRING,
    RN_NAMESPACE,
    RN_NAMESPACE_POLICY,
    RN_NUMERIC_ATTRIBUTE_DEFINITION,
    RN_REQUIREMENT_TEMPLATE,
    RN_SOURCE_TEMPLATE,
    RN_STRING_ATTRIBUTE_DEFINITION,
    RN_UPDATE_APPLICATION_REQUEST,
)
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON, main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

CLEAR_CST_CACHE: bool = False  # Track whether the CST cache needs to be cleared
CLEAR_CRT_CACHE: bool = False  # Track whether the CRT cache needs to be cleared
CLEAR_IMAGE_FAMILY_CACHE: bool = (
    False  # Track whether the image caches need to be cleared
)


@main_wrapper
def main():
    create_resources()


def create_resources(resources: list[dict] | None = None, show_secrets: bool = False):
    """
    Create a list of resources. Resources can be supplied as an argument, or
    loaded from one or more files.
    """
    if resources is None:
        resources = load_resource_specifications(creation_or_update=True)
    else:
        resources = deepcopy(resources)  # Avoid overwriting the input argument

    if ARGS_PARSER.dry_run:
        print_info(
            "Dry-run: displaying processed JSON resource specifications. Note:"
            " 'resource' property is removed."
        )

    failed = 0
    for resource in cast(list[dict], resources):  # Keep typing happy
        try:
            resource_type = resource.pop(PROP_RESOURCE)
            # There is potential additional processing for CRTs, CSTs and
            # Allowances; print JSON from within their creation functions
            if ARGS_PARSER.dry_run and resource_type not in [
                RN_ALLOWANCE,
                RN_REQUIREMENT_TEMPLATE,
                RN_SOURCE_TEMPLATE,
            ]:
                print_json(resource)
                continue
        except KeyError:
            print_error(
                f"Missing required '{PROP_RESOURCE}' property in the following resource"
                f" specification: {resource}"
            )
            failed += 1
            continue
        try:
            if resource_type == RN_SOURCE_TEMPLATE:
                create_compute_source_template(resource)
            elif resource_type == RN_REQUIREMENT_TEMPLATE:
                create_compute_requirement_template(resource)
            elif resource_type == RN_KEYRING:
                create_keyring(resource, show_secrets)
            elif resource_type == RN_CREDENTIAL:
                create_credential(resource)
            elif resource_type == RN_IMAGE_FAMILY:
                create_image_family(resource)
            elif resource_type == RN_CONFIGURED_POOL:
                create_configured_worker_pool(resource)
            elif resource_type == RN_ALLOWANCE:
                create_allowance(resource)
            elif resource_type in [
                RN_STRING_ATTRIBUTE_DEFINITION,
                RN_NUMERIC_ATTRIBUTE_DEFINITION,
            ]:
                create_attribute_definition(resource, resource_type)
            elif resource_type == RN_NAMESPACE_POLICY:
                create_namespace_policy(resource)
            elif resource_type == RN_GROUP:
                create_group(resource)
            elif resource_type == RN_APPLICATION:
                create_application(resource)
            elif resource_type == RN_INTERNAL_USER:
                update_user(resource, internal_user=True)
            elif resource_type == RN_EXTERNAL_USER:
                update_user(resource, internal_user=False)
            elif resource_type == RN_NAMESPACE:
                create_namespace(resource)
            else:
                print_error(f"Unknown resource type '{resource_type}'")
                failed += 1
        except Exception as e:
            print_error(f"Failed to create resource: {e}")
            # Allow resource creation to continue, if exceptions were not
            # already caught in the creation functions
            failed += 1

    if failed:
        raise RuntimeError(f"{failed} resource(s) failed to create")


def create_compute_source_template(resource: dict):
    """
    Create or update a Compute Source Template using a resource specification.
    Handles all Source types.
    """
    try:
        namespace = resource[PROP_NAMESPACE]
        source = resource.pop(PROP_SOURCE)  # Extract the Source properties
        source_type = source.pop(PROP_TYPE).split(".")[-1]  # Extract Source type
        name = source[PROP_NAME]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    # Allow image families (etc.) to be referenced by name rather than ID
    global CLEAR_IMAGE_FAMILY_CACHE
    if CLEAR_IMAGE_FAMILY_CACHE:  # Update the IF cache if required
        clear_image_caches()
        CLEAR_IMAGE_FAMILY_CACHE = False

    # Google CSTs use property name 'image' instead of 'imageId'
    image_property_name = (
        PROP_IMAGE_ID
        if source_type
        not in ["GceInstancesComputeSource", "GceInstanceGroupComputeSource"]
        else PROP_IMAGE
    )

    image_id = get_image_name_or_id(
        client=CLIENT,
        image_name_or_id=source.get(image_property_name),
        always_return_ydid=False,
        report_substitutions=True,
    )
    if image_id is not None:
        source[image_property_name] = image_id

    if ARGS_PARSER.dry_run:
        resource[PROP_SOURCE] = source
        _get_model_object(source_type, source)  # Report extras and omissions
        print_json(resource)
        return

    # Create the Compute Source
    compute_source = _get_model_object(source_type, source)

    # Create the Compute Source Template
    compute_source_template = _get_model_object(
        "ComputeSourceTemplate", resource, source=compute_source
    )

    # Prepend the namespace when searching for existing templates
    name = f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{name}"

    # Check for an existing ID
    source_id = get_compute_source_template_id_by_name(CLIENT, name, namespace)
    if source_id is None:
        compute_source = CLIENT.compute_client.add_compute_source_template(
            compute_source_template
        )
        print_info(f"Created Compute Source Template '{name}' ({compute_source.id})")
    else:
        if not confirmed(f"Update existing Compute Source Template '{name}'?"):
            return
        compute_source_template.id = source_id
        compute_source = CLIENT.compute_client.update_compute_source_template(
            compute_source_template
        )
        print_info(
            f"Updated existing Compute Source Template '{name}' ({compute_source.id})"
        )

    global CLEAR_CST_CACHE
    CLEAR_CST_CACHE = True

    if ARGS_PARSER.quiet and compute_source.id is not None:
        print(compute_source.id)


def create_compute_requirement_template(resource: dict):
    """
    Create or update a Compute Requirement Template. Handles all
    Compute Requirement types.
    """
    try:
        type = resource.pop(PROP_TYPE).split(".")[-1]  # Extract type
        name = resource[PROP_NAME]
        namespace = resource[PROP_NAMESPACE]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    # Allow source templates to be referenced by name instead of ID:
    # substitute ID for name
    global CLEAR_CST_CACHE
    if CLEAR_CST_CACHE:  # Update the CST cache if required
        clear_compute_source_template_cache()
        CLEAR_CST_CACHE = False

    # Allow image families to be referenced by name rather than ID
    global CLEAR_IMAGE_FAMILY_CACHE
    if CLEAR_IMAGE_FAMILY_CACHE:  # Update the IF cache if required
        clear_image_caches()
        CLEAR_IMAGE_FAMILY_CACHE = False

    def _get_images_id(image_str: str, context: dict, key: str):
        """
        Helper function to resolve an image ID.
        """
        images_id_ = get_image_name_or_id(
            client=CLIENT,
            image_name_or_id=image_str,
            always_return_ydid=False,
            report_substitutions=True,
        )
        if images_id_ is not None:
            context[key] = images_id_

    # Prepend the namespace when searching for existing templates
    name = f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{name}"

    source_template_substitutions = 0

    # Dynamic templates don't have 'sources'; return '[]'
    for source in resource.get(PROP_SOURCES, []):
        template_name_or_id = source[PROP_CST_ID]
        if get_ydid_type(template_name_or_id) != YDIDType.COMPUTE_SOURCE_TEMPLATE:
            template_id = get_compute_source_template_id_by_name(
                client=CLIENT, name=template_name_or_id, namespace=namespace
            )
            if template_id is None:
                print_error(
                    f"Compute Source Template name '{template_name_or_id}' not found"
                )
                return
            source[PROP_CST_ID] = template_id
            source_template_substitutions += 1

        source_image_id = source.get(PROP_IMAGE_ID)
        if source_image_id is not None:
            _get_images_id(source_image_id, source, PROP_IMAGE_ID)

    if source_template_substitutions > 0:
        print_info(
            f"Replaced {source_template_substitutions} Compute Source Template name(s) with ID(s)"
        )

    images_id = resource.get(PROP_IMAGES_ID)
    if images_id is not None:
        _get_images_id(cast(str, images_id), resource, PROP_IMAGES_ID)

    if ARGS_PARSER.dry_run:
        _get_model_object(type, resource)  # Report omissions, extras, errors
        print_json(resource)
        return

    # Overwrite source dictionaries with ComputeSourceUsage objects for static CRTs
    if resource.get(PROP_SOURCES) is not None:
        resource[PROP_SOURCES] = [
            _get_model_object("ComputeSourceUsage", source)
            for source in resource.get(PROP_SOURCES, [])
        ]

    compute_template = _get_model_object(type, resource)

    # Check for an existing ID
    template_id = get_compute_requirement_template_id_by_name(CLIENT, name)

    if template_id is None:  # Creation
        template = CLIENT.compute_client.add_compute_requirement_template(
            compute_template
        )
        global CLEAR_CRT_CACHE
        CLEAR_CRT_CACHE = True
        print_info(f"Created Compute Requirement Template '{name}' ({template.id})")
        if ARGS_PARSER.quiet:
            print(template.id)
        return

    # Update
    compute_template.id = template_id
    if not confirmed(
        f"Update existing Compute Requirement Template '{name}' ({template_id})?"
    ):
        return
    template = CLIENT.compute_client.update_compute_requirement_template(
        compute_template
    )
    print_info(
        f"Updated existing Compute Requirement Template '{name}' ({template.id})"
    )
    if ARGS_PARSER.quiet:
        print(template.id)


def create_keyring(resource: dict, show_secrets: bool = False):
    """
    Create or delete/recreate a Keyring.
    """
    try:
        name = resource[PROP_NAME]
        description = resource[PROP_DESCRIPTION]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    keyrings: list[model.KeyringSummary] = CLIENT.keyring_client.find_all_keyrings()
    for keyring in keyrings:
        if keyring.name == name:
            if not confirmed(f"Keyring '{name}' already exists: delete and recreate?"):
                return
            CLIENT.keyring_client.delete_keyring_by_name(name)
            print_info(f"Deleted Keyring '{name}'")

    try:
        keyring_response = CLIENT.keyring_client.add_keyring(name, description)
        keyring = keyring_response.keyring
        keyring_password = keyring_response.keyringPassword
        keyring_password = (
            keyring_password
            if ARGS_PARSER.show_keyring_passwords or show_secrets
            else "<REDACTED>"
        )
        print_info(
            f"Created Keyring '{name}' ({keyring.id}): Password = {keyring_password}"  # type: ignore[union-attr]
        )
        if ARGS_PARSER.quiet:
            print(f"{keyring.id} {keyring_password}")  # type: ignore[union-attr]
    except Exception as e:
        print_error(f"Failed to create Keyring '{name}': {e}")
        raise


def create_credential(resource: dict):
    """
    Create or update a Credential.
    """
    try:
        keyring_name = resource[PROP_KEYRING_NAME]
        credential_data = resource[PROP_CREDENTIAL]
        credential_type = credential_data.pop(PROP_TYPE).split(".")[
            -1
        ]  # Extract Source type
        name = credential_data[PROP_NAME]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    credential = _get_model_object(credential_type, credential_data)
    try:
        CLIENT.keyring_client.put_credential_by_name(keyring_name, credential)
        print_info(f"Added Credential '{name}' to Keyring '{keyring_name}'")
    except HTTPError as e:
        print_error(f"Failed to add Credential '{name}' to Keyring '{keyring_name}'")
        resp = e.response
        if resp is not None and resp.status_code == 400:
            print_error(f"{resp.text}")
        elif resp is not None and resp.status_code == 404:
            print_error(f"Keyring '{keyring_name}' not found")
        else:
            print_error(e)
        raise


def create_image_family(resource):
    """
    Create or update an Image Family.
    """
    try:
        family_name = resource[PROP_NAME]
        namespace = resource[PROP_NAMESPACE]
        os_type_str = resource.pop(PROP_OS_TYPE)
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    fq_name = f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{family_name}"

    try:
        os_type = ImageOsType[os_type_str]  # Change to Enum
    except KeyError:
        raise ValueError(
            f"Property '{PROP_OS_TYPE}' has invalid value '{os_type_str}'; valid values are"
            f" {[e.value for e in ImageOsType]}"
        )

    # Start by updating the outer Image Family
    image_family = _get_model_object("MachineImageFamily", resource, osType=os_type)

    # Check for existing Image Family
    try:
        existing_image_family: MachineImageFamily = (
            CLIENT.images_client.get_image_family_by_name(
                namespace=namespace, family_name=family_name
            )
        )  # Raises HTTP 404 Error if not found
        if not confirmed(f"Update existing Machine Image Family '{fq_name}'?"):
            return
        image_family.id = existing_image_family.id
        # This will update the Image Family but not its constituent
        # Image Group/Image resources
        CLIENT.images_client.update_image_family(image_family)
        print_info(
            f"Updated existing Machine Image Family '{fq_name}' ('{image_family.id}')"
        )
        if ARGS_PARSER.quiet:
            print(image_family.id)
    except HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            # This will create the Image Family and all of its constituent
            # Image Group/Image resources
            image_family = _create_image_family(image_family, fq_name)
            print_info(f"Created Machine Image Family '{fq_name}' ({image_family.id})")
            if ARGS_PARSER.quiet:
                print(image_family.id)
            return
        else:
            print_error(f"Failed to create/update Image Family '{fq_name}': {e}")
            raise

    # This is an update, so Image Groups have been ignored
    image_groups: list[MachineImageGroup] = image_family.imageGroups

    # Delete Image Groups that have been removed from
    # the new resource specification
    updated_image_group_names = [image_group.name for image_group in image_groups]
    for existing_image_group in existing_image_family.imageGroups or []:
        if existing_image_group.name not in updated_image_group_names:
            if confirmed(f"Remove existing Image Group '{existing_image_group.name}'?"):
                CLIENT.images_client.delete_image_group(existing_image_group)
                print_info(f"Deleted Image Group '{existing_image_group.name}'")

    # Update Image Groups
    for image_group in image_groups:
        _create_image_group(namespace, image_family, image_group)

    global CLEAR_IMAGE_FAMILY_CACHE
    CLEAR_IMAGE_FAMILY_CACHE = True


def _create_image_group(
    namespace: str, image_family: MachineImageFamily, image_group: MachineImageGroup
):
    """
    Create or update a Machine Image Group.
    """
    # Check for existing Image Group
    try:
        existing_image_group: MachineImageGroup = (
            CLIENT.images_client.get_image_group_by_name(
                namespace=namespace,
                family_name=image_family.name,
                group_name=image_group.name,
            )
        )  # Raises HTTP 404 Error if not found
        if not confirmed(f"Update existing Machine Image Group '{image_group.name}'?"):
            return
        image_group.id = existing_image_group.id
        CLIENT.images_client.update_image_group(image_group)
        print_info(f"Updated existing Machine Image Group '{image_group.name}'")
        if ARGS_PARSER.quiet:
            print(image_group.id)
    except HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            image_group = CLIENT.images_client.add_image_group(
                image_family, image_group
            )
            print_info(f"Created Machine Image Group '{image_group.name}'")
            if ARGS_PARSER.quiet:
                print(image_group.id)
            return
        else:
            print_error(
                f"Failed to create/update Image Group '{image_group.name}': {e}"
            )
            raise

    # This is an update, so Images have been ignored
    images: list[MachineImage] = image_group.images or []

    # Delete Images that have been removed from
    # the new resource specification
    updated_image_names = [image.name for image in images]
    for existing_image in existing_image_group.images or []:
        if existing_image.name not in updated_image_names:
            if confirmed(f"Remove existing Image '{existing_image.name}'?"):
                CLIENT.images_client.delete_image(existing_image)
                print_info(f"Deleted Image '{existing_image.name}'")

    # Update Images
    for image in images:
        # Populate the Image ID (this could be made more efficient)
        for existing_image in existing_image_group.images or []:
            if image.name == existing_image.name:
                image.id = existing_image.id
                break
        _create_image(image, image_group)


def _create_image(image: MachineImage, image_group: MachineImageGroup):
    """
    Create or update a Machine Image.
    """
    try:
        if image.id is not None:  # Existing Image
            if confirmed(f"Update existing Machine Image '{image.name}'?"):
                image = CLIENT.images_client.update_image(image)
                print_info(f"Updated existing Machine Image '{image.name}'")
        else:  # New Image
            image = CLIENT.images_client.add_image(image_group, image)
            print_info(f"Created Machine Image '{image.name}'")
    except InvalidRequestException as e:
        print_error(f"Unable to create/update Image '{image.name}': {e}")
        raise

    if ARGS_PARSER.quiet:
        print(image.id)


def create_configured_worker_pool(resource: dict):
    """
    Create a Configured Worker Pool. There's no API support for update.
    """
    try:
        name = resource[PROP_NAME]
        namespace = resource[PROP_NAMESPACE]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    name = f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{name}"

    try:
        cwp_request = _get_model_object("AddConfiguredWorkerPoolRequest", resource)
        cwp_response: AddConfiguredWorkerPoolResponse = (
            CLIENT.worker_pool_client.add_configured_worker_pool(cwp_request)
        )
        print_info(
            f"Created Configured Worker Pool '{name}' ({cwp_response.workerPool.id})"  # type: ignore[union-attr]
        )
        print_info(
            f"                   Worker Pool Token = '{cwp_response.token.secret}'"  # type: ignore[union-attr]
        )
        print_info(
            "                   Worker Pool Expiry Time = "
            f"{str(cwp_response.token.expiryTime).split('.')[0]}"  # type: ignore[union-attr]
        )
        if ARGS_PARSER.quiet:
            print(cwp_response.workerPool.id)  # type: ignore[union-attr]

    except Exception as e:
        print_error(f"Unable to create Configured Worker Pool '{name}': {e}")
        raise


def create_allowance(resource: dict):
    """
    Create an allowance.
    """
    try:
        original_type = resource.pop(PROP_TYPE)
        type = original_type.split(".")[-1]  # Extract type
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    if type == "SourcesAllowance":
        template_name_or_id = resource.get(PROP_SOURCE_CREATED_FROM)
        if template_name_or_id is not None:
            if get_ydid_type(template_name_or_id) != YDIDType.COMPUTE_SOURCE_TEMPLATE:
                global CLEAR_CST_CACHE
                if CLEAR_CST_CACHE:  # Update the CST cache if required
                    clear_compute_source_template_cache()
                    CLEAR_CST_CACHE = False
                template_id = get_compute_source_template_id_by_name(
                    client=CLIENT,
                    name=cast(str, template_name_or_id),
                    namespace=CONFIG_COMMON.namespace,  # Worth a try if namespace not included in name
                )
                if template_id is None:
                    print_error(
                        f"Compute Source Template name '{template_name_or_id}' not found"
                    )
                    return
                print_info(
                    f"Replaced Source Template name '{template_name_or_id}'"
                    f" with ID {template_id}"
                )
                resource[PROP_SOURCE_CREATED_FROM] = template_id

    elif type == "RequirementsAllowance":
        template_name_or_id = resource.get(PROP_REQUIREMENT_CREATED_FROM)
        if template_name_or_id is not None:
            if (
                get_ydid_type(template_name_or_id)
                != YDIDType.COMPUTE_REQUIREMENT_TEMPLATE
            ):
                global CLEAR_CRT_CACHE
                if CLEAR_CRT_CACHE:  # Update the CRT cache if required
                    clear_compute_requirement_template_cache()
                    CLEAR_CRT_CACHE = False
                template_id = get_compute_requirement_template_id_by_name(
                    client=CLIENT, name=cast(str, template_name_or_id)
                )
                if template_id is None:
                    print_error(
                        f"Compute Requirement Template name '{template_name_or_id}' not found"
                    )
                    return
                print_info(
                    f"Replaced Requirement Template name '{template_name_or_id}'"
                    f" with ID {template_id}"
                )
                resource[PROP_REQUIREMENT_CREATED_FROM] = template_id

    # Datetime string conversion
    def _display_datetime(dt: datetime, canonical: bool = False) -> str:
        if canonical:
            return dt.strftime("%Y-%m-%dT%H:%M:%S%Z%z").rstrip()
        else:
            return dt.strftime("%Y-%m-%d %H:%M:%S %Z%z").rstrip()

    effective_from = resource.get(PROP_EFFECTIVE_FROM)
    if effective_from is not None:
        resource[PROP_EFFECTIVE_FROM] = date_parse(cast(str, effective_from))
        if resource[PROP_EFFECTIVE_FROM] is None:
            raise ValueError(
                f"Unable to parse '{PROP_EFFECTIVE_FROM}' date '{effective_from}'"
            )
        print_info(
            f"Property '{PROP_EFFECTIVE_FROM}' = '{effective_from}' set to "
            f"'{_display_datetime(resource[PROP_EFFECTIVE_FROM])}'"
        )

    effective_until = resource.get(PROP_EFFECTIVE_UNTIL)
    if effective_until is not None:
        resource[PROP_EFFECTIVE_UNTIL] = date_parse(cast(str, effective_until))
        if resource[PROP_EFFECTIVE_UNTIL] is None:
            raise ValueError(
                f"Unable to parse '{PROP_EFFECTIVE_UNTIL}' date '{effective_until}'"
            )
        print_info(
            f"Property '{PROP_EFFECTIVE_UNTIL}' = '{effective_until}' set to "
            f"'{_display_datetime(resource[PROP_EFFECTIVE_UNTIL])}'"
        )

    if ARGS_PARSER.dry_run:
        _get_model_object(type, resource)  # Report extras and omissions
        # Datetime objects must be converted to strings for JSON presentation
        for property_ in [PROP_EFFECTIVE_FROM, PROP_EFFECTIVE_UNTIL]:
            if resource.get(property_) is not None:
                resource[property_] = _display_datetime(
                    resource[property_], canonical=True
                )
        resource[PROP_TYPE] = original_type  # Reinstate property
        print_json(resource)
        return

    description = resource.get(PROP_DESCRIPTION)
    if ARGS_PARSER.match_allowances_by_description:
        # Look for existing Allowances that match the description string
        if description is not None:
            print_info(
                "Checking for and removing existing Allowance(s) matching "
                f"description '{description}'"
            )
            remove_allowances_matching_description(CLIENT, description)

    try:
        allowance = CLIENT.allowances_client.add_allowance(
            _get_model_object(type, resource)
        )
        if description is None:
            print_info(f"Created new Allowance {allowance.id}")
        else:
            print_info(f"Created new Allowance '{description}' ({allowance.id})")
    except Exception as e:
        print_error(f"Unable to create Allowance: {e}")
        raise

    if ARGS_PARSER.quiet and allowance.id is not None:
        print(allowance.id)


def create_attribute_definition(resource: dict, resource_type: str):
    """
    Use the API to create/update user attribute definitions.
    """
    default_rank_order = None
    try:
        name = resource[PROP_NAME]
        title = resource[PROP_TITLE]
        if resource_type == RN_NUMERIC_ATTRIBUTE_DEFINITION:
            default_rank_order = resource[PROP_DEFAULT_RANK_ORDER]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    url = f"{CONFIG_COMMON.url}/compute/attributes/user"
    headers = {"Authorization": f"yd-key {CONFIG_COMMON.key}:{CONFIG_COMMON.secret}"}
    if resource_type == RN_STRING_ATTRIBUTE_DEFINITION:
        payload = {
            # Required
            PROP_TYPE: "co.yellowdog.platform.model.StringAttributeDefinition",
            PROP_NAME: name,
            PROP_TITLE: title,
            # Optional
            PROP_DESCRIPTION: resource.get(PROP_DESCRIPTION),
            PROP_OPTIONS: resource.get(PROP_OPTIONS),
        }
    else:  # RN_NUMERIC_ATTRIBUTE_DEFINITION
        payload = {
            # Required
            PROP_TYPE: "co.yellowdog.platform.model.NumericAttributeDefinition",
            PROP_NAME: name,
            PROP_TITLE: title,
            PROP_DEFAULT_RANK_ORDER: default_rank_order,
            # Optional
            PROP_DESCRIPTION: resource.get(PROP_DESCRIPTION),
            PROP_UNITS: resource.get(PROP_UNITS),
            # Note: Only one of 'range', 'options' can be supplied
            # Allow the API to error-check
            PROP_RANGE: resource.get(PROP_RANGE),
            PROP_OPTIONS: resource.get(PROP_OPTIONS),
        }

    # Attempt attribute creation
    print_info(f"Attempting to create or update Attribute Definition '{name}'")
    response = post(url=url, headers=headers, json=payload)

    if response.status_code == 200:
        print_info(f"Created new Attribute Definition '{name}'")
        return

    if "Attribute already exists" in response.text:
        if not confirmed(f"Update existing Attribute Definition '{name}'?"):
            return

        response = put(url=url, headers=headers, json=payload)
        if response.status_code == 200:
            print_info(f"Updated existing Attribute Definition '{name}'")
            return

    raise RuntimeError(f"HTTP {response.status_code} ({response.text})")


def create_namespace_policy(resource: dict):
    """
    Create or update a namespace policy.
    """
    try:
        namespace_policy = NamespacePolicy(
            namespace=resource[PROP_NAMESPACE],
            autoscalingMaxNodes=resource.get(PROP_AUTOSCALING_MAX_NODES),
        )
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    # Test for existing policy
    try:
        CLIENT.namespaces_client.get_namespace_policy(
            namespace=namespace_policy.namespace
        )
        if not confirmed(
            f"Update existing Namespace Policy '{namespace_policy.namespace}'?"
        ):
            return
    except Exception:
        # Assume it's not found ... 404 from API
        pass

    try:
        CLIENT.namespaces_client.save_namespace_policy(namespace_policy)
    except Exception as e:
        print_error(
            f"Unable to create or update Namespace Policy for '{namespace_policy.namespace}': {e}"
        )
        raise

    print_info(
        f"Created or updated Namespace Policy '{namespace_policy.namespace}' with "
        f"'autoscalingMaxNodes={namespace_policy.autoscalingMaxNodes}'"
    )


@dataclass
class RoleSpecification:
    """
    Class to represent a compact expression of a role.
    """

    id: str
    name: str
    global_: bool | None
    namespaces: set[str] | None


def create_group(resource: dict):
    """
    Create or update a group. Will also add or remove scoped
    roles specified by their names or IDs.
    """
    try:
        name = resource[PROP_NAME]
        description = resource.get(PROP_DESCRIPTION)
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    def get_updated_role_specifications() -> list[RoleSpecification]:
        """
        Helper function to generate the list of supplied role specifications.
        """
        roles_input = resource.get(PROP_ROLES)
        if roles_input is None:
            return []

        role_specifications = []
        for role_item in roles_input or []:
            # Get the role
            role = role_item.get(PROP_ROLE)
            if role is None:
                raise ValueError("Role must have 'role' specified")

            # Get the ID and name of the role
            id_ = role.get(PROP_ID)
            if id_ is None:
                name_ = role.get(PROP_NAME)
                if name_ is None:
                    raise ValueError("Group role must have 'id' or 'name' specified")
                id_ = get_role_id_by_name(CLIENT, name_)
            else:
                name_ = role.get(PROP_NAME)
                if name_ is None:
                    name_ = get_role_name_by_id(CLIENT, id_)

            # Get the scope of the role
            scope = role_item.get(PROP_SCOPE)
            if scope is None:
                raise ValueError(f"Group role '{name_}' must have 'scope' specified")
            global_ = scope.get(PROP_GLOBAL)
            if global_ is None or global_ is False:
                namespaces_ = scope.get(PROP_NAMESPACES)
                if namespaces_ is None:
                    raise ValueError(
                        f"Non-global group role '{name_}' must have 'namespaces' specified"
                    )
                namespace_names = []
                for namespace_ in namespaces_:
                    namespace_name = namespace_.get(PROP_NAMESPACE)
                    if namespace_name is None:
                        raise ValueError(
                            f"Namespace applied to role '{name_}' "
                            "must have 'namespace' property"
                        )
                    namespace_names.append(namespace_name)

                # Construct the role specification & add to the list
                if not namespace_names:
                    raise ValueError(
                        f"Non-global role '{name_}' must have at least one namespace scope"
                    )
                role_specifications.append(
                    RoleSpecification(
                        id=cast(str, id_),
                        name=cast(str, name_),
                        global_=False,
                        namespaces=set(namespace_names),
                    )
                )
            else:
                role_specifications.append(
                    RoleSpecification(
                        id=cast(str, id_),
                        name=cast(str, name_),
                        global_=True,
                        namespaces=None,
                    )
                )

        return role_specifications

    def add_or_update_roles(
        group_id_: str, role_specifications: list[RoleSpecification]
    ):
        """
        Helper function to add/update a list of roles.
        """
        for role_spec in role_specifications:
            CLIENT.account_client.add_role_to_group(
                group_id_,
                role_spec.id,
                RoleScope(cast(bool, role_spec.global_), role_spec.namespaces),
            )
            if role_spec.global_:
                print_info(f"Added/updated role '{role_spec.name}' with global scope")
            else:
                ns_list_quoted = [f"'{ns}'" for ns in role_spec.namespaces or []]
                print_info(
                    f"Added/updated role '{role_spec.name}' scoped to "
                    f"namespace(s): {', '.join(ns_list_quoted)}"
                )

    def remove_roles(group_id_: str, role_specifications: list[RoleSpecification]):
        """
        Helper function to remove a list of roles.
        """
        for role_spec in role_specifications:
            CLIENT.account_client.remove_role_from_group(
                group_id_,
                role_spec.id,
            )
            print_info(f"Removed role '{role_spec.name}'")

    def get_roles_to_remove(
        existing_roles: list[GroupRole], new_roles: list[RoleSpecification]
    ) -> list[RoleSpecification]:
        """
        Helper function to determine the roles to be removed.
        """
        existing_role_specifications = [
            RoleSpecification(
                id=cast(str, role.role.id),
                name=cast(str, role.role.name),
                global_=role.scope.global_,
                namespaces=(
                    None
                    if role.scope.namespaces is None
                    else {ns.namespace for ns in role.scope.namespaces}
                ),
            )
            for role in existing_roles
        ]
        # Select roles to remove
        return [
            role_spec
            for role_spec in existing_role_specifications
            if role_spec.name not in [role_spec.name for role_spec in new_roles]
        ]

    def add_group() -> Group:
        """
        Helper function to add a new group.
        Return the ID of the newly created group.
        """
        group_: Group = CLIENT.account_client.add_group(
            AddGroupRequest(name=name, description=description)
        )
        print_info(f"Created Group '{group_.name}' ({group_.id})")
        clear_group_caches()
        return group_

    def update_group(group_id_: str) -> Group | None:
        """
        Helper function to update an existing group, including updating
        its roles.
        """
        if not confirmed(f"Update Group '{name}' ({group_id_})?"):
            return None
        group_: Group = CLIENT.account_client.update_group(
            group_id_, UpdateGroupRequest(name=name, description=description)
        )
        print_info(f"Updated Group '{group_.name}' ({group_.id})")
        return group_

    # Main logic
    group_id = get_group_id_by_name(CLIENT, name)
    if group_id is None:  # New group
        group = add_group()
        add_or_update_roles(group.id, get_updated_role_specifications())  # type: ignore[arg-type]
    else:  # Existing group
        group = update_group(group_id)
        if group is not None:
            updated_role_specs = get_updated_role_specifications()
            add_or_update_roles(group_id, updated_role_specs)
            remove_roles(
                group_id, get_roles_to_remove(group.roles or [], updated_role_specs)
            )


def create_application(resource: dict):
    """
    Create or update an application. Will also add or remove groups specified
    by their names or IDs.
    """
    try:
        name = resource[PROP_NAME]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    groups: list[str] = resource.pop(PROP_GROUPS, [])
    keyrings: list[str] = resource.pop(PROP_KEYRINGS, [])
    # Convert group names to IDs
    new_group_ids = set()
    for group_name in groups:
        app_id = get_group_id_by_name(CLIENT, group_name)
        if app_id is None:
            print_warning(f"Group '{group_name}' not found ... ignoring")
        else:
            new_group_ids.add(app_id)

    def grant_keyrings(app_id: str, api_key: ApiKey):
        for keyring_name in keyrings:
            try:
                CLIENT.keyring_client.grant_application_access_to_keyring(
                    keyring_name, app_id, api_key
                )
                print_info(f"Granted Application access to Keyring '{keyring_name}'")
            except Exception as e:
                print_error(
                    f"Failed to grant Application access to Keyring '{keyring_name}': {e}"
                )
                if api_key.id is None:
                    print_warning(
                        "Re-run with '--regenerate-app-keys' to supply a valid API key"
                    )

    def update_groups(app: Application):
        """
        Helper function to add/remove groups from an application.
        """
        current_group_ids = {
            group.id
            for group in get_application_group_summaries(CLIENT, cast(str, app.id))
        }

        if current_group_ids == new_group_ids:
            print_info("No Group additions or deletions required")
            return

        group_ids_to_remove = current_group_ids - new_group_ids
        for group_id in group_ids_to_remove:
            CLIENT.account_client.remove_application_from_group(group_id, app.id)  # type: ignore[arg-type]
            print_info(
                f"Removed Group '{get_group_name_by_id(CLIENT, cast(str, group_id))}' "
                f"from Application ({group_id})"
            )

        group_ids_to_add = new_group_ids - current_group_ids
        for group_id in group_ids_to_add:
            CLIENT.account_client.add_application_to_group(group_id, app.id)  # type: ignore[arg-type]
            print_info(
                f"Added Group '{get_group_name_by_id(CLIENT, group_id)}' "
                f"to Application ({group_id})"
            )

    def show_key_and_secret(api_key: ApiKey):
        """
        Helper function to display the app key and secret.
        """
        print_info(f"Application Key ID     = '{api_key.id}'", override_quiet=True)
        print_info(f"Application Key Secret = '{api_key.secret}'", override_quiet=True)

    def add_application():
        """
        Helper function to add a new application and its groups.
        """
        app_response: AddApplicationResponse = CLIENT.account_client.add_application(
            _get_model_object(RN_ADD_APPLICATION_REQUEST, resource)
        )
        app = app_response.application
        print_info(f"Created Application '{app.name}' ({app.id})")  # type: ignore[union-attr]
        show_key_and_secret(app_response.apiKey)  # type: ignore[arg-type]
        clear_application_caches()
        update_groups(app)  # type: ignore[arg-type]
        if (
            keyrings
            and app_response.apiKey is not None
            and app is not None
            and app.id is not None
        ):
            grant_keyrings(app.id, app_response.apiKey)

    def update_application(app_id: str):
        """
        Helper function to update an existing application, including updating
        its groups.
        """
        if not confirmed(f"Update Application '{name}' ({app_id})?"):
            return

        app: Application = CLIENT.account_client.update_application(
            app_id, _get_model_object(RN_UPDATE_APPLICATION_REQUEST, resource)
        )
        print_info(f"Updated Application '{app.name}' ({app.id})")
        update_groups(app)

        api_key: ApiKey | None = None
        if ARGS_PARSER.regenerate_app_keys:
            print_info("Regenerating Application key and secret")
            api_key = CLIENT.account_client.regenerate_application_api_key(app_id)
            if api_key is None:
                print_error("New API key/secret not returned")
            else:
                show_key_and_secret(api_key)

        if keyrings:
            grant_keyrings(app_id, api_key if api_key is not None else ApiKey())

    # Main logic
    app_id = get_application_id_by_name(CLIENT, name)
    if app_id is None:
        add_application()
    else:
        update_application(app_id)


def update_user(resource: dict, internal_user: bool):
    """
    Update a user specified by name, username or ID. Will also add or remove
    groups specified by their names or IDs.
    """
    name = resource.get(PROP_NAME)
    username = resource.get(PROP_USERNAME)
    id = resource.get(PROP_ID)

    # Check we have a user identity
    if internal_user:
        if not any([username, name, id]):
            raise ValueError(
                f"Expected one of '{PROP_NAME}', '{PROP_USERNAME}', '{PROP_ID}' "
                f"to be defined for resource '{RN_INTERNAL_USER}' ({resource})"
            )
    elif not any([name, id]):
        raise ValueError(
            f"Expected one of '{PROP_NAME}', '{PROP_ID}' to be defined for "
            f"resource '{RN_EXTERNAL_USER}' ({resource})"
        )

    groups: list[str] = resource.pop(PROP_GROUPS, [])
    new_group_ids = set()
    # Convert group names to IDs
    for group_name in groups:
        group_id = get_group_id_by_name(CLIENT, group_name)
        if group_id is None:
            print_warning(f"Group '{group_name}' not found ... ignoring")
        else:
            new_group_ids.add(group_id)

    def update_groups():
        """
        Helper function to add/remove groups from a user.
        """
        current_group_ids = {group.id for group in get_user_groups(CLIENT, user.id)}  # type: ignore[union-attr]

        if current_group_ids == new_group_ids:
            print_info("No Group additions or deletions required")
            return

        if not confirmed(f"Update Groups for User '{username}' ({user.id})?"):  # type: ignore[union-attr]
            return

        group_ids_to_remove = current_group_ids - new_group_ids
        for group_id in group_ids_to_remove:
            CLIENT.account_client.remove_user_from_group(group_id, user.id)  # type: ignore[union-attr]
            print_info(
                f"Removed Group '{get_group_name_by_id(CLIENT, group_id)}' ({group_id})"
            )

        group_ids_to_add = new_group_ids - current_group_ids
        for group_id in group_ids_to_add:
            CLIENT.account_client.add_user_to_group(group_id, user.id)  # type: ignore[union-attr]
            print_info(
                f"Added Group '{get_group_name_by_id(CLIENT, group_id)}' ({group_id})"
            )

    # Main logic: try name, username, then ID if present; check for ID match
    user: User | None = None
    if name is not None:
        user = get_user_by_name_or_id(CLIENT, name)
    if user is None and username is not None:
        user = get_user_by_name_or_id(CLIENT, username)
    if user is not None and id is not None:
        if user.id != id:
            raise ValueError(f"User name and supplied ID do not match ({resource})")
    if user is None and id is not None:
        user = get_user_by_name_or_id(CLIENT, cast(str, id))

    if user is None:
        print_warning(
            f"User not found ({resource}); Users cannot be created using "
            "the CLI, please use the YellowDog Portal"
        )
        return

    username = user.username if isinstance(user, InternalUser) else user.name
    update_groups()
    print_info(f"Actions complete for User '{username}' ({user.id})")


def create_namespace(resource: dict):
    """
    Create a namespace.
    """
    try:
        name = resource[PROP_NAME]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    try:
        namespace_id = CLIENT.namespaces_client.create_namespace(
            CreateNamespaceRequest(namespace=name)
        )
    except Exception as e:
        if "ConflictException" in str(e):
            print_warning(f"Namespace '{name}' already exists")
            return
        else:
            raise RuntimeError(f"Failed to create namespace '{name}' ({e})")

    print_info(f"Created namespace '{name}' ({namespace_id})")

    if ARGS_PARSER.quiet:
        print(namespace_id)


def _get_model_object(class_name: str, resource: dict, **kwargs):
    """
    Return a populated YellowDog model object for the resource.
    Discard unexpected keywords.
    """
    cls = _get_model_class(class_name)
    valid_keys = {f.name for f in dataclasses.fields(cls)}
    unexpected = [k for k in resource if k not in valid_keys and k not in kwargs]
    for key in unexpected:
        print_warning(f"Ignoring unexpected property '{key}'")
        resource.pop(key)

    missing = [
        f.name
        for f in dataclasses.fields(cls)
        if f.name not in resource
        and f.name not in kwargs
        and f.default is dataclasses.MISSING
        and f.default_factory is dataclasses.MISSING
    ]
    if missing:
        raise KeyError(f"Missing expected property '{missing[0]}'")

    # Normalize all values to their JSON-compatible representations so that
    # Json.load can properly structure nested typed fields (e.g. enums,
    # timedeltas, and nested model objects) — necessary because the SDK's
    # proxy now calls Json.dump on every outbound request.
    merged = {}
    for k, v in {**resource, **kwargs}.items():
        if isinstance(v, (str, int, float, bool, type(None))):
            merged[k] = v
        else:
            merged[k] = Json.dump(v)
    return Json.load(merged, cls)


def _get_model_class(class_name: str):
    """
    Return a YellowDog model class using its class name.
    """
    return getattr(model, class_name)


def _create_image_family(
    image_family: MachineImageFamily, fq_name: str
) -> MachineImageFamily:
    """
    Creates a new image family. Only one image group can be added at the time of
    image family creation, so any additional image groups must be added separately.
    """

    # Remove all except the first image group; keep the rest as a separate list
    image_groups = image_family.imageGroups
    if image_groups is not None:
        image_family.imageGroups = image_groups[:1]
        image_groups = image_groups[1:]  # Remaining image groups

    # Create the image family
    try:
        image_family = CLIENT.images_client.add_image_family(image_family)
    except Exception as e:
        raise RuntimeError(f"Failed to create Machine Image Family '{fq_name}': {e}")

    if not image_groups:
        return image_family

    # Create any additional image groups
    for image_group in image_groups:
        try:
            image_group = CLIENT.images_client.add_image_group(
                image_family, image_group
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to add Machine Image Group '{image_group.name}' to "
                f"Image Family '{fq_name}': {e}"
            )

    return image_family


# Entry point
if __name__ == "__main__":
    main()
