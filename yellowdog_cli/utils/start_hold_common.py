#!/usr/bin/env python3

"""
Core functionality for starting and holding Work Requirements.
"""

from collections.abc import Callable
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
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON


def start_work_requirements():
    required_state = WorkRequirementStatus.HELD
    action_function = CLIENT.work_client.start_work_requirement_by_id
    wr_ids = _start_or_hold_work_requirements("Start", required_state, action_function)
    if ARGS_PARSER.follow:
        follow_ids(wr_ids)


def hold_work_requirements():
    required_state = WorkRequirementStatus.RUNNING
    action_function = CLIENT.work_client.hold_work_requirement_by_id
    wr_ids = _start_or_hold_work_requirements("Hold", required_state, action_function)
    if ARGS_PARSER.follow:
        follow_ids(wr_ids)


def _start_or_hold_work_requirements(
    action: str, required_state: WorkRequirementStatus, action_function: Callable
) -> list[str]:

    if ARGS_PARSER.work_requirement_names:
        return _start_or_hold_work_requirements_by_name_or_id(
            action=action,
            required_state=required_state,
            action_function=action_function,
            names_or_ids=ARGS_PARSER.work_requirement_names,
        )

    print_info(
        f"{action}ing Work Requirements in namespace "
        f"'{CONFIG_COMMON.namespace}' with "
        f"'{CONFIG_COMMON.name_tag}' in tag"
    )

    selected_work_requirement_summaries: list[WorkRequirementSummary] = (
        get_filtered_work_requirement_summaries(
            client=CLIENT,
            namespace=CONFIG_COMMON.namespace,
            tag=CONFIG_COMMON.name_tag,
            include_filter=[required_state],
        )
    )

    count = 0
    work_requirement_ids: list[str] = []

    if selected_work_requirement_summaries:
        selected_work_requirement_summaries = select(
            CLIENT, selected_work_requirement_summaries
        )

    if selected_work_requirement_summaries and confirmed(
        f"{action} {len(selected_work_requirement_summaries)} Work Requirement(s)?"
    ):
        for work_summary in selected_work_requirement_summaries:
            if work_summary.status != required_state:
                continue
            try:
                action_function(work_summary.id)  # type: ignore[arg-type]
            except Exception as e:
                print_error(
                    f"Failed to {action} Work Requirement '{work_summary.name}': {e}"
                )
                continue  # Don't follow Work Requirements that weren't actioned
            count += 1
            work_requirement_ids.append(cast(str, work_summary.id))
            # The refetch is only needed to generate the link; the
            # action has already succeeded
            try:
                work_requirement: WorkRequirement = (
                    CLIENT.work_client.get_work_requirement_by_id(work_summary.id)  # type: ignore[arg-type]
                )
                print_info(
                    f"Applied {action} to "
                    f"{link_entity(CONFIG_COMMON.url, work_requirement)} "
                    f"('{work_summary.name}')"
                )
            except Exception:
                print_info(
                    f"Applied {action} to Work Requirement '{work_summary.name}'"
                )

        if count > 0:
            print_info(f"{action} applied to {count} Work Requirement(s)")
        else:
            print_info(f"No Work Requirements to {action}")

    else:
        print_info(f"No Work Requirements available to {action}")

    return work_requirement_ids


def _start_or_hold_work_requirements_by_name_or_id(
    action: str,
    required_state: WorkRequirementStatus,
    action_function: Callable,
    names_or_ids: list[str],
) -> list[str]:
    """
    Start or hold Work Requirements by their names or IDs.
    Return the list actioned of YDIDs.
    """
    work_requirement_summaries: list[WorkRequirementSummary] = []

    for name_or_id in names_or_ids:
        work_requirement_summary = get_work_requirement_summary_by_name_or_id(
            CLIENT, name_or_id, namespace=CONFIG_COMMON.namespace
        )

        if work_requirement_summary is None:
            print_error(f"Work Requirement '{name_or_id}' not found")
            continue

        fq_name_and_id = (
            f"'{work_requirement_summary.namespace}/{work_requirement_summary.name}' "
            f"({work_requirement_summary.id})"
        )

        if work_requirement_summary.status != required_state:
            print_warning(
                f"Work Requirement {fq_name_and_id} is not in the required '{required_state}'"
                f" state for action '{action}'"
            )
            continue

        if not confirmed(f"{action} Work Requirement {fq_name_and_id}?"):
            continue

        try:
            action_function(work_requirement_summary.id)
            print_info(
                f"Applied action '{action}' to Work Requirement {fq_name_and_id}"
            )
            work_requirement_summaries.append(work_requirement_summary)
        except Exception as e:
            print_error(
                f"Failed to apply action '{action}' to Work Requirement {fq_name_and_id}: {e}"
            )

    return [cast(str, wr.id) for wr in work_requirement_summaries]
