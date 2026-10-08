#!/usr/bin/env python3

"""
A script to change the priority of Work Requirements and Task Groups.

Each target -- a Work Requirement's ID or name, or a Task Group's ID or
'wr/tg' name, read as utils/work_targets.py reads them -- is resolved in
the order given, recording any that cannot be changed as 'failed' (not
found, ambiguous) or 'skipped' (finished, or already at that priority).
What remains is confirmed once and changed one Work Requirement at a time:
the Platform takes a Work Requirement whole, so its targets are applied
together to a copy fetched just before it is sent back. The rules for what
cannot be changed, confirming and stopping on a session failure are
action_runner.py's.
"""

from dataclasses import dataclass
from typing import cast

from yellowdog_client.model import TaskGroup, WorkRequirement

from yellowdog_cli.utils.action_runner import (
    Item,
    Unit,
    Unresolved,
    carry_out,
    confirm_items,
    resolve_targets,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import ET_TASK_GROUPS, ET_WORK_REQUIREMENTS
from yellowdog_cli.utils.entity_utils import FINISHED_WORK_REQUIREMENT_STATUSES
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.printing import print_dry_run, print_info
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.work_targets import (
    MalformedTarget,
    TargetNotFound,
    named_target_entity_type,
    resolve_named_target,
)
from yellowdog_cli.utils.wrapper import main_wrapper
from yellowdog_cli.utils.ydid_utils import (
    YDIDType,
    get_ydid_type,
    work_requirement_id_of_task_group,
)

# The '--json' records' action and outcome
_PRIORITISE = "prioritise"
_PRIORITISED = "prioritised"


@dataclass(frozen=True)
class _Target:
    """
    A Work Requirement, or a Task Group in one, and its priority when
    resolved.
    """

    work_requirement_id: str
    work_requirement_name: str | None
    task_group_id: str | None
    task_group_name: str | None
    priority: float | None

    def label(self) -> str:
        if self.task_group_id is None:
            return f"'{self.work_requirement_name}'"
        return f"'{self.work_requirement_name}/{self.task_group_name}'"

    def entity(self) -> dict:
        if self.task_group_id is None:
            return {"id": self.work_requirement_id, "name": self.work_requirement_name}
        return {"id": self.task_group_id, "name": self.task_group_name}

    def entity_type(self) -> str:
        return ET_WORK_REQUIREMENTS if self.task_group_id is None else ET_TASK_GROUPS


def _record(
    entity: object,
    entity_type: str,
    outcome: str,
    error: str | None = None,
    **extra: object,
) -> None:
    record_action(entity, entity_type, _PRIORITISE, outcome, error, **extra)


@main_wrapper
def main(ctx: RunContext):
    set_priorities(ctx, ctx.args.priority, ctx.args.priority_targets)


def set_priorities(ctx: RunContext, priority: float, targets: list[str]):
    """
    Set the priority of each Work Requirement and Task Group named.
    """
    items = resolve_targets(
        targets,
        resolve=lambda target: _resolve(ctx, target, priority),
        describe=_describe,
        record=_record,
        verb="change the priority of",
        order=lambda items: items,
    )

    if not items:
        print_info("No priorities changed")
        return

    if ctx.args.dry_run:
        for item in items:
            target: _Target = item.value
            print_dry_run(
                f"Would change the priority of {target.label()}"
                f" from {target.priority} to {priority}"
            )
            _record(
                item.entity,
                item.entity_type,
                f"would {_PRIORITISE}",
                previousPriority=target.priority,
                priority=priority,
            )
        return

    if not confirm_items(_confirmation(priority, items), items, _record):
        print_info("No priorities changed")
        return

    carry_out(
        [
            Unit(
                group,
                act=lambda group=group: _apply(ctx, priority, group),
                failure=lambda e, group=group: (
                    "Unable to change the priority of "
                    + ", ".join(item.value.label() for item in group)
                    + f": {e}"
                ),
            )
            for group in _by_work_requirement(items)
        ],
        _record,
    )


def _describe(target: str) -> tuple[object, str]:
    match get_ydid_type(target):
        case YDIDType.WORK_REQUIREMENT:
            return target, ET_WORK_REQUIREMENTS
        case YDIDType.TASK_GROUP:
            return target, ET_TASK_GROUPS
        case _:
            return target, named_target_entity_type(target)


def _resolve(ctx: RunContext, target: str, priority: float) -> Item:
    """
    The Work Requirement or Task Group a target names, raising Unresolved if
    its priority cannot be changed. Anything else raised is a failure of the
    lookup itself.
    """
    ydid_type = get_ydid_type(target)
    if ydid_type == YDIDType.WORK_REQUIREMENT:
        work_requirement = _fetch(ctx, target, f"Work Requirement '{target}'")
        resolved = _target(work_requirement, None)
    elif ydid_type == YDIDType.TASK_GROUP:
        work_requirement = _fetch(
            ctx, work_requirement_id_of_task_group(target), f"Task Group '{target}'"
        )
        task_group = next(
            (g for g in work_requirement.taskGroups or [] if g.id == target), None
        )
        if task_group is None:
            raise Unresolved(f"Task Group '{target}' not found")
        resolved = _target(work_requirement, task_group)
    elif ydid_type is not None:
        raise Unresolved(
            f"'{target}' is a {ydid_type.value} ID, not a Work Requirement or"
            " Task Group ID"
        )
    else:
        try:
            named = resolve_named_target(ctx.client, target, ctx.config.namespace)
        except (TargetNotFound, MalformedTarget) as e:
            raise Unresolved(str(e)) from e
        resolved = _target(
            ctx.client.work_client.get_work_requirement_by_id(
                cast(str, named.work_requirement.id)
            ),
            named.task_group,
        )

    item = Item(
        resolved.entity(),
        resolved.entity_type(),
        (resolved.work_requirement_id, resolved.task_group_id),
        resolved,
    )
    if resolved.priority == priority:
        raise Unresolved(
            f"The priority of {resolved.label()} is already {priority}",
            "skipped",
            item.entity,
        )
    return item


def _fetch(ctx: RunContext, work_requirement_id: str, what: str) -> WorkRequirement:
    """
    A Work Requirement by its ID, whatever its namespace, raising Unresolved
    if it does not exist.
    """
    try:
        work_requirement = ctx.client.work_client.get_work_requirement_by_id(
            work_requirement_id
        )
    except Exception as e:
        if is_http_not_found(e):
            raise Unresolved(f"{what} not found") from e
        raise
    return work_requirement


def _finished(name: str | None, status: object) -> str:
    return f"Work Requirement '{name}' is {status}, so its priority cannot be changed"


def _target(work_requirement: WorkRequirement, task_group: TaskGroup | None) -> _Target:
    """
    A target as resolved, its priority read from the Work Requirement just
    fetched: a Task Group's from that Work Requirement's own copy of it.
    Raises Unresolved, skipped, if the Work Requirement has finished.
    """
    if work_requirement.status in FINISHED_WORK_REQUIREMENT_STATUSES:
        raise Unresolved(
            _finished(work_requirement.name, work_requirement.status),
            "skipped",
            {"id": work_requirement.id, "name": work_requirement.name}
            if task_group is None
            else {"id": task_group.id, "name": task_group.name},
        )
    if task_group is not None:
        task_group = next(
            (g for g in work_requirement.taskGroups or [] if g.id == task_group.id),
            task_group,
        )
    return _Target(
        work_requirement_id=cast(str, work_requirement.id),
        work_requirement_name=work_requirement.name,
        task_group_id=None if task_group is None else task_group.id,
        task_group_name=None if task_group is None else task_group.name,
        priority=(
            work_requirement.priority if task_group is None else task_group.priority
        ),
    )


def _confirmation(priority: float, items: list[Item]) -> str:
    return (
        f"Change the priority of {len(items)} Work Requirement(s) or Task"
        " Group(s) ("
        + ", ".join(
            f"{item.value.label()} {item.value.priority} -> {priority}"
            for item in items
        )
        + ")?"
    )


def _by_work_requirement(items: list[Item]) -> list[list[Item]]:
    """
    The items grouped by Work Requirement, each group in the order its first
    item was given: one update per Work Requirement.
    """
    groups: dict[str, list[Item]] = {}
    for item in items:
        groups.setdefault(item.value.work_requirement_id, []).append(item)
    return list(groups.values())


def _apply(ctx: RunContext, priority: float, group: list[Item]):
    """
    Set the priority of a Work Requirement's targets in one update, to a copy
    fetched just now, so that nothing changed since it was resolved is
    overwritten; print and record each. Raises on failure, for the caller to
    record.
    """
    work_client = ctx.client.work_client
    work_requirement: WorkRequirement = work_client.get_work_requirement_by_id(
        group[0].value.work_requirement_id
    )
    previous: list[float | None] = []
    for item in group:
        target: _Target = item.value
        if target.task_group_id is None:
            previous.append(work_requirement.priority)
            work_requirement.priority = priority
            continue
        task_group = next(
            (
                g
                for g in work_requirement.taskGroups or []
                if g.id == target.task_group_id
            ),
            None,
        )
        if task_group is None:
            raise LookupError(
                f"Task Group {target.label()} is no longer in its Work Requirement"
            )
        previous.append(task_group.priority)
        task_group.priority = priority
    work_client.update_work_requirement(work_requirement)

    for item, was in zip(group, previous):
        print_info(
            f"Changed the priority of {item.value.label()} from {was} to {priority}"
        )
        _record(
            item.entity,
            item.entity_type,
            _PRIORITISED,
            previousPriority=was,
            priority=priority,
        )


# Entry point
if __name__ == "__main__":
    main()
