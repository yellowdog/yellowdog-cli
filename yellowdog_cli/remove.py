#!/usr/bin/env python3

"""
yd-remove: remove YellowDog resources by specification file, by YellowDog
ID, or with --type by name or ID. The work is utils/resource_removal.py's; this reads the command line.
"""

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.load_resources import load_resource_specifications
from yellowdog_cli.utils.resource_removal import (
    RemoveOptions,
    remove_resources,
    remove_resources_by_id,
    remove_resources_by_name_or_id,
)
from yellowdog_cli.utils.wrapper import main_wrapper


@main_wrapper
def main(ctx: RunContext):
    if ctx.args.ids:
        # The IDs were checked as the command line was parsed
        remove_resources_by_id(ctx, ctx.args.resource_specifications)
        return
    if ctx.args.resource_type and ctx.args.resource_specifications:
        # With --type, the arguments are names or IDs, checked as parsed
        remove_resources_by_name_or_id(
            ctx,
            ctx.args.resource_type,
            ctx.args.resource_specifications,
            RemoveOptions(
                match_allowances_by_description=bool(
                    ctx.args.match_allowances_by_description
                )
            ),
        )
        return
    remove_resources(
        ctx,
        load_resource_specifications(ctx.args, creation_or_update=False),
        RemoveOptions(
            match_allowances_by_description=bool(
                ctx.args.match_allowances_by_description
            )
        ),
    )


# Entry point
if __name__ == "__main__":
    main()
