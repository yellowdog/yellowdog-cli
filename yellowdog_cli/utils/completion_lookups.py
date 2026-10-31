"""
Tab completion's Platform lookups: the names or IDs a LookupRequest asks
for (utils/completion.py), as yd-completion offers them.

The configuration is loaded as the command's own would be, by load_config,
under the options typed on the line (the request's settings), so the
namespace, tag and credentials are the command's. The entities are those
the command selects, as 'yd-list' lists them -- Work Requirements and
Compute Requirements by tag, Worker Pools by the tag in their name, '-t'
and '-n' typed on the line taking precedence; for '--within', which resolves
a name in the namespace, whatever their tag -- in the statuses the verb acts
on, newest first and at most LOOKUP_MAX_ITEMS of them. After 'wr/', a
Work Requirement's Task Groups are offered, as 'wr/tg', and after 'wr/tg/'
for a Task's verbs, the Task Group's Tasks, as 'wr/tg/task' (or, where no
such Task Group is found, 'namespace/wr/' read as a Work Requirement's). The
answer is kept for the Tabs that follow (utils/completion_cache.py), unless
nothing was found.

candidates() never raises: whatever fails -- no configuration, no
credentials, no connection, a refused search -- offers nothing, since a
traceback, or a message, would land in the user's command line. The SDK
and entity_utils are imported only inside the functions that need them, so
importing this module costs nothing until a lookup is made.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from itertools import islice
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from yellowdog_cli.utils import completion_cache
from yellowdog_cli.utils.completion import Candidate, LookupRequest
from yellowdog_cli.utils.completion_targets import Lookup
from yellowdog_cli.utils.config_types import ConfigCommon
from yellowdog_cli.utils.entity_names import (
    ET_COMPUTE_REQUIREMENTS,
    ET_WORK_REQUIREMENTS,
    ET_WORKER_POOLS,
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
)
from yellowdog_cli.utils.limits import LOOKUP_MAX_ITEMS, LOOKUP_TIMEOUT_SECONDS

if TYPE_CHECKING:
    from yellowdog_client import PlatformClient


def candidates(request: LookupRequest) -> tuple[Candidate, ...]:
    """
    What the lookup offers for the word being completed, or nothing if
    anything at all goes wrong.
    """
    try:
        common = _load_common(request.settings)
        if common is None:
            return ()
        if request.lookup.tasks and request.current.count("/") >= 2:
            parent, _, typed = request.current.rpartition("/")
            items = _task_items(common, parent, typed, request.lookup)
            return _offered(items or _task_group_items(common, parent), request)
        if request.lookup.task_groups and "/" in request.current:
            parent = request.current.rpartition("/")[0]
            return _offered(_task_group_items(common, parent), request)
        resource_type = request.lookup.resource
        if resource_type == RN_CREDENTIAL and "/" in request.current:
            keyring = request.current.partition("/")[0]
            return _offered(_credential_items(common, keyring), request)
        if resource_type is not None:
            return _offered(_resource_items(common, resource_type), request)
        return _offered(_items(common, request.lookup), request)
    except Exception:
        return ()


def _load_common(settings: dict[str, object]) -> ConfigCommon | None:
    """
    The [common] configuration, loaded as the command would load it under
    the options typed, or None if it cannot be: a missing file, a broken
    one, or no credentials, which load_config reports by exiting.
    """
    from yellowdog_cli.utils import load_config

    args = SimpleNamespace(**settings, namespace_required=False, tag_required=False)
    try:
        load_config.ensure_config_loaded(args)
        return load_config.load_config_common(strict=True)
    except SystemExit:
        return None


def _client(common: ConfigCommon) -> PlatformClient:
    """
    A Platform client for the configuration, as the command wrapper builds
    one, but waiting for a response no longer than a Tab's lookup may take.
    """
    from datetime import timedelta

    from yellowdog_client import PlatformClient
    from yellowdog_client.model import ApiKey, ServicesSchema

    from yellowdog_cli.utils.user_agent import set_user_agent

    set_user_agent()
    assert common.key is not None and common.secret is not None
    return PlatformClient.create(
        ServicesSchema(
            defaultUrl=common.url,
            readTimeout=timedelta(seconds=LOOKUP_TIMEOUT_SECONDS),
        ),
        ApiKey(common.key, common.secret),
    )


def _items(common: ConfigCommon, lookup: Lookup) -> list[dict[str, Any]]:
    """
    The entities the lookup is for, from the cache or else the Platform.
    """
    tag = common.name_tag if lookup.tagged else ""
    key = completion_cache.cache_key(
        common.url,
        common.key or "",
        common.namespace,
        tag,
        lookup.entity,
        ",".join(sorted(lookup.statuses or ())) if lookup.statuses else "*",
        str(lookup.configured_only),
        str(lookup.tagged),
    )
    cached = completion_cache.read(key)
    if cached is not None:
        return cached
    client = _client(common)
    try:
        items = _fetch(client, lookup, common.namespace, tag)
    finally:
        client.close()
    # Nothing found is not kept: it is the answer likeliest to be out of date
    # a moment later (a Work Requirement just submitted), and asking again
    # costs one search
    if items:
        completion_cache.write(key, items)
    return items


def _cached(
    common: ConfigCommon,
    parts: tuple[str, ...],
    fetch: Callable[[PlatformClient], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """
    What 'fetch' finds, from the cache or else the Platform, kept for the
    Tabs that follow unless it found nothing.
    """
    key = completion_cache.cache_key(
        common.url, common.key or "", common.namespace, *parts
    )
    cached = completion_cache.read(key)
    if cached is not None:
        return cached
    client = _client(common)
    try:
        items = fetch(client)
    finally:
        client.close()
    if items:
        completion_cache.write(key, items)
    return items


def _item(name: str | None, id_: str | None = None) -> dict[str, Any]:
    return {"id": id_, "name": name, "status": None}


def _capped(items: Iterable[Any]) -> list[Any]:
    return list(islice(items, LOOKUP_MAX_ITEMS))


def _resource_items(common: ConfigCommon, resource_type: str) -> list[dict[str, Any]]:
    """
    The names of a resource type, as 'yd resource remove' and 'show' take
    them after '--type'.
    """
    return _cached(
        common,
        ("resources", resource_type),
        lambda client: _fetch_resources(client, common, resource_type),
    )


def _credential_items(common: ConfigCommon, keyring: str) -> list[dict[str, Any]]:
    """
    A Keyring's Credentials, each named 'keyring/credential'.
    """

    def fetch(client: PlatformClient) -> list[dict[str, Any]]:
        from yellowdog_cli.utils import entity_utils

        summary = entity_utils.get_keyring_summary_by_name(client, keyring)
        if summary is None:
            return []
        found = client.keyring_client.get_keyring(cast(str, summary.id))
        return [
            _item(f"{keyring}/{credential.name}")
            for credential in _capped(found.credentials or [])
            if credential.name
        ]

    return _cached(common, ("credentials", keyring), fetch)


def _fetch_resources(
    client: PlatformClient, common: ConfigCommon, resource_type: str
) -> list[dict[str, Any]]:
    """
    The resources of a type, as items named as the commands take them: a
    Namespace Policy by its namespace, a User by its username (or name), an
    Allowance by its ID described by its description, and a namespaced type
    (a template, an Image Family, a Configured Worker Pool) in the configured
    namespace, by name.
    """
    from yellowdog_client.model import (
        AllowanceSearch,
        InternalUser,
        KeyringSearch,
        NamespacePolicySearch,
        NamespaceSearch,
    )

    from yellowdog_cli.utils import entity_utils

    namespace = common.namespace
    if resource_type in (RN_KEYRING, RN_CREDENTIAL):
        found = client.keyring_client.get_keyrings(KeyringSearch()).iterate()
        return [_item(k.name, k.id) for k in _capped(found)]
    if resource_type == RN_NAMESPACE:
        found = client.namespaces_client.get_namespaces(NamespaceSearch()).iterate()
        return [_item(n.namespace, n.id) for n in _capped(found)]
    if resource_type == RN_NAMESPACE_POLICY:
        found = client.namespaces_client.get_namespace_policies(
            NamespacePolicySearch(
                namespaces=entity_utils.search_namespaces(client, None)
            )
        ).iterate()
        return [_item(p.namespace) for p in _capped(found)]
    if resource_type == RN_GROUP:
        return [
            _item(g.name, g.id) for g in _capped(entity_utils.get_all_groups(client))
        ]
    if resource_type == RN_APPLICATION:
        return [
            _item(a.name, a.id)
            for a in _capped(entity_utils.get_all_applications(client))
        ]
    if resource_type in (RN_INTERNAL_USER, RN_EXTERNAL_USER):
        return [
            _item(
                (u.username or u.name) if isinstance(u, InternalUser) else u.name, u.id
            )
            for u in _capped(entity_utils.get_all_users(client))
        ]
    if resource_type in (RN_SOURCE_TEMPLATE, RN_REQUIREMENT_TEMPLATE, RN_IMAGE_FAMILY):
        search = {
            RN_SOURCE_TEMPLATE: entity_utils.get_compute_source_templates,
            RN_REQUIREMENT_TEMPLATE: entity_utils.get_compute_requirement_templates,
            RN_IMAGE_FAMILY: entity_utils.get_image_family_summaries,
        }[resource_type]
        return [
            _item(t.name, t.id)
            for t in _capped(search(client, namespace))
            if not namespace or t.namespace == namespace
        ]
    if resource_type == RN_CONFIGURED_POOL:
        pools = Lookup(
            ET_WORKER_POOLS,
            ids=False,
            statuses=None,
            configured_only=True,
            tagged=False,
        )
        return _fetch(client, pools, namespace, "")
    if resource_type in (
        RN_STRING_ATTRIBUTE_DEFINITION,
        RN_NUMERIC_ATTRIBUTE_DEFINITION,
    ):
        numeric = resource_type == RN_NUMERIC_ATTRIBUTE_DEFINITION
        return [
            _item(d.get("name"))
            for d in entity_utils.get_user_attribute_definitions(common)
            if ("Numeric" in str(d.get("type", ""))) is numeric
        ][:LOOKUP_MAX_ITEMS]
    if resource_type == RN_ALLOWANCE:
        found = client.allowances_client.get_allowances(AllowanceSearch()).iterate()
        return [_item(a.description or "", a.id) for a in _capped(found)]
    return []


def _task_group_items(common: ConfigCommon, parent: str) -> list[dict[str, Any]]:
    """
    The Task Groups of the Work Requirement named 'parent' ('wr' or
    'namespace/wr', as '--within' reads it), each named 'parent/tg', from
    the cache or else the Platform.
    """
    key = completion_cache.cache_key(
        common.url, common.key or "", common.namespace, "task-groups", parent
    )
    cached = completion_cache.read(key)
    if cached is not None:
        return cached
    from yellowdog_cli.utils.entity_utils import (
        find_work_requirement_by_name,
        get_task_groups_from_wr_by_id,
    )

    client = _client(common)
    try:
        work_requirement = find_work_requirement_by_name(
            client, parent, common.namespace, statuses=()
        )
        items = [
            {
                "id": task_group.id,
                "name": f"{parent}/{task_group.name}",
                "status": getattr(task_group.status, "name", None),
            }
            for task_group in get_task_groups_from_wr_by_id(client, work_requirement.id)
            if task_group.name
        ]
    finally:
        client.close()
    if items:
        completion_cache.write(key, items)
    return items


def _task_items(
    common: ConfigCommon, parent: str, typed: str, lookup: Lookup
) -> list[dict[str, Any]]:
    """
    The Tasks of the Task Group named 'parent' ('wr/tg' or 'namespace/wr/tg')
    whose names contain what is typed of the Task's ('typed', the Platform
    filtering), in the lookup's Task statuses, each named 'parent/task': at
    most LOOKUP_MAX_ITEMS, from the cache or else the Platform. None where
    there is no such Task Group.
    """
    key = completion_cache.cache_key(
        common.url,
        common.key or "",
        common.namespace,
        "tasks",
        parent,
        typed,
        ",".join(sorted(lookup.task_statuses or ())) or "*",
    )
    cached = completion_cache.read(key)
    if cached is not None:
        return cached
    from yellowdog_cli.utils.entity_utils import (
        AmbiguousNameError,
        find_work_requirement_by_name,
        get_task_groups_from_wr_by_id,
        iterate_tasks_in_task_group,
    )
    from yellowdog_cli.utils.exit_codes import NotFoundError

    work_requirement_name, _, task_group_name = parent.rpartition("/")
    if not work_requirement_name:
        return []
    client = _client(common)
    try:
        try:
            work_requirement = find_work_requirement_by_name(
                client, work_requirement_name, common.namespace, statuses=()
            )
        except (NotFoundError, AmbiguousNameError):
            # 'namespace/wr/' perhaps, for the caller to read as that
            return []
        task_group = next(
            (
                task_group
                for task_group in get_task_groups_from_wr_by_id(
                    client, work_requirement.id
                )
                if task_group.name == task_group_name
            ),
            None,
        )
        if task_group is None:
            return []
        found = iterate_tasks_in_task_group(
            client,
            cast(str, task_group.id),
            statuses=(
                tuple(sorted(lookup.task_statuses))
                if lookup.task_statuses is not None
                else None
            ),
            name_contains=typed or None,
        )
        items = [
            {
                "id": task.id,
                "name": f"{parent}/{task.name}",
                "status": getattr(task.status, "name", None),
            }
            for task in _capped(found)
            if task.name
        ]
    finally:
        client.close()
    if items:
        completion_cache.write(key, items)
    return items


def _fetch(
    client: PlatformClient, lookup: Lookup, namespace: str, tag: str
) -> list[dict[str, Any]]:
    """
    Search for the entities, as the command selects them, newest first:
    one page of LOOKUP_MAX_ITEMS.
    """
    from yellowdog_client.model import (
        ComputeRequirementStatus,
        ComputeRequirementSummarySearch,
        SliceReference,
        SortDirection,
        WorkerPoolSearch,
        WorkerPoolStatus,
        WorkRequirementSearch,
        WorkRequirementStatus,
    )

    from yellowdog_cli.utils.entity_utils import search_namespaces

    namespaces = search_namespaces(client, namespace)
    sorting: dict[str, Any] = {
        "sortField": "createdTime",
        "sortDirection": SortDirection.DESCENDING,
    }
    statuses = sorted(lookup.statuses) if lookup.statuses is not None else None
    if lookup.entity == ET_WORK_REQUIREMENTS:
        search = client.work_client.get_work_requirements(
            WorkRequirementSearch(
                namespaces=namespaces,
                tag=tag or None,
                statuses=_enums(WorkRequirementStatus, statuses),
                **sorting,
            )
        )
    elif lookup.entity == ET_COMPUTE_REQUIREMENTS:
        search = client.compute_client.get_compute_requirement_summaries(
            ComputeRequirementSummarySearch(
                namespaces=namespaces,
                tag=tag or None,
                statuses=_enums(ComputeRequirementStatus, statuses),
                **sorting,
            )
        )
    elif lookup.entity == ET_WORKER_POOLS:
        search = client.worker_pool_client.get_worker_pools(
            WorkerPoolSearch(
                namespaces=namespaces,
                name=tag or None,
                statuses=_enums(WorkerPoolStatus, statuses),
                **sorting,
            )
        )
    else:
        return []
    # One page of LOOKUP_MAX_ITEMS: paging at the server's default size
    # could cost several round trips within the Tab's time limit
    page = search.slice(SliceReference(size=LOOKUP_MAX_ITEMS))
    summaries = [
        summary for summary in page.items or [] if _selected(summary, lookup, tag)
    ]
    summaries.sort(key=_created, reverse=True)
    return [
        {
            "id": summary.id,
            "name": summary.name,
            "status": getattr(summary.status, "name", None),
        }
        for summary in summaries
    ]


def _enums(enum: Any, names: list[str] | None) -> list[Any] | None:
    return None if names is None else [enum[name] for name in names]


def _selected(summary: Any, lookup: Lookup, tag: str) -> bool:
    """
    Whether the command would take the entity, as 'yd-list' lists it: it has
    a name; a Worker Pool's holds the tag (the search matches a name
    partially); and only a Configured Worker Pool has a token.
    """
    if summary.name is None:
        return False
    if lookup.entity != ET_WORKER_POOLS:
        return True
    if tag not in summary.name:
        return False
    return not (
        lookup.configured_only
        and (summary.type or "").split(".")[-1] != RN_CONFIGURED_POOL
    )


def _created(summary: Any) -> float:
    created = summary.createdTime
    return created.timestamp() if created is not None else 0.0


def _offered(
    items: list[dict[str, Any]], request: LookupRequest
) -> tuple[Candidate, ...]:
    """
    The candidates for the word being completed: names described by status,
    or IDs described by name and status (by name alone with no status), each
    once, in the order found, leaving out those typed already. An item of
    any other shape -- a cache file written by something else -- is passed
    over.
    """
    offered: dict[str, Candidate] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name, status = item.get("name"), item.get("status")
        if not isinstance(name, str):
            continue
        status = status if isinstance(status, str) else ""
        if request.lookup.ids:
            value = item.get("id")
            description = f"{name} ({status})" if status else name
        else:
            value, description = name, status
        if (
            isinstance(value, str)
            and value.startswith(request.current)
            and value not in request.given
            and value not in offered
        ):
            offered[value] = Candidate(value, description)
    return tuple(offered.values())
