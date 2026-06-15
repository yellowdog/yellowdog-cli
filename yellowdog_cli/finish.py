#!/usr/bin/env python3

"""
A script to finish Work Requirements.
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


@main_wrapper
def main():
    if ARGS_PARSER.work_requirement_names:
        _finish_work_requirements_by_name_or_id(ARGS_PARSER.work_requirement_names)
        return

    print_info(
        "Finishing Work Requirements in namespace "
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
                WorkRequirementStatus.CANCELLING,
            ],
        )
    )

    finished_count = 0
    finishing_count = 0
    work_requirement_ids: list[str] = []

    if selected_work_requirement_summaries:
        selected_work_requirement_summaries = select(
            CLIENT, selected_work_requirement_summaries
        )

    if selected_work_requirement_summaries and confirmed(
        f"Finish {len(selected_work_requirement_summaries)} Work Requirement(s)?"
    ):
        for work_summary in selected_work_requirement_summaries:
            if work_summary.status != WorkRequirementStatus.FINISHING:
                try:
                    CLIENT.work_client.finish_work_requirement_by_id(work_summary.id)  # type: ignore[arg-type]
                except Exception as e:
                    print_error(
                        f"Failed to finish Work Requirement '{work_summary.name}': {e}"
                    )
                    continue  # Don't follow Work Requirements that failed to finish
                finished_count += 1
                # The refetch is only needed to generate the link; the
                # action has already succeeded
                try:
                    work_requirement: WorkRequirement = (
                        CLIENT.work_client.get_work_requirement_by_id(work_summary.id)  # type: ignore[arg-type]
                    )
                    print_info(
                        f"Finished {link_entity(CONFIG_COMMON.url, work_requirement)} "
                        f"('{work_summary.name}')"
                    )
                except Exception:
                    print_info(f"Finished Work Requirement '{work_summary.name}'")

            elif work_summary.status == WorkRequirementStatus.FINISHING:
                print_info(
                    f"Work Requirement '{work_summary.name}' is already finishing"
                )
                finishing_count += 1
            work_requirement_ids.append(work_summary.id)  # type: ignore[arg-type]

        if finished_count > 1:
            print_info(f"Finished {finished_count} Work Requirement(s)")
        elif finished_count == 0 and finishing_count == 0:
            print_info("No Work Requirements to finish")

        if ARGS_PARSER.follow:
            follow_ids(work_requirement_ids)

    else:
        print_info("No Work Requirements to finish")


def _finish_work_requirements_by_name_or_id(names_or_ids: list[str]):
    """
    Finish Work Requirements by their names or IDs.
    """
    work_requirement_summaries: list[WorkRequirementSummary] = []

    for name_or_id in names_or_ids:
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
        ]:
            print_warning(
                f"Work Requirement '{name_or_id}' is not in a valid state"
                f" ('{work_requirement_summary.status}') to be finished"
            )
            continue

        fq_name = (
            f"{work_requirement_summary.namespace}/{work_requirement_summary.name}"
        )
        if work_requirement_summary.status == WorkRequirementStatus.FINISHING:
            print_info(
                f"Work Requirement '{fq_name}' ({work_requirement_summary.id}) "
                "is already finishing"
            )
        else:
            if not confirmed(
                f"Finish Work Requirement '{fq_name}' ({work_requirement_summary.id})"
            ):
                continue
            try:
                CLIENT.work_client.finish_work_requirement_by_id(
                    work_requirement_summary.id  # type: ignore[arg-type]
                )
                print_info(
                    f"Finished Work Requirement '{fq_name}' ({work_requirement_summary.id})"
                )
            except Exception as e:
                print_error(
                    f"Failed to finish Work Requirement '{fq_name}' "
                    f"({work_requirement_summary.id}): {e}"
                )
                continue  # Don't follow Work Requirements that failed to finish

        # Only follow Work Requirements that are actually finishing
        work_requirement_summaries.append(work_requirement_summary)

    if ARGS_PARSER.follow:
        follow_ids([cast(str, wrs.id) for wrs in work_requirement_summaries])


# Entry point
if __name__ == "__main__":
    main()
