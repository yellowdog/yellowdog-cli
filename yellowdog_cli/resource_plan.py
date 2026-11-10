#!/usr/bin/env python3

"""
yd-resource-plan: show what 'yd resource create' would do, changing nothing.
The work is utils/resource_plan.py's; this reads the command line.
"""

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.load_resources import load_resource_specifications
from yellowdog_cli.utils.resource_plan import PlanOptions, plan_resources
from yellowdog_cli.utils.wrapper import main_wrapper


@main_wrapper
def main(ctx: RunContext):
    plan_resources(
        ctx,
        load_resource_specifications(ctx.args, creation_or_update=True),
        PlanOptions(
            json_output=bool(ctx.args.json_output),
            fail_on_changes=bool(ctx.args.fail_on_changes),
            match_allowances_by_description=bool(
                ctx.args.match_allowances_by_description
            ),
            regenerate_app_keys=bool(ctx.args.regenerate_app_keys),
        ),
    )


# Entry point
if __name__ == "__main__":
    main()
