#!/usr/bin/env python3

"""
A script to deprovision Instances: terminate them and reduce their Compute
Requirements' target counts to match, so that they are not replaced.
"""

from yellowdog_cli.utils.compute_action_common import (
    COMPUTE_DEPROVISION,
    apply_compute_action,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.wrapper import main_wrapper


@main_wrapper
def main(ctx: RunContext):
    apply_compute_action(ctx, COMPUTE_DEPROVISION)


# Entry point
if __name__ == "__main__":
    main()
