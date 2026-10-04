#!/usr/bin/env python3

"""
A script to cancel Work Requirements and Tasks, optionally aborting their
executing Tasks.

Work Requirements are selected by the namespace and tag, by glob patterns
matched against their names, or explicitly by name or ID, with Task IDs
alongside. A Work Requirement that is already CANCELLING is a target only
with '--abort', which cancels it again to abort its executing Tasks; without
it, it is left out of a listing and skipped when named. Explicit targets are
resolved first, in the order given (see start_hold_common.py, which handles
its targets the same way), then confirmed once and acted on. A failure every
later call would repeat (exit_codes.SESSION_FAILURES: authentication,
connection) stops the run, and the targets not yet attempted are recorded
as skipped.
"""

from typing import Any, TypeAlias, cast

from yellowdog_client.model import (
    Task,
    TaskStatus,
    WorkRequirement,
    WorkRequirementStatus,
    WorkRequirementSummary,
)

from yellowdog_cli.utils.dryrun_utils import report_dry_run
from yellowdog_cli.utils.entity_utils import (
    AmbiguousNameError,
    describe_glob_scope,
    expand_name_globs,
    find_work_requirement_by_name,
    get_filtered_work_requirement_summaries,
)
from yellowdog_cli.utils.exit_codes import (
    SESSION_FAILURES,
    NotFoundError,
    ReportedFailure,
    classify,
)
from yellowdog_cli.utils.follow_utils import follow_ids
from yellowdog_cli.utils.glob_utils import contains_glob_chars
from yellowdog_cli.utils.interactive import confirmed, select
from yellowdog_cli.utils.misc_utils import is_http_not_found, link_entity
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.settings import ET_TASKS, ET_WORK_REQUIREMENTS
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON, main_wrapper
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


def _cancellable_statuses() -> list[WorkRequirementStatus]:
    return _CANCELLABLE_STATUSES + (
        [WorkRequirementStatus.CANCELLING] if ARGS_PARSER.abort else []
    )


def _abort_phrase() -> str:
    return " and abort their executing Tasks" if ARGS_PARSER.abort else ""


@main_wrapper
def main():
    cancel(ARGS_PARSER.work_requirement_names or [])


def cancel(names: list[str]):
    """
    Cancel the Work Requirements and Tasks named, or the Work Requirements
    matching the glob patterns given, or, given nothing, those in the
    namespace whose tags include the tag.
    """
    globs = [n for n in names if contains_glob_chars(n)]

    if names and not globs:
        # All literal names/IDs: exact path (mixing is rejected at parse time)
        _cancel_by_name_or_id(names)
        return

    if globs:
        print_info(
            f"Cancelling Work Requirements "
            f"{describe_glob_scope(globs, CONFIG_COMMON.namespace)}"
        )
        summaries: list[WorkRequirementSummary] = expand_name_globs(
            globs,
            CONFIG_COMMON.namespace,
            fetch=lambda namespace, prefix: get_filtered_work_requirement_summaries(
                CLIENT,
                name=prefix or None,
                namespace=namespace,
                include_filter=_cancellable_statuses(),
            ),
        )
    else:
        print_info(
            "Cancelling Work Requirements in namespace "
            f"'{CONFIG_COMMON.namespace}' with tags "
            f"including '{CONFIG_COMMON.name_tag}'"
        )
        summaries = get_filtered_work_requirement_summaries(
            client=CLIENT,
            namespace=CONFIG_COMMON.namespace,
            tag=CONFIG_COMMON.name_tag,
            include_filter=_cancellable_statuses(),
        )

    if ARGS_PARSER.dry_run:
        report_dry_run(
            CLIENT,
            summaries,
            "Work Requirement",
            "cancelled",
            ET_WORK_REQUIREMENTS,
            _CANCEL,
            bool(ARGS_PARSER.json_output),
        )
        return

    selected: list[WorkRequirementSummary] = (
        select(CLIENT, summaries) if summaries else []
    )
    if selected and not confirmed(
        f"Cancel {len(selected)} Work Requirement(s){_abort_phrase()}?"
    ):
        for summary in selected:
            _record(summary, "skipped")
        selected = []

    _carry_out(list(selected), [])


class _Unresolved(Exception):
    """
    A target that cannot be cancelled, for a reason the user should see:
    'failed' unless it exists but is in another state ('skipped'), in which
    case 'entity' is what was found, to be recorded by its ID and name.
    """

    def __init__(
        self, message: str, outcome: str = "failed", entity: object | None = None
    ):
        super().__init__(message)
        self.outcome = outcome
        self.entity = entity


def _is_task(target: str) -> bool:
    return get_ydid_type(target) == YDIDType.TASK


def _cancel_by_name_or_id(names_or_ids: list[str]):
    """
    Cancel Work Requirements by their names or IDs, and Tasks by their IDs.
    """
    targets = list(dict.fromkeys(names_or_ids))  # In order, without duplicates
    work_requirements: list[_WorkRequirementTarget] = []
    tasks: list[Task] = []

    for index, target in enumerate(targets):
        entity_type = ET_TASKS if _is_task(target) else ET_WORK_REQUIREMENTS
        try:
            resolved = _resolve(target)
        except _Unresolved as e:
            (print_warning if e.outcome == "skipped" else print_error)(str(e))
            _record(e.entity or target, e.outcome, str(e), entity_type)
            continue
        except Exception as e:
            print_error(f"Unable to cancel '{target}': {e}")
            _record(target, "failed", str(e), entity_type)
            if classify(e) in SESSION_FAILURES:
                _warn_not_attempted(
                    len(targets) - index - 1 + len(work_requirements) + len(tasks)
                )
                for work_requirement in work_requirements:
                    _record(work_requirement, "skipped", f"not attempted: {e}")
                for task in tasks:
                    _record(task, "skipped", f"not attempted: {e}", ET_TASKS)
                for remaining in targets[index + 1 :]:
                    _record(
                        remaining,
                        "skipped",
                        f"not attempted: {e}",
                        ET_TASKS if _is_task(remaining) else ET_WORK_REQUIREMENTS,
                    )
                raise ReportedFailure(e)
            continue

        if entity_type == ET_TASKS:
            if all(task.id != resolved.id for task in tasks):
                tasks.append(cast(Task, resolved))
        elif all(wr.id != resolved.id for wr in work_requirements):  # name and ID
            work_requirements.append(cast(_WorkRequirementTarget, resolved))

    if not work_requirements and not tasks:
        print_info("No Work Requirements or Tasks cancelled")
        return

    if not confirmed(_confirmation(work_requirements, tasks)):
        for work_requirement in work_requirements:
            _record(work_requirement, "skipped")
        for task in tasks:
            _record(task, "skipped", entity_type=ET_TASKS)
        print_info("No Work Requirements or Tasks cancelled")
        return

    _carry_out(work_requirements, tasks)


def _resolve(target: str) -> _WorkRequirementTarget | Task:
    """
    The Work Requirement or Task a target names, raising _Unresolved if it
    cannot be cancelled. Anything else raised is a failure of the lookup.
    """
    ydid_type = get_ydid_type(target)

    if ydid_type == YDIDType.TASK:
        try:
            task: Task = CLIENT.work_client.get_task_by_id(target)
        except Exception as e:
            if is_http_not_found(e):
                raise _Unresolved(f"Cannot find Task {target}") from e
            raise
        if task.status in _FINISHED_TASK_STATUSES:
            raise _Unresolved(
                f"Task {_task_label(task)} is {task.status}", "skipped", task
            )
        return task

    if ydid_type == YDIDType.WORK_REQUIREMENT:
        try:
            work_requirement: _WorkRequirementTarget = (
                CLIENT.work_client.get_work_requirement_by_id(target)
            )
        except Exception as e:
            if is_http_not_found(e):
                raise _Unresolved(f"Cannot find Work Requirement {target}") from e
            raise
    elif ydid_type is not None:
        raise _Unresolved(f"'{target}' is not a Work Requirement or Task ID")
    else:
        try:
            work_requirement = find_work_requirement_by_name(
                CLIENT, target, CONFIG_COMMON.namespace, _cancellable_statuses()
            )
        except (NotFoundError, AmbiguousNameError) as e:
            raise _Unresolved(str(e)) from e

    if work_requirement.status not in _cancellable_statuses():
        reason = (
            " (use --abort to abort its executing Tasks)"
            if work_requirement.status == WorkRequirementStatus.CANCELLING
            else ""
        )
        raise _Unresolved(
            f"Work Requirement {_label(work_requirement)} is already"
            f" {work_requirement.status}{reason}",
            "skipped",
            work_requirement,
        )
    return work_requirement


def _label(work_requirement: _WorkRequirementTarget) -> str:
    return f"'{work_requirement.namespace}/{work_requirement.name}'"


def _task_label(task: Task) -> str:
    return f"'{task.name}' ({task.id})" if task.name else str(task.id)


def _confirmation(
    work_requirements: list[_WorkRequirementTarget], tasks: list[Task]
) -> str:
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
    return f"Cancel {' and '.join(parts)}{_abort_phrase()}?"


def _warn_not_attempted(count: int):
    if count:
        print_warning(
            f"Not attempting the remaining {count} item(s),"
            " which would fail in the same way"
        )


def _carry_out(work_requirements: list[_WorkRequirementTarget], tasks: list[Task]):
    """
    Cancel confirmed Work Requirements, then Tasks; report, and follow the
    Work Requirements cancelled.
    """
    work: list[tuple[str, Any]] = []
    work.extend((ET_WORK_REQUIREMENTS, wr) for wr in work_requirements)
    work.extend((ET_TASKS, task) for task in tasks)
    cancelled_ids: list[str] = []
    tasks_cancelled = 0

    for index, (entity_type, target) in enumerate(work):
        try:
            if entity_type == ET_WORK_REQUIREMENTS:
                _cancel_work_requirement(target)
                cancelled_ids.append(cast(str, target.id))
            else:
                _cancel_task(target)
                tasks_cancelled += 1
        except Exception as e:
            label = (
                f"Work Requirement {_label(target)}"
                if entity_type == ET_WORK_REQUIREMENTS
                else f"Task {_task_label(target)}"
            )
            print_error(f"Failed to cancel {label}: {e}")
            _record(target, "failed", str(e), entity_type)
            if classify(e) in SESSION_FAILURES:
                not_attempted = work[index + 1 :]
                _warn_not_attempted(len(not_attempted))
                for remaining_type, remaining in not_attempted:
                    _record(remaining, "skipped", f"not attempted: {e}", remaining_type)
                raise ReportedFailure(e)

    if cancelled_ids or tasks_cancelled:
        if cancelled_ids:
            print_info(f"Cancelled {len(cancelled_ids)} Work Requirement(s)")
        if tasks_cancelled:
            print_info(f"Cancelled {tasks_cancelled} Task(s)")
        if ARGS_PARSER.follow and cancelled_ids:
            follow_ids(cancelled_ids)
    else:
        print_info("No Work Requirements or Tasks cancelled")


def _cancel_work_requirement(work_requirement: _WorkRequirementTarget):
    """
    Cancel a Work Requirement, recording and reporting it. One already
    CANCELLING (a target only with '--abort') is cancelled again, which
    aborts its executing Tasks, and is recorded with "abortedTasks". Raises
    on failure, for the caller to record.
    """
    already_cancelling = work_requirement.status == WorkRequirementStatus.CANCELLING
    result = CLIENT.work_client.cancel_work_requirement_by_id(
        cast(str, work_requirement.id), bool(ARGS_PARSER.abort)
    )
    if already_cancelling:
        _record(work_requirement, _CANCELLED, abortedTasks=True)
        print_info(
            "Aborted the executing Tasks in already-cancelling Work Requirement"
            f" {_label(work_requirement)}"
        )
        return
    _record(work_requirement, _CANCELLED)
    aborted = " and aborted its executing Tasks" if ARGS_PARSER.abort else ""
    if isinstance(result, WorkRequirement):
        print_info(
            f"Cancelled {link_entity(CONFIG_COMMON.url, result)}"
            f" ({_label(work_requirement)}){aborted}"
        )
    else:
        print_info(f"Cancelled Work Requirement {_label(work_requirement)}{aborted}")


def _cancel_task(task: Task):
    CLIENT.work_client.cancel_task_by_id(cast(str, task.id), bool(ARGS_PARSER.abort))
    aborted = " and aborted" if ARGS_PARSER.abort else ""
    print_info(f"Cancelled{aborted} Task {_task_label(task)}")
    _record(task, _CANCELLED, entity_type=ET_TASKS)
