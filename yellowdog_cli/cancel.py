#!/usr/bin/env python3

"""
A script to cancel Work Requirements and optionally abort Tasks.
"""

from typing import cast

from yellowdog_client.model import (
    WorkRequirement,
    WorkRequirementStatus,
    WorkRequirementSummary,
)

from yellowdog_cli.utils.entity_utils import (
    get_filtered_work_requirement_summaries,
    get_work_requirement_summary_by_name_or_id,
)
from yellowdog_cli.utils.follow_utils import follow_ids
from yellowdog_cli.utils.interactive import confirmed, select
from yellowdog_cli.utils.misc_utils import link_entity
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON, main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type


@main_wrapper
def main():
    if ARGS_PARSER.work_requirement_names:
        _cancel_work_requirements_by_name_or_id(ARGS_PARSER.work_requirement_names)
        return

    print_info(
        "Cancelling Work Requirements in namespace "
        f"'{CONFIG_COMMON.namespace}' with tags "
        f"including '{CONFIG_COMMON.name_tag}'"
    )

    selected_work_requirement_summaries: list[WorkRequirementSummary] = (
        get_filtered_work_requirement_summaries(
            client=CLIENT,
            namespace=CONFIG_COMMON.namespace,
            tag=CONFIG_COMMON.name_tag,
            exclude_filter=[
                WorkRequirementStatus.COMPLETED,
                WorkRequirementStatus.CANCELLED,
                WorkRequirementStatus.FAILED,
            ],
        )
    )

    cancelled_count = 0
    cancelling_count = 0
    work_requirement_ids: list[str] = []

    if selected_work_requirement_summaries:
        selected_work_requirement_summaries = select(
            CLIENT, selected_work_requirement_summaries
        )

    if selected_work_requirement_summaries and confirmed(
        f"Cancel {len(selected_work_requirement_summaries)} "
        f"Work Requirement(s)"
        f"{'' if not ARGS_PARSER.abort else ' and abort all executing tasks'}?"
    ):
        for work_summary in selected_work_requirement_summaries:
            if work_summary.status != WorkRequirementStatus.CANCELLING:
                try:
                    CLIENT.work_client.cancel_work_requirement_by_id(
                        work_summary.id,  # type: ignore[arg-type]
                        ARGS_PARSER.abort,
                    )
                except Exception as e:
                    print_error(
                        f"Failed to cancel Work Requirement '{work_summary.name}': {e}"
                    )
                    continue  # Don't follow Work Requirements that failed to cancel
                cancelled_count += 1
                cancel_msg_postfix = (
                    "" if not ARGS_PARSER.abort else " and aborted all executing tasks"
                )
                # The refetch is only needed to generate the link; the
                # cancellation has already succeeded
                try:
                    work_requirement: WorkRequirement = (
                        CLIENT.work_client.get_work_requirement_by_id(work_summary.id)  # type: ignore[arg-type]
                    )
                    print_info(
                        f"Cancelled {link_entity(CONFIG_COMMON.url, work_requirement)} "
                        f"('{work_summary.name}')"
                        f"{cancel_msg_postfix}"
                    )
                except Exception:
                    print_info(
                        f"Cancelled Work Requirement '{work_summary.name}'"
                        f"{cancel_msg_postfix}"
                    )

            elif work_summary.status == WorkRequirementStatus.CANCELLING:
                # Re-issue the cancel with abort=True so the platform aborts
                # the still-executing Tasks; the user already confirmed the
                # cancel-and-abort intent at the batch prompt
                if ARGS_PARSER.abort:
                    try:
                        CLIENT.work_client.cancel_work_requirement_by_id(
                            work_summary.id,  # type: ignore[arg-type]
                            True,
                        )
                        print_info(
                            f"Aborted executing Tasks in already-cancelling"
                            f" Work Requirement '{work_summary.name}'"
                        )
                    except Exception as e:
                        print_error(
                            f"Failed to abort Tasks in '{work_summary.name}': {e}"
                        )
                        continue
                else:
                    print_info(
                        f"Work Requirement '{work_summary.name}' is already cancelling"
                    )
                cancelling_count += 1
            work_requirement_ids.append(work_summary.id)  # type: ignore[arg-type]

        if cancelled_count > 1:
            print_info(f"Cancelled {cancelled_count} Work Requirement(s)")
        elif cancelled_count == 0 and cancelling_count == 0:
            print_info("No Work Requirements to cancel")

        if ARGS_PARSER.follow:
            follow_ids(work_requirement_ids)

    else:
        print_info("No Work Requirements to cancel")


def _cancel_work_requirements_by_name_or_id(names_or_ids: list[str]):
    """
    Cancel Work Requirements by their names or IDs.
    """
    work_requirement_summaries: list[WorkRequirementSummary] = []

    for name_or_id in names_or_ids:
        # Handle a task ID
        if get_ydid_type(name_or_id) == YDIDType.TASK:
            if not confirmed(
                f"Cancel {'' if not ARGS_PARSER.abort else 'and abort '}"
                f"Task '{name_or_id}'?"
            ):
                continue
            try:
                CLIENT.work_client.cancel_task_by_id(name_or_id, ARGS_PARSER.abort)
                print_info(
                    f"Cancelled{'' if not ARGS_PARSER.abort else ' and aborted'}"
                    f" Task '{name_or_id}'"
                )
            except Exception as e:
                print_error(f"Failed to cancel Task '{name_or_id}': {e}")
            continue

        work_requirement_summary = get_work_requirement_summary_by_name_or_id(
            CLIENT,
            name_or_id,
            namespace=CONFIG_COMMON.namespace,
        )
        if work_requirement_summary is None:
            print_error(f"Work Requirement '{name_or_id}' not found")
            continue

        if work_requirement_summary.status not in [
            WorkRequirementStatus.RUNNING,
            WorkRequirementStatus.HELD,
            WorkRequirementStatus.FINISHING,
            WorkRequirementStatus.CANCELLING,
        ]:
            print_warning(
                f"Work Requirement '{name_or_id}' is not in a valid state"
                f" ('{work_requirement_summary.status}') for cancellation"
            )
            continue

        fq_name = (
            f"{work_requirement_summary.namespace}/{work_requirement_summary.name}"
        )
        if work_requirement_summary.status == WorkRequirementStatus.CANCELLING:
            # The user explicitly asked for Tasks to be aborted via '-a'; the
            # WR cancel is already in flight, so re-issue with abort=True to
            # promote it to also abort the still-executing Tasks
            if ARGS_PARSER.abort:
                if not confirmed(
                    f"Abort executing Tasks in already-cancelling Work"
                    f" Requirement '{fq_name}' ({work_requirement_summary.id})?"
                ):
                    continue
                try:
                    CLIENT.work_client.cancel_work_requirement_by_id(
                        work_requirement_summary.id,  # type: ignore[arg-type]
                        True,
                    )
                    print_info(
                        f"Aborted executing Tasks in already-cancelling Work"
                        f" Requirement '{fq_name}' ({work_requirement_summary.id})"
                    )
                except Exception as e:
                    print_error(
                        f"Failed to abort Tasks in '{fq_name}'"
                        f" ({work_requirement_summary.id}): {e}"
                    )
                    continue
            else:
                print_info(
                    f"Work Requirement '{fq_name}' ({work_requirement_summary.id}) "
                    "is already cancelling"
                )
        else:
            if not confirmed(
                f"Cancel Work Requirement '{fq_name}' ({work_requirement_summary.id})"
                f"{'' if not ARGS_PARSER.abort else ' and abort all executing tasks'}?"
            ):
                continue
            try:
                CLIENT.work_client.cancel_work_requirement_by_id(
                    work_requirement_summary.id,  # type: ignore[arg-type]
                    ARGS_PARSER.abort,
                )
                print_info(
                    f"Cancelled Work Requirement '{fq_name}' ({work_requirement_summary.id})"
                    f"{'' if not ARGS_PARSER.abort else ' and aborted all executing tasks'}"
                )
            except Exception as e:
                print_error(
                    f"Failed to cancel Work Requirement '{fq_name}' "
                    f"({work_requirement_summary.id}): {e}"
                )
                continue  # Don't follow Work Requirements that failed to cancel

        # Only follow Work Requirements that are actually cancelling
        work_requirement_summaries.append(work_requirement_summary)

    if ARGS_PARSER.follow:
        follow_ids([cast(str, wrs.id) for wrs in work_requirement_summaries])


# Entry point
if __name__ == "__main__":
    main()
