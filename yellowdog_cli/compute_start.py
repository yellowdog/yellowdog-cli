#!/usr/bin/env python3

"""
A script to start stopped Compute Requirements and Instances.
"""

from yellowdog_cli.utils.compute_action_common import (
    COMPUTE_START,
    apply_compute_action,
)
from yellowdog_cli.utils.wrapper import main_wrapper


@main_wrapper
def main():
    apply_compute_action(COMPUTE_START)


# Entry point
if __name__ == "__main__":
    main()
