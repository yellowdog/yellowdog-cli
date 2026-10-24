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

Every name is looked up before anything else is done, and those that find
nothing are reported together; a failure every later lookup would repeat
(authentication, connection) is raised as it is, for the wrapper.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from yellowdog_cli.utils.entity_utils import (
    AmbiguousNameError,
    find_compute_requirement_by_name,
    find_work_requirement_by_name,
    get_worker_pool_id_by_name,
    iterate_tasks_in_task_group,
)
from yellowdog_cli.utils.exit_codes import NotFoundError, ReportedFailure, classify
from yellowdog_cli.utils.printing import print_error
from yellowdog_cli.utils.settings import NAMESPACE_PREFIX_SEPARATOR
from yellowdog_cli.utils.work_targets import resolve_named_target
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

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


def resolve_targets(
    ctx: RunContext, targets: list[str], ydid_type: YDIDType | None
) -> list[str]:
    """
    The targets with each name replaced by the ID of the object of
    'ydid_type' it names, in the order given; 'targets' as they are when
    'ydid_type' is None (a command taking IDs alone). Every name that finds
    nothing is reported, and then ReportedFailure raised with the cause
    they share (NOT_FOUND), or FAILURE for different causes.
    """
    if ydid_type is None:
        return list(targets)
    named: YDIDType = ydid_type  # As narrowed, for the lambdas
    return _resolved(
        [
            (lambda target=target: _id_or_lookup(ctx, target, named))
            for target in targets
        ]
    )


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
        if named is None:
            return work_target_id(ctx, wr_or_tg)
        return _id_or_lookup(ctx, wr_or_tg, named)

    resolved = _resolved(
        [
            first,
            *(
                (lambda pool=pool: _id_or_lookup(ctx, pool, YDIDType.WORKER_POOL))
                for pool in worker_pools
            ),
        ]
    )
    return resolved[0], resolved[1:]


def _resolved(lookups: list[Callable[[], str]]) -> list[str]:
    """
    Each lookup's ID, in order. Every one refused is reported, and then
    ReportedFailure raised with the cause they share (NOT_FOUND), or
    FAILURE for different causes.
    """
    resolved: list[str] = []
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


def _id_or_lookup(ctx: RunContext, target: str, ydid_type: YDIDType) -> str:
    """
    A YellowDog ID as it is; a name looked up as 'ydid_type'.
    """
    if get_ydid_type(target) is not None:
        return target
    return target_id(ctx, target, ydid_type)


def target_id(ctx: RunContext, target: str, ydid_type: YDIDType) -> str:
    """
    The ID of the object of 'ydid_type' that 'target' names. Raises
    NotFoundError, AmbiguousNameError or ValueError (a name of the wrong
    form, or one needing a namespace when none is configured).
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
    if named.task_group is not None:
        return str(named.task_group.id)
    return str(named.work_requirement.id)


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
