#!/usr/bin/env python3

"""
A script to finish Work Requirements.
"""

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.start_hold_common import finish_work_requirements
from yellowdog_cli.utils.wrapper import main_wrapper


@main_wrapper
def main(ctx: RunContext):
    finish_work_requirements(ctx)


# Entry point
if __name__ == "__main__":
    main()
