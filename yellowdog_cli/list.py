#!/usr/bin/env python3

"""
Command to list YellowDog entities.
"""

import fnmatch
import logging
from collections.abc import Callable, Iterable, Iterator
from itertools import chain, islice
from os.path import exists
from typing import Any, TypeVar, cast

from requests import HTTPError, get
from yellowdog_client.common import SearchClient
from yellowdog_client.model import (
    Allowance,
    AllowanceSearch,
    CloudProvider,
    ComputeRequirementStatus,
    ComputeRequirementSummary,
    ComputeRequirementTemplateSummary,
    Group,
    Instance,
    InstanceSearch,
    InstanceStatus,
    KeyringSearch,
    KeyringSummary,
    MachineImageFamilySearch,
    MachineImageFamilySummary,
    Namespace,
    NamespacePolicy,
    NamespacePolicySearch,
    NamespaceSearch,
    Node,
    NodeSearch,
    NodeStatus,
    PermissionDetail,
    Role,
    Task,
    TaskGroup,
    TaskGroupStatus,
    TaskStatus,
    User,
    Worker,
    WorkerPool,
    WorkerPoolStatus,
    WorkerPoolSummary,
    WorkerStatus,
    WorkRequirementStatus,
    WorkRequirementSummary,
)

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    ET_ALLOWANCES,
    ET_APPLICATIONS,
    ET_ATTRIBUTE_DEFINITIONS,
    ET_COMPUTE_REQUIREMENT_TEMPLATES,
    ET_COMPUTE_REQUIREMENTS,
    ET_COMPUTE_SOURCE_TEMPLATES,
    ET_GROUPS,
    ET_IMAGE_FAMILIES,
    ET_INSTANCES,
    ET_KEYRINGS,
    ET_NAMESPACE_POLICIES,
    ET_NAMESPACES,
    ET_NODES,
    ET_PERMISSIONS,
    ET_ROLES,
    ET_TASK_GROUPS,
    ET_TASKS,
    ET_USERS,
    ET_WORK_REQUIREMENTS,
    ET_WORKER_POOLS,
    ET_WORKERS,
    RN_ALLOWANCE,
    RN_APPLICATION,
    RN_GROUP,
    RN_IMAGE_FAMILY,
    RN_KEYRING,
    RN_NAMESPACE,
    RN_NUMERIC_ATTRIBUTE_DEFINITION,
    RN_REQUIREMENT_TEMPLATE,
    RN_ROLE,
    RN_SOURCE_TEMPLATE,
    RN_STRING_ATTRIBUTE_DEFINITION,
)
from yellowdog_cli.utils.entity_utils import (
    filter_phrase,
    filter_summaries_by_name_glob,
    find_compute_requirement_by_name,
    get_all_applications,
    get_all_groups,
    get_all_roles,
    get_all_users,
    get_application_group_summaries,
    get_compute_requirement_summaries,
    get_compute_requirement_templates,
    get_compute_source_templates,
    get_filtered_work_requirement_summaries,
    get_task_groups_from_wr_by_id,
    get_user_attribute_definitions,
    get_user_groups,
    get_worker_pool_by_id,
    get_worker_pool_id_by_name,
    get_worker_pool_summaries,
    iterate_tasks_in_task_group,
    namespace_scope,
    resolve_name_glob,
    search_namespaces,
    substitute_id_for_name_in_allowance,
    substitute_ids_for_names_in_crt,
    substitute_image_family_id_for_name_in_cst,
)
from yellowdog_cli.utils.exit_codes import NotFoundError
from yellowdog_cli.utils.glob_utils import glob_literal_hint, glob_search_prefix
from yellowdog_cli.utils.interactive import confirmed, select
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.output_settings import configure_output
from yellowdog_cli.utils.printing import (
    print_info,
    print_json,
    print_objects_as_json,
    print_warning,
    print_yd_object,
    print_yd_object_list,
)
from yellowdog_cli.utils.property_names import PROP_GROUPS, PROP_RESOURCE
from yellowdog_cli.utils.tables import print_numbered_object_list, sorted_objects
from yellowdog_cli.utils.work_targets import resolve_named_target
from yellowdog_cli.utils.wrapper import main_wrapper
from yellowdog_cli.utils.ydid_utils import (
    YDIDType,
    get_ydid_type,
    work_requirement_id_of_task_group,
)

_LOG = logging.getLogger(__name__)


def _filter_by_name_glob_with_warning(
    objects: list, pattern: str, entity_label: str
) -> list:
    """
    Filter account-global entities by a name glob (client-side, exact-glob on
    '.name'). Warn when entries without a name are excluded — their name is
    optional, so a name pattern can never match them, and dropping them
    silently would understate the result.
    """
    unnamed = sum(1 for obj in objects if getattr(obj, "name", None) is None)
    if unnamed:
        print_warning(
            f"{unnamed} {entity_label}(s) have no name and are excluded from "
            "'--name' pattern matching"
        )
    return filter_summaries_by_name_glob(objects, pattern)


_KNOWN_STATUSES: dict[str, frozenset[str]] = {
    ET_WORK_REQUIREMENTS: frozenset(e.value for e in WorkRequirementStatus),
    ET_TASK_GROUPS: frozenset(e.value for e in TaskGroupStatus),
    ET_TASKS: frozenset(e.value for e in TaskStatus),
    ET_WORKER_POOLS: frozenset(e.value for e in WorkerPoolStatus),
    ET_NODES: frozenset(e.value for e in NodeStatus),
    ET_WORKERS: frozenset(e.value for e in WorkerStatus),
    ET_COMPUTE_REQUIREMENTS: frozenset(e.value for e in ComputeRequirementStatus),
    ET_INSTANCES: frozenset(e.value for e in InstanceStatus),
}


def _apply_count_option(ctx: RunContext) -> None:
    """
    The '--count' option implies '--quiet' and prints only the number of
    matching items, overriding the '--details', '--json' and '--ids-only'
    output options.
    """
    if not ctx.args.count_only:
        return
    ctx.args.quiet = True
    ctx.args.json_output = False
    ctx.args.details = False
    ctx.args.ids_only = False


def _print_json_or_count(ctx: RunContext, objects: list) -> None:
    """
    Final output for the non-interactive aggregate modes: the item count
    for '--count', otherwise a JSON array for '--json'.
    """
    if ctx.args.count_only:
        print(len(objects))
    else:
        print_objects_as_json(objects)


def _listing_all(ctx: RunContext) -> bool:
    """
    The non-interactive modes, which list every matching entity, the
    children of every matching parent included, without asking which:
    '--json', '--count' and '--ids-only'.
    """
    return bool(ctx.args.json_output or ctx.args.count_only or ctx.args.ids_only)


def _print_all(ctx: RunContext, objects: list) -> None:
    """
    Final output for the non-interactive modes: the IDs for '--ids-only',
    otherwise as _print_json_or_count().
    """
    if ctx.args.ids_only:
        for obj in objects:
            print(obj.id)
    else:
        _print_json_or_count(ctx, objects)


def _emit(
    ctx: RunContext,
    objects: list,
    *,
    detail: Callable[[Any], Any] | None = None,
    extra: Callable[[Any], dict] | None = None,
    type_name: str | None = None,
    announce: str | None = None,
) -> None:
    """
    The output the listers share, of what they found (not nothing), sorted:
    the number for '--count'; the objects for '--json', with '--details'
    each as 'detail' gives it (fetched in full, say); their IDs for
    '--ids-only'; otherwise their table ('type_name' naming the type where
    it cannot be told), or with '--details' those selected, each as 'detail'
    gives it with the properties 'extra' adds (its 'resource', a User's
    'groups'), after 'announce' where '--substitute-ids' is given.
    """
    ordered = sorted_objects(objects)
    if ctx.args.json_output or ctx.args.count_only:
        if ctx.args.details and detail is not None:
            print_objects_as_json([detail(obj) for obj in ordered])
        else:
            _print_json_or_count(ctx, ordered)
        return
    if ctx.args.ids_only:
        for obj in ordered:
            print(obj.id)
        return
    if not ctx.args.details:
        print_numbered_object_list(ctx.client, ordered, object_type_name=type_name)
        return
    selected = select(ctx.client, ordered)
    if selected and announce is not None and ctx.args.substitute_ids:
        print_info(announce)
    print_yd_object_list(
        [
            (
                obj if detail is None else detail(obj),
                None if extra is None else extra(obj),
            )
            for obj in selected
        ]
    )


def _print_empty(ctx: RunContext, message: str) -> None:
    """
    Report an empty result: '0' in count mode, otherwise an info message.
    """
    if ctx.args.count_only:
        print(0)
    else:
        print_info(message)


def _apply_status_filter(ctx: RunContext, objects: list) -> list:
    """
    Filter a list of objects to those whose status matches ctx.args.status_filter.
    """
    sf = ctx.args.status_filter
    if not sf:
        return objects
    upper = {s.upper() for s in sf}
    result = []
    for obj in objects:
        status = getattr(obj, "status", None)
        if status is None:
            result.append(obj)
            continue
        try:
            status_str = status.value.upper()
        except AttributeError:
            status_str = str(status).upper()
        if status_str in upper:
            result.append(obj)
    return result


def _apply_name_filter(ctx: RunContext, objects: list, entity_type: str) -> list:
    """
    '--name' on the objects' own names, where they are the type listed: a
    Task's or a Task Group's, never then the Work Requirements or Task Groups
    walked to reach them.
    """
    glob = ctx.args.name_glob
    if not glob or ctx.args.entity_type != entity_type:
        return objects
    return [
        obj
        for obj in objects
        if getattr(obj, "name", None) is not None
        and fnmatch.fnmatchcase(obj.name, glob)
    ]


def _apply_health_filter(ctx: RunContext, objects: list) -> list:
    """
    '--unhealthy': only what the Platform marks unhealthy ('healthy' false).
    """
    if not ctx.args.unhealthy:
        return objects
    return [obj for obj in objects if getattr(obj, "healthy", None) is False]


def _apply_provider_filter(
    ctx: RunContext, objects: list, provider_of: Callable[[Any], Any]
) -> list:
    """
    '--provider': only those whose cloud provider ('provider_of' gives it, a
    CloudProvider or None) is the one named, 'on-premise' for ON_PREMISE.
    """
    if not ctx.args.provider:
        return objects
    wanted = ctx.args.provider.upper().replace("-", "_")
    return [
        obj
        for obj in objects
        if (provider := provider_of(obj)) is not None
        and getattr(provider, "name", str(provider)) == wanted
    ]


def _apply_description_filter(ctx: RunContext, objects: list) -> list:
    """
    '--description': only those whose description matches the glob.
    """
    glob = ctx.args.description_glob
    if not glob:
        return objects
    return [
        obj
        for obj in objects
        if getattr(obj, "description", None) is not None
        and fnmatch.fnmatchcase(obj.description, glob)
    ]


def _task_search_terms(ctx: RunContext) -> dict[str, Any]:
    """
    The Task filters the Platform can apply itself, so a Task Group of
    millions of Tasks sends only what is asked for: '--status' as the Task
    statuses among those given, '--with-errors', and '--name' as a substring
    every match contains (its longest literal run; the Platform's name search
    is a case-sensitive substring, with no wildcards). Empty when there are
    none, or Tasks are not what is listed; the client-side filters still
    decide either way.
    """
    if ctx.args.entity_type != ET_TASKS:
        return {}
    terms: dict[str, Any] = {}
    if ctx.args.status_filter:
        known = _KNOWN_STATUSES[ET_TASKS]
        statuses = {s.upper() for s in ctx.args.status_filter} & known
        if statuses:
            terms["statuses"] = tuple(sorted(statuses))
    if ctx.args.with_errors:
        terms["has_errors"] = True
    if ctx.args.name_glob and (hint := glob_literal_hint(ctx.args.name_glob)):
        terms["name_contains"] = hint
    return terms


def _summary_task_count(ctx: RunContext, task_group: Any) -> int | None:
    """
    Under '--count', a Task Group's own count of the Tasks listed, from its
    'taskSummary' ('taskCount', or with '--status' the matching
    'statusCounts'), so its Tasks, which can number in the millions, are
    not fetched to be counted. None where the summary cannot answer: with
    '--name' or '--with-errors', which it does not count by, or a summary
    that is absent or not numbers.
    """
    if not ctx.args.count_only or ctx.args.name_glob or ctx.args.with_errors:
        return None
    summary = getattr(task_group, "taskSummary", None)
    total = getattr(summary, "taskCount", None)
    counts = getattr(summary, "statusCounts", None)
    if not isinstance(total, int) or not isinstance(counts, dict):
        return None
    if not ctx.args.status_filter:
        return total
    wanted = {status.upper() for status in ctx.args.status_filter}
    return sum(
        count
        for status, count in counts.items()
        if getattr(status, "value", str(status)).upper() in wanted
    )


def _apply_errors_filter(ctx: RunContext, objects: list) -> list:
    """
    '--with-errors': only the Tasks that recorded an error, whatever their
    status.
    """
    if not ctx.args.with_errors:
        return objects
    return [obj for obj in objects if getattr(obj, "errors", None)]


@main_wrapper
def main(ctx: RunContext):
    _adjust_output_options(ctx)

    if ctx.args.output_file and ctx.args.details:
        if exists(ctx.args.output_file):
            if not confirmed(
                f"Overwrite file '{ctx.args.output_file}' with new resource details?"
            ):
                return

    _warn_of_unknown_statuses(ctx)

    # An option that does not apply to the entity type has been refused as
    # the command line was parsed ('check_list_options' in the registry); the
    # type itself is a required positional, so is always given
    _LISTERS[cast(str, ctx.args.entity_type)](ctx)


def _adjust_output_options(ctx: RunContext) -> None:
    """
    Settle the output options the others imply, configuring the output from
    them as they are adjusted.
    """
    _apply_count_option(ctx)

    if not (ctx.args.json_output or ctx.args.count_only):
        ctx.args.interactive = True
    # Output follows the options as adjusted: '--count' is quiet
    configure_output(ctx.args)

    if (
        (
            ctx.args.auto_select_all
            or ctx.args.strip_ids
            or ctx.args.substitute_ids
            or ctx.args.output_file
        )
        and not ctx.args.details
        and not ctx.args.count_only
    ):
        print_info("Automatically setting the '--details' option")
        ctx.args.details = True

    if ctx.args.details and ctx.args.strip_ids:
        _LOG.debug("Stripping YellowDog IDs (etc.) from detailed JSON objects")

    # ... and '--details' as set here
    configure_output(ctx.args)


def _warn_of_unknown_statuses(ctx: RunContext) -> None:
    """
    Warn of a '--status' value the entity type has no status for.
    """
    known = _KNOWN_STATUSES.get(ctx.args.entity_type or "", frozenset())
    if not (ctx.args.status_filter and known):
        return
    unknown = [s for s in ctx.args.status_filter if s.upper() not in known]
    if unknown:
        print_warning(
            f"Unrecognised status value(s): {', '.join(repr(s) for s in unknown)}. "
            f"Known values: {', '.join(sorted(known))}"
        )


def list_work_requirements(ctx: RunContext):
    """
    List Work Requirements whenever --work-requirements, --task-groups or
    --tasks are selected.

    This function falls through from WRs to TGs to Tasks, depending on the
    options chosen.
    """
    if ctx.args.within_target:
        _list_within(ctx)
        return

    if ctx.args.active_only:
        print_info("Listing active Work Requirements only")
    if ctx.args.entity_type == ET_TASKS and ctx.args.with_errors:
        print_info("Listing Tasks with errors only")

    exclude_filter = (
        [
            WorkRequirementStatus.COMPLETED,
            WorkRequirementStatus.CANCELLED,
            WorkRequirementStatus.FAILED,
        ]
        if ctx.args.active_only
        else []
    )
    work_requirement_summaries: list[WorkRequirementSummary]
    if ctx.args.name_glob and ctx.args.entity_type == ET_WORK_REQUIREMENTS:
        namespace, name = resolve_name_glob(ctx.args.name_glob, ctx.config.namespace)
        print_info(
            f"Listing Work Requirements {namespace_scope(ctx.client, namespace)} "
            f"matching name pattern '{name}'"
        )
        work_requirement_summaries = filter_summaries_by_name_glob(
            get_filtered_work_requirement_summaries(
                ctx.client,
                name=glob_search_prefix(name) or None,
                namespace=namespace,
                exclude_filter=exclude_filter,
            ),
            name,
        )
    else:
        print_info(
            f"Listing Work Requirements {namespace_scope(ctx.client, ctx.config.namespace)}"
            + filter_phrase("with '{}' in tag", ctx.config.name_tag),
        )
        work_requirement_summaries = get_filtered_work_requirement_summaries(
            ctx.client,
            namespace=ctx.config.namespace,
            tag=ctx.config.name_tag,
            exclude_filter=exclude_filter,
        )
    if not work_requirement_summaries:
        _print_empty(ctx, "No matching Work Requirements")
        return

    work_requirement_summaries = sorted_objects(work_requirement_summaries)
    if ctx.args.entity_type == ET_WORK_REQUIREMENTS:
        work_requirement_summaries = _apply_health_filter(
            ctx, _apply_status_filter(ctx, work_requirement_summaries)
        )
        if not work_requirement_summaries:
            _print_empty(ctx, "No matching Work Requirements")
            return
        if ctx.args.json_output or ctx.args.count_only:
            if ctx.args.details:
                print_objects_as_json(
                    [
                        ctx.client.work_client.get_work_requirement_by_id(
                            cast(str, wr.id)
                        )
                        for wr in work_requirement_summaries
                    ]
                )
            else:
                _print_json_or_count(ctx, work_requirement_summaries)
        elif ctx.args.details:
            print_yd_object_list(
                [
                    (
                        ctx.client.work_client.get_work_requirement_by_id(
                            cast(str, wr_summary.id)
                        ),
                        None,
                    )  # type: ignore[arg-type]
                    for wr_summary in select(ctx.client, work_requirement_summaries)
                ]
            )
        elif ctx.args.ids_only:
            for wr_summary in work_requirement_summaries:
                print(wr_summary.id)
        else:
            print_numbered_object_list(ctx.client, work_requirement_summaries)
    elif _listing_all(ctx):
        # Collect all task groups / tasks across all work requirements; under
        # '--count', a Task Group whose summary can say how many is counted
        # from it rather than fetched
        all_objects: list = []
        summarised = 0
        limit = _ListLimit(ctx)
        for work_summary in work_requirement_summaries:
            if limit.more:
                break
            tgs = sorted_objects(
                get_task_groups_from_wr_by_id(ctx.client, cast(str, work_summary.id))
            )
            if ctx.args.entity_type == ET_TASK_GROUPS:
                all_objects.extend(_filtered_task_groups(ctx, tgs))
                continue
            counted, tasks = _tasks_of(ctx, tgs, limit)
            summarised += counted
            all_objects.extend(tasks)
        if ctx.args.count_only:
            print(summarised + len(all_objects))
        else:
            _print_all(ctx, all_objects)
        limit.warn()
    else:
        selected_work_summaries = select(
            ctx.client, work_requirement_summaries, single_result=True
        )
        for work_summary in selected_work_summaries:
            print_info(f"Work Requirement '{work_summary.name}'")
            list_task_groups(ctx, work_summary)


def _filtered_task_groups(ctx: RunContext, task_groups: list) -> list:
    """
    The Task Groups that '--name' and '--status' leave.
    """
    return _apply_name_filter(
        ctx, _apply_status_filter(ctx, task_groups), ET_TASK_GROUPS
    )


_Fetched = TypeVar("_Fetched")
_Item = TypeVar("_Item")

# The types '--limit' applies to: as named in its warning (in the singular),
# and the options
# that narrow their listing
_LIMITED = {
    ET_TASKS: ("Task", "--status, --name or --within"),
    ET_INSTANCES: ("Instance", "--status, --provider, --active-only or --within"),
    ET_NODES: ("Node", "--status, --provider, --active-only or --within"),
    ET_WORKERS: ("Worker", "--status, --active-only or --within"),
}


class _ListLimit:
    """
    The Tasks, Instances, Nodes or Workers a listing may still list
    ('--limit'; none under '--count', which is exact, or for another type),
    and whether more matched than it listed. A
    search is read only as far as one item past the limit, to know whether
    more match.
    """

    def __init__(self, ctx: RunContext):
        self._limited = _LIMITED.get(ctx.args.entity_type or "")
        self.limit = (
            ctx.args.list_limit if self._limited and not ctx.args.count_only else 0
        )
        self._left = self.limit or None
        self.more = False

    def take(self, items: Iterable[_Item]) -> list[_Item]:
        """
        As many of the items as the limit leaves room for.
        """
        if self._left is None:
            return list(items)
        if self.more:
            return []
        taken = list(islice(items, self._left + 1))
        if len(taken) > self._left:
            self.more = True
            taken = taken[: self._left]
        self._left -= len(taken)
        return taken

    def warn(self) -> None:
        """
        Say that more matched than were listed, on stderr, '--quiet' or not:
        the listing is incomplete.
        """
        if self.more and self._limited:
            noun, narrowing = self._limited
            listed = noun if self.limit == 1 else f"{self.limit} {noun}s"
            print_warning(
                f"Listed the first {listed}; more match. Narrow the listing"
                f" with {narrowing}, or give --limit 0 to list them all",
                override_quiet=True,
                stderr=True,
            )


def _matching_tasks(ctx: RunContext, task_group: Any) -> Iterator[Task]:
    """
    A Task Group's Tasks that the filters leave, read from its search as they
    are wanted: the Platform applies the filters, '--name' as a substring,
    and its glob is applied here, Task by Task.
    """
    for task in iterate_tasks_in_task_group(
        ctx.client, cast(str, task_group.id), **_task_search_terms(ctx)
    ):
        if _apply_errors_filter(
            ctx,
            _apply_name_filter(ctx, _apply_status_filter(ctx, [task]), ET_TASKS),
        ):
            yield task


def _tasks_of(
    ctx: RunContext, task_groups: list, limit: _ListLimit
) -> tuple[int, list]:
    """
    The Tasks of the given Task Groups that the filters leave, as many as
    'limit' allows: the number counted from Task Groups' summaries under
    '--count' (see _summary_task_count()), and the Tasks fetched from the
    rest.
    """
    summarised = 0
    tasks: list = []
    for tg in task_groups:
        if limit.more:
            break
        if (counted := _summary_task_count(ctx, tg)) is not None:
            summarised += counted
            continue
        tasks.extend(limit.take(_matching_tasks(ctx, tg)))
    return summarised, tasks


def _fetched_within(kind: str, target: str, fetch: Callable[[], _Fetched]) -> _Fetched:
    """
    What fetching the '--within' target by its ID returns, a 404 raised as
    NotFoundError naming it ("Worker Pool '<id>' not found") rather than as
    the Platform's response.
    """
    try:
        return fetch()
    except HTTPError as error:
        if not is_http_not_found(error):
            raise
        raise NotFoundError(f"{kind} '{target}' not found") from error


def _task_groups_within(ctx: RunContext) -> list[TaskGroup]:
    """
    The Task Groups '--within' names: a Work Requirement's, or one Task
    Group, given by YDID or by name as yd-abort takes it ('wr', 'wr/tg',
    'namespace/wr', 'namespace/wr/tg'). A target that names nothing raises
    NotFoundError.
    """
    target = cast(str, ctx.args.within_target)
    match get_ydid_type(target):
        case YDIDType.WORK_REQUIREMENT:
            return _fetched_within(
                "Work Requirement",
                target,
                lambda: get_task_groups_from_wr_by_id(ctx.client, target),
            )
        case YDIDType.TASK_GROUP:
            task_groups = _fetched_within(
                "Task Group",
                target,
                lambda: get_task_groups_from_wr_by_id(
                    ctx.client, work_requirement_id_of_task_group(target)
                ),
            )
            found = [tg for tg in task_groups if tg.id == target]
            if not found:
                raise NotFoundError(f"Task Group '{target}' not found")
            return found
        case None:
            named = resolve_named_target(ctx.client, target, ctx.config.namespace)
            if named.task_group is not None:
                return [named.task_group]
            return get_task_groups_from_wr_by_id(
                ctx.client, cast(str, named.work_requirement.id)
            )
        case other:
            raise ValueError(
                f"'{target}' is a {other.value} ID, not a Work Requirement or"
                " Task Group ID"
            )


def _list_within(ctx: RunContext) -> None:
    """
    '--within': the Task Groups or Tasks of one Work Requirement or Task
    Group, listed without asking which Work Requirement or Task Group.
    """
    errors = " with errors" if ctx.args.with_errors else ""
    print_info(
        f"Listing {ctx.args.entity_type}{errors} within '{ctx.args.within_target}'"
    )
    task_groups = sorted_objects(_task_groups_within(ctx))
    summarised = 0
    limit = _ListLimit(ctx)
    if ctx.args.entity_type == ET_TASK_GROUPS:
        objects = _filtered_task_groups(ctx, task_groups)
    else:
        # Grouped by Task Group, each group's Tasks in order: Tasks sort by
        # their number, which every Task Group's Tasks share
        objects = []
        for task_group in task_groups:
            counted, tasks = _tasks_of(ctx, [task_group], limit)
            summarised += counted
            objects.extend(sorted_objects(tasks))
    if ctx.args.count_only:
        print(summarised + len(objects))
    elif _listing_all(ctx):
        _print_all(ctx, objects)
    elif not objects:
        print_info(f"No matching {ctx.args.entity_type}")
    elif ctx.args.details:
        print_yd_object_list([(obj, None) for obj in select(ctx.client, objects)])
    else:
        print_numbered_object_list(ctx.client, objects)
    limit.warn()


def list_task_groups(ctx: RunContext, work_summary: WorkRequirementSummary):
    task_groups: list[TaskGroup] = get_task_groups_from_wr_by_id(
        ctx.client, cast(str, work_summary.id)
    )
    task_groups = sorted_objects(task_groups)
    # '--status' and '--name' are the Tasks' when listing Tasks, so are no
    # test of the Task Groups walked to reach them
    if ctx.args.entity_type == ET_TASK_GROUPS:
        task_groups = _filtered_task_groups(ctx, task_groups)
    if ctx.args.entity_type != ET_TASKS:
        # Interactive alone: '--ids-only' lists everything, with no choosing
        if ctx.args.details:
            print_yd_object_list(
                [(task_group, None) for task_group in select(ctx.client, task_groups)]
            )
        else:
            print_numbered_object_list(ctx.client, task_groups)
    # Several Task Groups may be chosen; none (the choice cancelled) lists nothing
    elif chosen := select(ctx.client, task_groups):
        list_tasks(ctx, chosen)


def list_tasks(ctx: RunContext, task_groups: list[TaskGroup]):
    """
    The Tasks of the chosen Task Groups, in one table: grouped by Task Group,
    in the Task Groups' order, each group's Tasks in order (the table names
    each Task's Task Group), as many as '--limit' allows.
    """
    limit = _ListLimit(ctx)
    tasks: list[Task] = []
    for task_group in task_groups:
        if limit.more:
            break
        tasks.extend(sorted_objects(limit.take(_matching_tasks(ctx, task_group))))
    if not tasks:
        _print_empty(ctx, f"No matching {ET_TASKS}")
    # Interactive alone, as list_task_groups() is
    elif ctx.args.details:
        print_yd_object_list([(task, None) for task in select(ctx.client, tasks)])
    else:
        print_numbered_object_list(ctx.client, tasks)
    limit.warn()


def _worker_pool_within(ctx: RunContext, target: str) -> WorkerPool:
    """
    The Worker Pool '--within' names: by its ID, or by its name, in the
    configured namespace unless given as 'namespace/name'. A name that
    names nothing raises NotFoundError.
    """
    if get_ydid_type(target) != YDIDType.WORKER_POOL:
        worker_pool_id = get_worker_pool_id_by_name(
            ctx.client, target, ctx.config.namespace
        )
        if worker_pool_id is None:
            raise NotFoundError(f"Worker Pool '{target}' not found")
        target = worker_pool_id
    return _fetched_within(
        "Worker Pool", target, lambda: get_worker_pool_by_id(ctx.client, target)
    )


def _list_nodes_within(ctx: RunContext) -> None:
    """
    '--within' for Nodes and Workers: the Nodes of a Worker Pool, or for
    Workers those of a Worker Pool or of one Node, listed without searching
    for Worker Pools or asking which.
    """
    target = cast(str, ctx.args.within_target)
    print_info(f"Listing {ctx.args.entity_type} within '{target}'")
    if get_ydid_type(target) == YDIDType.NODE:
        node: Node = _fetched_within(
            "Node",
            target,
            lambda: ctx.client.worker_pool_client.get_node_by_id(target),
        )
        node.workerPoolName = get_worker_pool_by_id(  # type: ignore[attr-defined]
            ctx.client, cast(str, node.workerPoolId)
        ).name
        list_workers(ctx, [node])
        return
    list_nodes(ctx, [_worker_pool_within(ctx, target)])  # type: ignore[list-item]


def list_worker_pools(ctx: RunContext):
    if ctx.args.within_target:
        _list_nodes_within(ctx)
        return

    worker_pool_summaries: list[WorkerPoolSummary]
    if ctx.args.name_glob:
        namespace, name = resolve_name_glob(ctx.args.name_glob, ctx.config.namespace)
        print_info(
            f"Displaying Worker Pools {namespace_scope(ctx.client, namespace)} "
            f"matching name pattern '{name}'"
        )
        searched_namespace = namespace
        worker_pool_summaries = filter_summaries_by_name_glob(
            get_worker_pool_summaries(
                ctx.client,
                namespace,
                glob_search_prefix(name) or None,
                partial_name_matches=True,
            ),
            name,
        )
    else:
        print_info(
            f"Displaying Worker Pools {namespace_scope(ctx.client, ctx.config.namespace)}"
            + filter_phrase("with '{}' in name", ctx.config.name_tag)
        )
        worker_pool_summaries = get_worker_pool_summaries(
            ctx.client,
            ctx.config.namespace,
            ctx.config.name_tag,
            partial_name_matches=True,
        )
        searched_namespace = ctx.config.namespace

    excluded_states = (
        [WorkerPoolStatus.TERMINATED, WorkerPoolStatus.SHUTDOWN]
        if ctx.args.active_only
        else []
    )

    if ctx.args.active_only:
        print_info("Displaying active Worker Pools only")

    # Only the namespace searched, matched exactly: a substring match let
    # 'dev' take in 'dev-team'
    worker_pools = [
        wp_summary
        for wp_summary in worker_pool_summaries
        if wp_summary.status not in excluded_states
        and (not searched_namespace or wp_summary.namespace == searched_namespace)
    ]
    # A Worker Pool's own status filters Worker Pools, not their Nodes or
    # Workers, which are filtered on theirs
    worker_pool_summaries = (
        worker_pools
        if ctx.args.entity_type in (ET_NODES, ET_WORKERS)
        else _apply_health_filter(ctx, _apply_status_filter(ctx, worker_pools))
    )

    if not worker_pool_summaries:
        _print_empty(ctx, "No Worker Pools to display")
        return

    if ctx.args.entity_type in (ET_NODES, ET_WORKERS):
        if _listing_all(ctx):
            list_nodes(ctx, worker_pool_summaries)
            return
        print_info(
            "Please select the Worker Pool(s) for which to list "
            f"{'Nodes' if ctx.args.entity_type == ET_NODES else 'Workers'}"
        )
        worker_pool_summaries = cast(
            list[WorkerPoolSummary],
            select(ctx.client, sorted_objects(worker_pool_summaries)),
        )
        list_nodes(ctx, worker_pool_summaries)
        return

    if ctx.args.json_output or ctx.args.count_only:
        if ctx.args.details:
            print_objects_as_json(
                [
                    ctx.client.worker_pool_client.get_worker_pool_by_id(wp.id)  # type: ignore[arg-type]
                    for wp in sorted_objects(worker_pool_summaries)
                ]
            )
        else:
            _print_json_or_count(ctx, sorted_objects(worker_pool_summaries))
    elif ctx.args.details:
        print_yd_object_list(
            [
                (
                    ctx.client.worker_pool_client.get_worker_pool_by_id(
                        worker_pool_summary.id  # type: ignore[arg-type]
                    ),
                    None,
                )
                for worker_pool_summary in select(ctx.client, worker_pool_summaries)
            ]
        )
    elif ctx.args.ids_only:
        for wp_summary in worker_pool_summaries:
            print(wp_summary.id)
    else:
        print_numbered_object_list(ctx.client, sorted_objects(worker_pool_summaries))


# A Compute Requirement still provisioning counts as active
_ACTIVE_CR_STATUSES: tuple[ComputeRequirementStatus, ...] = (
    ComputeRequirementStatus.NEW,
    ComputeRequirementStatus.PROVISIONING,
    ComputeRequirementStatus.STARTING,
    ComputeRequirementStatus.RUNNING,
    ComputeRequirementStatus.STOPPING,
    ComputeRequirementStatus.STOPPED,
    ComputeRequirementStatus.TERMINATING,
)


def _list_instances_within(ctx: RunContext) -> None:
    """
    '--within' for Instances: those of one Compute Requirement, by its ID or
    by its name (found as the actions find one, in the configured namespace
    unless given as 'namespace/name'), listed without searching for Compute
    Requirements or asking which.
    """
    target = cast(str, ctx.args.within_target)
    print_info(f"Listing instances within '{target}'")
    if get_ydid_type(target) == YDIDType.COMPUTE_REQUIREMENT:
        # Fetched, since an Instance search for an ID that names nothing
        # finds nothing rather than failing
        _fetched_within(
            "Compute Requirement",
            target,
            lambda: ctx.client.compute_client.get_compute_requirement_by_id(target),
        )
        compute_requirement_id = target
    else:
        compute_requirement_id = cast(
            str,
            find_compute_requirement_by_name(
                ctx.client,
                target,
                ctx.config.namespace,
                _ACTIVE_CR_STATUSES,
            ).id,
        )
    if _listing_all(ctx):
        _print_all_instances(ctx, [compute_requirement_id])
    else:
        list_instances(ctx, compute_requirement_id)


def _print_all_instances(ctx: RunContext, compute_requirement_ids: list[str]) -> None:
    """
    The Instances of the Compute Requirements, for the non-interactive
    modes: each named as 'cr_id.instance_id' for '--ids-only', the form the
    commands taking an Instance accept.
    """
    limit = _ListLimit(ctx)
    all_instances: list[tuple[str, Instance]] = []
    for compute_requirement_id in compute_requirement_ids:
        if limit.more:
            break
        all_instances.extend(
            (compute_requirement_id, instance)
            for instance in limit.take(_matching_instances(ctx, compute_requirement_id))
        )
    if ctx.args.ids_only:
        for cr_id, instance in all_instances:
            print(f"{cr_id}.{instance.id.instanceId}")  # type: ignore[union-attr]
    else:
        _print_json_or_count(ctx, [instance for _, instance in all_instances])
    limit.warn()


def list_compute_requirements(ctx: RunContext):
    if ctx.args.within_target:
        _list_instances_within(ctx)
        return

    if ctx.args.active_only:
        print_info("Listing active Compute Requirements only")
        included_statuses: list[ComputeRequirementStatus] | None = list(
            _ACTIVE_CR_STATUSES
        )
    else:
        included_statuses = None

    compute_requirement_summaries: list[ComputeRequirementSummary]
    if ctx.args.name_glob:
        namespace, name = resolve_name_glob(ctx.args.name_glob, ctx.config.namespace)
        print_info(
            f"Listing Compute Requirements {namespace_scope(ctx.client, namespace)} "
            f"matching name pattern '{name}'"
        )
        compute_requirement_summaries = filter_summaries_by_name_glob(
            get_compute_requirement_summaries(
                ctx.client,
                namespace,
                None,
                included_statuses,
                name=glob_search_prefix(name) or None,
            ),
            name,
        )
    else:
        print_info(
            f"Listing Compute Requirements {namespace_scope(ctx.client, ctx.config.namespace)}"
            + filter_phrase("with tags including '{}'", ctx.config.name_tag)
        )
        compute_requirement_summaries = get_compute_requirement_summaries(
            ctx.client, ctx.config.namespace, ctx.config.name_tag, included_statuses
        )

    if not compute_requirement_summaries:
        _print_empty(ctx, "No matching Compute Requirements")
        return

    compute_requirement_summaries = sorted_objects(compute_requirement_summaries)
    # A Compute Requirement's own status filters Compute Requirements, not
    # their Instances, which are filtered on theirs
    if ctx.args.entity_type != ET_INSTANCES:
        compute_requirement_summaries = _apply_health_filter(
            ctx, _apply_status_filter(ctx, compute_requirement_summaries)
        )
    if not compute_requirement_summaries:
        _print_empty(ctx, "No matching Compute Requirements")
        return

    if ctx.args.entity_type == ET_INSTANCES:
        if _listing_all(ctx):
            _print_all_instances(
                ctx, [cast(str, cr.id) for cr in compute_requirement_summaries]
            )
            return
        for compute_requirement_summary in select(
            ctx.client, compute_requirement_summaries, single_result=True
        ):
            list_instances(ctx, compute_requirement_summary.id)  # type: ignore[arg-type]
        return

    if ctx.args.json_output or ctx.args.count_only:
        if ctx.args.details:
            print_objects_as_json(
                [
                    ctx.client.compute_client.get_compute_requirement_by_id(
                        cast(str, cr.id)
                    )
                    for cr in compute_requirement_summaries
                ]
            )
        else:
            _print_json_or_count(ctx, compute_requirement_summaries)
    elif ctx.args.details:
        print_yd_object_list(
            [
                (
                    ctx.client.compute_client.get_compute_requirement_by_id(
                        cast(str, compute_requirement.id)
                    ),
                    None,
                )
                for compute_requirement in select(
                    ctx.client, compute_requirement_summaries
                )
            ]
        )
    elif ctx.args.ids_only:
        for compute_requirement_summary in compute_requirement_summaries:
            print(compute_requirement_summary.id)
    else:
        print_numbered_object_list(ctx.client, compute_requirement_summaries)


def _searched_statuses(
    ctx: RunContext, entity_type: str, active: frozenset[str] | None
) -> list[str] | None:
    """
    The statuses to send with a search, by name: those '--status' gives that
    the type has, and under '--active-only' only the 'active' ones among them
    (all of them without '--status'). None to send none, and [] when nothing
    can match, so nothing need be searched.
    """
    statuses: set[str] | None = None
    if ctx.args.status_filter:
        statuses = {s.upper() for s in ctx.args.status_filter} & _KNOWN_STATUSES[
            entity_type
        ]
    if active is not None and ctx.args.active_only:
        statuses = set(active) if statuses is None else statuses & active
    return None if statuses is None else sorted(statuses)


def _searched_providers(ctx: RunContext) -> list[CloudProvider] | None:
    """
    '--provider' as a search sends it: 'on-premise' as ON_PREMISE.
    """
    if not ctx.args.provider:
        return None
    return [CloudProvider[ctx.args.provider.upper().replace("-", "_")]]


# The Instance statuses that are active: any but TERMINATED, as TERMINATING
# is an active Compute Requirement's
_ACTIVE_INSTANCE_STATUSES = frozenset(
    status.value for status in InstanceStatus if status != InstanceStatus.TERMINATED
)


def _matching_instances(
    ctx: RunContext, compute_requirement_id: str
) -> Iterator[Instance]:
    """
    A Compute Requirement's Instances, as --status, --provider and
    --active-only filter them (the Platform first, then here), read from its
    search as they are wanted: an
    Instance's own status, since its Compute Requirement's says nothing of it
    (a RUNNING one holds TERMINATED Instances once scaled down). Active is
    any status but TERMINATED, as TERMINATING is an active Compute
    Requirement's.
    """
    statuses = _searched_statuses(ctx, ET_INSTANCES, _ACTIVE_INSTANCE_STATUSES)
    if statuses == []:
        return
    search_client: SearchClient = ctx.client.compute_client.get_instances(
        instance_search=InstanceSearch(
            computeRequirementId=compute_requirement_id,
            statuses=None
            if statuses is None
            else [InstanceStatus(s) for s in statuses],
            providers=_searched_providers(ctx),
        )
    )
    for instance in search_client.iterate():
        if ctx.args.active_only and (
            _status_name(instance) == InstanceStatus.TERMINATED.value
        ):
            continue
        if _apply_provider_filter(
            ctx,
            _apply_status_filter(ctx, [instance]),
            lambda instance: getattr(instance, "provider", None),
        ):
            yield instance


def _status_name(entity: Any) -> str | None:
    """
    An entity's status as its name, whether an enum or (in a test) a string.
    """
    status = getattr(entity, "status", None)
    return getattr(status, "value", status)


def list_instances(ctx: RunContext, compute_requirement_id: str):
    """
    List the instances within a Compute Requirement.
    """
    limit = _ListLimit(ctx)
    instances = limit.take(_matching_instances(ctx, compute_requirement_id))
    if not instances:
        print_info("No instances to list")
        return

    if ctx.args.public_ips_only:
        print_info("Listing public IP addresses only:")
        for instance in instances:
            if instance.publicIpAddress is not None:
                print(instance.publicIpAddress)
    elif ctx.args.details:
        print_yd_object_list(
            [(instance, None) for instance in select(ctx.client, instances)]
        )
    else:
        print_numbered_object_list(ctx.client, instances)
    limit.warn()


def list_nodes(ctx: RunContext, worker_pool_summaries: list[WorkerPoolSummary]):
    """
    List the Nodes in a list of Worker Pools.
    """
    if ctx.args.entity_type == ET_WORKERS:
        list_workers(
            ctx,
            chain.from_iterable(
                _matching_nodes(ctx, worker_pool_summary)
                for worker_pool_summary in worker_pool_summaries
            ),
        )
        return

    limit = _ListLimit(ctx)
    nodes_all: list[Node] = []
    for worker_pool_summary in worker_pool_summaries:
        if limit.more:
            break
        nodes_all += limit.take(_matching_nodes(ctx, worker_pool_summary))
    if not nodes_all:
        _print_empty(ctx, "No Nodes to display")
        return

    if _listing_all(ctx):
        _print_all(ctx, nodes_all)
    elif ctx.args.details:
        print_yd_object_list([(node, None) for node in select(ctx.client, nodes_all)])
    else:
        print_numbered_object_list(ctx.client, nodes_all)
    limit.warn()


# The Node status that is active
_ACTIVE_NODE_STATUSES = frozenset({NodeStatus.RUNNING.value})


def _matching_nodes(ctx: RunContext, worker_pool_summary: Any) -> Iterator[Node]:
    """
    A Worker Pool's Nodes, as --active-only, --status and --provider filter
    them (the Platform first, then here), read from its search as they are
    wanted, each given its Worker Pool's name. '--status' is the Workers' own
    when Workers are listed, not their Nodes'.
    """
    if ctx.args.entity_type == ET_NODES:
        statuses = _searched_statuses(ctx, ET_NODES, _ACTIVE_NODE_STATUSES)
    else:
        statuses = sorted(_ACTIVE_NODE_STATUSES) if ctx.args.active_only else None
    if statuses == []:
        return
    search_client = ctx.client.worker_pool_client.get_nodes(
        search=NodeSearch(
            worker_pool_summary.id,
            statuses=None if statuses is None else [NodeStatus(s) for s in statuses],
            providers=_searched_providers(ctx),
        )
    )
    for node in search_client.iterate():
        node.workerPoolName = worker_pool_summary.name  # type: ignore[attr-defined]
        kept = [node]
        if ctx.args.entity_type == ET_NODES:
            kept = _apply_status_filter(ctx, kept)
        if _apply_provider_filter(
            ctx, kept, lambda node: node.details.provider if node.details else None
        ):
            yield node


def _matching_workers(ctx: RunContext, nodes: Iterable[Node]) -> Iterator[Worker]:
    """
    The Workers on the Nodes, as --active-only and --status filter them,
    each given its Node's ID, Worker tag, task types and Worker Pool name; the
    Nodes read only as far as the Workers are wanted.
    """
    for node in nodes:
        for worker in node.workers or []:
            # The SDK's own test (RUNNING, BATCH_ALLOCATION and LATE as well
            # as the single-allocation states), not LOST or SHUTDOWN
            if ctx.args.active_only and not (
                isinstance(worker.status, WorkerStatus) and worker.status.available
            ):
                continue
            # Add extra info to the Worker object
            worker.nodeId = node.id  # type: ignore[attr-defined]
            if node.details is not None:
                worker.workerTag = node.details.workerTag  # type: ignore[attr-defined]
                worker.taskTypes = node.details.supportedTaskTypes  # type: ignore[attr-defined]
                worker.workerPoolName = (  # type: ignore[attr-defined]
                    node.workerPoolName  # type: ignore[attr-defined]
                )  # This property is added by the caller
            # Listed whether or not its Node reports details
            if _apply_status_filter(ctx, [worker]):
                yield worker


def list_workers(ctx: RunContext, nodes: Iterable[Node]):
    """
    List the Workers on the Nodes, as many as '--limit' allows.
    """
    limit = _ListLimit(ctx)
    workers_all = limit.take(_matching_workers(ctx, nodes))
    if not workers_all:
        _print_empty(ctx, "No Workers to display")
        return

    if _listing_all(ctx):
        _print_all(ctx, workers_all)
    elif ctx.args.details:
        print_yd_object_list(
            [(worker, None) for worker in select(ctx.client, workers_all)]
        )
    else:
        print_numbered_object_list(ctx.client, workers_all)
    limit.warn()


def _shared_tag(ctx: RunContext) -> str:
    """
    The tag a shared resource (a template, an Image Family) is listed by: the
    one given with '--tag', else none. The configured tag scopes what the
    commands act on (Work Requirements, Worker Pools, Compute Requirements),
    which a listing of those previews; nothing selects a shared resource by
    it, and it would hide those named for no one in particular.
    """
    return "" if ctx.args.tag is None else ctx.config.name_tag


def list_compute_requirement_templates(ctx: RunContext):
    """
    Print the list of Compute Requirement Templates, filtered on Namespace
    and Name. Set these both to empty strings to generate an unfiltered list.
    """
    cr_templates: list[ComputeRequirementTemplateSummary]
    if ctx.args.name_glob:
        namespace, name = resolve_name_glob(ctx.args.name_glob, ctx.config.namespace)
        print_info(
            "Listing Compute Requirement Templates "
            f"{namespace_scope(ctx.client, namespace)} matching name pattern '{name}'"
        )
        cr_templates = filter_summaries_by_name_glob(
            get_compute_requirement_templates(
                ctx.client,
                namespace,
                glob_search_prefix(name) or None,
                partial_name_matches=True,
            ),
            name,
        )
    else:
        print_info(
            "Listing Compute Requirement Templates "
            f"{namespace_scope(ctx.client, ctx.config.namespace)}"
            + filter_phrase("with names including '{}'", _shared_tag(ctx))
        )
        cr_templates = get_compute_requirement_templates(
            ctx.client,
            ctx.config.namespace,
            _shared_tag(ctx),
            partial_name_matches=True,
        )

    if not cr_templates:
        _print_empty(ctx, "No matching Compute Requirement Templates found")
        return

    _emit(
        ctx,
        cr_templates,
        detail=lambda crt: substitute_ids_for_names_in_crt(
            ctx.client,
            ctx.client.compute_client.get_compute_requirement_template(
                cast(str, crt.id)
            ),
            substitute=bool(ctx.args.substitute_ids),
        ),
        extra=lambda _: {PROP_RESOURCE: RN_REQUIREMENT_TEMPLATE},
        announce=(
            "Substituting Compute Source Template IDs and Image Family IDs with names"
        ),
    )


def list_compute_source_templates(ctx: RunContext):
    """
    Print the list of Compute Source Templates, filtered on Namespace
    and Name. Set these both to empty strings to generate an unfiltered list.
    """

    if ctx.args.name_glob:
        namespace, name = resolve_name_glob(ctx.args.name_glob, ctx.config.namespace)
        print_info(
            f"Listing Compute Source Templates {namespace_scope(ctx.client, namespace)} "
            f"matching name pattern '{name}'"
        )
        cs_templates = filter_summaries_by_name_glob(
            get_compute_source_templates(
                ctx.client, namespace=namespace, name=glob_search_prefix(name) or None
            ),
            name,
        )
    else:
        print_info(
            "Listing Compute Source Templates "
            f"{namespace_scope(ctx.client, ctx.config.namespace)}"
            + filter_phrase("with names including '{}'", _shared_tag(ctx))
        )
        cs_templates = get_compute_source_templates(
            ctx.client, namespace=ctx.config.namespace, name=_shared_tag(ctx)
        )

    cs_templates = _apply_provider_filter(
        ctx, cs_templates, lambda template: template.provider
    )
    if not cs_templates:
        _print_empty(ctx, "No matching Compute Source Templates found")
        return

    _emit(
        ctx,
        cs_templates,
        detail=lambda cst: substitute_image_family_id_for_name_in_cst(
            ctx.client,
            ctx.client.compute_client.get_compute_source_template(cst.id),  # type: ignore[arg-type]
            substitute=bool(ctx.args.substitute_ids),
        ),
        extra=lambda _: {PROP_RESOURCE: RN_SOURCE_TEMPLATE},
    )


def list_keyrings(ctx: RunContext):
    """
    Print the list of Keyrings
    """
    # The server search takes a partial name: the glob's literal prefix
    # narrows it, and the glob itself is applied to what comes back
    search_client: SearchClient = ctx.client.keyring_client.get_keyrings(
        KeyringSearch(
            name=(glob_search_prefix(ctx.args.name_glob) or None)
            if ctx.args.name_glob
            else None
        )
    )
    keyrings: list[KeyringSummary] = search_client.list_all()
    if ctx.args.name_glob:
        keyrings = _filter_by_name_glob_with_warning(
            keyrings, ctx.args.name_glob, "Keyring"
        )
    if not keyrings:
        _print_empty(ctx, "No Keyrings found")
        return

    _emit(ctx, keyrings, extra=lambda _: {PROP_RESOURCE: RN_KEYRING})


def list_image_families(ctx: RunContext):
    """
    List the Machine Image Families.
    """
    image_family_summaries: list[MachineImageFamilySummary]
    if ctx.args.name_glob:
        namespace, name = resolve_name_glob(ctx.args.name_glob, ctx.config.namespace)
        print_info(
            f"Listing Machine Image Families {namespace_scope(ctx.client, namespace)} "
            f"matching name pattern '{name}'"
        )
        image_search = MachineImageFamilySearch(
            includePublic=True,
            namespaces=search_namespaces(ctx.client, namespace),
            familyName=glob_search_prefix(name) or None,
        )
        search_client: SearchClient = ctx.client.images_client.get_image_families(
            image_search
        )
        image_family_summaries = filter_summaries_by_name_glob(
            search_client.list_all(), name
        )
        if not image_family_summaries:
            _print_empty(
                ctx,
                "No matching Machine Image Families found "
                f"{namespace_scope(ctx.client, namespace)} matching name pattern '{name}'",
            )
            return
    else:
        image_search = MachineImageFamilySearch(
            includePublic=True,
            namespaces=search_namespaces(ctx.client, ctx.config.namespace),
            familyName=_shared_tag(ctx) or None,  # Supports partial match
        )
        search_client: SearchClient = ctx.client.images_client.get_image_families(
            image_search
        )
        image_family_summaries = search_client.list_all()
        if not image_family_summaries:
            _print_empty(
                ctx,
                "No matching Machine Image Families found "
                f"{namespace_scope(ctx.client, ctx.config.namespace)}"
                + filter_phrase("with names including '{}'", _shared_tag(ctx)),
            )
            return

    _emit(
        ctx,
        image_family_summaries,
        detail=lambda family: ctx.client.images_client.get_image_family_by_id(
            family.id  # type: ignore[arg-type]
        ),
        extra=lambda _: {PROP_RESOURCE: RN_IMAGE_FAMILY},
    )


def list_allowances(ctx: RunContext):
    """
    List allowances.
    """
    allowances_search = AllowanceSearch()
    search_client: SearchClient = ctx.client.allowances_client.get_allowances(
        allowances_search
    )
    allowances: list[Allowance] = _apply_description_filter(
        ctx, sorted_objects(search_client.list_all())
    )
    if not allowances:
        _print_empty(ctx, "No Allowances to display")
        return

    _emit(
        ctx,
        allowances,
        detail=lambda allowance: substitute_id_for_name_in_allowance(
            ctx.client,
            allowance,  # type: ignore[arg-type]
            substitute=bool(ctx.args.substitute_ids),
        ),
        extra=lambda _: {PROP_RESOURCE: RN_ALLOWANCE},
        announce=(
            "Substituting Compute Requirement Template IDs with names (if applicable)"
        ),
    )


def list_attribute_definitions(ctx: RunContext):
    """
    List user compute attribute definitions using the API.
    """
    attribute_definition_list = get_user_attribute_definitions(ctx.config)

    if ctx.args.json_output or ctx.args.count_only:
        _print_json_or_count(ctx, attribute_definition_list)
        return

    if not ctx.args.details:
        print_numbered_object_list(
            ctx.client,
            attribute_definition_list,
            object_type_name="Attribute Definition",
        )
        return

    # Show details
    attribute_definition_list = [
        (
            attribute,
            {
                PROP_RESOURCE: (
                    RN_NUMERIC_ATTRIBUTE_DEFINITION
                    if "Numeric" in attribute["type"]
                    else RN_STRING_ATTRIBUTE_DEFINITION
                )
            },
        )
        for attribute in select(
            ctx.client,
            attribute_definition_list,
            object_type_name="Attribute Definition",
            sort_objects=False,
        )
    ]
    print_yd_object_list(attribute_definition_list)  # type: ignore[arg-type]


def list_namespaces(ctx: RunContext):
    """
    List namespaces: with '--name', those whose name matches the glob (the
    search narrowed to names containing its literal prefix, since the
    Platform matches a substring); with '--deletable', only those the
    Platform can delete, never having been populated.
    """
    name_glob = ctx.args.name_glob
    namespaces: list[Namespace] = ctx.client.namespaces_client.get_namespaces(
        NamespaceSearch(
            namespaceContains=(glob_search_prefix(name_glob) or None)
            if name_glob
            else None,
            deletable=True if ctx.args.deletable else None,
        )
    ).list_all()
    if name_glob:
        namespaces = [
            ns
            for ns in namespaces
            if ns.namespace is not None and fnmatch.fnmatchcase(ns.namespace, name_glob)
        ]

    if not namespaces:
        _print_empty(ctx, "No Namespaces found")
        return
    _emit(ctx, namespaces, extra=lambda _: {PROP_RESOURCE: RN_NAMESPACE})


def list_namespace_policies(ctx: RunContext):
    """
    List namespace policies.
    """

    np_search = NamespacePolicySearch(namespaces=search_namespaces(ctx.client, None))
    search_client: SearchClient = ctx.client.namespaces_client.get_namespace_policies(
        np_search
    )
    namespace_policies: list[NamespacePolicy] = search_client.list_all()
    if not namespace_policies:
        _print_empty(ctx, "No Namespace Policies to display")
        return
    namespace_policies = sorted_objects(namespace_policies)

    if ctx.args.json_output or ctx.args.count_only:
        _print_json_or_count(ctx, namespace_policies)
        return

    if not ctx.args.details:
        print_numbered_object_list(ctx.client, namespace_policies)
        return

    for selected_namespace_policy in select(
        ctx.client, namespace_policies, object_type_name="Namespace Policy"
    ):
        if selected_namespace_policy.autoscalingMaxNodes is None:
            print_yd_object(selected_namespace_policy)
        else:
            details = get_autoscaling_capacity(ctx, selected_namespace_policy.namespace)
            details["autoscalingMaxNodes"] = (
                selected_namespace_policy.autoscalingMaxNodes
            )
            print_json(details)


def list_users(ctx: RunContext):
    """
    List all users in the account.
    """
    users: list[User] = get_all_users(ctx.client)

    if ctx.args.name_glob:
        users = _filter_by_name_glob_with_warning(users, ctx.args.name_glob, "User")

    if not users:
        _print_empty(ctx, "No Users to display")
        return

    # With '--details', each User's Groups by name, as yd-create takes them
    _emit(
        ctx,
        users,
        type_name="User",
        extra=lambda user: {
            PROP_GROUPS: [
                group.name
                for group in get_user_groups(ctx.client, user.id)  # type: ignore[arg-type]
            ],
            PROP_RESOURCE: user.__class__.__name__,
        },
    )


def list_applications(ctx: RunContext):
    """
    List all applications in the account.
    """
    applications = get_all_applications(ctx.client)

    if ctx.args.name_glob:
        applications = _filter_by_name_glob_with_warning(
            applications, ctx.args.name_glob, "Application"
        )

    if not applications:
        _print_empty(ctx, "No Applications to display")
        return

    # With '--details', each Application's Groups by name
    _emit(
        ctx,
        applications,
        type_name="Application",
        extra=lambda application: {
            PROP_GROUPS: [
                group.name
                for group in get_application_group_summaries(ctx.client, application.id)
            ],
            PROP_RESOURCE: RN_APPLICATION,
        },
    )


def list_groups(ctx: RunContext):
    """
    List all groups in the account.
    """
    group_summaries = get_all_groups(ctx.client)

    if ctx.args.name_glob:
        group_summaries = _filter_by_name_glob_with_warning(
            group_summaries, ctx.args.name_glob, "Group"
        )

    if not group_summaries:
        _print_empty(ctx, "No Groups to display")
        return

    group_summaries = sorted_objects(group_summaries)

    # The summaries are enough to count the Groups or give their IDs; the
    # table, '--json' and '--details' show each one's roles, which only the
    # Group itself carries, so it is fetched, one call each, only for those
    if ctx.args.count_only:
        print(len(group_summaries))
        return

    if ctx.args.ids_only:
        for group_summary in group_summaries:
            print(group_summary.id)
        return

    groups: list[Group] = [
        ctx.client.account_client.get_group(cast(str, group.id))
        for group in group_summaries
    ]

    if ctx.args.json_output:
        print_objects_as_json(groups)
        return

    if not ctx.args.details:
        print_numbered_object_list(ctx.client, groups, object_type_name="Group")
        return

    print_yd_object_list(
        [(group, {PROP_RESOURCE: RN_GROUP}) for group in select(ctx.client, groups)]
    )


def list_roles(ctx: RunContext):
    """
    List all roles in the account.
    """
    role_summaries = get_all_roles(ctx.client)

    if ctx.args.name_glob:
        role_summaries = _filter_by_name_glob_with_warning(
            role_summaries, ctx.args.name_glob, "Role"
        )

    if not role_summaries:
        _print_empty(ctx, "No Roles to display")
        return

    role_summaries = sorted_objects(role_summaries)

    # The summaries are enough to count the Roles or give their IDs; the
    # table, '--json' and '--details' show each one's permissions, which only
    # the Role itself carries, so it is fetched, one call each, only for those
    if ctx.args.count_only:
        print(len(role_summaries))
        return

    if ctx.args.ids_only:
        for role_summary in role_summaries:
            print(role_summary.id)
        return

    print_info("Obtaining permissions for each role ...")
    roles: list[Role] = [
        ctx.client.account_client.get_role(cast(str, role.id))
        for role in role_summaries
    ]
    # Sort permissions alphabetically (contorting the type)
    for role in roles:
        role.permissions = list(role.permissions)
        role.permissions.sort(key=lambda permission: permission.name)

    if ctx.args.json_output:
        print_objects_as_json(roles)
        return

    if not ctx.args.details:
        print_numbered_object_list(ctx.client, roles, object_type_name="Role")
        return

    print_yd_object_list(
        [(role, {PROP_RESOURCE: RN_ROLE}) for role in select(ctx.client, roles)]
    )


def list_permissions(ctx: RunContext):
    """
    List all permissions in the account.
    """
    permissions: list[PermissionDetail] = ctx.client.account_client.list_permissions()
    if ctx.args.name_glob:
        permissions = _filter_by_name_glob_with_warning(
            permissions, ctx.args.name_glob, "Permission"
        )
    permissions.sort(key=lambda permission_: permission_.name)  # type: ignore[arg-type]

    if ctx.args.json_output or ctx.args.count_only:
        _print_json_or_count(ctx, permissions)
        return

    if not ctx.args.details:
        print_numbered_object_list(
            ctx.client, permissions, object_type_name="Permission"
        )
        return

    for permission in select(ctx.client, permissions, object_type_name="Permission"):
        print_yd_object(permission)


def get_autoscaling_capacity(ctx: RunContext, namespace: str) -> dict:
    """
    Get the current autoscaling values for a namespace.
    """
    response = get(
        url=f"{ctx.config.url}/workerPools/namespaces/{namespace}/autoscalingCapacity",
        headers={"Authorization": f"yd-key {ctx.config.key}:{ctx.config.secret}"},
        timeout=ctx.config.request_timeout,
    )
    if response.status_code == 200:
        return response.json()
    else:
        print_warning(
            f"Failed to get autoscaling details for namespace '{namespace}' ({response.text})"
        )
        return {"namespace": namespace}


# The function listing each entity type; one listing a parent's children lists
# the parent's type too. Every type yd-list accepts, held to that by
# tests/test_list.py
_LISTERS: dict[str, Callable[[RunContext], None]] = {
    ET_WORK_REQUIREMENTS: list_work_requirements,
    ET_TASK_GROUPS: list_work_requirements,
    ET_TASKS: list_work_requirements,
    ET_WORKER_POOLS: list_worker_pools,
    ET_NODES: list_worker_pools,
    ET_WORKERS: list_worker_pools,
    ET_COMPUTE_REQUIREMENTS: list_compute_requirements,
    ET_INSTANCES: list_compute_requirements,
    ET_COMPUTE_REQUIREMENT_TEMPLATES: list_compute_requirement_templates,
    ET_COMPUTE_SOURCE_TEMPLATES: list_compute_source_templates,
    ET_KEYRINGS: list_keyrings,
    ET_IMAGE_FAMILIES: list_image_families,
    ET_ALLOWANCES: list_allowances,
    ET_ATTRIBUTE_DEFINITIONS: list_attribute_definitions,
    ET_NAMESPACES: list_namespaces,
    ET_NAMESPACE_POLICIES: list_namespace_policies,
    ET_USERS: list_users,
    ET_APPLICATIONS: list_applications,
    ET_GROUPS: list_groups,
    ET_ROLES: list_roles,
    ET_PERMISSIONS: list_permissions,
}


# Entry point
if __name__ == "__main__":
    main()
