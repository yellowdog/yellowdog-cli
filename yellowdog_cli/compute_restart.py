#!/usr/bin/env python3

"""
A script to restart Instances.
"""

from yellowdog_cli.utils.compute_action_common import (
    COMPUTE_RESTART,
    apply_compute_action,
)
from yellowdog_cli.utils.wrapper import main_wrapper


@main_wrapper
def main():
    apply_compute_action(COMPUTE_RESTART)


# Entry point
if __name__ == "__main__":
    main()
