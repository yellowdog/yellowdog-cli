#!/usr/bin/env python3

"""
A script to stop Compute Requirements and Instances.
"""

from yellowdog_cli.utils.compute_action_common import COMPUTE_STOP, apply_compute_action
from yellowdog_cli.utils.wrapper import main_wrapper


@main_wrapper
def main():
    apply_compute_action(COMPUTE_STOP)


# Entry point
if __name__ == "__main__":
    main()
