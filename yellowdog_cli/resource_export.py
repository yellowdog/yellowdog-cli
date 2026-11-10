#!/usr/bin/env python3

"""
yd-resource-export: write existing resources out as resource specifications.
The work is utils/resource_export.py's; this reads the command line.
"""

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.resource_export import ExportOptions, export_resources
from yellowdog_cli.utils.wrapper import main_wrapper


@main_wrapper
def main(ctx: RunContext):
    export_resources(
        ctx,
        ExportOptions(
            types=tuple(ctx.args.export_types or ()),
            all_types=bool(ctx.args.all_types),
            name_glob=ctx.args.name_glob,
            interactive=bool(ctx.args.interactive),
            with_dependencies=bool(ctx.args.with_dependencies),
            include_credentials=bool(ctx.args.include_credentials),
            output_file=ctx.args.export_file,
        ),
    )


# Entry point
if __name__ == "__main__":
    main()
