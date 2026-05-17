#!/usr/bin/env python3

"""
A script to abort Tasks without cancelling their Work Requirements.
"""

from yellowdog_client.model import (
    Task,
    TaskSearch,
    TaskStatus,
    WorkRequirementStatus,
    WorkRequirementSummary,
)

from yellowdog_cli.utils.entity_utils import (
    get_filtered_work_requirement_summaries,
    get_task_group_by_id,
    get_task_group_name,
    get_task_groups_from_wr_by_id,
    get_work_requirement_summary_by_name_or_id,
)
from yellowdog_cli.utils.interactive import confirmed, select
from yellowdog_cli.utils.printing import (
    print_error,
    print_info,
    sorted_objects,
)
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON, main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type


@main_wrapper
def main():

    if ARGS_PARSER.task_id_list:
        task_ids = [
            a for a in ARGS_PARSER.task_id_list if get_ydid_type(a) == YDIDType.TASK
        ]
        tg_ids = [
            a
            for a in ARGS_PARSER.task_id_list
            if get_ydid_type(a) == YDIDType.TASK_GROUP
        ]
        wr_names = [
            a
            for a in ARGS_PARSER.task_id_list
            if get_ydid_type(a) not in (YDIDType.TASK, YDIDType.TASK_GROUP)
        ]
        if task_ids:
            _abort_tasks_by_name_or_id(task_ids)
        if tg_ids:
            _abort_tasks_in_tg_by_id(tg_ids)
        if wr_names:
            _abort_tasks_in_wrs_by_name(wr_names)
        return

    print_info(
        "Finding active Work Requirements in "
        f"namespace '{CONFIG_COMMON.namespace}' with tags "
        f"including '{CONFIG_COMMON.name_tag}'"
    )

    # Abort Tasks is always interactive
    ARGS_PARSER.interactive = True

    selected_work_requirement_summaries: list[WorkRequirementSummary] = (
        get_filtered_work_requirement_summaries(
            CLIENT,
            namespace=CONFIG_COMMON.namespace,
            tag=CONFIG_COMMON.name_tag,
            exclude_filter=[
                WorkRequirementStatus.COMPLETED,
                WorkRequirementStatus.CANCELLED,
                WorkRequirementStatus.FAILED,
            ],
        )
    )

    if not selected_work_requirement_summaries:
        print_info("No matching Work Requirements found")
        return

    if not ARGS_PARSER.yes:
        selected_work_requirement_summaries = select(
            CLIENT,
            selected_work_requirement_summaries,
            override_quiet=True,
        )

    for wr_summary in selected_work_requirement_summaries:
        abort_tasks_selectively(wr_summary)


def abort_tasks_selectively(
    wr_summary: WorkRequirementSummary,
) -> None:
    """
    Abort selected Tasks in a Work Requirement.
    With --yes, all executing tasks are aborted without prompting.
    """
    print_info(f"Aborting Tasks in Work Requirement '{wr_summary.name}'")
    tasks: list[Task] = CLIENT.work_client.find_tasks(
        TaskSearch(workRequirementId=wr_summary.id, statuses=[TaskStatus.EXECUTING])
    )
    if not tasks:
        print_info(
            "No currently executing Tasks in this Work Requirement",
            override_quiet=True,
        )
        return
    _do_abort_tasks(
        tasks,
        context=f"Work Requirement '{wr_summary.name}'",
        wr_summary=wr_summary,
    )


def _do_abort_tasks(
    tasks: list[Task],
    context: str,
    wr_summary: WorkRequirementSummary | None = None,
) -> None:
    """
    Select (unless --yes), confirm (unless --yes), then abort the given tasks.
    """
    if not ARGS_PARSER.yes:
        tasks = select(CLIENT, sorted_objects(tasks), override_quiet=True)
        if not tasks or not confirmed(f"Abort {len(tasks)} Task(s)?"):
            print_info("No Tasks Aborted")
            return

    aborted_tasks = 0
    for task in tasks:
        try:
            CLIENT.work_client.cancel_task(task, abort=True)
            tg_part = (
                f" in Task Group '{get_task_group_name(CLIENT, wr_summary, task)}'"
                if wr_summary is not None
                else ""
            )
            print_info(f"Aborted Task '{task.name}'{tg_part} in {context}")
            aborted_tasks += 1
        except Exception as e:
            print_error(f"Unable to abort Task '{task.name}': {e}")

    if aborted_tasks == 0:
        print_info("No Tasks Aborted")
    elif aborted_tasks > 1:
        print_info(f"Aborted {aborted_tasks} Tasks")


def _abort_tasks_in_tg_by_id(tg_ids: list[str]) -> None:
    """
    Abort executing tasks in Task Groups identified by YDID.
    """
    for tg_id in tg_ids:
        try:
            tg = get_task_group_by_id(CLIENT, tg_id)
        except (KeyError, RuntimeError) as e:
            print_error(str(e))
            continue
        print_info(f"Aborting Tasks in Task Group '{tg.name}'")
        tasks: list[Task] = CLIENT.work_client.find_tasks(
            TaskSearch(taskGroupId=tg_id, statuses=[TaskStatus.EXECUTING])
        )
        if not tasks:
            print_info(
                "No currently executing Tasks in this Task Group",
                override_quiet=True,
            )
            continue
        _do_abort_tasks(tasks, context=f"Task Group '{tg.name}'")


def _abort_tasks_in_wrs_by_name(wr_names: list[str]) -> None:
    """
    Look up Work Requirements by name/ID, then abort their executing tasks.
    If a name is not found as a WR and contains '/', the part before the last
    '/' is tried as a WR name and the part after as a Task Group name within it.
    """
    for name in wr_names:
        wr_summary = get_work_requirement_summary_by_name_or_id(
            CLIENT, name, namespace=CONFIG_COMMON.namespace
        )
        if wr_summary is not None:
            abort_tasks_selectively(wr_summary)
            continue

        if "/" not in name:
            print_error(f"Work Requirement '{name}' not found")
            continue

        # Try wr-name/tg-name (rsplit handles namespace/wr-name/tg-name correctly)
        wr_part, tg_part = name.rsplit("/", 1)
        wr_summary = get_work_requirement_summary_by_name_or_id(
            CLIENT, wr_part, namespace=CONFIG_COMMON.namespace
        )
        if wr_summary is None:
            print_error(f"Work Requirement '{wr_part}' not found")
            continue

        tg_groups = get_task_groups_from_wr_by_id(CLIENT, wr_summary.id)  # type: ignore[arg-type]
        tg = next((g for g in tg_groups if g.name == tg_part), None)
        if tg is None:
            print_error(
                f"Task Group '{tg_part}' not found in Work Requirement '{wr_summary.name}'"
            )
            continue

        print_info(
            f"Aborting Tasks in Task Group '{tg.name}'"
            f" in Work Requirement '{wr_summary.name}'"
        )
        tasks: list[Task] = CLIENT.work_client.find_tasks(
            TaskSearch(taskGroupId=tg.id, statuses=[TaskStatus.EXECUTING])
        )
        if not tasks:
            print_info(
                "No currently executing Tasks in this Task Group",
                override_quiet=True,
            )
            continue
        _do_abort_tasks(
            tasks,
            context=f"Task Group '{tg.name}' in Work Requirement '{wr_summary.name}'",
        )


def _abort_tasks_by_name_or_id(task_id_list: list[str]):
    """
    Abort Tasks by their YDIDs.
    """
    aborted_count = 0
    for task_id in task_id_list:
        if get_ydid_type(task_id) != YDIDType.TASK:
            print_error(f"ID '{task_id}' is not a valid Task YDID")
            continue

        if not confirmed(f"Cancel and abort Task '{task_id}'?"):
            continue

        try:
            CLIENT.work_client.cancel_task_by_id(task_id, abort=True)
            print_info(f"Cancelled and aborted Task '{task_id}'")
            aborted_count += 1
        except Exception as e:
            print_error(f"Unable to cancel and abort Task '{task_id}': {e}")

    if aborted_count > 1:
        print_info(f"Cancelled and aborted {aborted_count} Tasks")
    elif aborted_count == 0:
        print_info("No Tasks cancelled and aborted")


# Entry point
if __name__ == "__main__":
    main()
