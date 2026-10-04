#!/usr/bin/env python3

"""
A script to remove YellowDog resources.
"""

from copy import deepcopy
from typing import cast

from requests import delete
from requests.exceptions import HTTPError
from yellowdog_client.model import (
    MachineImage,
    MachineImageFamily,
    MachineImageGroup,
)

from yellowdog_cli.utils.entity_utils import (
    clear_application_caches,
    clear_compute_requirement_template_cache,
    clear_compute_source_template_cache,
    clear_group_caches,
    clear_image_caches,
    clear_keyring_cache,
    get_application_id_by_name,
    get_compute_requirement_template_id_by_name,
    get_compute_source_template_id_by_name,
    get_group_id_by_name,
    get_namespace_id_by_name,
    get_worker_pool_summaries,
    remove_allowances_matching_description,
)
from yellowdog_cli.utils.interactive import confirmed
from yellowdog_cli.utils.load_resources import (
    load_resource_specifications,
    resource_display_name,
)
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.results import record_resource
from yellowdog_cli.utils.settings import (
    NAMESPACE_PREFIX_SEPARATOR,
    PROP_CREDENTIAL,
    PROP_DESCRIPTION,
    PROP_KEYRING_NAME,
    PROP_NAME,
    PROP_NAMESPACE,
    PROP_RESOURCE,
    PROP_SOURCE,
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
)
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON, main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type


@main_wrapper
def main():
    remove_resources()


def remove_resources(resources: list[dict] | None = None):
    """
    Remove a list of resources either supplied as an argument
    or loaded from files, or by ID.
    """
    if ARGS_PARSER.ids:
        failed = 0
        for resource_id in ARGS_PARSER.resource_specifications:
            if not remove_resource_by_id(resource_id):
                failed += 1
        if failed:
            raise RuntimeError(f"{failed} resource(s) failed to remove")
        return

    if resources is None:
        resources = load_resource_specifications(creation_or_update=False)
    else:
        resources = deepcopy(resources)  # Avoid overwriting the input argument

    failed = 0
    for resource in resources or []:
        name = resource_display_name(resource.get(PROP_RESOURCE), resource)
        try:
            resource_type = resource.pop(PROP_RESOURCE)
        except KeyError:
            error = (
                "Missing required 'resource' property in the following resource"
                f" specification: {resource}"
            )
            print_error(error)
            record_resource(None, name, None, "failed", error=error)
            failed += 1
            continue
        try:
            if resource_type == RN_SOURCE_TEMPLATE:
                remove_compute_source_template(resource)
            elif resource_type == RN_REQUIREMENT_TEMPLATE:
                remove_compute_requirement_template(resource)
            elif resource_type == RN_KEYRING:
                remove_keyring(resource)
            elif resource_type == RN_CREDENTIAL:
                remove_credential(resource)
            elif resource_type == RN_IMAGE_FAMILY:
                remove_image_family(resource)
            elif resource_type == RN_CONFIGURED_POOL:
                remove_configured_worker_pool(resource)
            elif resource_type == RN_ALLOWANCE:
                if ARGS_PARSER.match_allowances_by_description:
                    remove_allowance(resource, name)
                else:
                    print_warning(
                        "To remove Allowances by matching on their 'description', "
                        "please use the '--match-allowances-by-description' flag; "
                        "alternatively, Allowances can be removed by their "
                        "YellowDog IDs (yd-remove --ids)"
                    )
                    record_resource(resource_type, name, None, "skipped")
            elif resource_type in [
                RN_STRING_ATTRIBUTE_DEFINITION,
                RN_NUMERIC_ATTRIBUTE_DEFINITION,
            ]:
                remove_attribute_definition(resource, resource_type)
            elif resource_type == RN_NAMESPACE_POLICY:
                remove_namespace_policy(resource)
            elif resource_type == RN_GROUP:
                remove_group(resource)
            elif resource_type == RN_APPLICATION:
                remove_application(resource)
            elif resource_type in [RN_INTERNAL_USER, RN_EXTERNAL_USER]:
                print_warning(
                    "Users cannot be removed by the CLI; please use the YellowDog Portal"
                )
                record_resource(resource_type, name, None, "skipped")
            elif resource_type == RN_NAMESPACE:
                remove_namespace(resource)
            else:
                error = f"Unknown resource type '{resource_type}'"
                print_error(error)
                record_resource(resource_type, name, None, "failed", error=error)
                failed += 1
        except Exception as e:
            print_error(f"Failed to remove resource: {e}")
            record_resource(resource_type, name, None, "failed", error=str(e))
            # Allow removal to continue
            failed += 1

    if failed:
        raise RuntimeError(f"{failed} resource(s) failed to remove")


def remove_compute_source_template(resource: dict):
    """
    Remove a Compute Source Template using a resource specification.
    Should handle any Source Type.
    """
    try:
        namespace = resource[PROP_NAMESPACE]
        source = resource.pop(PROP_SOURCE)  # Extract the Source properties
        name = source[PROP_NAME]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    name = f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{name}"

    source_id = get_compute_source_template_id_by_name(CLIENT, name)
    if source_id is None:
        print_warning(f"Cannot find Compute Source Template '{name}'")
        record_resource(RN_SOURCE_TEMPLATE, name, None, "skipped")
        return

    if not confirmed(f"Remove Compute Source Template '{name}'?"):
        record_resource(RN_SOURCE_TEMPLATE, name, source_id, "skipped")
        return

    try:
        CLIENT.compute_client.delete_compute_source_template_by_id(source_id)
        clear_compute_source_template_cache()
        print_info(f"Removed Compute Source Template '{name}' ({source_id})")
        record_resource(RN_SOURCE_TEMPLATE, name, source_id, "removed")
    except Exception as e:
        raise RuntimeError(
            f"Unable to remove Compute Source Template '{name}' ({source_id}): {e}"
        )


def remove_compute_requirement_template(resource: dict):
    """
    Remove a Compute Requirement Template.
    """
    try:
        name = resource[PROP_NAME]
        namespace = resource[PROP_NAMESPACE]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    name = f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{name}"

    template_id = get_compute_requirement_template_id_by_name(CLIENT, name)
    if template_id is None:
        print_warning(f"Cannot find Compute Requirement Template '{name}'")
        record_resource(RN_REQUIREMENT_TEMPLATE, name, None, "skipped")
        return

    if not confirmed(f"Remove Compute Requirement Template '{name}' ({template_id})?"):
        record_resource(RN_REQUIREMENT_TEMPLATE, name, template_id, "skipped")
        return

    try:
        CLIENT.compute_client.delete_compute_requirement_template_by_id(template_id)
        clear_compute_requirement_template_cache()
        print_info(f"Removed Compute Requirement Template '{name}' ({template_id})")
        record_resource(RN_REQUIREMENT_TEMPLATE, name, template_id, "removed")
    except Exception as e:
        raise RuntimeError(
            f"Unable to remove Compute Requirement Template '{name}'"
            f" ({template_id}): {e}"
        )


def remove_keyring(resource: dict):
    """
    Remove a Keyring.
    """
    try:
        name = resource[PROP_NAME]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    if not confirmed(f"Remove Keyring '{name}'?"):
        record_resource(RN_KEYRING, name, None, "skipped")
        return

    try:
        CLIENT.keyring_client.delete_keyring_by_name(name)
        clear_keyring_cache()
        print_info(f"Removed Keyring '{name}'")
        record_resource(RN_KEYRING, name, None, "removed")
    except HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            print_warning(f"Cannot find Keyring '{name}'")
            record_resource(RN_KEYRING, name, None, "skipped")
        else:
            print_error(f"Unable to remove Keyring '{name}': {e}")
            raise


def remove_credential(resource: dict):
    """
    Remove a Credential from a Keyring.
    """
    try:
        keyring_name = resource[PROP_KEYRING_NAME]
        credential_data = resource[PROP_CREDENTIAL]
        credential_name = credential_data[PROP_NAME]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    if not confirmed(
        f"Remove Credential '{credential_name}' from Keyring '{keyring_name}'?"
    ):
        record_resource(
            RN_CREDENTIAL, credential_name, None, "skipped", keyring=keyring_name
        )
        return

    try:
        CLIENT.keyring_client.delete_credential_by_name(keyring_name, credential_name)
        print_info(
            f"Removed Credential '{credential_name}' from Keyring '{keyring_name}' (if"
            " it was present)"
        )
        record_resource(
            RN_CREDENTIAL, credential_name, None, "removed", keyring=keyring_name
        )
    except HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            print_warning(
                f"Cannot find Keyring '{keyring_name}'(possibly already deleted,"
                " including its credentials?)"
            )
            record_resource(
                RN_CREDENTIAL, credential_name, None, "skipped", keyring=keyring_name
            )
        else:
            print_error(f"Unable to remove Keyring '{keyring_name}': {e}")
            raise


def remove_image_family(resource: dict):
    """
    Remove an Image Family.
    """
    try:
        name = resource[PROP_NAME]
        namespace = resource[PROP_NAMESPACE]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    fq_name = f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{name}"

    # Check for existence of Image Family
    try:
        image_family: MachineImageFamily = (
            CLIENT.images_client.get_image_family_by_name(
                namespace=namespace, family_name=name
            )
        )
    except HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            print_warning(f"Cannot find Machine Image Family '{fq_name}'")
            record_resource(RN_IMAGE_FAMILY, fq_name, None, "skipped")
            return
        else:
            raise e

    if not confirmed(f"Remove Machine Image Family '{fq_name}'?"):
        record_resource(RN_IMAGE_FAMILY, fq_name, image_family.id, "skipped")
        return

    try:
        CLIENT.images_client.delete_image_family(image_family)
        clear_image_caches()
        print_info(f"Removed Image Family '{fq_name}' ({image_family.id})")
        record_resource(RN_IMAGE_FAMILY, fq_name, image_family.id, "removed")
    except Exception as e:
        print_error(f"Unable to remove Image Family '{fq_name}': {e}")
        raise


def remove_configured_worker_pool(resource: dict):
    """
    Shutdown a Configured Worker Pool.
    """
    try:
        name = resource[PROP_NAME]
        namespace = resource[PROP_NAMESPACE]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    fq_name = f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{name}"

    try:
        worker_pool = get_worker_pool_summaries(
            CLIENT, namespace, name, partial_name_matches=False
        )[0]
    except IndexError:
        print_warning(f"Cannot find Configured Worker Pool '{fq_name}'")
        record_resource(RN_CONFIGURED_POOL, fq_name, None, "skipped")
        return

    # Shut down if a configured worker pool, in an appropriate state
    if worker_pool.type.split(".")[-1] != "ConfiguredWorkerPool":  # type: ignore[union-attr]
        print_warning(
            f"Worker Pool '{fq_name}' is not a Configured Pool ({worker_pool.id})"
        )
        record_resource(RN_CONFIGURED_POOL, fq_name, worker_pool.id, "skipped")
        return

    if worker_pool.status.finished:  # type: ignore[union-attr]
        print_info(
            f"Not shutting down already {worker_pool.status} Configured "
            f"Worker Pool '{fq_name}' ({worker_pool.id})"
        )
        record_resource(RN_CONFIGURED_POOL, fq_name, worker_pool.id, "skipped")
        return

    if not confirmed(
        f"Shut down Configured Worker Pool '{fq_name}' ({worker_pool.id})?"
    ):
        record_resource(RN_CONFIGURED_POOL, fq_name, worker_pool.id, "skipped")
        return

    try:
        CLIENT.worker_pool_client.shutdown_worker_pool_by_id(worker_pool.id)  # type: ignore[arg-type]
        print_info(
            f"Shut down {worker_pool.status} Configured Worker Pool"
            f" '{fq_name}' ({worker_pool.id})"
        )
        record_resource(RN_CONFIGURED_POOL, fq_name, worker_pool.id, "removed")
        return
    except Exception as e:
        print_error(f"Failed to shut down Configured Worker Pool: {e}")
        raise


def remove_allowance(resource: dict, name: str | None = None):
    """
    Remove an allowance, matching on the 'description' property. 'name' is
    the display name the caller reports the specification by.
    """
    description = resource.get(PROP_DESCRIPTION)
    if description is not None:
        print_info(f"Removing allowance(s) matching description '{description}'")
        num_removed = len(
            remove_allowances_matching_description(CLIENT, cast(str, description))
        )
        if num_removed > 0:
            print_info(f"Removed {num_removed} Allowance(s)")
        # Removed by description, so no IDs: the count says how many
        record_resource(
            RN_ALLOWANCE,
            description,
            None,
            "removed" if num_removed > 0 else "skipped",
            count=num_removed,
        )
    else:
        record_resource(RN_ALLOWANCE, name, None, "skipped")


class _IdNotFound(Exception):
    """
    A resource named by its YDID was not found.
    """


# The 'resource' a YDID's removal is reported as, for '--json'
_RESOURCE_BY_YDID_TYPE: dict[YDIDType, str] = {
    YDIDType.COMPUTE_SOURCE_TEMPLATE: RN_SOURCE_TEMPLATE,
    YDIDType.COMPUTE_REQUIREMENT_TEMPLATE: RN_REQUIREMENT_TEMPLATE,
    YDIDType.IMAGE_FAMILY: RN_IMAGE_FAMILY,
    YDIDType.IMAGE_GROUP: RN_IMAGE_GROUP,
    YDIDType.IMAGE: RN_IMAGE,
    YDIDType.KEYRING: RN_KEYRING,
    YDIDType.WORKER_POOL: "WorkerPool",
    YDIDType.ALLOWANCE: RN_ALLOWANCE,
    YDIDType.GROUP: RN_GROUP,
    YDIDType.APPLICATION: RN_APPLICATION,
}


def remove_resource_by_id(resource_id: str) -> bool:
    """
    Remove a resource by its YDID, and record the outcome. Returns False on
    failure.
    """
    ydid_type = get_ydid_type(resource_id)
    resource_type = _RESOURCE_BY_YDID_TYPE.get(ydid_type) if ydid_type else None

    def _failed(error: str) -> bool:
        print_error(error)
        if ydid_type is None:  # Not an ID: it's reported as the name given
            record_resource(None, resource_id, None, "failed", error=error)
        else:
            record_resource(resource_type, None, resource_id, "failed", error=error)
        return False

    if ydid_type is None:
        return _failed(f"Invalid YellowDog ID '{resource_id}'")
    if resource_type is None:
        return _failed(f"Resource ID type is unknown/unsupported: {resource_id}")

    try:
        action = _remove_resource_by_id(resource_id, ydid_type)
    except _IdNotFound as e:
        print_warning(str(e))
        record_resource(resource_type, None, resource_id, "failed", error=str(e))
        return False
    except Exception as e:
        return _failed(f"Unable to remove resource with ID {resource_id}: {e}")

    record_resource(resource_type, None, resource_id, action)
    return True


def _remove_resource_by_id(resource_id: str, ydid_type: YDIDType) -> str:
    """
    Remove a resource of a supported type by its YDID: return 'removed', or
    'skipped' if declined; raise _IdNotFound if it is not found (which the
    caller records as 'failed'), or any other failure.
    """
    if ydid_type == YDIDType.COMPUTE_SOURCE_TEMPLATE:
        if not confirmed(f"Remove Compute Source Template {resource_id}?"):
            return "skipped"
        CLIENT.compute_client.delete_compute_source_template_by_id(resource_id)
        clear_compute_source_template_cache()
        print_info(f"Removed Compute Source Template {resource_id} (if present)")

    elif ydid_type == YDIDType.COMPUTE_REQUIREMENT_TEMPLATE:
        if not confirmed(f"Remove Compute Requirement Template {resource_id}?"):
            return "skipped"
        CLIENT.compute_client.delete_compute_requirement_template_by_id(resource_id)
        clear_compute_requirement_template_cache()
        print_info(f"Removed Compute Requirement Template {resource_id} (if present)")

    elif ydid_type == YDIDType.IMAGE_FAMILY:
        if not confirmed(f"Remove Image Family '{resource_id}'?"):
            return "skipped"
        family: MachineImageFamily = CLIENT.images_client.get_image_family_by_id(
            resource_id
        )
        CLIENT.images_client.delete_image_family(family)
        clear_image_caches()
        print_info(f"Removed Image Family {resource_id} (if present)")

    elif ydid_type == YDIDType.IMAGE_GROUP:
        if not confirmed(f"Remove Image Group '{resource_id}'?"):
            return "skipped"
        group: MachineImageGroup = CLIENT.images_client.get_image_group_by_id(
            resource_id
        )
        CLIENT.images_client.delete_image_group(group)
        clear_image_caches()
        print_info(f"Removed Image Group {resource_id} (if present)")

    elif ydid_type == YDIDType.IMAGE:
        if not confirmed(f"Remove Image '{resource_id}'?"):
            return "skipped"
        image: MachineImage = CLIENT.images_client.get_image(resource_id)
        CLIENT.images_client.delete_image(image)
        clear_image_caches()
        print_info(f"Removed Image {resource_id} (if present)")

    elif ydid_type == YDIDType.KEYRING:
        if not confirmed(f"Remove Keyring {resource_id}?"):
            return "skipped"
        try:
            keyring = CLIENT.keyring_client.get_keyring(resource_id)
        except HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                # A failure, as it always was here, unlike a name not
                # found, though reported as a warning
                raise _IdNotFound(f"Cannot find Keyring {resource_id}")
            raise
        CLIENT.keyring_client.delete_keyring_by_name(keyring.name)  # type: ignore[arg-type]
        clear_keyring_cache()
        print_info(f"Removed Keyring {resource_id}")

    elif ydid_type == YDIDType.WORKER_POOL:
        if not confirmed(f"Shut down Worker Pool {resource_id}?"):
            return "skipped"
        CLIENT.worker_pool_client.shutdown_worker_pool_by_id(resource_id)
        print_info(f"Shut down Worker Pool {resource_id}")

    elif ydid_type == YDIDType.ALLOWANCE:
        if not confirmed(f"Remove Allowance {resource_id}?"):
            return "skipped"
        CLIENT.allowances_client.delete_allowance_by_id(resource_id)
        print_info(f"Removed Allowance {resource_id} (if present)")

    elif ydid_type == YDIDType.GROUP:
        if not confirmed(f"Remove Group {resource_id}?"):
            return "skipped"
        CLIENT.account_client.delete_group(resource_id)
        clear_group_caches()
        print_info(f"Removed Group {resource_id} (if present)")

    elif ydid_type == YDIDType.APPLICATION:
        if not confirmed(f"Remove Application {resource_id}?"):
            return "skipped"
        CLIENT.account_client.delete_application(resource_id)
        clear_application_caches()
        print_info(f"Removed Application {resource_id} (if present)")

    return "removed"


def remove_attribute_definition(resource: dict, resource_type: str):
    """
    Use the API to remove user attribute definitions.
    """
    try:
        name = resource[PROP_NAME]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    if not confirmed(f"Remove Attribute Definition '{name}'?"):
        record_resource(resource_type, name, None, "skipped")
        return

    url = f"{CONFIG_COMMON.url}/compute/attributes/user/{name}"
    headers = {"Authorization": f"yd-key {CONFIG_COMMON.key}:{CONFIG_COMMON.secret}"}
    response = delete(url=url, headers=headers)

    if response.status_code == 200:
        print_info(f"Removed Attribute Definition '{name}' (if present)")
        record_resource(resource_type, name, None, "removed")
        return

    raise RuntimeError(f"HTTP {response.status_code} ({response.text})")


def remove_namespace_policy(resource: dict):
    """
    Remove a Namespace Policy (if it exists).
    """
    try:
        namespace = resource[PROP_NAMESPACE]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    # Test for existing policy
    try:
        CLIENT.namespaces_client.get_namespace_policy(namespace=namespace)
    except HTTPError as e:
        if is_http_not_found(e):
            print_warning(f"Cannot find Namespace Policy '{namespace}'")
            record_resource(RN_NAMESPACE_POLICY, namespace, None, "skipped")
            return
        raise

    if not confirmed(f"Remove Namespace Policy '{namespace}'?"):
        record_resource(RN_NAMESPACE_POLICY, namespace, None, "skipped")
        return

    try:
        CLIENT.namespaces_client.delete_namespace_policy(namespace)
        print_info(f"Removed Namespace Policy '{namespace}'")
        record_resource(RN_NAMESPACE_POLICY, namespace, None, "removed")
    except Exception as e:
        print_error(f"Unable to remove Namespace Policy '{namespace}': {e}")
        raise


def remove_group(resource: dict):
    """
    Remove a group.
    """
    try:
        group_name = resource[PROP_NAME]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    group_id = get_group_id_by_name(CLIENT, group_name)
    if group_id is None:
        print_warning(f"Cannot find Group '{group_name}'")
        record_resource(RN_GROUP, group_name, None, "skipped")
        return

    if not confirmed(f"Remove Group '{group_name}' ({group_id})?"):
        record_resource(RN_GROUP, group_name, group_id, "skipped")
        return

    try:
        CLIENT.account_client.delete_group(group_id)
        print_info(f"Removed Group '{group_name}' ({group_id})")
        record_resource(RN_GROUP, group_name, group_id, "removed")
        clear_group_caches()
    except Exception as e:
        print_error(f"Unable to remove Group '{group_name}' ({group_id}): {e}")
        raise


def remove_application(resource: dict):
    """
    Remove an application.
    """
    try:
        app_name = resource[PROP_NAME]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    app_id = get_application_id_by_name(CLIENT, app_name)
    if app_id is None:
        print_warning(f"Cannot find Application '{app_name}'")
        record_resource(RN_APPLICATION, app_name, None, "skipped")
        return

    if not confirmed(f"Remove Application '{app_name}' ({app_id})?"):
        record_resource(RN_APPLICATION, app_name, app_id, "skipped")
        return

    try:
        CLIENT.account_client.delete_application(app_id)
        print_info(f"Removed Application '{app_name}' ({app_id})")
        record_resource(RN_APPLICATION, app_name, app_id, "removed")
        clear_application_caches()
    except Exception as e:
        print_error(f"Unable to remove Application '{app_name}' ({app_id}): {e}")
        raise


def remove_namespace(resource: dict):
    """
    Remove a namespace.
    """
    try:
        name = resource[PROP_NAME]
    except KeyError as e:
        raise KeyError(f"Expected property to be defined ({e})")

    namespace_id = get_namespace_id_by_name(CLIENT, name)
    if namespace_id is None:
        print_warning(f"Cannot find Namespace '{name}'")
        record_resource(RN_NAMESPACE, name, None, "skipped")
        return

    if not confirmed(f"Remove Namespace '{name}'?"):
        record_resource(RN_NAMESPACE, name, namespace_id, "skipped")
        return

    try:
        CLIENT.namespaces_client.delete_namespace(
            get_namespace_id_by_name(CLIENT, name)  # type: ignore[arg-type]
        )
        print_info(f"Removed Namespace '{name}' ({namespace_id})")
        record_resource(RN_NAMESPACE, name, namespace_id, "removed")
    except Exception as e:
        if "ConflictException" in str(e):
            error = (
                f"Unable to remove Namespace '{name}'; note: Namespaces that "
                f"have been populated cannot currently be removed"
            )
            print_error(error)
            record_resource(RN_NAMESPACE, name, namespace_id, "failed", error=error)
        else:
            print_error(f"Unable to remove Namespace '{name}': {e}")
            raise


# Entry point
if __name__ == "__main__":
    main()
