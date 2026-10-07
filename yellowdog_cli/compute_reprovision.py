#!/usr/bin/env python3

"""
A script to reprovision Compute Requirements: provision Instances until as
many are running as each one's target count asks for.
"""

from yellowdog_cli.utils.compute_action_common import (
    COMPUTE_REPROVISION,
    apply_compute_action,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.wrapper import main_wrapper


@main_wrapper
def main(ctx: RunContext):
    apply_compute_action(ctx, COMPUTE_REPROVISION)


# Entry point
if __name__ == "__main__":
    main()
