#!/usr/bin/env python3

"""
A script to cancel Work Requirements and Tasks, optionally aborting their
executing Tasks.

Work Requirements are selected by the namespace and tag, by glob patterns
matched against their names, or explicitly by name or ID, with Task IDs
alongside. A Work Requirement that is already CANCELLING is a target only
with '--abort', which cancels it again to abort its executing Tasks; without
it, it is left out of a listing and skipped when named. Explicit targets are
resolved first, in the order given, then confirmed once and acted on, under
action_runner.py's rules.
"""

from typing import Any, TypeAlias, cast

from yellowdog_client.model import (
    Task,
    TaskStatus,
    WorkRequirement,
    WorkRequirementStatus,
    WorkRequirementSummary,
)

from yellowdog_cli.utils.action_runner import (
    SKIPPED,
    Item,
    Unit,
    Unresolved,
    by_type,
    carry_out,
    confirm_items,
    resolve_targets,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.dryrun_utils import report_dry_run, report_dry_run_items
from yellowdog_cli.utils.entity_names import ET_TASKS, ET_WORK_REQUIREMENTS
from yellowdog_cli.utils.entity_utils import (
    AmbiguousNameError,
    describe_glob_scope,
    expand_name_globs,
    find_work_requirement_by_name,
    get_filtered_work_requirement_summaries,
)
from yellowdog_cli.utils.exit_codes import NotFoundError
from yellowdog_cli.utils.follow_utils import follow_ids
from yellowdog_cli.utils.glob_utils import contains_glob_chars
from yellowdog_cli.utils.interactive import select
from yellowdog_cli.utils.misc_utils import is_http_not_found, link_entity
from yellowdog_cli.utils.printing import print_info
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.wrapper import main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

# The '--json' record's action and outcome
_CANCEL = "cancel"
_CANCELLED = "cancelled"

# The Work Requirement states a cancellation applies to; a CANCELLING one is
# added with '--abort' (_cancellable_statuses())
_CANCELLABLE_STATUSES = [
    WorkRequirementStatus.RUNNING,
    WorkRequirementStatus.HELD,
    WorkRequirementStatus.FINISHING,
]

# The Task states a cancellation no longer applies to
_FINISHED_TASK_STATUSES = [
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.ABORTED,
    TaskStatus.CANCELLED,
    TaskStatus.DISCARDED,
]

# A Work Requirement to cancel: fetched by its ID, or listed or found by name
_WorkRequirementTarget: TypeAlias = WorkRequirement | WorkRequirementSummary


def _record(
    entity: object,
    outcome: str,
    error: str | None = None,
    entity_type: str = ET_WORK_REQUIREMENTS,
    **extra: Any,
) -> None:
    record_action(entity, entity_type, _CANCEL, outcome, error, **extra)


def _recorder(entity: object, entity_type: str, outcome: str, error: str | None):
    """
    _record, as action_runner calls it.
    """
    _record(entity, outcome, error, entity_type)


def _cancellable_statuses(ctx: RunContext) -> list[WorkRequirementStatus]:
    return _CANCELLABLE_STATUSES + (
        [WorkRequirementStatus.CANCELLING] if ctx.args.abort else []
    )


def _abort_phrase(ctx: RunContext) -> str:
    return " and abort their executing Tasks" if ctx.args.abort else ""


@main_wrapper
def main(ctx: RunContext):
    cancel(ctx, ctx.args.work_requirement_names or [])


def cancel(ctx: RunContext, names: list[str]):
    """
    Cancel the Work Requirements and Tasks named, or the Work Requirements
    matching the glob patterns given, or, given nothing, those in the
    namespace whose tags include the tag.
    """
    globs = [n for n in names if contains_glob_chars(n)]

    if names and not globs:
        # All literal names/IDs: exact path (mixing is rejected at parse time)
        _cancel_by_name_or_id(ctx, names)
        return

    if globs:
        print_info(
            f"Cancelling Work Requirements "
            f"{describe_glob_scope(globs, ctx.config.namespace)}"
        )
        summaries: list[WorkRequirementSummary] = expand_name_globs(
            globs,
            ctx.config.namespace,
            fetch=lambda namespace, prefix: get_filtered_work_requirement_summaries(
                ctx.client,
                name=prefix or None,
                namespace=namespace,
                include_filter=_cancellable_statuses(ctx),
            ),
        )
    else:
        print_info(
            "Cancelling Work Requirements in namespace "
            f"'{ctx.config.namespace}' with tags "
            f"including '{ctx.config.name_tag}'"
        )
        summaries = get_filtered_work_requirement_summaries(
            client=ctx.client,
            namespace=ctx.config.namespace,
            tag=ctx.config.name_tag,
            include_filter=_cancellable_statuses(ctx),
        )

    if ctx.args.dry_run:
        report_dry_run(
            ctx.client,
            summaries,
            "Work Requirement",
            "cancelled",
            ET_WORK_REQUIREMENTS,
            _CANCEL,
            bool(ctx.args.json_output),
        )
        return

    selected: list[WorkRequirementSummary] = (
        select(ctx.client, summaries) if summaries else []
    )
    items = [_wr_item(summary) for summary in selected]
    if items and not confirm_items(
        f"Cancel {len(items)} Work Requirement(s){_abort_phrase(ctx)}?",
        items,
        _recorder,
    ):
        items = []

    _carry_out(ctx, items)


def _is_task(target: str) -> bool:
    return get_ydid_type(target) == YDIDType.TASK


def _wr_item(work_requirement: _WorkRequirementTarget) -> Item:
    return Item(
        work_requirement,
        ET_WORK_REQUIREMENTS,
        ("wr", work_requirement.id),
        work_requirement,
    )


def _task_item(task: Task) -> Item:
    return Item(task, ET_TASKS, ("task", task.id), task)


def _describe(target: str) -> tuple[object, str]:
    return target, ET_TASKS if _is_task(target) else ET_WORK_REQUIREMENTS


def _cancel_by_name_or_id(ctx: RunContext, names_or_ids: list[str]):
    """
    Cancel Work Requirements by their names or IDs, and Tasks by their IDs.
    """
    items = resolve_targets(
        names_or_ids,
        resolve=lambda target: _resolve(ctx, target),
        describe=_describe,
        record=_recorder,
        verb="cancel",
        order=by_type(ET_WORK_REQUIREMENTS, ET_TASKS),
    )

    if not items:
        print_info("No Work Requirements or Tasks cancelled")
        return

    if ctx.args.dry_run:
        report_dry_run_items(
            items,
            _CANCEL,
            lambda item, status: _record(
                item.entity,
                f"would {_CANCEL}",
                entity_type=item.entity_type,
                status=status,
            ),
        )
        return

    if not confirm_items(_confirmation(ctx, items), items, _recorder):
        print_info("No Work Requirements or Tasks cancelled")
        return

    _carry_out(ctx, items)


def _resolve(ctx: RunContext, target: str) -> Item:
    """
    The Work Requirement or Task a target names, raising Unresolved if it
    cannot be cancelled. Anything else raised is a failure of the lookup.
    """
    ydid_type = get_ydid_type(target)

    if ydid_type == YDIDType.TASK:
        try:
            task: Task = ctx.client.work_client.get_task_by_id(target)
        except Exception as e:
            if is_http_not_found(e):
                raise Unresolved(f"Cannot find Task {target}") from e
            raise
        if task.status in _FINISHED_TASK_STATUSES:
            raise Unresolved(
                f"Task {_task_label(task)} is {task.status}", SKIPPED, task
            )
        return _task_item(task)

    if ydid_type == YDIDType.WORK_REQUIREMENT:
        try:
            work_requirement: _WorkRequirementTarget = (
                ctx.client.work_client.get_work_requirement_by_id(target)
            )
        except Exception as e:
            if is_http_not_found(e):
                raise Unresolved(f"Cannot find Work Requirement {target}") from e
            raise
    elif ydid_type is not None:
        raise Unresolved(f"'{target}' is not a Work Requirement or Task ID")
    else:
        try:
            work_requirement = find_work_requirement_by_name(
                ctx.client, target, ctx.config.namespace, _cancellable_statuses(ctx)
            )
        except (NotFoundError, AmbiguousNameError) as e:
            raise Unresolved(str(e)) from e

    if work_requirement.status not in _cancellable_statuses(ctx):
        reason = (
            " (use --abort to abort its executing Tasks)"
            if work_requirement.status == WorkRequirementStatus.CANCELLING
            else ""
        )
        raise Unresolved(
            f"Work Requirement {_label(work_requirement)} is already"
            f" {work_requirement.status}{reason}",
            SKIPPED,
            work_requirement,
        )
    return _wr_item(work_requirement)


def _label(work_requirement: _WorkRequirementTarget) -> str:
    return f"'{work_requirement.namespace}/{work_requirement.name}'"


def _task_label(task: Task) -> str:
    return f"'{task.name}' ({task.id})" if task.name else str(task.id)


def _confirmation(ctx: RunContext, items: list[Item]) -> str:
    work_requirements = [i.value for i in items if i.entity_type != ET_TASKS]
    tasks = [i.value for i in items if i.entity_type == ET_TASKS]
    parts = []
    if work_requirements:
        parts.append(
            f"{len(work_requirements)} Work Requirement(s) ("
            + ", ".join(_label(wr) for wr in work_requirements)
            + ")"
        )
    if tasks:
        parts.append(
            f"{len(tasks)} Task(s) (" + ", ".join(_task_label(t) for t in tasks) + ")"
        )
    return f"Cancel {' and '.join(parts)}{_abort_phrase(ctx)}?"


def _carry_out(ctx: RunContext, items: list[Item]):
    """
    Cancel confirmed Work Requirements, then Tasks; report, and follow the
    Work Requirements cancelled.
    """
    done = carry_out(
        [
            (
                Unit(
                    [item],
                    act=lambda task=item.value: _cancel_task(ctx, task),
                    failure=lambda e, task=item.value: (
                        f"Failed to cancel Task {_task_label(task)}: {e}"
                    ),
                )
                if item.entity_type == ET_TASKS
                else Unit(
                    [item],
                    act=lambda wr=item.value: _cancel_work_requirement(ctx, wr),
                    failure=lambda e, wr=item.value: (
                        f"Failed to cancel Work Requirement {_label(wr)}: {e}"
                    ),
                )
            )
            for item in items
        ],
        _recorder,
    )
    cancelled_ids = [
        cast(str, unit.items[0].value.id)
        for unit in done
        if unit.items[0].entity_type == ET_WORK_REQUIREMENTS
    ]
    tasks_cancelled = len(done) - len(cancelled_ids)

    if cancelled_ids or tasks_cancelled:
        if cancelled_ids:
            print_info(f"Cancelled {len(cancelled_ids)} Work Requirement(s)")
        if tasks_cancelled:
            print_info(f"Cancelled {tasks_cancelled} Task(s)")
        if ctx.args.follow and cancelled_ids:
            follow_ids(ctx, cancelled_ids)
    else:
        print_info("No Work Requirements or Tasks cancelled")


def _cancel_work_requirement(ctx: RunContext, work_requirement: _WorkRequirementTarget):
    """
    Cancel a Work Requirement, recording and reporting it. One already
    CANCELLING (a target only with '--abort') is cancelled again, which
    aborts its executing Tasks, and is recorded with "abortedTasks". Raises
    on failure, for the caller to record.
    """
    already_cancelling = work_requirement.status == WorkRequirementStatus.CANCELLING
    result = ctx.client.work_client.cancel_work_requirement_by_id(
        cast(str, work_requirement.id), bool(ctx.args.abort)
    )
    if already_cancelling:
        _record(work_requirement, _CANCELLED, abortedTasks=True)
        print_info(
            "Aborted the executing Tasks in already-cancelling Work Requirement"
            f" {_label(work_requirement)}"
        )
        return
    _record(work_requirement, _CANCELLED)
    aborted = " and aborted its executing Tasks" if ctx.args.abort else ""
    if isinstance(result, WorkRequirement):
        print_info(
            f"Cancelled {link_entity(ctx.config.url, result)}"
            f" ({_label(work_requirement)}){aborted}"
        )
    else:
        print_info(f"Cancelled Work Requirement {_label(work_requirement)}{aborted}")


def _cancel_task(ctx: RunContext, task: Task):
    ctx.client.work_client.cancel_task_by_id(cast(str, task.id), bool(ctx.args.abort))
    aborted = " and aborted" if ctx.args.abort else ""
    print_info(f"Cancelled{aborted} Task {_task_label(task)}")
    _record(task, _CANCELLED, entity_type=ET_TASKS)


if __name__ == "__main__":
    main()
