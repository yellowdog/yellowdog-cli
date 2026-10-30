"""
Targets given by name to the noun verbs that otherwise take YellowDog IDs
(yd-show, yd-follow, yd-wait and yd-compare as 'yd <noun> <verb>'): each name
looked up as the type the noun gives it, and replaced by its ID; an ID is
left as it is. A Work Requirement, Worker Pool or Compute Requirement is
'name', a Task Group 'wr/tg' and a Task 'wr/tg/task', each with a leading
'namespace/' to look in another namespace than the configured one
('--namespace'). A name finds its object whether it is live or finished:
a live one if there is one, else, a Work Requirement's or Compute
Requirement's name being reusable once it has finished, the newest.

A name pattern (a name holding '*', '?' or '[', which no name can) stands
for every object of the type whose name it matches, exactly as 'yd list
--name' matches: in the last part alone ('wr/tg-*', never 'wr-*/tg'), and
for yd-follow and yd-wait only among the unfinished ('live_only'). A pattern
matching nothing is reported as a name finding nothing is.

Every name is looked up before anything else is done, and those that find
nothing are reported together; a failure every later lookup would repeat
(authentication, connection) is raised as it is, for the wrapper. An object
named twice (by its ID and a pattern, or two patterns) is given once.
"""

from __future__ import annotations

import fnmatch
import logging
from collections.abc import Callable
from itertools import chain
from typing import TYPE_CHECKING, TypeVar, cast

from yellowdog_cli.utils.entity_utils import (
    AmbiguousNameError,
    expand_name_globs,
    find_compute_requirement_by_name,
    find_work_requirement_by_name,
    get_compute_requirement_summaries,
    get_filtered_work_requirement_summaries,
    get_task_groups_from_wr_by_id,
    get_worker_pool_id_by_name,
    get_worker_pool_summaries,
    iterate_tasks_in_task_group,
)
from yellowdog_cli.utils.exit_codes import NotFoundError, ReportedFailure, classify
from yellowdog_cli.utils.glob_utils import contains_glob_chars, glob_search_prefix
from yellowdog_cli.utils.limits import PATTERN_MATCH_WARNING
from yellowdog_cli.utils.printing import print_error, print_warning
from yellowdog_cli.utils.settings import NAMESPACE_PREFIX_SEPARATOR
from yellowdog_cli.utils.work_targets import resolve_named_target
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

_LOG = logging.getLogger(__name__)

if TYPE_CHECKING:
    from yellowdog_cli.utils.context import RunContext

# How many parts a name of each type has without a namespace: one more is
# 'namespace/' ahead of them
_PARTS: dict[YDIDType, int] = {
    YDIDType.WORK_REQUIREMENT: 1,
    YDIDType.WORKER_POOL: 1,
    YDIDType.COMPUTE_REQUIREMENT: 1,
    YDIDType.TASK_GROUP: 2,
    YDIDType.TASK: 3,
}
# What a refused name is reported as
_FAILURES = (NotFoundError, AmbiguousNameError, ValueError)

_Resolved = TypeVar("_Resolved")


def resolve_targets(
    ctx: RunContext,
    targets: list[str],
    ydid_type: YDIDType | None,
    live_only: bool = False,
) -> list[str]:
    """
    The targets with each name replaced by the ID of the object of
    'ydid_type' it names, and each pattern by the IDs of those it matches
    (the unfinished alone if 'live_only'), in the order given, each object
    once; 'targets' as they are when 'ydid_type' is None (a command taking
    IDs alone). Every name or pattern that finds nothing is reported, and
    then ReportedFailure raised with the cause they share (NOT_FOUND), or
    FAILURE for different causes.
    """
    if ydid_type is None:
        return list(targets)
    named: YDIDType = ydid_type  # As narrowed, for the lambdas
    found = resolved_each(
        [
            (lambda target=target: _ids_of(ctx, target, named, live_only))
            for target in targets
        ]
    )
    return list(dict.fromkeys(chain.from_iterable(found)))


def resolve_compare_targets(
    ctx: RunContext, wr_or_tg: str, worker_pools: list[str]
) -> tuple[str, list[str]]:
    """
    yd-compare's targets with names replaced by IDs, as resolve_targets()
    replaces them: a Work Requirement ('wr') or Task Group ('wr/tg'), or
    only the type the noun verb gives, then Worker Pools.
    """
    named: YDIDType | None = ctx.args.named_target_type

    def first() -> str:
        _refuse_pattern(wr_or_tg)
        if named is None:
            return work_target_id(ctx, wr_or_tg)
        return _id_or_lookup(ctx, wr_or_tg, named)

    def pool_id(pool: str) -> str:
        _refuse_pattern(pool)
        return _id_or_lookup(ctx, pool, YDIDType.WORKER_POOL)

    resolved = resolved_each(
        [
            first,
            *((lambda pool=pool: pool_id(pool)) for pool in worker_pools),
        ]
    )
    return resolved[0], resolved[1:]


def resolved_each(lookups: list[Callable[[], _Resolved]]) -> list[_Resolved]:
    """
    Each lookup's result (an ID, or what it found), in order. Every one
    refused is reported, and then ReportedFailure raised with the cause they
    share (NOT_FOUND), or FAILURE for different causes.
    """
    resolved: list[_Resolved] = []
    failures: list[Exception] = []
    for lookup in lookups:
        try:
            resolved.append(lookup())
        except _FAILURES as e:
            print_error(str(e))
            failures.append(e)
    if failures:
        codes = {classify(e) for e in failures}
        raise ReportedFailure(
            failures[0]
            if len(codes) == 1
            else RuntimeError(f"{len(failures)} name(s) not resolved")
        )
    return resolved


def is_pattern(target: str) -> bool:
    """
    Whether a target is a name pattern: not an ID, and holding a wildcard.
    """
    return get_ydid_type(target) is None and contains_glob_chars(target)


def _refuse_pattern(target: str) -> None:
    """
    Refuses a name pattern where one object is wanted (yd-compare's).
    """
    if is_pattern(target):
        raise ValueError(f"'{target}' is a pattern: give one name or ID")


def _ids_of(
    ctx: RunContext, target: str, ydid_type: YDIDType, live_only: bool
) -> list[str]:
    """
    The ID a target gives, or for a pattern the IDs of the objects it
    matches (warned of when there are many). Raises as target_id() does,
    and NotFoundError for a pattern matching nothing.
    """
    if not is_pattern(target):
        return [_id_or_lookup(ctx, target, ydid_type)]
    namespace = _namespace_for(ctx, target, ydid_type)
    leading, separator, _ = target.rpartition(NAMESPACE_PREFIX_SEPARATOR)
    if separator and contains_glob_chars(leading):
        raise ValueError(
            f"'{target}': a wildcard may be given in the last part of the name alone"
        )
    ids = _matching_ids(ctx, target, ydid_type, namespace, live_only)
    if not ids:
        unfinished = "unfinished " if live_only else ""
        raise NotFoundError(
            f"No {unfinished}{ydid_type.value} matches '{target}'"
            f"{_in(target, namespace)}"
        )
    _LOG.debug("'%s' matches %s", target, ", ".join(ids))
    if len(ids) > PATTERN_MATCH_WARNING:
        print_warning(f"'{target}' matches {len(ids)} {ydid_type.value}s")
    return ids


def _matching_ids(
    ctx: RunContext,
    target: str,
    ydid_type: YDIDType,
    namespace: str | None,
    live_only: bool,
) -> list[str]:
    """
    The IDs of the objects of the type whose names the pattern matches, in
    the order the Platform lists them.
    """
    from yellowdog_client.model import (
        ComputeRequirementStatus,
        TaskGroupStatus,
        WorkRequirementStatus,
    )

    from yellowdog_cli.utils.entity_utils import FINISHED_WORK_REQUIREMENT_STATUSES

    match ydid_type:
        case YDIDType.WORK_REQUIREMENT:
            unfinished = [
                status
                for status in WorkRequirementStatus
                if status not in FINISHED_WORK_REQUIREMENT_STATUSES
            ]
            found = expand_name_globs(
                [target],
                namespace,
                fetch=lambda ns, prefix: get_filtered_work_requirement_summaries(
                    ctx.client,
                    name=prefix or None,
                    namespace=ns,
                    include_filter=unfinished if live_only else None,
                ),
            )
        case YDIDType.COMPUTE_REQUIREMENT:
            found = expand_name_globs(
                [target],
                namespace,
                fetch=lambda ns, prefix: get_compute_requirement_summaries(
                    ctx.client,
                    ns,
                    statuses=[
                        status
                        for status in ComputeRequirementStatus
                        if status != ComputeRequirementStatus.TERMINATED
                    ]
                    if live_only
                    else None,
                    name=prefix or None,
                ),
            )
        case YDIDType.WORKER_POOL:
            found = [
                summary
                for summary in expand_name_globs(
                    [target],
                    namespace,
                    fetch=lambda ns, prefix: get_worker_pool_summaries(
                        ctx.client, ns, prefix or None
                    ),
                )
                if not (live_only and _finished(summary))
            ]
        case YDIDType.TASK_GROUP:
            # The Work Requirement as a name of one is found ('wr', or
            # 'namespace/wr'), never as 'wr/tg' might read
            path, _, pattern = target.rpartition(NAMESPACE_PREFIX_SEPARATOR)
            work_requirement = find_work_requirement_by_name(
                ctx.client,
                path,
                namespace,
                [
                    status
                    for status in WorkRequirementStatus
                    if status not in FINISHED_WORK_REQUIREMENT_STATUSES
                ],
            )
            finished = {
                TaskGroupStatus.COMPLETED,
                TaskGroupStatus.FAILED,
                TaskGroupStatus.CANCELLED,
            }
            found = [
                task_group
                for task_group in get_task_groups_from_wr_by_id(
                    ctx.client, cast(str, work_requirement.id)
                )
                if _matches(task_group.name, pattern)
                and not (live_only and task_group.status in finished)
            ]
        case YDIDType.TASK:
            path, _, pattern = target.rpartition(NAMESPACE_PREFIX_SEPARATOR)
            found = [
                task
                for task in iterate_tasks_in_task_group(
                    ctx.client,
                    _task_group_id(ctx, path, namespace),
                    name_contains=glob_search_prefix(pattern) or None,
                )
                if _matches(task.name, pattern) and not (live_only and _finished(task))
            ]
        case _:
            raise ValueError(f"A {ydid_type.value} cannot be given by name")
    return [str(item.id) for item in found]


def _matches(name: str | None, pattern: str) -> bool:
    return name is not None and fnmatch.fnmatchcase(name, pattern)


def _finished(item: object) -> bool:
    """
    Whether an object's status says it has finished (a status's own
    'finished', as the SDK gives a Worker Pool's and a Task's).
    """
    return bool(getattr(getattr(item, "status", None), "finished", False))


def _namespace_for(ctx: RunContext, target: str, ydid_type: YDIDType) -> str | None:
    """
    The configured namespace, having checked the target's form: as many
    parts as the type's names have, or one more for a namespace, and a
    namespace configured when none is given. Raises ValueError.
    """
    if target.startswith("ydid:"):
        raise ValueError(f"'{target}' is not a valid YellowDog ID")
    namespace = ctx.config.namespace or None
    parts = target.split(NAMESPACE_PREFIX_SEPARATOR)
    expected = _PARTS[ydid_type]
    if len(parts) not in (expected, expected + 1) or not all(parts):
        raise ValueError(f"'{target}' is not {_form(ydid_type)}")
    if len(parts) == expected and namespace is None:
        raise ValueError(
            f"No namespace is configured to look up '{target}' in: give"
            f" --namespace, or 'namespace/{target}'"
        )
    return namespace


def _id_or_lookup(ctx: RunContext, target: str, ydid_type: YDIDType) -> str:
    """
    A YellowDog ID as it is; a name looked up as 'ydid_type'.
    """
    if get_ydid_type(target) is not None:
        return target
    ydid = target_id(ctx, target, ydid_type)
    _LOG.debug("'%s' is %s", target, ydid)
    return ydid


def target_id(ctx: RunContext, target: str, ydid_type: YDIDType) -> str:
    """
    The ID of the object of 'ydid_type' that 'target' names. Raises
    NotFoundError, AmbiguousNameError or ValueError (a name of the wrong
    form, or one needing a namespace when none is configured).
    """
    namespace = _namespace_for(ctx, target, ydid_type)

    match ydid_type:
        case YDIDType.WORK_REQUIREMENT:
            from yellowdog_client.model import WorkRequirementStatus

            from yellowdog_cli.utils.entity_utils import (
                FINISHED_WORK_REQUIREMENT_STATUSES,
            )

            return cast(
                str,
                find_work_requirement_by_name(
                    ctx.client,
                    target,
                    namespace,
                    [
                        status
                        for status in WorkRequirementStatus
                        if status not in FINISHED_WORK_REQUIREMENT_STATUSES
                    ],
                ).id,
            )
        case YDIDType.COMPUTE_REQUIREMENT:
            from yellowdog_client.model import ComputeRequirementStatus

            return cast(
                str,
                find_compute_requirement_by_name(
                    ctx.client,
                    target,
                    namespace,
                    [
                        status
                        for status in ComputeRequirementStatus
                        if status != ComputeRequirementStatus.TERMINATED
                    ],
                ).id,
            )
        case YDIDType.WORKER_POOL:
            worker_pool_id = get_worker_pool_id_by_name(ctx.client, target, namespace)
            if worker_pool_id is None:
                raise NotFoundError(
                    f"Cannot find Worker Pool '{target}'{_in(target, namespace)}"
                )
            return worker_pool_id
        case YDIDType.TASK_GROUP:
            return _task_group_id(ctx, target, namespace)
        case YDIDType.TASK:
            path, _, name = target.rpartition(NAMESPACE_PREFIX_SEPARATOR)
            task_group_id = _task_group_id(ctx, path, namespace)
            for task in iterate_tasks_in_task_group(
                ctx.client, task_group_id, name_contains=name
            ):
                if task.name == name:
                    return str(task.id)
            raise NotFoundError(f"Cannot find Task '{name}' in Task Group '{path}'")
    raise ValueError(f"A {ydid_type.value} cannot be given by name")


def work_target_id(ctx: RunContext, target: str) -> str:
    """
    The ID of the Work Requirement ('wr') or Task Group ('wr/tg') a name
    gives, each with an optional leading 'namespace/', as yd-compare takes
    either; an ID as it is.
    """
    if get_ydid_type(target) is not None:
        return target
    named = resolve_named_target(ctx.client, target, ctx.config.namespace or None)
    ydid = str(
        (
            named.task_group if named.task_group is not None else named.work_requirement
        ).id
    )
    _LOG.debug("'%s' is %s", target, ydid)
    return ydid


def _task_group_id(ctx: RunContext, target: str, namespace: str | None) -> str:
    named = resolve_named_target(ctx.client, target, namespace)
    if named.task_group is None:
        raise NotFoundError(
            f"'{target}' names a Work Requirement, not a Task Group: give 'wr/tg'"
        )
    return str(named.task_group.id)


def _form(ydid_type: YDIDType) -> str:
    """
    How a name of the type is written, for a refusal.
    """
    forms = {
        YDIDType.TASK_GROUP: "'wr/tg' or 'namespace/wr/tg'",
        YDIDType.TASK: "'wr/tg/task' or 'namespace/wr/tg/task'",
    }
    return forms.get(
        ydid_type, f"a {ydid_type.value} name ('name' or 'namespace/name')"
    )


def _in(target: str, namespace: str | None) -> str:
    return (
        "" if NAMESPACE_PREFIX_SEPARATOR in target else f" in namespace '{namespace}'"
    )
