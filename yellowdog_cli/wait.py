#!/usr/bin/env python3

"""
Wait for Work Requirements, Worker Pools, or Compute Requirements to reach
a terminal state.

Each is followed to the end of its event stream (or until '--timeout'), and
its status then fetched. The exit code is 0 if every one reached a terminal
state and no Work Requirement FAILED or was CANCELLED; 1 if one did, or if
the failures had different causes; otherwise the code of the one cause --
6 for an entity that does not exist, 4 for credentials not accepted, 8 for a
connection lost for good. An entity not in a terminal state when following
ends (a timeout, a stream that could not be followed) is a failure: it has
not finished, whatever the reason.
"""

import sys
from typing import Any

from yellowdog_cli.utils.exit_codes import ExitCode, classify
from yellowdog_cli.utils.follow_utils import (
    WR_FAILURE_STATUS_VALUES,
    follow_exit_code,
    follow_ids,
)
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.results import record
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

# The states each type's event stream concludes in, and of those the ones
# counted as success
_TERMINAL_STATUSES = {
    YDIDType.WORK_REQUIREMENT: frozenset({"COMPLETED", "FAILED", "CANCELLED"}),
    YDIDType.WORKER_POOL: frozenset({"SHUTDOWN", "TERMINATED"}),
    YDIDType.COMPUTE_REQUIREMENT: frozenset({"TERMINATED"}),
}


def _record_status(ydid: str, name: str | None, status: str | None) -> None:
    """
    Record one ID's final status for '--json', as {"id", "name", "status",
    "succeeded"}: 'succeeded' is false for a failed Work Requirement, a
    state that is not terminal, or a status that could not be fetched.
    """
    ydid_type = get_ydid_type(ydid)
    succeeded = (
        status is not None
        and ydid_type in _TERMINAL_STATUSES
        and status in _TERMINAL_STATUSES[ydid_type]
        and status not in WR_FAILURE_STATUS_VALUES
    )
    record({"id": ydid, "name": name, "status": status, "succeeded": succeeded})


def _fetch(ydid: str, ydid_type: YDIDType | None) -> Any:
    if ydid_type == YDIDType.WORK_REQUIREMENT:
        return CLIENT.work_client.get_work_requirement_by_id(ydid)
    if ydid_type == YDIDType.WORKER_POOL:
        return CLIENT.worker_pool_client.get_worker_pool_by_id(ydid)
    return CLIENT.compute_client.get_compute_requirement_by_id(ydid)


@main_wrapper
def main():
    # At least one ID is required, each a Work Requirement's, Worker Pool's or
    # Compute Requirement's, as the command line is parsed
    follow_ids(ARGS_PARSER.yellowdog_ids, timeout=ARGS_PARSER.timeout)
    # Why an entity may still be live once following has ended: a stream
    # that could not be followed (its cause), else the timeout
    following_code = follow_exit_code() or ExitCode.FAILURE

    # Errors and failure warnings are always printed, including with
    # '--quiet': exiting non-zero silently is unhelpful. Recorded in the order
    # given, once each.
    failures: list[ExitCode] = []
    work_requirement_failed = False
    for ydid in dict.fromkeys(ARGS_PARSER.yellowdog_ids):
        ydid_type = get_ydid_type(ydid)
        label = ydid_type.value if ydid_type is not None else "Entity"
        try:
            entity = _fetch(ydid, ydid_type)
        except Exception as e:
            print_error(f"Could not fetch final status for '{ydid}': {e}")
            failures.append(classify(e))
            _record_status(ydid, None, None)
            continue

        status = entity.status.value if entity.status else "UNKNOWN"
        _record_status(ydid, entity.name, status)
        if ydid_type is None or status not in _TERMINAL_STATUSES[ydid_type]:
            print_error(
                f"{label} '{ydid}' is still {status}: following ended before it"
                " finished"
            )
            failures.append(following_code)
        elif status in WR_FAILURE_STATUS_VALUES:
            print_warning(
                f"{label} '{ydid}' ended with status '{status}'", override_quiet=True
            )
            failures.append(ExitCode.FAILURE)
            work_requirement_failed = True
        else:
            print_info(f"{label} '{ydid}' finished with status '{status}'")

    if work_requirement_failed:
        print_error("One or more Work Requirements did not complete successfully")
    if failures:
        codes = set(failures)
        sys.exit(
            codes.pop()
            if len(codes) == 1 and not work_requirement_failed
            else ExitCode.FAILURE
        )


# Entry point
if __name__ == "__main__":
    main()
