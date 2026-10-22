#!/usr/bin/env python3

"""
A script to set when Compute Requirements are automatically terminated, or
that they never are.
"""

from yellowdog_cli.utils.compute_action_common import (
    apply_compute_action,
    compute_auto_shutdown,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.provision_utils import auto_shutdown
from yellowdog_cli.utils.wrapper import main_wrapper


@main_wrapper
def main(ctx: RunContext):
    apply_compute_action(
        ctx, compute_auto_shutdown(auto_shutdown(ctx.args.auto_shutdown_minutes))
    )


# Entry point
if __name__ == "__main__":
    main()
