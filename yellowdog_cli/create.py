#!/usr/bin/env python3

"""
yd-create: create or update YellowDog resources from specification files.
The work is utils/resource_creation.py's; this reads the command line.
"""

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.load_resources import load_resource_specifications
from yellowdog_cli.utils.resource_creation import CreateOptions, create_resources
from yellowdog_cli.utils.wrapper import main_wrapper


@main_wrapper
def main(ctx: RunContext):
    create_resources(
        ctx,
        load_resource_specifications(creation_or_update=True),
        CreateOptions(
            dry_run=bool(ctx.args.dry_run),
            json_output=bool(ctx.args.json_output),
            match_allowances_by_description=bool(
                ctx.args.match_allowances_by_description
            ),
            show_keyring_passwords=bool(ctx.args.show_keyring_passwords),
            regenerate_app_keys=bool(ctx.args.regenerate_app_keys),
        ),
    )


# Entry point
if __name__ == "__main__":
    main()
