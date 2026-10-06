#!/usr/bin/env python3

"""
yd-remove: remove YellowDog resources by specification file or by YellowDog
ID. The work is utils/resource_removal.py's; this reads the command line.
"""

from yellowdog_cli.utils.load_resources import load_resource_specifications
from yellowdog_cli.utils.resource_removal import (
    RemoveOptions,
    remove_resources,
    remove_resources_by_id,
)
from yellowdog_cli.utils.wrapper import ARGS_PARSER, main_wrapper


@main_wrapper
def main():
    if ARGS_PARSER.ids:
        # The IDs were checked as the command line was parsed
        remove_resources_by_id(ARGS_PARSER.resource_specifications)
        return
    remove_resources(
        load_resource_specifications(creation_or_update=False),
        RemoveOptions(
            match_allowances_by_description=bool(
                ARGS_PARSER.match_allowances_by_description
            )
        ),
    )


# Entry point
if __name__ == "__main__":
    main()
