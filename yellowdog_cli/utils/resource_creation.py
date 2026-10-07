"""
Creating and updating YellowDog resources from their specifications: the
library behind yd-create, which the Cloud Wizard uses too. It reads no
command-line options: what yd-create's options decide arrives as a
CreateOptions, so a caller that is not yd-create gets the defaults rather
than whatever its own command line happens to hold.

create.py is a thin command over it. That is the general rule: a utility
never imports a command module, so shared work lives in a library like this
one, which the command and any other caller both use.
"""

import dataclasses
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, cast

import yellowdog_client.model as model
from dateparser import parse as date_parse
from requests import Response, post, put
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

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    RN_ADD_APPLICATION_REQUEST,
    RN_ALLOWANCE,
    RN_APPLICATION,
    RN_CONFIGURED_POOL,
    RN_CREDENTIAL,
    RN_EXTERNAL_USER,
    RN_GROUP,
    RN_IMAGE,
    RN_IMAGE_FAMILY,
    RN_IMAGE_GROUP,
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
from yellowdog_cli.utils.entity_utils import (
    allowances_to_remove,
    clear_application_caches,
    clear_compute_requirement_template_cache,
    clear_compute_source_template_cache,
    clear_group_caches,
    clear_image_caches,
    clear_keyring_cache,
    get_application_group_summaries,
    get_application_id_by_name,
    get_compute_requirement_template_id_by_name,
    get_compute_source_template_id_by_name,
    get_group_id_by_name,
    get_group_name_by_id,
    get_image_name_or_id,
    get_keyring_summary_by_name,
    get_role_id_by_name,
    get_role_name_by_id,
    get_user_by_name_or_id,
    get_user_groups,
    remove_allowances,
)
from yellowdog_cli.utils.exit_codes import (
    NotFoundError,
)
from yellowdog_cli.utils.interactive import confirmed
from yellowdog_cli.utils.limits import RAW_REQUEST_TIMEOUT
from yellowdog_cli.utils.load_resources import (
    RESOURCE_SOURCE_DIR,
)
from yellowdog_cli.utils.misc_utils import is_http_not_found, shown_expiry
from yellowdog_cli.utils.output_style import REDACTED_VALUE
from yellowdog_cli.utils.printing import (
    print_dry_run,
    print_info,
    print_json,
    print_quiet_result,
    print_warning,
    user_data_as_shown,
)
from yellowdog_cli.utils.property_names import (
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
)
from yellowdog_cli.utils.provision_utils import resolve_user_data_in_spec
from yellowdog_cli.utils.resource_processing import (
    missing_property,
    process_resources,
)
from yellowdog_cli.utils.results import record, record_resource
from yellowdog_cli.utils.settings import NAMESPACE_PREFIX_SEPARATOR
from yellowdog_cli.utils.type_check import check_dict, check_list
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type


@dataclass(frozen=True)
class CreateOptions:
    """
    What yd-create's options decide, for a run of create_resources().
    """

    dry_run: bool = False
    json_output: bool = False
    match_allowances_by_description: bool = False
    show_keyring_passwords: bool = False
    regenerate_app_keys: bool = False


# The options of the run in progress, set by create_resources() for its
# duration: every creator reads them here rather than having them threaded
# through each call
_OPTIONS: CreateOptions = CreateOptions()


def create_resources(
    ctx: RunContext,
    resources: list[dict],
    options: CreateOptions | None = None,
    show_secrets: bool = False,
):
    """
    Create or update the resources a list of specifications describes, with
    'options' (the defaults when None). The list is not changed.
    """
    global _OPTIONS
    previous, _OPTIONS = _OPTIONS, options or CreateOptions()
    try:
        _create_all(ctx, deepcopy(resources), show_secrets)
    finally:
        _OPTIONS = previous


def _create_all(ctx: RunContext, resources: list[dict], show_secrets: bool) -> None:

    if _OPTIONS.dry_run:
        print_dry_run(
            "Displaying processed JSON resource specifications. Note:"
            " 'resource' property is removed."
        )

    def _process(resource_type: str, resource: dict) -> None:
        # Strip the internal source-dir stamp before any further processing
        # so it never reaches _get_model_object or appears in dry-run output.
        source_dir: str | None = resource.pop(RESOURCE_SOURCE_DIR, None)
        # There is potential additional processing for CRTs, CSTs and
        # Allowances; print JSON from within their creation functions
        if _OPTIONS.dry_run and resource_type not in [
            RN_ALLOWANCE,
            RN_REQUIREMENT_TEMPLATE,
            RN_SOURCE_TEMPLATE,
        ]:
            _show_dry_run_specification(resource_type, resource)
            return
        _create_resource(ctx, resource_type, resource, source_dir, show_secrets)

    # In a dry run, '--json' is the processed specifications, so failures
    # are reported on stderr and in the exit code instead. Whether a
    # specification creates or updates is decided by its creator, after
    # this wording is chosen, so the wording covers both
    process_resources(
        cast(list[dict], resources),
        _process,
        "create or update",
        record_outcomes=not _OPTIONS.dry_run,
    )


def _create_resource(
    ctx: RunContext,
    resource_type: str,
    resource: dict,
    source_dir: str | None,
    show_secrets: bool,
) -> None:
    """
    Create or update one resource, by its type.
    """
    if resource_type == RN_SOURCE_TEMPLATE:
        create_compute_source_template(ctx, resource, source_dir)
    elif resource_type == RN_REQUIREMENT_TEMPLATE:
        create_compute_requirement_template(ctx, resource, source_dir)
    elif resource_type == RN_KEYRING:
        create_keyring(ctx, resource, show_secrets)
    elif resource_type == RN_CREDENTIAL:
        create_credential(ctx, resource)
    elif resource_type == RN_IMAGE_FAMILY:
        create_image_family(ctx, resource)
    elif resource_type == RN_CONFIGURED_POOL:
        create_configured_worker_pool(ctx, resource)
    elif resource_type == RN_ALLOWANCE:
        create_allowance(ctx, resource)
    elif resource_type in [
        RN_STRING_ATTRIBUTE_DEFINITION,
        RN_NUMERIC_ATTRIBUTE_DEFINITION,
    ]:
        create_attribute_definition(ctx, resource, resource_type)
    elif resource_type == RN_NAMESPACE_POLICY:
        create_namespace_policy(ctx, resource)
    elif resource_type == RN_GROUP:
        create_group(ctx, resource)
    elif resource_type == RN_APPLICATION:
        create_application(ctx, resource)
    elif resource_type == RN_INTERNAL_USER:
        update_user(ctx, resource, internal_user=True)
    elif resource_type == RN_EXTERNAL_USER:
        update_user(ctx, resource, internal_user=False)
    elif resource_type == RN_NAMESPACE:
        create_namespace(ctx, resource)
    else:
        raise ValueError(f"Unknown resource type '{resource_type}'")


def _show_dry_run_specification(resource_type: str, resource: dict) -> None:
    """
    Show one processed resource specification in a dry run: printed, or
    under '--json' recorded, so the dry run's document is the array of them.
    The record puts back the 'resource' the loop popped, first, so a mixed
    file's array stays typed; the printed form is unchanged.
    """
    if _OPTIONS.json_output:
        record({PROP_RESOURCE: resource_type, **resource})
    else:
        print_json(user_data_as_shown(resource))


def create_compute_source_template(
    ctx: RunContext, resource: dict, source_dir: str | None = None
):
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
        raise missing_property(e) from e

    # Google CSTs use property name 'image' instead of 'imageId'
    image_property_name = (
        PROP_IMAGE_ID
        if source_type
        not in ["GceInstancesComputeSource", "GceInstanceGroupComputeSource"]
        else PROP_IMAGE
    )

    image_id = get_image_name_or_id(
        client=ctx.client,
        image_name_or_id=source.get(image_property_name),
        always_return_ydid=False,
    )
    if image_id is not None:
        source[image_property_name] = image_id

    # Resolve userDataFile / userDataFiles -> userData
    resolve_user_data_in_spec(source, base_dir=source_dir)

    if _OPTIONS.dry_run:
        resource[PROP_SOURCE] = source
        _get_model_object(source_type, source)  # Report extras and omissions
        _show_dry_run_specification(RN_SOURCE_TEMPLATE, resource)
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
    source_id = get_compute_source_template_id_by_name(ctx.client, name, namespace)
    if source_id is None:
        compute_source = ctx.client.compute_client.add_compute_source_template(
            compute_source_template
        )
        clear_compute_source_template_cache()
        print_info(f"Created Compute Source Template '{name}' ({compute_source.id})")
        record_resource(RN_SOURCE_TEMPLATE, name, compute_source.id, "created")
    else:
        if not confirmed(f"Update existing Compute Source Template '{name}'?"):
            record_resource(RN_SOURCE_TEMPLATE, name, source_id, "skipped")
            return
        compute_source_template.id = source_id
        compute_source = ctx.client.compute_client.update_compute_source_template(
            compute_source_template
        )
        clear_compute_source_template_cache()
        print_info(
            f"Updated existing Compute Source Template '{name}' ({compute_source.id})"
        )
        record_resource(RN_SOURCE_TEMPLATE, name, compute_source.id, "updated")

    if compute_source.id is not None:
        print_quiet_result(compute_source.id)


def create_compute_requirement_template(
    ctx: RunContext, resource: dict, source_dir: str | None = None
):
    """
    Create or update a Compute Requirement Template. Handles all
    Compute Requirement types.
    """
    try:
        type = resource.pop(PROP_TYPE).split(".")[-1]  # Extract type
        name = resource[PROP_NAME]
        namespace = resource[PROP_NAMESPACE]
    except KeyError as e:
        raise missing_property(e) from e

    def _get_images_id(image_str: str, context: dict, key: str):
        """
        Helper function to resolve an image ID.
        """
        images_id_ = get_image_name_or_id(
            client=ctx.client,
            image_name_or_id=image_str,
            always_return_ydid=False,
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
                client=ctx.client, name=template_name_or_id, namespace=namespace
            )
            if template_id is None:
                if _OPTIONS.dry_run:
                    # It may be created by an earlier specification, which
                    # a dry run does not create
                    print_dry_run(
                        f"Compute Source Template '{template_name_or_id}' not found"
                        " (yet): its name is left unresolved"
                    )
                    continue
                raise NotFoundError(
                    f"Compute Source Template name '{template_name_or_id}' not found"
                )
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

    # Resolve userDataFile / userDataFiles -> userData
    resolve_user_data_in_spec(resource, base_dir=source_dir)

    if _OPTIONS.dry_run:
        _get_model_object(type, resource)  # Report omissions, extras, errors
        _show_dry_run_specification(RN_REQUIREMENT_TEMPLATE, resource)
        return

    # Overwrite source dictionaries with ComputeSourceUsage objects for static CRTs
    if resource.get(PROP_SOURCES) is not None:
        resource[PROP_SOURCES] = [
            _get_model_object("ComputeSourceUsage", source)
            for source in resource.get(PROP_SOURCES, [])
        ]

    compute_template = _get_model_object(type, resource)

    # Check for an existing ID
    template_id = get_compute_requirement_template_id_by_name(ctx.client, name)

    if template_id is None:  # Creation
        template = ctx.client.compute_client.add_compute_requirement_template(
            compute_template
        )
        clear_compute_requirement_template_cache()
        print_info(f"Created Compute Requirement Template '{name}' ({template.id})")
        record_resource(RN_REQUIREMENT_TEMPLATE, name, template.id, "created")
        print_quiet_result(template.id)
        return

    # Update
    compute_template.id = template_id
    if not confirmed(
        f"Update existing Compute Requirement Template '{name}' ({template_id})?"
    ):
        record_resource(RN_REQUIREMENT_TEMPLATE, name, template_id, "skipped")
        return
    template = ctx.client.compute_client.update_compute_requirement_template(
        compute_template
    )
    clear_compute_requirement_template_cache()
    print_info(
        f"Updated existing Compute Requirement Template '{name}' ({template.id})"
    )
    record_resource(RN_REQUIREMENT_TEMPLATE, name, template.id, "updated")
    print_quiet_result(template.id)


def create_keyring(ctx: RunContext, resource: dict, show_secrets: bool = False):
    """
    Create a Keyring, or update the description of an existing one in place.
    The description is the only thing the Platform lets a Keyring change; the
    name is what an existing one is matched on. Credentials and accessors are
    untouched by an update -- the Keyring is no longer deleted and recreated.
    """
    try:
        name = resource[PROP_NAME]
        description = resource[PROP_DESCRIPTION]
    except KeyError as e:
        raise missing_property(e) from e

    existing = get_keyring_summary_by_name(ctx.client, name)
    if existing is not None:
        if not confirmed(f"Keyring '{name}' already exists: update its description?"):
            record_resource(RN_KEYRING, name, existing.id, "skipped")
            return
        keyring = ctx.client.keyring_client.update_keyring(
            cast(str, existing.id), model.UpdateKeyringRequest(description=description)
        )
        clear_keyring_cache()  # the cached summary carries the old description
        print_info(f"Updated Keyring '{name}' ({keyring.id})")
        record_resource(RN_KEYRING, name, keyring.id, "updated")
        print_quiet_result(keyring.id)
        return

    keyring_response = ctx.client.keyring_client.add_keyring(name, description)
    clear_keyring_cache()
    keyring = keyring_response.keyring
    keyring_password = keyring_response.keyringPassword
    show_password = bool(_OPTIONS.show_keyring_passwords or show_secrets)
    keyring_password = keyring_password if show_password else REDACTED_VALUE
    print_info(
        f"Created Keyring '{name}' ({keyring.id}): Password = {keyring_password}"  # type: ignore[union-attr]
    )
    # The password only when asked for: never even as REDACTED_VALUE
    record_resource(
        RN_KEYRING,
        name,
        keyring.id,  # type: ignore[union-attr]
        "created",
        **({"password": keyring_password} if show_password else {}),
    )
    print_quiet_result(f"{keyring.id} {keyring_password}")  # type: ignore[union-attr]


def create_credential(ctx: RunContext, resource: dict):
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
        raise missing_property(e) from e

    credential = _get_model_object(credential_type, credential_data)
    try:
        ctx.client.keyring_client.put_credential_by_name(keyring_name, credential)
        print_info(f"Added Credential '{name}' to Keyring '{keyring_name}'")
        # A put: the Platform does not say whether it replaced one
        record_resource(RN_CREDENTIAL, name, None, "created", keyring=keyring_name)
    except HTTPError as e:
        resp = e.response
        if resp is not None and resp.status_code == 400:
            raise ValueError(
                f"Credential '{name}' was refused for Keyring '{keyring_name}':"
                f" {resp.text}"
            ) from e
        if resp is not None and resp.status_code == 404:
            raise NotFoundError(f"Keyring '{keyring_name}' not found") from e
        raise


def create_image_family(ctx: RunContext, resource):
    """
    Create or update an Image Family.
    """
    try:
        family_name = resource[PROP_NAME]
        namespace = resource[PROP_NAMESPACE]
        os_type_str = resource.pop(PROP_OS_TYPE)
    except KeyError as e:
        raise missing_property(e) from e

    fq_name = f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{family_name}"

    try:
        os_type = ImageOsType[os_type_str]  # Change to Enum
    except KeyError:
        raise ValueError(
            f"Property '{PROP_OS_TYPE}' has invalid value '{os_type_str}'; valid values are"
            f" {[e.value for e in ImageOsType]}"
        ) from None

    # Start by updating the outer Image Family
    image_family = _get_model_object("MachineImageFamily", resource, osType=os_type)

    # Check for existing Image Family
    try:
        existing_image_family: MachineImageFamily | None = (
            ctx.client.images_client.get_image_family_by_name(
                namespace=namespace, family_name=family_name
            )
        )
    except HTTPError as e:
        if not is_http_not_found(e):
            raise
        existing_image_family = None

    if existing_image_family is None:
        # This will create the Image Family and all of its constituent
        # Image Group/Image resources
        image_family = _create_image_family(ctx, image_family, fq_name)
        print_info(f"Created Machine Image Family '{fq_name}' ({image_family.id})")
        print_quiet_result(image_family.id)
        return

    if not confirmed(f"Update existing Machine Image Family '{fq_name}'?"):
        record_resource(RN_IMAGE_FAMILY, fq_name, existing_image_family.id, "skipped")
        return
    image_family.id = existing_image_family.id
    # This will update the Image Family but not its constituent
    # Image Group/Image resources
    ctx.client.images_client.update_image_family(image_family)
    clear_image_caches()
    print_info(
        f"Updated existing Machine Image Family '{fq_name}' ('{image_family.id}')"
    )
    record_resource(RN_IMAGE_FAMILY, fq_name, image_family.id, "updated")
    print_quiet_result(image_family.id)

    # This is an update, so Image Groups have been ignored
    image_groups: list[MachineImageGroup] = image_family.imageGroups or []

    # Delete Image Groups that have been removed from
    # the new resource specification
    updated_image_group_names = [image_group.name for image_group in image_groups]
    for existing_image_group in existing_image_family.imageGroups or []:
        if existing_image_group.name not in updated_image_group_names:
            if confirmed(f"Remove existing Image Group '{existing_image_group.name}'?"):
                ctx.client.images_client.delete_image_group(existing_image_group)
                clear_image_caches()
                print_info(f"Deleted Image Group '{existing_image_group.name}'")
                record_resource(
                    RN_IMAGE_GROUP,
                    existing_image_group.name,
                    existing_image_group.id,
                    "removed",
                )

    # Update Image Groups
    for image_group in image_groups:
        _create_image_group(ctx, namespace, image_family, image_group)


def _create_image_group(
    ctx: RunContext,
    namespace: str,
    image_family: MachineImageFamily,
    image_group: MachineImageGroup,
):
    """
    Create or update a Machine Image Group.
    """
    # Check for existing Image Group
    try:
        existing_image_group: MachineImageGroup | None = (
            ctx.client.images_client.get_image_group_by_name(
                namespace=namespace,
                family_name=image_family.name,
                group_name=image_group.name,
            )
        )
    except HTTPError as e:
        if not is_http_not_found(e):
            raise
        existing_image_group = None

    if existing_image_group is None:
        image_group = ctx.client.images_client.add_image_group(
            image_family, image_group
        )
        clear_image_caches()
        print_info(f"Created Machine Image Group '{image_group.name}'")
        _record_image_group_created(image_group)
        print_quiet_result(image_group.id)
        return

    if not confirmed(f"Update existing Machine Image Group '{image_group.name}'?"):
        record_resource(
            RN_IMAGE_GROUP, image_group.name, existing_image_group.id, "skipped"
        )
        return
    image_group.id = existing_image_group.id
    ctx.client.images_client.update_image_group(image_group)
    clear_image_caches()
    print_info(f"Updated existing Machine Image Group '{image_group.name}'")
    record_resource(RN_IMAGE_GROUP, image_group.name, image_group.id, "updated")
    print_quiet_result(image_group.id)

    # This is an update, so Images have been ignored
    images: list[MachineImage] = image_group.images or []

    # Delete Images that have been removed from
    # the new resource specification
    updated_image_names = [image.name for image in images]
    for existing_image in existing_image_group.images or []:
        if existing_image.name not in updated_image_names:
            if confirmed(f"Remove existing Image '{existing_image.name}'?"):
                ctx.client.images_client.delete_image(existing_image)
                clear_image_caches()
                print_info(f"Deleted Image '{existing_image.name}'")
                record_resource(
                    RN_IMAGE, existing_image.name, existing_image.id, "removed"
                )

    # Update Images
    existing_image_ids = {
        existing_image.name: existing_image.id
        for existing_image in existing_image_group.images or []
    }
    for image in images:
        image.id = existing_image_ids.get(image.name)
        _create_image(ctx, image, image_group)


def _create_image(ctx: RunContext, image: MachineImage, image_group: MachineImageGroup):
    """
    Create or update a Machine Image.
    """
    try:
        if image.id is not None:  # Existing Image
            if not confirmed(f"Update existing Machine Image '{image.name}'?"):
                record_resource(RN_IMAGE, image.name, image.id, "skipped")
                return
            image = ctx.client.images_client.update_image(image)
            clear_image_caches()
            print_info(f"Updated existing Machine Image '{image.name}'")
            record_resource(RN_IMAGE, image.name, image.id, "updated")
        else:  # New Image
            image = ctx.client.images_client.add_image(image_group, image)
            clear_image_caches()
            print_info(f"Created Machine Image '{image.name}'")
            record_resource(RN_IMAGE, image.name, image.id, "created")
    except InvalidRequestException as e:
        raise RuntimeError(f"Unable to create/update Image '{image.name}': {e}") from e

    print_quiet_result(image.id)


def _record_image_group_created(image_group: MachineImageGroup) -> None:
    """
    Record a newly created Image Group, and the Images created with it.
    """
    record_resource(RN_IMAGE_GROUP, image_group.name, image_group.id, "created")
    for image in image_group.images or []:
        record_resource(RN_IMAGE, image.name, image.id, "created")


def create_configured_worker_pool(ctx: RunContext, resource: dict):
    """
    Create a Configured Worker Pool. There's no API support for update.
    """
    try:
        name = resource[PROP_NAME]
        namespace = resource[PROP_NAMESPACE]
    except KeyError as e:
        raise missing_property(e) from e

    name = f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{name}"

    cwp_request = _get_model_object("AddConfiguredWorkerPoolRequest", resource)
    cwp_response: AddConfiguredWorkerPoolResponse = (
        ctx.client.worker_pool_client.add_configured_worker_pool(cwp_request)
    )
    print_info(
        f"Created Configured Worker Pool '{name}' ({cwp_response.workerPool.id})"  # type: ignore[union-attr]
    )
    print_info(
        f"                   Worker Pool Token = '{cwp_response.token.secret}'"  # type: ignore[union-attr]
    )
    print_info(
        "                   Worker Pool Expiry Time = "
        f"{shown_expiry(cwp_response.token.expiryTime)}"  # type: ignore[union-attr]
    )
    # The token too, which '--json' otherwise silences with the prints
    # above, and which is how a Configured Worker Pool is used
    token = cwp_response.token
    record_resource(
        RN_CONFIGURED_POOL,
        name,
        cwp_response.workerPool.id,  # type: ignore[union-attr]
        "created",
        token=None if token is None else token.secret,
        expiryTime=(
            None
            if token is None or token.expiryTime is None
            else token.expiryTime.isoformat()
        ),
    )
    print_quiet_result(cwp_response.workerPool.id)  # type: ignore[union-attr]


def create_allowance(ctx: RunContext, resource: dict):
    """
    Create an allowance.
    """
    try:
        original_type = resource.pop(PROP_TYPE)
        type = original_type.split(".")[-1]  # Extract type
    except KeyError as e:
        raise missing_property(e) from e

    if type == "SourcesAllowance":
        _resolve_allowance_template(
            ctx,
            resource,
            PROP_SOURCE_CREATED_FROM,
            YDIDType.COMPUTE_SOURCE_TEMPLATE,
            "Compute Source Template",
            get_compute_source_template_id_by_name,
        )
    elif type == "RequirementsAllowance":
        _resolve_allowance_template(
            ctx,
            resource,
            PROP_REQUIREMENT_CREATED_FROM,
            YDIDType.COMPUTE_REQUIREMENT_TEMPLATE,
            "Compute Requirement Template",
            get_compute_requirement_template_id_by_name,
        )

    for property_ in [PROP_EFFECTIVE_FROM, PROP_EFFECTIVE_UNTIL]:
        value = resource.get(property_)
        if value is not None:
            resource[property_] = _parsed_datetime(property_, value)
            print_info(
                f"Property '{property_}' = '{value}' set to "
                f"'{_display_datetime(resource[property_])}'"
            )

    if _OPTIONS.dry_run:
        _get_model_object(type, resource)  # Report extras and omissions
        # Datetime objects must be converted to strings for JSON presentation
        for property_ in [PROP_EFFECTIVE_FROM, PROP_EFFECTIVE_UNTIL]:
            if resource.get(property_) is not None:
                resource[property_] = resource[property_].isoformat()
        resource[PROP_TYPE] = original_type  # Reinstate property
        _show_dry_run_specification(RN_ALLOWANCE, resource)
        return

    description = resource.get(PROP_DESCRIPTION)

    # Existing Allowances with the same description are chosen and confirmed
    # now, before anything changes, so a prompt that cannot be answered
    # fails the run before the replacement exists; they are removed only
    # once it does, so a creation that fails loses nothing
    to_replace = []
    if _OPTIONS.match_allowances_by_description and description is not None:
        print_info(
            f"Checking for existing Allowance(s) matching description '{description}'"
        )
        to_replace = allowances_to_remove(ctx.client, description)

    allowance = ctx.client.allowances_client.add_allowance(
        _get_model_object(type, resource)
    )
    if description is None:
        print_info(f"Created new Allowance {allowance.id}")
    else:
        print_info(f"Created new Allowance '{description}' ({allowance.id})")
    record_resource(RN_ALLOWANCE, description, allowance.id, "created")
    if allowance.id is not None:
        print_quiet_result(allowance.id)

    for removed_id in remove_allowances(ctx.client, to_replace):
        record_resource(RN_ALLOWANCE, description, removed_id, "removed")


def _group_shown(ctx: RunContext, group_id: str | None) -> str:
    """
    A Group as a message names it once its membership has changed: by name
    and ID, or by ID alone when the name cannot be fetched, the change
    having been made either way.
    """
    name = get_group_name_by_id(ctx.client, cast(str, group_id))
    return str(group_id) if name is None else f"'{name}' ({group_id})"


def _resolve_allowance_template(
    ctx: RunContext,
    resource: dict,
    property_: str,
    ydid_type: YDIDType,
    label: str,
    lookup,
) -> None:
    """
    Replace a template name in an Allowance with its ID. A name without a
    namespace is looked for in the configured namespace. In a dry run, a
    name not found is left as it is: an earlier specification may create it.
    """
    template_name_or_id = resource.get(property_)
    if template_name_or_id is None or get_ydid_type(template_name_or_id) == ydid_type:
        return
    template_id = lookup(
        ctx.client, cast(str, template_name_or_id), ctx.config.namespace
    )
    if template_id is None:
        if _OPTIONS.dry_run:
            print_dry_run(
                f"{label} '{template_name_or_id}' not found (yet): its name is"
                " left unresolved"
            )
            return
        raise NotFoundError(f"{label} name '{template_name_or_id}' not found")
    print_info(f"Replaced {label} name '{template_name_or_id}' with ID {template_id}")
    resource[property_] = template_id


def _parsed_datetime(property_: str, value: object) -> datetime:
    """
    An Allowance date: a TOML datetime or date as it is, or a string as
    dateparser reads it ('2026-01-01', 'in 2 days').
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if not isinstance(value, str):
        raise ValueError(f"Property '{property_}' must be a date, not '{value}'")
    parsed = date_parse(value)
    if parsed is None:
        raise ValueError(f"Unable to parse '{property_}' date '{value}'")
    return parsed


def _display_datetime(dt: datetime) -> str:
    """
    A date as the 'set to' message shows it.
    """
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z%z").rstrip()


def create_attribute_definition(ctx: RunContext, resource: dict, resource_type: str):
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
        raise missing_property(e) from e

    url = f"{ctx.config.url}/compute/attributes/user"
    headers = {"Authorization": f"yd-key {ctx.config.key}:{ctx.config.secret}"}
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
    response = post(url=url, headers=headers, json=payload, timeout=RAW_REQUEST_TIMEOUT)

    if response.ok:
        print_info(f"Created new Attribute Definition '{name}'")
        record_resource(resource_type, name, None, "created")
        return

    if "Attribute already exists" not in response.text:
        _raise_for_response(response)

    if not confirmed(f"Update existing Attribute Definition '{name}'?"):
        record_resource(resource_type, name, None, "skipped")
        return

    response = put(url=url, headers=headers, json=payload, timeout=RAW_REQUEST_TIMEOUT)
    if not response.ok:
        _raise_for_response(response)
    print_info(f"Updated existing Attribute Definition '{name}'")
    record_resource(resource_type, name, None, "updated")


def _raise_for_response(response: Response) -> None:
    """
    Raise a failed raw response as an HTTPError carrying it, so its status
    gives the exit code, with the Platform's own message.
    """
    raise HTTPError(f"HTTP {response.status_code} ({response.text})", response=response)


def create_namespace_policy(ctx: RunContext, resource: dict):
    """
    Create or update a namespace policy.
    """
    try:
        namespace_policy = NamespacePolicy(
            namespace=resource[PROP_NAMESPACE],
            autoscalingMaxNodes=resource.get(PROP_AUTOSCALING_MAX_NODES),
        )
    except KeyError as e:
        raise missing_property(e) from e

    # Test for existing policy
    try:
        ctx.client.namespaces_client.get_namespace_policy(
            namespace=namespace_policy.namespace
        )
        existing = True
    except Exception as e:
        if not is_http_not_found(e):
            raise
        existing = False
    if existing and not confirmed(
        f"Update existing Namespace Policy '{namespace_policy.namespace}'?"
    ):
        record_resource(
            RN_NAMESPACE_POLICY, namespace_policy.namespace, None, "skipped"
        )
        return

    ctx.client.namespaces_client.save_namespace_policy(namespace_policy)

    print_info(
        f"Created or updated Namespace Policy '{namespace_policy.namespace}' with "
        f"'autoscalingMaxNodes={namespace_policy.autoscalingMaxNodes}'"
    )
    record_resource(
        RN_NAMESPACE_POLICY,
        namespace_policy.namespace,
        None,
        "updated" if existing else "created",
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


def create_group(ctx: RunContext, resource: dict):
    """
    Create or update a group, and the scoped roles it holds, specified by
    their names or IDs. Without 'roles' an existing group's roles are left
    as they are; with 'roles' they are made to match it, so '[]' removes
    them all. Every role is resolved before anything is changed.
    """
    try:
        name = resource[PROP_NAME]
        description = resource.get(PROP_DESCRIPTION)
    except KeyError as e:
        raise missing_property(e) from e

    roles_input = resource.get(PROP_ROLES)
    role_specifications = (
        None if roles_input is None else _role_specifications(ctx, roles_input)
    )

    group_id = get_group_id_by_name(ctx.client, name)
    if group_id is None:  # New group
        group: Group = ctx.client.account_client.add_group(
            AddGroupRequest(name=name, description=description)
        )
        clear_group_caches()
        print_info(f"Created Group '{group.name}' ({group.id})")
        added = _add_or_update_roles(
            ctx, cast(str, group.id), role_specifications or []
        )
        record_resource(RN_GROUP, name, group.id, "created", rolesAdded=added)
        print_quiet_result(group.id)
        return

    if not confirmed(f"Update Group '{name}' ({group_id})?"):
        record_resource(RN_GROUP, name, group_id, "skipped")
        return
    group = ctx.client.account_client.update_group(
        group_id, UpdateGroupRequest(name=name, description=description)
    )
    clear_group_caches()
    print_info(f"Updated Group '{group.name}' ({group.id})")
    if role_specifications is None:
        record_resource(RN_GROUP, name, group.id, "updated")
    else:
        added = _add_or_update_roles(ctx, group_id, role_specifications)
        removed = _remove_roles(
            ctx, group_id, _roles_to_remove(group.roles or [], role_specifications)
        )
        clear_group_caches()
        record_resource(
            RN_GROUP,
            name,
            group.id,
            "updated",
            rolesAdded=added,
            rolesRemoved=removed,
        )
    print_quiet_result(group.id)


def _role_specifications(ctx: RunContext, roles_input: list) -> list[RoleSpecification]:
    """
    The role specifications of a Group's 'roles', each role resolved by its
    name or ID; a role that does not exist is an error.
    """
    role_specifications = []
    for role_item in check_list(roles_input, PROP_ROLES):
        if not isinstance(role_item, dict):
            raise TypeError(
                f"Group role '{role_item}' must be an object with 'role' and "
                "'scope' properties, such as "
                '{"role": {"name": "work-viewer"}, "scope": {"global": true}}'
            )
        role = check_dict(role_item.get(PROP_ROLE), PROP_ROLE)
        if role is None:
            raise ValueError("Role must have 'role' specified")

        # Get the ID and name of the role
        id_ = role.get(PROP_ID)
        name_ = role.get(PROP_NAME)
        if id_ is None:
            if name_ is None:
                raise ValueError("Group role must have 'id' or 'name' specified")
            id_ = get_role_id_by_name(ctx.client, name_)
            if id_ is None:
                raise NotFoundError(f"Role '{name_}' not found")
        elif name_ is None:
            name_ = get_role_name_by_id(ctx.client, id_)
            if name_ is None:
                raise NotFoundError(f"Role ID '{id_}' not found")

        # Get the scope of the role
        scope = check_dict(role_item.get(PROP_SCOPE), PROP_SCOPE)
        if scope is None:
            raise ValueError(f"Group role '{name_}' must have 'scope' specified")
        if scope.get(PROP_GLOBAL):
            role_specifications.append(
                RoleSpecification(id=id_, name=name_, global_=True, namespaces=None)
            )
            continue

        namespaces_ = check_list(scope.get(PROP_NAMESPACES), PROP_NAMESPACES)
        if namespaces_ is None:
            raise ValueError(
                f"Non-global group role '{name_}' must have 'namespaces' specified"
            )
        namespace_names = []
        for namespace_ in namespaces_:
            namespace_name = check_dict(namespace_, PROP_NAMESPACES).get(PROP_NAMESPACE)
            if namespace_name is None:
                raise ValueError(
                    f"Namespace applied to role '{name_}' "
                    "must have 'namespace' property"
                )
            namespace_names.append(namespace_name)
        if not namespace_names:
            raise ValueError(
                f"Non-global role '{name_}' must have at least one namespace scope"
            )
        role_specifications.append(
            RoleSpecification(
                id=id_, name=name_, global_=False, namespaces=set(namespace_names)
            )
        )

    return role_specifications


def _add_or_update_roles(
    ctx: RunContext, group_id: str, role_specifications: list[RoleSpecification]
) -> list[str]:
    """
    Add or update a Group's roles; returns their names.
    """
    for role_spec in role_specifications:
        ctx.client.account_client.add_role_to_group(
            group_id,
            role_spec.id,
            RoleScope(cast(bool, role_spec.global_), role_spec.namespaces),
        )
        if role_spec.global_:
            print_info(f"Added/updated role '{role_spec.name}' with global scope")
        else:
            ns_list_quoted = [f"'{ns}'" for ns in sorted(role_spec.namespaces or [])]
            print_info(
                f"Added/updated role '{role_spec.name}' scoped to "
                f"namespace(s): {', '.join(ns_list_quoted)}"
            )
    return [role_spec.name for role_spec in role_specifications]


def _remove_roles(
    ctx: RunContext, group_id: str, role_specifications: list[RoleSpecification]
) -> list[str]:
    """
    Remove roles from a Group; returns their names.
    """
    for role_spec in role_specifications:
        ctx.client.account_client.remove_role_from_group(group_id, role_spec.id)
        print_info(f"Removed role '{role_spec.name}'")
    return [role_spec.name for role_spec in role_specifications]


def _roles_to_remove(
    existing_roles: list[GroupRole], new_roles: list[RoleSpecification]
) -> list[RoleSpecification]:
    """
    The roles a Group holds that its specification does not name.
    """
    new_role_ids = {role_spec.id for role_spec in new_roles}
    return [
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
        if role.role.id not in new_role_ids
    ]


def _group_ids(ctx: RunContext, group_names: list[str]) -> set[str]:
    """
    The IDs of Groups named by name or ID; a Group that does not exist is an
    error, before anything is changed, since memberships are made to match.
    """
    group_ids = set()
    for group_name in group_names:
        group_id = get_group_id_by_name(ctx.client, group_name)
        if group_id is None:
            raise NotFoundError(f"Group '{group_name}' not found")
        group_ids.add(group_id)
    return group_ids


def create_application(ctx: RunContext, resource: dict):
    """
    Create or update an application, the groups it belongs to (by their
    names or IDs) and the Keyrings it may access. Without 'groups' an
    existing application's groups are left as they are; with 'groups' they
    are made to match it, so '[]' removes them all.
    """
    try:
        name = resource[PROP_NAME]
    except KeyError as e:
        raise missing_property(e) from e

    groups: list[str] | None = resource.pop(PROP_GROUPS, None)
    keyrings: list[str] = resource.pop(PROP_KEYRINGS, None) or []
    # Every Group is resolved before anything is changed
    new_group_ids = None if groups is None else _group_ids(ctx, groups)

    app_id = get_application_id_by_name(ctx.client, name)
    if app_id is None:
        _add_application(ctx, resource, name, new_group_ids, keyrings)
    else:
        _update_application(ctx, resource, name, app_id, new_group_ids, keyrings)


def _add_application(
    ctx: RunContext,
    resource: dict,
    name: str,
    new_group_ids: set[str] | None,
    keyrings: list[str],
):
    """
    Add a new application, its groups and its Keyring grants.
    """
    app_response: AddApplicationResponse = ctx.client.account_client.add_application(
        _get_model_object(RN_ADD_APPLICATION_REQUEST, resource)
    )
    app = cast(Application, app_response.application)
    print_info(f"Created Application '{app.name}' ({app.id})")
    _show_key_and_secret(app_response.apiKey)  # type: ignore[arg-type]
    record_resource(
        RN_APPLICATION,
        name,
        app.id,
        "created",
        **_key_and_secret(app_response.apiKey),
    )
    clear_application_caches()
    print_quiet_result(app.id)
    _update_application_groups(ctx, app, new_group_ids)
    if keyrings:
        if app_response.apiKey is None:
            raise RuntimeError(
                "Application created, but no API key was returned with which"
                " to grant it access to its Keyring(s)"
            )
        _grant_keyrings(
            ctx, keyrings, cast(str, app.id), app_response.apiKey, "created"
        )


def _update_application(
    ctx: RunContext,
    resource: dict,
    name: str,
    app_id: str,
    new_group_ids: set[str] | None,
    keyrings: list[str],
):
    """
    Update an existing application, including its groups, its key (with
    '--regenerate-app-keys') and its Keyring grants.
    """
    if keyrings and not _OPTIONS.regenerate_app_keys:
        # A grant needs the key, which the Platform returns only when the
        # application is created or its key regenerated
        raise ValueError(
            f"Application '{name}' exists: granting it access to Keyring(s)"
            " needs its API key; re-run with '--regenerate-app-keys'"
        )
    if not confirmed(f"Update Application '{name}' ({app_id})?"):
        record_resource(RN_APPLICATION, name, app_id, "skipped")
        return

    app: Application = ctx.client.account_client.update_application(
        app_id, _get_model_object(RN_UPDATE_APPLICATION_REQUEST, resource)
    )
    clear_application_caches()
    print_info(f"Updated Application '{app.name}' ({app.id})")
    _update_application_groups(ctx, app, new_group_ids)

    api_key: ApiKey | None = None
    if _OPTIONS.regenerate_app_keys:
        print_info("Regenerating Application key and secret")
        api_key = ctx.client.account_client.regenerate_application_api_key(app_id)
        clear_application_caches()
        if api_key is not None:
            _show_key_and_secret(api_key)
    record_resource(RN_APPLICATION, name, app.id, "updated", **_key_and_secret(api_key))
    print_quiet_result(app.id)
    if _OPTIONS.regenerate_app_keys and api_key is None:
        raise RuntimeError("Application updated, but no new API key was returned")

    if keyrings:
        _grant_keyrings(ctx, keyrings, app_id, cast(ApiKey, api_key), "updated")


def _grant_keyrings(
    ctx: RunContext, keyrings: list[str], app_id: str, api_key: ApiKey, outcome: str
):
    """
    Grant the application access to its Keyrings; a grant that fails fails
    the resource, after the others have been tried.
    """
    failures: list[tuple[str, Exception]] = []
    for keyring_name in keyrings:
        try:
            ctx.client.keyring_client.grant_application_access_to_keyring(
                keyring_name, app_id, api_key
            )
            print_info(f"Granted Application access to Keyring '{keyring_name}'")
        except Exception as e:
            failures.append((keyring_name, e))
    if failures:
        keyring_names = ", ".join(f"'{k}'" for k, _ in failures)
        raise RuntimeError(
            f"Application {outcome}, but access to Keyring(s) {keyring_names}"
            f" could not be granted: {failures[0][1]}"
        ) from failures[0][1]


def _update_application_groups(
    ctx: RunContext, app: Application, new_group_ids: set[str] | None
):
    """
    Make the application's groups match those given; None leaves them as
    they are.
    """
    if new_group_ids is None:
        return
    current_group_ids = {
        group.id
        for group in get_application_group_summaries(ctx.client, cast(str, app.id))
    }

    if current_group_ids == new_group_ids:
        print_info("No Group additions or deletions required")
        return

    group_ids_to_remove = current_group_ids - new_group_ids
    for group_id in group_ids_to_remove:
        ctx.client.account_client.remove_application_from_group(group_id, app.id)  # type: ignore[arg-type]
        clear_application_caches()
        print_info(f"Removed Group {_group_shown(ctx, group_id)} from Application")

    group_ids_to_add = new_group_ids - current_group_ids
    for group_id in group_ids_to_add:
        ctx.client.account_client.add_application_to_group(group_id, app.id)  # type: ignore[arg-type]
        clear_application_caches()
        print_info(f"Added Group {_group_shown(ctx, group_id)} to Application")


def _show_key_and_secret(api_key: ApiKey):
    """
    Display the app key and secret. Under '--json' they are the record's
    instead, since stdout holds only the document, and this is the only time
    the Platform returns them.
    """
    if _OPTIONS.json_output:
        return
    print_info(f"Application Key ID     = '{api_key.id}'", override_quiet=True)
    print_info(f"Application Key Secret = '{api_key.secret}'", override_quiet=True)


def _key_and_secret(api_key: ApiKey | None) -> dict:
    """
    The record's extra fields for a key and secret the Platform returned.
    """
    if api_key is None:
        return {}
    return {"apiKeyId": api_key.id, "apiKeySecret": api_key.secret}


def update_user(ctx: RunContext, resource: dict, internal_user: bool):
    """
    Update the groups of a user specified by name, username or ID; the
    groups are named by their names or IDs. Without 'groups' the user's
    groups are left as they are; with 'groups' they are made to match it,
    so '[]' removes them all. Users cannot be created by the CLI.
    """
    name = resource.get(PROP_NAME)
    username = resource.get(PROP_USERNAME)
    id = resource.get(PROP_ID)
    resource_type = RN_INTERNAL_USER if internal_user else RN_EXTERNAL_USER

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

    groups: list[str] | None = resource.pop(PROP_GROUPS, None)
    # Every Group is resolved before anything is changed
    new_group_ids = None if groups is None else _group_ids(ctx, groups)

    # Every identifier given must find the same User, if it finds one
    identifiers = [i for i in (name, username, id) if i is not None]
    users = {}
    for identifier in identifiers:
        found = get_user_by_name_or_id(ctx.client, cast(str, identifier))
        if found is not None:
            users[found.id] = found
    if not users:
        raise NotFoundError(
            f"User not found ({', '.join(map(str, identifiers))}); Users cannot be"
            " created using the CLI, please use the YellowDog Portal"
        )
    if len(users) > 1:
        raise ValueError(
            f"The identifiers {', '.join(map(str, identifiers))} name different Users"
        )
    user: User = next(iter(users.values()))
    if id is not None and user.id != id:
        raise ValueError(f"User name and supplied ID do not match ({resource})")
    username = user.username if isinstance(user, InternalUser) else user.name

    def update_groups() -> bool:
        """
        Helper function to add/remove groups from a user. False if the
        update was declined.
        """
        if new_group_ids is None:
            print_info("No Groups specified: the User's Groups are left unchanged")
            return True

        current_group_ids = {group.id for group in get_user_groups(ctx.client, user.id)}  # type: ignore[arg-type]

        if current_group_ids == new_group_ids:
            print_info("No Group additions or deletions required")
            return True

        if not confirmed(f"Update Groups for User '{username}' ({user.id})?"):
            return False

        group_ids_to_remove = current_group_ids - new_group_ids
        for group_id in group_ids_to_remove:
            ctx.client.account_client.remove_user_from_group(group_id, user.id)  # type: ignore[arg-type]
            print_info(f"Removed Group {_group_shown(ctx, group_id)}")

        group_ids_to_add = new_group_ids - current_group_ids
        for group_id in group_ids_to_add:
            ctx.client.account_client.add_user_to_group(group_id, user.id)  # type: ignore[arg-type]
            print_info(f"Added Group {_group_shown(ctx, group_id)}")
        return True

    updated = update_groups()
    print_info(f"Actions complete for User '{username}' ({user.id})")
    record_resource(
        resource_type, username, user.id, "updated" if updated else "skipped"
    )


def create_namespace(ctx: RunContext, resource: dict):
    """
    Create a namespace.
    """
    try:
        name = resource[PROP_NAME]
    except KeyError as e:
        raise missing_property(e) from e

    try:
        namespace_id = ctx.client.namespaces_client.create_namespace(
            CreateNamespaceRequest(namespace=name)
        )
    except Exception as e:
        if "ConflictException" in str(e):
            print_warning(f"Namespace '{name}' already exists")
            record_resource(RN_NAMESPACE, name, None, "skipped")
            return
        else:
            raise RuntimeError(f"Failed to create namespace '{name}' ({e})") from e

    print_info(f"Created namespace '{name}' ({namespace_id})")
    record_resource(RN_NAMESPACE, name, namespace_id, "created")

    print_quiet_result(namespace_id)


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
        names = ", ".join(f"'{name}'" for name in missing)
        raise ValueError(
            f"Missing expected propert{'y' if len(missing) == 1 else 'ies'} {names}"
        )

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


def _get_model_class(class_name: str) -> Any:
    """
    Return a YellowDog model class using its class name.
    """
    cls = getattr(model, class_name, None)
    if not (isinstance(cls, type) and dataclasses.is_dataclass(cls)):
        raise ValueError(f"Unknown type '{class_name}'")
    return cls


def _create_image_family(
    ctx: RunContext, image_family: MachineImageFamily, fq_name: str
) -> MachineImageFamily:
    """
    Creates a new image family, recording it and the Image Groups and Images
    created with it. Only one image group can be added at the time of image
    family creation, so any additional image groups are added separately.
    """

    # Remove all except the first image group; keep the rest as a separate list
    image_groups = image_family.imageGroups
    if image_groups is not None:
        image_family.imageGroups = image_groups[:1]
        image_groups = image_groups[1:]  # Remaining image groups

    # Create the image family
    try:
        image_family = ctx.client.images_client.add_image_family(image_family)
        clear_image_caches()
    except Exception as e:
        raise RuntimeError(
            f"Failed to create Machine Image Family '{fq_name}': {e}"
        ) from e
    record_resource(RN_IMAGE_FAMILY, fq_name, image_family.id, "created")
    for image_group in image_family.imageGroups or []:
        _record_image_group_created(image_group)

    # Create any additional image groups
    for image_group in image_groups or []:
        try:
            image_group = ctx.client.images_client.add_image_group(
                image_family, image_group
            )
            clear_image_caches()
        except Exception as e:
            raise RuntimeError(
                f"Failed to add Machine Image Group '{image_group.name}' to "
                f"Image Family '{fq_name}': {e}"
            ) from e
        print_info(f"Created Machine Image Group '{image_group.name}'")
        _record_image_group_created(image_group)

    return image_family
