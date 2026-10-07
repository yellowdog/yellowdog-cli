"""
Removing YellowDog resources, by specification or by YellowDog ID: the
library behind yd-remove, which the Cloud Wizard uses too. It reads no
command-line options: what yd-remove's options decide arrives as a
RemoveOptions. remove.py is a thin command over it, since a utility never
imports a command module (see resource_creation.py).
"""

import functools
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from requests import Response, delete
from requests.exceptions import HTTPError
from yellowdog_client.model import MachineImageFamily

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
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
    get_keyring_summary_by_name,
    get_namespace_id_by_name,
    get_worker_pool_summaries,
    remove_allowances_matching_description,
)
from yellowdog_cli.utils.exit_codes import (
    SESSION_FAILURES,
    NotFoundError,
    ReportedFailure,
    classify,
)
from yellowdog_cli.utils.interactive import confirmed
from yellowdog_cli.utils.limits import RAW_REQUEST_TIMEOUT
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.property_names import (
    PROP_CREDENTIAL,
    PROP_DESCRIPTION,
    PROP_ID,
    PROP_KEYRING_NAME,
    PROP_NAME,
    PROP_NAMESPACE,
    PROP_SOURCE,
    PROP_USERNAME,
)
from yellowdog_cli.utils.resource_processing import (
    missing_property,
    process_each,
    process_resources,
)
from yellowdog_cli.utils.results import record_resource
from yellowdog_cli.utils.settings import NAMESPACE_PREFIX_SEPARATOR
from yellowdog_cli.utils.ydid_utils import REMOVABLE_YDID_TYPES, YDIDType, get_ydid_type


@dataclass(frozen=True)
class RemoveOptions:
    """
    What yd-remove's options decide, for a run of remove_resources().
    """

    match_allowances_by_description: bool = False


# The options of the run in progress, set by remove_resources() and
# remove_resources_by_id() for their duration
_OPTIONS: RemoveOptions = RemoveOptions()


def remove_resources(
    ctx: RunContext, resources: list[dict], options: RemoveOptions | None = None
):
    """
    Remove the resources a list of specifications describes, with 'options'
    (the defaults when None). The list is not changed.
    """
    global _OPTIONS
    previous, _OPTIONS = _OPTIONS, options or RemoveOptions()
    try:
        process_resources(
            deepcopy(resources), functools.partial(_remove_resource, ctx), "remove"
        )
    finally:
        _OPTIONS = previous


def remove_resources_by_id(ctx: RunContext, resource_ids: list[str]):
    """
    Remove resources by their YellowDog IDs, each once, in the order given;
    the IDs are of the types REMOVABLE_YDID_TYPES names.
    """
    process_each(
        list(dict.fromkeys(resource_ids)),
        functools.partial(_remove_and_record_by_id, ctx),
        lambda resource_id: resource_id,
        functools.partial(_record_by_id, ctx),
        "remove",
    )


def _remove_resource(ctx: RunContext, resource_type: str, resource: dict) -> None:
    """
    Remove one resource, by its type.
    """
    if resource_type == RN_SOURCE_TEMPLATE:
        remove_compute_source_template(ctx, resource)
    elif resource_type == RN_REQUIREMENT_TEMPLATE:
        remove_compute_requirement_template(ctx, resource)
    elif resource_type == RN_KEYRING:
        remove_keyring(ctx, resource)
    elif resource_type == RN_CREDENTIAL:
        remove_credential(ctx, resource)
    elif resource_type == RN_IMAGE_FAMILY:
        remove_image_family(ctx, resource)
    elif resource_type == RN_CONFIGURED_POOL:
        remove_configured_worker_pool(ctx, resource)
    elif resource_type == RN_ALLOWANCE:
        remove_allowance(ctx, resource)
    elif resource_type in [
        RN_STRING_ATTRIBUTE_DEFINITION,
        RN_NUMERIC_ATTRIBUTE_DEFINITION,
    ]:
        remove_attribute_definition(ctx, resource, resource_type)
    elif resource_type == RN_NAMESPACE_POLICY:
        remove_namespace_policy(ctx, resource)
    elif resource_type == RN_GROUP:
        remove_group(ctx, resource)
    elif resource_type == RN_APPLICATION:
        remove_application(ctx, resource)
    elif resource_type in [RN_INTERNAL_USER, RN_EXTERNAL_USER]:
        print_warning(
            "Users cannot be removed by the CLI; please use the YellowDog Portal"
        )
        record_resource(
            resource_type,
            resource.get(PROP_NAME)
            or resource.get(PROP_USERNAME)
            or resource.get(PROP_ID),
            None,
            "skipped",
        )
    elif resource_type == RN_NAMESPACE:
        remove_namespace(ctx, resource)
    else:
        raise ValueError(f"Unknown resource type '{resource_type}'")


def remove_compute_source_template(ctx: RunContext, resource: dict):
    """
    Remove a Compute Source Template using a resource specification.
    Should handle any Source Type.
    """
    try:
        namespace = resource[PROP_NAMESPACE]
        source = resource.pop(PROP_SOURCE)  # Extract the Source properties
        name = source[PROP_NAME]
    except KeyError as e:
        raise missing_property(e) from e

    name = f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{name}"

    source_id = get_compute_source_template_id_by_name(ctx.client, name)
    if source_id is None:
        print_warning(f"Cannot find Compute Source Template '{name}'")
        record_resource(RN_SOURCE_TEMPLATE, name, None, "skipped")
        return

    if not confirmed(f"Remove Compute Source Template '{name}'?"):
        record_resource(RN_SOURCE_TEMPLATE, name, source_id, "skipped")
        return

    ctx.client.compute_client.delete_compute_source_template_by_id(source_id)
    clear_compute_source_template_cache()
    print_info(f"Removed Compute Source Template '{name}' ({source_id})")
    record_resource(RN_SOURCE_TEMPLATE, name, source_id, "removed")


def remove_compute_requirement_template(ctx: RunContext, resource: dict):
    """
    Remove a Compute Requirement Template.
    """
    try:
        name = resource[PROP_NAME]
        namespace = resource[PROP_NAMESPACE]
    except KeyError as e:
        raise missing_property(e) from e

    name = f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{name}"

    template_id = get_compute_requirement_template_id_by_name(ctx.client, name)
    if template_id is None:
        print_warning(f"Cannot find Compute Requirement Template '{name}'")
        record_resource(RN_REQUIREMENT_TEMPLATE, name, None, "skipped")
        return

    if not confirmed(f"Remove Compute Requirement Template '{name}' ({template_id})?"):
        record_resource(RN_REQUIREMENT_TEMPLATE, name, template_id, "skipped")
        return

    ctx.client.compute_client.delete_compute_requirement_template_by_id(template_id)
    clear_compute_requirement_template_cache()
    print_info(f"Removed Compute Requirement Template '{name}' ({template_id})")
    record_resource(RN_REQUIREMENT_TEMPLATE, name, template_id, "removed")


def remove_keyring(ctx: RunContext, resource: dict):
    """
    Remove a Keyring, found by its name first, so that one that does not
    exist is reported before anything is asked, and the record has its ID.
    """
    try:
        name = resource[PROP_NAME]
    except KeyError as e:
        raise missing_property(e) from e

    keyring = get_keyring_summary_by_name(ctx.client, name)
    if keyring is None:
        print_warning(f"Cannot find Keyring '{name}'")
        record_resource(RN_KEYRING, name, None, "skipped")
        return

    if not confirmed(f"Remove Keyring '{name}' ({keyring.id})?"):
        record_resource(RN_KEYRING, name, keyring.id, "skipped")
        return

    ctx.client.keyring_client.delete_keyring_by_name(name)
    clear_keyring_cache()
    print_info(f"Removed Keyring '{name}' ({keyring.id})")
    record_resource(RN_KEYRING, name, keyring.id, "removed")


def remove_credential(ctx: RunContext, resource: dict):
    """
    Remove a Credential from a Keyring.
    """
    try:
        keyring_name = resource[PROP_KEYRING_NAME]
        credential_data = resource[PROP_CREDENTIAL]
        credential_name = credential_data[PROP_NAME]
    except KeyError as e:
        raise missing_property(e) from e

    if not confirmed(
        f"Remove Credential '{credential_name}' from Keyring '{keyring_name}'?"
    ):
        record_resource(
            RN_CREDENTIAL, credential_name, None, "skipped", keyring=keyring_name
        )
        return

    try:
        ctx.client.keyring_client.delete_credential_by_name(
            keyring_name, credential_name
        )
    except HTTPError as e:
        if not is_http_not_found(e):
            raise
        print_warning(
            f"Cannot find Keyring '{keyring_name}' (possibly already removed,"
            " with its Credentials)"
        )
        record_resource(
            RN_CREDENTIAL, credential_name, None, "skipped", keyring=keyring_name
        )
        return

    # The Platform does not say whether the Keyring held the Credential
    print_info(
        f"Removed Credential '{credential_name}' from Keyring '{keyring_name}'"
        " (the Platform does not report whether it was there)"
    )
    record_resource(
        RN_CREDENTIAL, credential_name, None, "removed", keyring=keyring_name
    )


def remove_image_family(ctx: RunContext, resource: dict):
    """
    Remove an Image Family.
    """
    try:
        name = resource[PROP_NAME]
        namespace = resource[PROP_NAMESPACE]
    except KeyError as e:
        raise missing_property(e) from e

    fq_name = f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{name}"

    # Check for existence of Image Family
    try:
        image_family: MachineImageFamily = (
            ctx.client.images_client.get_image_family_by_name(
                namespace=namespace, family_name=name
            )
        )
    except HTTPError as e:
        if not is_http_not_found(e):
            raise
        print_warning(f"Cannot find Machine Image Family '{fq_name}'")
        record_resource(RN_IMAGE_FAMILY, fq_name, None, "skipped")
        return

    if not confirmed(f"Remove Machine Image Family '{fq_name}'?"):
        record_resource(RN_IMAGE_FAMILY, fq_name, image_family.id, "skipped")
        return

    ctx.client.images_client.delete_image_family(image_family)
    clear_image_caches()
    print_info(f"Removed Image Family '{fq_name}' ({image_family.id})")
    record_resource(RN_IMAGE_FAMILY, fq_name, image_family.id, "removed")


def remove_configured_worker_pool(ctx: RunContext, resource: dict):
    """
    Shut down the Configured Worker Pool(s) of a name that have not finished.
    A pool that has been shut down stays listed under its name, so a name
    can match finished pools as well as a live one; the finished ones are
    left alone.
    """
    try:
        name = resource[PROP_NAME]
        namespace = resource[PROP_NAMESPACE]
    except KeyError as e:
        raise missing_property(e) from e

    fq_name = f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{name}"

    worker_pools = get_worker_pool_summaries(
        ctx.client, namespace, name, partial_name_matches=False
    )
    if not worker_pools:
        print_warning(f"Cannot find Configured Worker Pool '{fq_name}'")
        record_resource(RN_CONFIGURED_POOL, fq_name, None, "skipped")
        return

    configured = [
        worker_pool
        for worker_pool in worker_pools
        if cast(str, worker_pool.type).split(".")[-1] == "ConfiguredWorkerPool"
    ]
    if not configured:
        print_warning(f"Worker Pool '{fq_name}' is not a Configured Worker Pool")
        record_resource(RN_CONFIGURED_POOL, fq_name, worker_pools[0].id, "skipped")
        return

    unfinished = [
        worker_pool
        for worker_pool in configured
        if not cast(Any, worker_pool.status).finished
    ]
    if not unfinished:
        print_info(f"Configured Worker Pool '{fq_name}' has already been shut down")
        record_resource(RN_CONFIGURED_POOL, fq_name, configured[0].id, "skipped")
        return

    for worker_pool in unfinished:
        if not confirmed(
            f"Shut down Configured Worker Pool '{fq_name}' ({worker_pool.id})?"
        ):
            record_resource(RN_CONFIGURED_POOL, fq_name, worker_pool.id, "skipped")
            continue
        ctx.client.worker_pool_client.shutdown_worker_pool_by_id(
            cast(str, worker_pool.id)
        )
        print_info(
            f"Shut down {worker_pool.status} Configured Worker Pool"
            f" '{fq_name}' ({worker_pool.id})"
        )
        record_resource(RN_CONFIGURED_POOL, fq_name, worker_pool.id, "removed")


def remove_allowance(ctx: RunContext, resource: dict):
    """
    Remove the Allowances matching an Allowance specification's
    'description', with '--match-allowances-by-description'; each is
    recorded with its ID.
    """
    description = resource.get(PROP_DESCRIPTION)
    if not _OPTIONS.match_allowances_by_description:
        print_warning(
            "To remove Allowances by matching on their 'description', "
            "please use the '--match-allowances-by-description' flag; "
            "alternatively, Allowances can be removed by their "
            "YellowDog IDs (yd-remove --ids)"
        )
        record_resource(RN_ALLOWANCE, description, None, "skipped")
        return

    if description is None:
        print_warning(
            "An Allowance specification without a 'description' cannot be"
            " matched; it is skipped"
        )
        record_resource(RN_ALLOWANCE, None, None, "skipped")
        return

    print_info(f"Removing Allowance(s) matching description '{description}'")
    removed_ids = remove_allowances_matching_description(
        ctx.client, cast(str, description)
    )
    if not removed_ids:
        record_resource(RN_ALLOWANCE, description, None, "skipped")
        return
    print_info(f"Removed {len(removed_ids)} Allowance(s)")
    for removed_id in removed_ids:
        record_resource(RN_ALLOWANCE, description, removed_id, "removed")


# ---------------------------------------------------------------------------
# Removal by YellowDog ID
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RemovableById:
    """
    How one type of resource is removed by its YellowDog ID: fetched first,
    so an ID that does not exist is reported before anything is asked.
    """

    resource_type: str  # As '--json' reports it
    label: str  # As the messages name it
    fetch: Callable[[str], Any]
    name_of: Callable[[Any], str | None]
    remove: Callable[[str, Any], None]  # (ID, the fetched entity)
    clear: Callable[[], None] | None = None


def _qualified(namespace: str | None, name: str | None) -> str | None:
    if name is None or namespace is None:
        return name
    return f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{name}"


def _removable_by_id(ctx: RunContext, ydid_type: YDIDType) -> _RemovableById:
    """
    The removal for a type of YellowDog ID, one of REMOVABLE_YDID_TYPES.
    Built when asked for, since the calls are the client's.
    """
    compute = ctx.client.compute_client
    images = ctx.client.images_client
    account = ctx.client.account_client
    match ydid_type:
        case YDIDType.COMPUTE_SOURCE_TEMPLATE:
            return _RemovableById(
                RN_SOURCE_TEMPLATE,
                "Compute Source Template",
                compute.get_compute_source_template,
                lambda t: _qualified(t.namespace, t.source.name),
                lambda ydid, _: compute.delete_compute_source_template_by_id(ydid),
                clear_compute_source_template_cache,
            )
        case YDIDType.COMPUTE_REQUIREMENT_TEMPLATE:
            return _RemovableById(
                RN_REQUIREMENT_TEMPLATE,
                "Compute Requirement Template",
                compute.get_compute_requirement_template_by_id,
                lambda t: _qualified(t.namespace, t.name),
                lambda ydid, _: compute.delete_compute_requirement_template_by_id(ydid),
                clear_compute_requirement_template_cache,
            )
        case YDIDType.IMAGE_FAMILY:
            return _RemovableById(
                RN_IMAGE_FAMILY,
                "Machine Image Family",
                images.get_image_family_by_id,
                lambda f: _qualified(f.namespace, f.name),
                lambda _, family: images.delete_image_family(family),
                clear_image_caches,
            )
        case YDIDType.IMAGE_GROUP:
            return _RemovableById(
                RN_IMAGE_GROUP,
                "Machine Image Group",
                images.get_image_group_by_id,
                lambda g: g.name,
                lambda _, group: images.delete_image_group(group),
                clear_image_caches,
            )
        case YDIDType.IMAGE:
            return _RemovableById(
                RN_IMAGE,
                "Machine Image",
                images.get_image,
                lambda i: i.name,
                lambda _, image: images.delete_image(image),
                clear_image_caches,
            )
        case YDIDType.KEYRING:
            return _RemovableById(
                RN_KEYRING,
                "Keyring",
                ctx.client.keyring_client.get_keyring,
                lambda k: k.name,
                lambda _, keyring: ctx.client.keyring_client.delete_keyring_by_name(
                    keyring.name
                ),
                clear_keyring_cache,
            )
        case YDIDType.WORKER_POOL:
            return _RemovableById(
                "WorkerPool",
                "Worker Pool",
                ctx.client.worker_pool_client.get_worker_pool_by_id,
                lambda p: _qualified(p.namespace, p.name),
                lambda ydid, _: (
                    ctx.client.worker_pool_client.shutdown_worker_pool_by_id(ydid)
                ),
            )
        case YDIDType.ALLOWANCE:
            return _RemovableById(
                RN_ALLOWANCE,
                "Allowance",
                ctx.client.allowances_client.get_allowance_by_id,
                lambda a: a.description,
                lambda ydid, _: ctx.client.allowances_client.delete_allowance_by_id(
                    ydid
                ),
            )
        case YDIDType.GROUP:
            return _RemovableById(
                RN_GROUP,
                "Group",
                account.get_group,
                lambda g: g.name,
                lambda ydid, _: account.delete_group(ydid),
                clear_group_caches,
            )
        case YDIDType.APPLICATION:
            return _RemovableById(
                RN_APPLICATION,
                "Application",
                account.get_application,
                lambda a: a.name,
                lambda ydid, _: account.delete_application(ydid),
                clear_application_caches,
            )
    raise ValueError(f"Resources of this type cannot be removed by ID: {ydid_type}")


def _record_by_id(ctx: RunContext, resource_id: str, action: str, error: str) -> None:
    """
    Record a removal by ID that failed, or was not attempted.
    """
    ydid_type = get_ydid_type(resource_id)
    if ydid_type not in REMOVABLE_YDID_TYPES:  # Reported as given
        record_resource(None, resource_id, None, action, error=error)
        return
    resource_type = _removable_by_id(ctx, cast(YDIDType, ydid_type)).resource_type
    record_resource(resource_type, None, resource_id, action, error=error)


def _remove_and_record_by_id(ctx: RunContext, resource_id: str) -> None:
    """
    Remove a resource by its YellowDog ID, and record the outcome: 'removed',
    or 'skipped' when declined, or when a Worker Pool has already been shut
    down. Raises NotFoundError for an ID that does not exist, and any other
    failure, for the caller to record.
    """
    ydid_type = get_ydid_type(resource_id)
    if ydid_type not in REMOVABLE_YDID_TYPES:
        raise ValueError(f"Not the ID of a resource that can be removed: {resource_id}")
    removable = _removable_by_id(ctx, cast(YDIDType, ydid_type))

    try:
        entity = removable.fetch(resource_id)
    except HTTPError as e:
        if is_http_not_found(e):
            raise NotFoundError(f"Cannot find {removable.label} {resource_id}") from e
        raise
    name = removable.name_of(entity)
    described = f"{removable.label} {resource_id}" + (
        "" if name is None else f" ('{name}')"
    )

    def _record(action: str) -> None:
        record_resource(removable.resource_type, name, resource_id, action)

    shut_down = ydid_type == YDIDType.WORKER_POOL
    if shut_down and entity.status is not None and entity.status.finished:
        print_info(f"{described} has already been shut down")
        _record("skipped")
        return

    if not confirmed(f"{'Shut down' if shut_down else 'Remove'} {described}?"):
        _record("skipped")
        return

    removable.remove(resource_id, entity)
    if removable.clear is not None:
        removable.clear()
    print_info(f"{'Shut down' if shut_down else 'Removed'} {described}")
    _record("removed")


def remove_resource_by_id(ctx: RunContext, resource_id: str) -> bool:
    """
    Remove a resource by its YDID, and record the outcome. Returns False on
    failure, which is reported and recorded; an authentication or connection
    failure, which every later request would repeat, is raised as
    ReportedFailure once recorded, for the caller to stop. For callers other
    than yd-remove itself (the Cloud Wizard).
    """
    try:
        _remove_and_record_by_id(ctx, resource_id)
    except Exception as e:
        print_error(f"Failed to remove {resource_id}: {e}")
        _record_by_id(ctx, resource_id, "failed", str(e))
        if classify(e) in SESSION_FAILURES:
            raise ReportedFailure(e)
        return False
    return True


def record_not_attempted(
    ctx: RunContext, resource_ids: list[str], cause: BaseException
) -> None:
    """
    Record the removals by ID that a session failure stopped before they
    were attempted.
    """
    for resource_id in resource_ids:
        _record_by_id(ctx, resource_id, "skipped", f"not attempted: {cause}")


# ---------------------------------------------------------------------------
# The other resources removed by specification
# ---------------------------------------------------------------------------


def remove_attribute_definition(ctx: RunContext, resource: dict, resource_type: str):
    """
    Use the API to remove user attribute definitions.
    """
    try:
        name = resource[PROP_NAME]
    except KeyError as e:
        raise missing_property(e) from e

    if not confirmed(f"Remove Attribute Definition '{name}'?"):
        record_resource(resource_type, name, None, "skipped")
        return

    url = f"{ctx.config.url}/compute/attributes/user/{name}"
    headers = {"Authorization": f"yd-key {ctx.config.key}:{ctx.config.secret}"}
    response = delete(url=url, headers=headers, timeout=RAW_REQUEST_TIMEOUT)

    if response.ok:
        print_info(f"Removed Attribute Definition '{name}'")
        record_resource(resource_type, name, None, "removed")
        return

    if response.status_code == 404:
        print_warning(f"Cannot find Attribute Definition '{name}'")
        record_resource(resource_type, name, None, "skipped")
        return

    _raise_for_response(response)


def _raise_for_response(response: Response) -> None:
    """
    Raise a failed raw response as an HTTPError carrying it, so its status
    gives the exit code, with the Platform's own message.
    """
    raise HTTPError(f"HTTP {response.status_code} ({response.text})", response=response)


def remove_namespace_policy(ctx: RunContext, resource: dict):
    """
    Remove a Namespace Policy (if it exists).
    """
    try:
        namespace = resource[PROP_NAMESPACE]
    except KeyError as e:
        raise missing_property(e) from e

    # Test for existing policy
    try:
        ctx.client.namespaces_client.get_namespace_policy(namespace=namespace)
    except HTTPError as e:
        if is_http_not_found(e):
            print_warning(f"Cannot find Namespace Policy '{namespace}'")
            record_resource(RN_NAMESPACE_POLICY, namespace, None, "skipped")
            return
        raise

    if not confirmed(f"Remove Namespace Policy '{namespace}'?"):
        record_resource(RN_NAMESPACE_POLICY, namespace, None, "skipped")
        return

    ctx.client.namespaces_client.delete_namespace_policy(namespace)
    print_info(f"Removed Namespace Policy '{namespace}'")
    record_resource(RN_NAMESPACE_POLICY, namespace, None, "removed")


def remove_group(ctx: RunContext, resource: dict):
    """
    Remove a group.
    """
    try:
        group_name = resource[PROP_NAME]
    except KeyError as e:
        raise missing_property(e) from e

    group_id = get_group_id_by_name(ctx.client, group_name)
    if group_id is None:
        print_warning(f"Cannot find Group '{group_name}'")
        record_resource(RN_GROUP, group_name, None, "skipped")
        return

    if not confirmed(f"Remove Group '{group_name}' ({group_id})?"):
        record_resource(RN_GROUP, group_name, group_id, "skipped")
        return

    ctx.client.account_client.delete_group(group_id)
    clear_group_caches()
    print_info(f"Removed Group '{group_name}' ({group_id})")
    record_resource(RN_GROUP, group_name, group_id, "removed")


def remove_application(ctx: RunContext, resource: dict):
    """
    Remove an application.
    """
    try:
        app_name = resource[PROP_NAME]
    except KeyError as e:
        raise missing_property(e) from e

    app_id = get_application_id_by_name(ctx.client, app_name)
    if app_id is None:
        print_warning(f"Cannot find Application '{app_name}'")
        record_resource(RN_APPLICATION, app_name, None, "skipped")
        return

    if not confirmed(f"Remove Application '{app_name}' ({app_id})?"):
        record_resource(RN_APPLICATION, app_name, app_id, "skipped")
        return

    ctx.client.account_client.delete_application(app_id)
    clear_application_caches()
    print_info(f"Removed Application '{app_name}' ({app_id})")
    record_resource(RN_APPLICATION, app_name, app_id, "removed")


def remove_namespace(ctx: RunContext, resource: dict):
    """
    Remove a namespace.
    """
    try:
        name = resource[PROP_NAME]
    except KeyError as e:
        raise missing_property(e) from e

    namespace_id = get_namespace_id_by_name(ctx.client, name)
    if namespace_id is None:
        print_warning(f"Cannot find Namespace '{name}'")
        record_resource(RN_NAMESPACE, name, None, "skipped")
        return

    if not confirmed(f"Remove Namespace '{name}'?"):
        record_resource(RN_NAMESPACE, name, namespace_id, "skipped")
        return

    try:
        ctx.client.namespaces_client.delete_namespace(namespace_id)
    except Exception as e:
        if "ConflictException" in str(e):
            raise RuntimeError(
                f"Unable to remove Namespace '{name}'; note: Namespaces that"
                f" have been populated cannot currently be removed ({e})"
            ) from e
        raise
    print_info(f"Removed Namespace '{name}' ({namespace_id})")
    record_resource(RN_NAMESPACE, name, namespace_id, "removed")
