#!/usr/bin/env python3

"""
A script to follow event streams.
"""

import sys

from yellowdog_cli.utils.follow_utils import follow_exit_code, follow_ids
from yellowdog_cli.utils.results import results_are_streamed
from yellowdog_cli.utils.wrapper import ARGS_PARSER, main_wrapper


@main_wrapper
def main():
    # Under '--json' the events are the output, printed as JSON as they
    # arrive, with no document after them
    results_are_streamed()

    # At least one ID is required, and each must be a Work Requirement's,
    # Worker Pool's or Compute Requirement's, as the command line is parsed
    follow_ids(ARGS_PARSER.yellowdog_ids, ARGS_PARSER.auto_cr)

    # If any stream could not be followed (entity not found, credentials
    # refused, connection lost for good), exit with the code its failure has,
    # or 1 if the streams failed for different reasons; the errors have
    # already been printed
    if exit_code := follow_exit_code():
        sys.exit(exit_code)


# Entry point
if __name__ == "__main__":
    main()
