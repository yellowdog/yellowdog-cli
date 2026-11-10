"""
The Work Requirement that '--add-to' names, shared by 'yd workrequirement
submit' and 'yd workrequirement resubmit': found by YDID or name and checked
to be in a state that can still take Tasks.
"""

from typing import cast

from yellowdog_client.model import WorkRequirement, WorkRequirementStatus

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_utils import (
    AmbiguousNameError,
    find_work_requirement_by_name,
)
from yellowdog_cli.utils.exit_codes import NotFoundError
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

# The states of a Work Requirement that can still take Tasks: a FINISHING one
# takes no new ones, and the rest have finished or are being cancelled
ADDABLE_STATUSES = (WorkRequirementStatus.RUNNING, WorkRequirementStatus.HELD)


def work_requirement_to_add_to(ctx: RunContext, target: str) -> WorkRequirement:
    """
    The Work Requirement '--add-to' names, fetched in full: by its YDID,
    whatever its namespace, or by its name, preferring the one that can still
    take Tasks. Raises NotFoundError if there is none, and ValueError if it
    cannot take Tasks (or the name is ambiguous).
    """
    if get_ydid_type(target) == YDIDType.WORK_REQUIREMENT:
        work_requirement_id = target
    else:
        try:
            summary = find_work_requirement_by_name(
                ctx.client, target, ctx.config.namespace, ADDABLE_STATUSES
            )
        except AmbiguousNameError as e:
            raise ValueError(str(e)) from e
        work_requirement_id = cast(str, summary.id)
    try:
        work_requirement = ctx.client.work_client.get_work_requirement_by_id(
            work_requirement_id
        )
    except Exception as e:
        if is_http_not_found(e):
            raise NotFoundError(f"Cannot find Work Requirement {target}") from e
        raise
    if work_requirement.status not in ADDABLE_STATUSES:
        raise ValueError(
            f"Work Requirement '{work_requirement.namespace}/{work_requirement.name}'"
            f" is {work_requirement.status}, and cannot take Tasks: only a"
            " RUNNING or HELD one can"
        )
    return work_requirement
