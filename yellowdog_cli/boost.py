#!/usr/bin/env python3

"""
A script to boost allowances.
"""

from yellowdog_cli.utils.interactive import confirmed
from yellowdog_cli.utils.printing import print_error, print_info
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.settings import ET_ALLOWANCES
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type


def _record(allowance: str, outcome: str, error: str | None = None) -> None:
    record_action(
        allowance,
        ET_ALLOWANCES,
        "boost",
        outcome,
        error,
        hours=ARGS_PARSER.boost_hours,
    )


@main_wrapper
def main():

    count = 0
    for allowance in ARGS_PARSER.allowance_list:
        if get_ydid_type(allowance) != YDIDType.ALLOWANCE:
            print_error(f"Not a valid Allowance ID: '{allowance}'")
            _record(allowance, "failed", "not a valid Allowance ID")
            continue
        if not confirmed(
            f"Boost Allowance {allowance} by {ARGS_PARSER.boost_hours} hours?"
        ):
            _record(allowance, "skipped")
            continue
        try:
            CLIENT.allowances_client.boost_allowance_by_id(
                allowance, ARGS_PARSER.boost_hours
            )
            print_info(
                f"Boosted Allowance {allowance} by {ARGS_PARSER.boost_hours} hours"
            )
            _record(allowance, "boosted")
            count += 1
        except Exception as e:
            print_error(f"Unable to boost Allowance {allowance}: {e}")
            _record(allowance, "failed", str(e))

    if count > 1:
        print_info(f"Boosted {count} allowances by {ARGS_PARSER.boost_hours} hours")


# Standalone entry point
if __name__ == "__main__":
    main()
