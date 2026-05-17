#!/usr/bin/env python3

"""
Wait for Work Requirements, Worker Pools, or Compute Requirements to reach
a terminal state. Exits with code 1 if any Work Requirement ended in a
FAILED or CANCELLED state.
"""

import sys

from yellowdog_cli.utils.follow_utils import follow_ids
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

# Work Requirement terminal states that indicate failure
_WR_FAILURE_VALUES = {"FAILED", "CANCELLED"}


@main_wrapper
def main():
    if not ARGS_PARSER.yellowdog_ids:
        print_info("No YellowDog IDs to wait for")
        return

    # follow_ids handles deduplication, validation, and event-stream following;
    # it returns the valid original IDs (WR/WP/CR) for the post-stream status check.
    valid_ydids = follow_ids(ARGS_PARSER.yellowdog_ids)
    if not valid_ydids:
        raise Exception("No valid YellowDog IDs to wait for")

    # Check final status of each entity and determine exit code
    any_failed = False
    for ydid in valid_ydids:
        ydid_type = get_ydid_type(ydid)
        try:
            if ydid_type == YDIDType.WORK_REQUIREMENT:
                wr = CLIENT.work_client.get_work_requirement_by_id(ydid)
                status = wr.status.value if wr.status else "UNKNOWN"
                if status in _WR_FAILURE_VALUES:
                    if not ARGS_PARSER.quiet:
                        print_warning(
                            f"Work Requirement '{ydid}' ended with status '{status}'"
                        )
                    any_failed = True
                else:
                    print_info(
                        f"Work Requirement '{ydid}' completed with status '{status}'"
                    )
            elif ydid_type == YDIDType.WORKER_POOL:
                wp = CLIENT.worker_pool_client.get_worker_pool_by_id(ydid)
                status = wp.status.value if wp.status else "UNKNOWN"
                print_info(f"Worker Pool '{ydid}' reached terminal status '{status}'")
            else:  # COMPUTE_REQUIREMENT
                cr = CLIENT.compute_client.get_compute_requirement_by_id(ydid)
                status = cr.status.value if cr.status else "UNKNOWN"
                print_info(
                    f"Compute Requirement '{ydid}' reached terminal status '{status}'"
                )
        except Exception as e:
            if not ARGS_PARSER.quiet:
                print_error(f"Could not fetch final status for '{ydid}': {e}")
            any_failed = True

    if any_failed:
        if not ARGS_PARSER.quiet:
            print_error("One or more Work Requirements did not complete successfully")
        sys.exit(1)


if __name__ == "__main__":
    main()
