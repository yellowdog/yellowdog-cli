#!/usr/bin/env python3

"""
yd-remove: remove YellowDog resources by specification file, by YellowDog
ID, or with --type by name or ID. An argument that is a YellowDog ID is
removed by its ID, so files and IDs can be given together; '--ids', which
says they are all IDs, is kept for the scripts that use it. The work is
utils/resource_removal.py's; this reads the command line.
"""

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.load_resources import load_resource_specifications
from yellowdog_cli.utils.printing import print_info
from yellowdog_cli.utils.resource_removal import (
    RemoveOptions,
    remove_resources,
    remove_resources_and_ids,
    remove_resources_by_id,
    remove_resources_by_name_or_id,
)
from yellowdog_cli.utils.wrapper import main_wrapper
from yellowdog_cli.utils.ydid_utils import get_ydid_type


@main_wrapper
def main(ctx: RunContext):
    remove(ctx)


def remove(ctx: RunContext) -> None:
    """
    Remove what the command line names: IDs, specification files, both, or
    with --type names or IDs of that type. The arguments were checked as
    they were parsed.
    """
    options = RemoveOptions(
        match_allowances_by_description=bool(ctx.args.match_allowances_by_description)
    )
    arguments = ctx.args.resource_specifications or []
    if ctx.args.ids:
        print_info(
            "--ids is optional: an argument that is a YellowDog ID is removed by its ID"
        )
        remove_resources_by_id(ctx, arguments)
        return
    if ctx.args.resource_type and arguments:
        remove_resources_by_name_or_id(ctx, ctx.args.resource_type, arguments, options)
        return
    ids = [argument for argument in arguments if get_ydid_type(argument) is not None]
    files = [argument for argument in arguments if get_ydid_type(argument) is None]
    if ids and not files and not ctx.args.resource_type:
        remove_resources_by_id(ctx, ids)
        return
    resources = load_resource_specifications(
        ctx.args, creation_or_update=False, files=files
    )
    if ids:
        remove_resources_and_ids(ctx, resources, ids, options)
    else:
        remove_resources(ctx, resources, options)


# Entry point
if __name__ == "__main__":
    main()
