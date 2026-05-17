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
    get_task_group_name,
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
        _abort_tasks_by_name_or_id(ARGS_PARSER.task_id_list)
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

    task_search = TaskSearch(
        workRequirementId=wr_summary.id,
        statuses=[TaskStatus.EXECUTING],
    )
    tasks: list[Task] = CLIENT.work_client.find_tasks(task_search)

    if not tasks:
        print_info(
            "No currently executing Tasks in this Work Requirement",
            override_quiet=True,
        )
        return

    if not ARGS_PARSER.yes:
        tasks = select(CLIENT, sorted_objects(tasks), override_quiet=True)
        if not tasks or not confirmed(f"Abort {len(tasks)} Task(s)?"):
            print_info("No Tasks Aborted")
            return

    aborted_tasks = 0
    for task in tasks:
        try:
            CLIENT.work_client.cancel_task(task, abort=True)
            print_info(
                f"Aborted Task '{task.name}' in Task Group"
                f" '{get_task_group_name(CLIENT, wr_summary, task)}' in Work"
                f" Requirement '{wr_summary.name}'"
            )
            aborted_tasks += 1
        except Exception as e:
            print_error(f"Unable to abort Task '{task.name}': {e}")

    if aborted_tasks == 0:
        print_info("No Tasks Aborted")
    elif aborted_tasks > 1:
        print_info(f"Aborted {aborted_tasks} Tasks")


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
