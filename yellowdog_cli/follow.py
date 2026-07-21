#!/usr/bin/env python3

"""
A script to follow event streams.
"""

import sys

from yellowdog_cli.utils.follow_utils import follow_errors_occurred, follow_ids
from yellowdog_cli.utils.printing import print_info
from yellowdog_cli.utils.wrapper import ARGS_PARSER, main_wrapper


@main_wrapper
def main():
    if not ARGS_PARSER.yellowdog_ids:
        print_info("No YellowDog IDs to follow")
        return

    follow_ids(ARGS_PARSER.yellowdog_ids, ARGS_PARSER.auto_cr)

    # Exit 1 if any of the event streams couldn't be followed (invalid ID,
    # entity not found, connection/stream error); the specific error(s) have
    # already been printed
    if follow_errors_occurred():
        sys.exit(1)


# Standalone entry point
if __name__ == "__main__":
    main()
