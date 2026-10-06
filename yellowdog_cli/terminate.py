#!/usr/bin/env python3

"""
A script to terminate Compute Requirements, Instances and Nodes.
"""

from yellowdog_cli.utils.compute_action_common import (
    COMPUTE_TERMINATE,
    apply_compute_action,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.wrapper import main_wrapper


@main_wrapper
def main(ctx: RunContext):
    apply_compute_action(ctx, COMPUTE_TERMINATE)


# Entry point
if __name__ == "__main__":
    main()
