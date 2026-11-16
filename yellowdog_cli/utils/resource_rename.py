"""
yd resource rename's engine: a resource renamed in place, keeping its ID, so
what refers to it by ID (a Compute Requirement Template's sources, an
Allowance's template, a Group's members) is unaffected. Only the types whose
update the Platform takes a new name in, by ID, are renamed
(entity_names.RENAMEABLE_RESOURCE_TYPES, each checked live): a table entry
per type (_RENAMERS) finds the resource by name or ID, reads its name and
namespace, renames it and clears the lookups the rename makes stale.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    RENAMEABLE_RESOURCE_TYPES,
    RN_APPLICATION,
    RN_GROUP,
    RN_REQUIREMENT_TEMPLATE,
    RN_SOURCE_TEMPLATE,
)
from yellowdog_cli.utils.entity_utils import (
    clear_application_caches,
    clear_compute_requirement_template_cache,
    clear_compute_source_template_cache,
    clear_group_caches,
    get_application_id_by_name,
    get_compute_requirement_template_id_by_name,
    get_compute_source_template_id_by_name,
    get_group_id_by_name,
    split_namespace_and_name,
)
from yellowdog_cli.utils.exit_codes import NotFoundError
from yellowdog_cli.utils.interactive import confirmed
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.printing import print_dry_run, print_info
from yellowdog_cli.utils.results import record_resource
from yellowdog_cli.utils.settings import NAMESPACE_PREFIX_SEPARATOR
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

if TYPE_CHECKING:
    from yellowdog_client import PlatformClient

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Renamer:
    """
    How one resource type is found, read and renamed. 'find_id' takes the
    name and the namespace it is looked for in (None for an account-wide
    type), 'fetch' the ID; 'rename' is given the fetched resource.
    """

    shown: str  # as messages name the type: 'Compute Source Template'
    ydid_type: YDIDType
    namespaced: bool
    find_id: Callable[[PlatformClient, str, str | None], str | None]
    fetch: Callable[[PlatformClient, str], Any]
    name_of: Callable[[Any], str]
    namespace_of: Callable[[Any], str | None]
    rename: Callable[[PlatformClient, Any, str], None]
    clear: Callable[[], None]


def _rename_source_template(client: PlatformClient, template: Any, name: str) -> None:
    # A Compute Source Template's name is its source's
    template.source.name = name
    client.compute_client.update_compute_source_template(template)


def _rename_requirement_template(
    client: PlatformClient, template: Any, name: str
) -> None:
    template.name = name
    client.compute_client.update_compute_requirement_template(template)


def _rename_group(client: PlatformClient, group: Any, name: str) -> None:
    from yellowdog_client.model import UpdateGroupRequest

    client.account_client.update_group(
        group.id, UpdateGroupRequest(name=name, description=group.description)
    )


def _rename_application(client: PlatformClient, application: Any, name: str) -> None:
    from yellowdog_client.model import UpdateApplicationRequest

    client.account_client.update_application(
        application.id,
        UpdateApplicationRequest(name=name, description=application.description),
    )


_RENAMERS: dict[str, _Renamer] = {
    RN_SOURCE_TEMPLATE: _Renamer(
        "Compute Source Template",
        YDIDType.COMPUTE_SOURCE_TEMPLATE,
        True,
        lambda client, name, namespace: get_compute_source_template_id_by_name(
            client, name, namespace
        ),
        lambda client, ydid: client.compute_client.get_compute_source_template(ydid),
        lambda template: template.source.name,
        lambda template: template.namespace,
        _rename_source_template,
        clear_compute_source_template_cache,
    ),
    RN_REQUIREMENT_TEMPLATE: _Renamer(
        "Compute Requirement Template",
        YDIDType.COMPUTE_REQUIREMENT_TEMPLATE,
        True,
        lambda client, name, namespace: get_compute_requirement_template_id_by_name(
            client, name, namespace
        ),
        lambda client, ydid: client.compute_client.get_compute_requirement_template(
            ydid
        ),
        lambda template: template.name,
        lambda template: template.namespace,
        _rename_requirement_template,
        clear_compute_requirement_template_cache,
    ),
    RN_GROUP: _Renamer(
        "Group",
        YDIDType.GROUP,
        False,
        lambda client, name, _namespace: get_group_id_by_name(client, name),
        lambda client, ydid: client.account_client.get_group(ydid),
        lambda group: group.name,
        lambda _group: None,
        _rename_group,
        clear_group_caches,
    ),
    RN_APPLICATION: _Renamer(
        "Application",
        YDIDType.APPLICATION,
        False,
        lambda client, name, _namespace: get_application_id_by_name(client, name),
        lambda client, ydid: client.account_client.get_application(ydid),
        lambda application: application.name,
        lambda _application: None,
        _rename_application,
        clear_application_caches,
    ),
}
assert tuple(_RENAMERS) == RENAMEABLE_RESOURCE_TYPES


def renameable_type_of(ydid: str) -> str | None:
    """
    The resource type a YellowDog ID is of, where it is one rename takes.
    """
    ydid_type = get_ydid_type(ydid)
    return next(
        (
            resource_type
            for resource_type, renamer in _RENAMERS.items()
            if renamer.ydid_type == ydid_type
        ),
        None,
    )


def _qualified(renamer: _Renamer, namespace: str | None, name: str) -> str:
    if renamer.namespaced and namespace:
        return f"{namespace}{NAMESPACE_PREFIX_SEPARATOR}{name}"
    return name


def _fetch(ctx: RunContext, renamer: _Renamer, ydid: str) -> Any:
    """
    The resource with this ID: one that does not exist is NotFoundError.
    """
    try:
        return renamer.fetch(ctx.client, ydid)
    except Exception as e:
        if is_http_not_found(e):
            raise NotFoundError(f"{renamer.shown} {ydid} not found") from e
        raise


def rename_resource(
    ctx: RunContext,
    resource_type: str | None,
    target: str,
    new_name: str,
    dry_run: bool,
) -> None:
    """
    Rename the resource 'target' names (its ID, or its name, as
    'namespace/name' or in the configured namespace for a namespaced type)
    to 'new_name', in the same namespace, keeping its ID. A resource of that
    type already named 'new_name' refuses the rename; one already named so
    is left unchanged. Asks first, unless '--yes'; recorded either way.
    """
    if resource_type is None:
        resource_type = renameable_type_of(target)
        if resource_type is None:
            raise ValueError(
                f"'{target}' is not the ID of a resource that can be renamed;"
                " give --type with a name"
            )
    renamer = _RENAMERS[resource_type]
    if NAMESPACE_PREFIX_SEPARATOR in new_name:
        raise ValueError(
            f"The new name '{new_name}' holds a '{NAMESPACE_PREFIX_SEPARATOR}':"
            " a rename keeps the namespace, so give the name alone"
        )
    if not new_name.strip():
        raise ValueError("The new name is empty")

    if get_ydid_type(target) is not None:
        if get_ydid_type(target) != renamer.ydid_type:
            raise ValueError(f"'{target}' is not the ID of a {renamer.shown}")
        ydid = target
    else:
        namespace, name = split_namespace_and_name(target)
        if not renamer.namespaced and namespace is not None:
            raise ValueError(f"A {renamer.shown} has no namespace: give '{name}' alone")
        namespace = namespace or (ctx.config.namespace if renamer.namespaced else None)
        found = renamer.find_id(ctx.client, str(name), namespace)
        if found is None:
            raise NotFoundError(
                f"{renamer.shown} '{_qualified(renamer, namespace, str(name))}'"
                " not found"
            )
        ydid = found

    resource = _fetch(ctx, renamer, ydid)
    old_name = renamer.name_of(resource)
    namespace = renamer.namespace_of(resource)
    old_shown = _qualified(renamer, namespace, old_name)
    new_shown = _qualified(renamer, namespace, new_name)

    if new_name == old_name:
        print_info(f"{renamer.shown} '{old_shown}' ({ydid}) is already so named")
        record_resource(resource_type, old_name, ydid, "unchanged")
        return

    taken = renamer.find_id(ctx.client, new_name, namespace)
    if taken is not None:
        raise ValueError(
            f"Cannot rename {renamer.shown} '{old_shown}' ({ydid}): '{new_shown}'"
            f" is already the name of {taken}"
        )

    if dry_run:
        print_dry_run(
            f"Would rename {renamer.shown} '{old_shown}' ({ydid}) to '{new_shown}'"
        )
        record_resource(
            resource_type, new_name, ydid, "would rename", previousName=old_name
        )
        return

    if not confirmed(
        f"Rename {renamer.shown} '{old_shown}' ({ydid}) to '{new_shown}'?"
    ):
        record_resource(resource_type, old_name, ydid, "skipped")
        return

    _LOG.debug("renaming %s %s from %s to %s", resource_type, ydid, old_name, new_name)
    renamer.rename(ctx.client, resource, new_name)
    renamer.clear()  # the name lookups cached hold the old name
    print_info(f"Renamed {renamer.shown} '{old_shown}' to '{new_shown}' ({ydid})")
    record_resource(resource_type, new_name, ydid, "renamed", previousName=old_name)
