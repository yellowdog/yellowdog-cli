#!/usr/bin/env python3

"""
yd-cloud-info: list the cloud providers' regions, sub-regions, instance types
and prices from the Platform's Cloud Info service. The searching, filtering,
joining and sorting are utils/cloud_info.py's; this module turns the command
line into a query and prints, records or counts what comes back.
"""

from collections.abc import Callable
from typing import Any, cast

from yellowdog_cli.utils.cloud_info import (
    CloudInfoQuery,
    PricedInstanceType,
    instance_types,
    instance_types_with_prices,
    prices,
    regions,
    sub_regions,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    CI_INSTANCE_TYPES,
    CI_PRICES,
    CI_REGIONS,
    CI_SUB_REGIONS,
)
from yellowdog_cli.utils.output_settings import configure_output
from yellowdog_cli.utils.printing import print_info, print_simple
from yellowdog_cli.utils.results import record
from yellowdog_cli.utils.tables import (
    cloud_regions_table,
    cloud_sub_regions_table,
    instance_type_prices_table,
    instance_types_table,
    priced_instance_types_table,
    print_table,
)
from yellowdog_cli.utils.wrapper import main_wrapper

_DISPLAY_NAMES = {
    CI_REGIONS: "Regions",
    CI_SUB_REGIONS: "Sub-regions",
    CI_INSTANCE_TYPES: "Instance Types",
    CI_PRICES: "Instance Type Prices",
}

_FETCHERS: dict[str, Callable[[RunContext, CloudInfoQuery], list[Any]]] = {
    CI_REGIONS: regions,
    CI_SUB_REGIONS: sub_regions,
    CI_INSTANCE_TYPES: instance_types,
    CI_PRICES: prices,
}


@main_wrapper
def main(ctx: RunContext):
    list_cloud_info(ctx)


def query_from_args(args: Any) -> CloudInfoQuery:
    """
    The query a command line asks for: its ranges as CLIParser's
    'vcpus_range' and 'ram_range' parse them, the validator having refused a
    malformed one.
    """
    return CloudInfoQuery(
        providers=tuple(args.providers or ()),
        region=args.region,
        sub_region=args.sub_region,
        name_glob=args.name_glob,
        vcpus=args.vcpus_range,
        ram_gib=args.ram_range,
        arch=args.arch,
        usage=args.usage,
        os_licence=args.os_licence or "none",
        sort=tuple(args.sort or ("name",)),
        reverse=bool(args.reverse),
    )


def list_cloud_info(ctx: RunContext) -> None:
    """
    Fetch what the command line asks for, then print its count, record it for
    '--json', or print it as a table.
    """
    _settle_output(ctx)
    # The positional is required, so the type is always set
    info_type = cast(str, ctx.args.cloud_info_type)
    with_prices = bool(ctx.args.prices)
    query = query_from_args(ctx.args)
    items = (
        instance_types_with_prices(ctx, query)
        if with_prices
        else _FETCHERS[info_type](ctx, query)
    )

    if ctx.args.count_only:
        print_simple(str(len(items)), override_quiet=True)
        return
    if ctx.args.json_output:
        for item in items:
            record(item.as_record() if isinstance(item, PricedInstanceType) else item)
        return
    if not items:
        print_info(f"No matching {_DISPLAY_NAMES[info_type]} found")
        return
    print_table(*_table(info_type, items, query.region, with_prices))


def _settle_output(ctx: RunContext) -> None:
    """
    '--count' overrides '--json', as yd-list's does: the count is all that is
    printed, so the results flush must not print '[]' after it.
    """
    if ctx.args.count_only and ctx.args.json_output:
        ctx.args.json_output = False
        configure_output(ctx.args)


def _table(
    info_type: str, items: list[Any], region: str | None, with_prices: bool
) -> tuple[list[str], list[list]]:
    if info_type == CI_INSTANCE_TYPES:
        if with_prices:
            return priced_instance_types_table(items, region)
        return instance_types_table(items, region)
    if info_type == CI_SUB_REGIONS:
        return cloud_sub_regions_table(items)
    if info_type == CI_PRICES:
        return instance_type_prices_table(items)
    return cloud_regions_table(items)


if __name__ == "__main__":
    main()
