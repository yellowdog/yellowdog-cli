#!/usr/bin/env python3

"""
A script to abort Tasks without cancelling their Work Requirements.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from yellowdog_client.model import (
    Task,
    TaskSearch,
    TaskStatus,
    WorkRequirementStatus,
    WorkRequirementSummary,
)

from yellowdog_cli.utils.action_runner import warn_not_attempted
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    ET_TASK_GROUPS,
    ET_TASKS,
    ET_WORK_REQUIREMENTS,
)
from yellowdog_cli.utils.entity_utils import (
    AmbiguousNameError,
    get_filtered_work_requirement_summaries,
    get_task_groups_from_wr_by_id,
    get_work_requirement_summary_by_name_or_id,
)
from yellowdog_cli.utils.exit_codes import SESSION_FAILURES, ReportedFailure, classify
from yellowdog_cli.utils.interactive import NoAnswerToPrompt, confirmed, select
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.results import json_requested, record_action
from yellowdog_cli.utils.wrapper import main_wrapper
from yellowdog_cli.utils.ydid_utils import (
    YDIDType,
    get_ydid_type,
    work_requirement_id_of_task_group,
)

NO_RUNNING_TASKS = "no running Tasks"

# The states of a Task running on a Worker, which a Work Requirement's or
# Task Group's abort applies to: one yet to start would be cancelled
# instead, and a finished one has nothing to abort. A Task named by its ID
# is aborted whatever its state.
_RUNNING_TASK_STATUSES = [
    TaskStatus.DOWNLOADING,
    TaskStatus.EXECUTING,
    TaskStatus.UPLOADING,
]


@dataclass
class _Run:
    """
    The run: what it runs with, the outcomes for Tasks across it, and the
    Tasks handled.
    """

    ctx: RunContext
    aborted: int = 0
    skipped: int = 0
    failed: int = 0
    handled: set[str | None] = field(default_factory=set)

    @property
    def total(self) -> int:
        return self.aborted + self.skipped + self.failed


class _SessionFailure(Exception):
    """
    A failure every later call would repeat (see SESSION_FAILURES), raised
    once the failing item and the rest of its batch have been recorded, so
    that no later target is attempted either.
    """

    def __init__(self, cause: Exception, not_attempted: int):
        super().__init__(str(cause))
        self.cause = cause
        self.not_attempted = not_attempted


# The entities a unit of work is recorded as if it fails as a whole, and the
# work itself
_Unit = tuple[list[tuple[object, str]], Callable[[], None]]


def _record(
    entity: object,
    outcome: str,
    error: str | None = None,
    entity_type: str = ET_TASKS,
) -> None:
    record_action(entity, entity_type, "abort", outcome, error)


def _label(entity: object) -> str:
    """An entity's name for a message: its name, else its ID, else itself."""
    if isinstance(entity, dict):
        return str(entity.get("name") or entity.get("id"))
    return str(getattr(entity, "name", None) or getattr(entity, "id", entity))


@main_wrapper
def main(ctx: RunContext) -> None:
    run = _Run(ctx)
    if ctx.args.task_id_list:
        _run_units(_target_units(_without_duplicates(ctx.args.task_id_list), run), run)
    else:
        _run_units(_interactive_units(run), run)

    if run.total > 1:
        print_info(
            f"Aborted {run.aborted} of {run.total} Tasks"
            f" ({run.skipped} skipped, {run.failed} failed)"
        )
    elif run.aborted == 0:
        print_info("No Tasks aborted")


def _without_duplicates(targets: list[str]) -> list[str]:
    """
    The targets in the order given, each once: a repeated target would
    otherwise have its Tasks aborted again.
    """
    unique = list(dict.fromkeys(targets))
    if len(unique) < len(targets):
        print_warning(f"Ignoring {len(targets) - len(unique)} duplicate target(s)")
    return unique


def _run_units(units: list[_Unit], run: _Run) -> None:
    """
    Do each unit of work in turn. A unit that fails as a whole (a lookup
    failing, say) is recorded as failed and the next one is done, unless
    the failure is the session's, when nothing further is attempted.
    """
    for index, (entities, work) in enumerate(units):
        try:
            work()
            continue
        except NoAnswerToPrompt:
            raise
        except _SessionFailure as e:
            failure = e
        except Exception as e:
            for entity, entity_type in entities:
                if entity in run.handled:  # a Task ID already recorded
                    continue
                print_error(f"Unable to abort Tasks for '{_label(entity)}': {e}")
                _record(entity, "failed", str(e), entity_type)
                if entity_type == ET_TASKS:
                    run.failed += 1
            if classify(e) not in SESSION_FAILURES:
                continue
            failure = _SessionFailure(e, 0)

        not_attempted = failure.not_attempted
        for entities, _ in units[index + 1 :]:
            for entity, entity_type in entities:
                _record(
                    entity, "skipped", f"not attempted: {failure.cause}", entity_type
                )
                if entity_type == ET_TASKS:
                    run.skipped += 1
                not_attempted += 1
        warn_not_attempted(not_attempted)
        raise ReportedFailure(failure.cause)


def _target_units(targets: list[str], run: _Run) -> list[_Unit]:
    """
    One unit per target, in the order given, except that the Task IDs are
    one unit, at the place the first of them was given, so that they are
    confirmed together, as a Work Requirement's or Task Group's Tasks are.
    """
    units: list[_Unit] = []
    task_ids: list[str] = []
    task_entities: list[tuple[object, str]] = []  # filled as the IDs are seen
    for target in targets:
        ydid_type = get_ydid_type(target)
        if ydid_type == YDIDType.TASK:
            if not task_ids:
                units.append((task_entities, lambda: _abort_tasks_by_id(task_ids, run)))
            task_ids.append(target)
            task_entities.append((target, ET_TASKS))
        elif ydid_type == YDIDType.TASK_GROUP:
            units.append(
                (
                    [(target, ET_TASK_GROUPS)],
                    lambda t=target: _abort_task_group_by_id(t, run),
                )
            )
        elif ydid_type == YDIDType.WORK_REQUIREMENT:
            units.append(
                (
                    [(target, ET_WORK_REQUIREMENTS)],
                    lambda t=target: _abort_work_requirement_by_id(t, run),
                )
            )
        elif ydid_type is None:
            units.append(
                (
                    [(target, _named_target_type(target))],
                    lambda t=target: _abort_named_target(t, run),
                )
            )
        else:
            units.append(
                (
                    [(target, _ydid_entity_type(ydid_type))],
                    lambda t=target, y=ydid_type: _not_a_target(t, y),
                )
            )
    return units


def _not_a_target(target: str, ydid_type: YDIDType) -> None:
    message = (
        f"'{target}' is a {ydid_type.value} ID, not a Task, Task Group or"
        " Work Requirement ID"
    )
    print_error(message)
    _record(target, "failed", message, _ydid_entity_type(ydid_type))


def _ydid_entity_type(ydid_type: YDIDType) -> str:
    """
    The type a YDID of the wrong kind is recorded as: its own, spelled as
    yd-list spells types ('Worker Pool' as 'worker-pools').
    """
    return f"{ydid_type.value.lower().replace(' ', '-')}s"


def _named_target_type(target: str) -> str:
    """The type a named target is recorded as: a Task Group if it names one."""
    return ET_WORK_REQUIREMENTS if "/" not in target else ET_TASK_GROUPS


def _interactive_units(run: _Run) -> list[_Unit]:
    """The Work Requirements in the namespace and tag the user selects."""
    print_info(
        "Finding active Work Requirements in "
        f"namespace '{run.ctx.config.namespace}' with tags "
        f"including '{run.ctx.config.name_tag}'"
    )

    # The Work Requirements, and then their Tasks, are chosen from lists,
    # unless --yes is given
    run.ctx.args.interactive = True

    work_requirement_summaries: list[WorkRequirementSummary] = (
        get_filtered_work_requirement_summaries(
            run.ctx.client,
            namespace=run.ctx.config.namespace,
            tag=run.ctx.config.name_tag,
            exclude_filter=[
                WorkRequirementStatus.COMPLETED,
                WorkRequirementStatus.CANCELLED,
                WorkRequirementStatus.FAILED,
            ],
        )
    )

    if not work_requirement_summaries:
        print_info("No matching Work Requirements found")
        return []

    if not run.ctx.args.yes:
        work_requirement_summaries = select(
            run.ctx.client, work_requirement_summaries, override_quiet=True
        )

    return [
        (
            [(summary, ET_WORK_REQUIREMENTS)],
            lambda s=summary: _abort_in_work_requirement(s.id, s.name, run),
        )
        for summary in work_requirement_summaries
    ]


def _running_tasks(run: _Run, search: TaskSearch) -> list[Task]:
    return run.ctx.client.work_client.get_tasks(search).list_all()


def _nothing_running(entity: object, entity_type: str, where: str) -> None:
    print_info(
        f"No Tasks running in this {where}",
        override_quiet=not json_requested(),
    )
    _record(entity, "skipped", NO_RUNNING_TASKS, entity_type)


def _task_group_part(run: _Run, work_requirement_id: str | None, task: Task) -> str:
    """
    " in Task Group '<name>'" for a message about a Task, or "" when its
    Work Requirement is not known or the name cannot be found: the Task has
    been acted on by then, and a lookup failing must not report otherwise.
    """
    if work_requirement_id is None:
        return ""
    try:
        task_groups = get_task_groups_from_wr_by_id(run.ctx.client, work_requirement_id)
    except Exception:
        return ""
    name = next((g.name for g in task_groups if g.id == task.taskGroupId), None)
    return "" if name is None else f" in Task Group '{name}'"


def _abort_in_work_requirement(
    work_requirement_id: str | None, work_requirement_name: str | None, run: _Run
) -> None:
    print_info(f"Aborting Tasks in Work Requirement '{work_requirement_name}'")
    tasks = _running_tasks(
        run,
        TaskSearch(
            workRequirementId=work_requirement_id, statuses=_RUNNING_TASK_STATUSES
        ),
    )
    entity = {"id": work_requirement_id, "name": work_requirement_name}
    if not tasks:
        _nothing_running(entity, ET_WORK_REQUIREMENTS, "Work Requirement")
        return
    _abort_tasks(
        tasks,
        run,
        context=f"Work Requirement '{work_requirement_name}'",
        work_requirement_id=work_requirement_id,
    )


def _abort_in_task_group(
    task_group_id: str | None, task_group_name: str | None, context: str, run: _Run
) -> None:
    print_info(f"Aborting Tasks in {context}")
    tasks = _running_tasks(
        run, TaskSearch(taskGroupId=task_group_id, statuses=_RUNNING_TASK_STATUSES)
    )
    if not tasks:
        _nothing_running(
            {"id": task_group_id, "name": task_group_name},
            ET_TASK_GROUPS,
            "Task Group",
        )
        return
    _abort_tasks(tasks, run, context=context)


def _abort_work_requirement_by_id(work_requirement_id: str, run: _Run) -> None:
    """
    By ID, in whatever namespace: a YDID is unique, so it is fetched rather
    than looked for among the configured namespace's Work Requirements.
    """
    try:
        work_requirement = run.ctx.client.work_client.get_work_requirement_by_id(
            work_requirement_id
        )
    except Exception as e:
        if not is_http_not_found(e):
            raise
        _not_found(
            f"Work Requirement '{work_requirement_id}'",
            work_requirement_id,
            ET_WORK_REQUIREMENTS,
        )
        return
    _abort_in_work_requirement(work_requirement.id, work_requirement.name, run)


def _abort_task_group_by_id(task_group_id: str, run: _Run) -> None:
    try:
        task_groups = get_task_groups_from_wr_by_id(
            run.ctx.client, work_requirement_id_of_task_group(task_group_id)
        )
    except Exception as e:
        if not is_http_not_found(e):
            raise
        task_groups = []
    task_group = next((g for g in task_groups if g.id == task_group_id), None)
    if task_group is None:
        _not_found(f"Task Group '{task_group_id}'", task_group_id, ET_TASK_GROUPS)
        return
    _abort_in_task_group(
        task_group_id, task_group.name, f"Task Group '{task_group.name}'", run
    )


def _not_found(what: str, entity: object, entity_type: str) -> None:
    print_error(f"{what} not found")
    _record(entity, "failed", "not found", entity_type)


def _work_requirement_named(
    run: _Run, name: str, namespace: str | None
) -> WorkRequirementSummary | None:
    """A Work Requirement by its name, which holds no '/', in a namespace."""
    return get_work_requirement_summary_by_name_or_id(
        run.ctx.client, name, namespace=namespace
    )


def _abort_in_named_task_group(
    work_requirement: WorkRequirementSummary, task_group_name: str, run: _Run
) -> bool:
    """
    Abort the executing Tasks in the Work Requirement's Task Group of that
    name, returning False, having done nothing, if it has none.
    """
    task_groups = get_task_groups_from_wr_by_id(run.ctx.client, work_requirement.id)  # type: ignore[arg-type]
    task_group = next((g for g in task_groups if g.name == task_group_name), None)
    if task_group is None:
        return False
    _abort_in_task_group(
        task_group.id,
        task_group.name,
        f"Task Group '{task_group.name}' in Work Requirement '{work_requirement.name}'",
        run,
    )
    return True


def _abort_named_target(target: str, run: _Run) -> None:
    """
    A target by name: 'wr', 'wr/tg', 'namespace/wr' or 'namespace/wr/tg'.
    Of the two readings of 'a/b', the Task Group is tried first, being the
    form documented for this command.
    """
    namespace = run.ctx.config.namespace
    parts = target.split("/")
    if parts[0] == "" and len(parts) > 1:  # a leading '/' names no namespace
        parts = parts[1:]

    if len(parts) == 1:
        work_requirement = _work_requirement_named(run, parts[0], namespace)
        if work_requirement is None:
            _not_found(f"Work Requirement '{target}'", target, ET_WORK_REQUIREMENTS)
            return
        _abort_in_work_requirement(work_requirement.id, work_requirement.name, run)
        return

    if len(parts) == 2:
        first, second = parts
        # An ambiguous Work Requirement name rules out only this reading
        ambiguous: AmbiguousNameError | None = None
        try:
            work_requirement = _work_requirement_named(run, first, namespace)
        except AmbiguousNameError as e:
            work_requirement, ambiguous = None, e
        if work_requirement is not None and _abort_in_named_task_group(
            work_requirement, second, run
        ):
            return
        namespaced = _work_requirement_named(run, second, first)
        if namespaced is not None:
            _abort_in_work_requirement(namespaced.id, namespaced.name, run)
            return
        if ambiguous is not None:
            raise ambiguous
        if work_requirement is not None:
            _not_found(
                f"Task Group '{second}' in Work Requirement '{first}'",
                target,
                ET_TASK_GROUPS,
            )
        else:
            _not_found(
                f"Work Requirement '{first}' (or '{second}' in namespace '{first}')",
                target,
                ET_WORK_REQUIREMENTS,
            )
        return

    if len(parts) == 3:
        target_namespace, work_requirement_name, task_group_name = parts
        work_requirement = _work_requirement_named(
            run, work_requirement_name, target_namespace
        )
        if work_requirement is None:
            _not_found(
                f"Work Requirement '{work_requirement_name}' in namespace"
                f" '{target_namespace}'",
                target,
                ET_TASK_GROUPS,
            )
            return
        if not _abort_in_named_task_group(work_requirement, task_group_name, run):
            _not_found(
                f"Task Group '{task_group_name}' in Work Requirement"
                f" '{work_requirement_name}'",
                target,
                ET_TASK_GROUPS,
            )
        return

    message = (
        f"'{target}' is not of the form 'wr', 'wr/tg', 'namespace/wr' or"
        " 'namespace/wr/tg'"
    )
    print_error(message)
    _record(target, "failed", message, ET_TASK_GROUPS)


def _abort_tasks_by_id(task_ids: list[str], run: _Run) -> None:
    """
    Abort Tasks by their YDIDs, whatever their state: a Task named by its
    ID is aborted as asked, and the Platform decides what that means for
    one that is not running.
    """
    tasks: list[Task] = []
    for index, task_id in enumerate(task_ids):
        try:
            task = run.ctx.client.work_client.get_task_by_id(task_id)
        except Exception as e:
            error = "not found" if is_http_not_found(e) else str(e)
            print_error(f"Unable to abort Task '{task_id}': {error}")
            _record(task_id, "failed", error)
            run.failed += 1
            run.handled.add(task_id)
            _stop_if_session_failure(e, [*tasks, *task_ids[index + 1 :]], run)
            continue
        tasks.append(task)

    if tasks:
        _abort_tasks(tasks, run)


def _stop_if_session_failure(
    e: Exception, not_attempted: Sequence[Task | str], run: _Run
) -> None:
    """
    If the failure is the session's, record the Tasks not yet attempted as
    skipped and raise _SessionFailure, so that nothing further is attempted.
    """
    if classify(e) not in SESSION_FAILURES:
        return
    for task in not_attempted:
        _record(task, "skipped", f"not attempted: {e}")
        run.skipped += 1
        run.handled.add(task if isinstance(task, str) else task.id)
    raise _SessionFailure(e, len(not_attempted))


def _abort_tasks(
    tasks: list[Task],
    run: _Run,
    context: str | None = None,
    work_requirement_id: str | None = None,
) -> None:
    """
    Select (unless --yes), confirm (unless --yes), then abort the given
    Tasks, each once in the run however many targets include it.
    """
    already_handled = [task for task in tasks if task.id in run.handled]
    if already_handled:
        print_info(f"Ignoring {len(already_handled)} Task(s) already handled")
    tasks = [task for task in tasks if task.id not in run.handled]
    if not tasks:
        return

    if not run.ctx.args.yes:
        selected = select(run.ctx.client, tasks, override_quiet=True)
        selected_ids = {task.id for task in selected}
        for task in tasks:
            if task.id not in selected_ids:
                _record(task, "skipped", "not selected")
                run.skipped += 1
                run.handled.add(task.id)
        if not selected:
            return
        if not confirmed(f"Abort {len(selected)} Task(s)?"):
            for task in selected:
                _record(task, "skipped", "declined")
                run.skipped += 1
                run.handled.add(task.id)
            return
        tasks = selected

    in_context = "" if context is None else f" in {context}"
    for index, task in enumerate(tasks):
        run.handled.add(task.id)
        try:
            run.ctx.client.work_client.cancel_task(task, abort=True)
        except Exception as e:
            print_error(f"Unable to abort Task '{task.name}': {e}")
            _record(task, "failed", str(e))
            run.failed += 1
            _stop_if_session_failure(e, tasks[index + 1 :], run)
            continue
        print_info(
            f"Aborted Task '{task.name}'"
            f"{_task_group_part(run, work_requirement_id, task)}{in_context}"
        )
        _record(task, "aborted")
        run.aborted += 1


# Entry point
if __name__ == "__main__":
    main()
