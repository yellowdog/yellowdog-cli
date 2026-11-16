#!/usr/bin/env python3

"""
yd-resource-rename: rename a resource in place, keeping its ID. The work is
utils/resource_rename.py's; this reads the command line.
"""

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.resource_rename import rename_resource
from yellowdog_cli.utils.wrapper import main_wrapper


@main_wrapper
def main(ctx: RunContext):
    rename_resource(
        ctx,
        ctx.args.resource_type,
        str(ctx.args.rename_target),  # both positional, so always given
        str(ctx.args.new_name),
        dry_run=bool(ctx.args.dry_run),
    )


# Entry point
if __name__ == "__main__":
    main()
