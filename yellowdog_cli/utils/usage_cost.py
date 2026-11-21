"""
yd usage's '--cost': an estimate of what each group's running time cost at
list prices, from the Platform's Cloud Info price search (one search per
provider and region counted). An on-demand Instance is priced at its
instance type's on-demand price, a spot Instance at the mean of the region's
spot prices for it, since the usage report names no sub-region; the prices
are per hour, for Linux (the report names no operating system), and only in
US dollars. An Instance with no such price is left out of its group's cost
and noted with its running time; one with no running time costs nothing,
priced or not.

Imports the SDK only inside the functions that search.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from yellowdog_cli.utils.completion_cache import cache_key, read, write
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import SESSION_FAILURES, ExitCode, classify
from yellowdog_cli.utils.limits import USAGE_PRICES_KEPT_SECONDS

if TYPE_CHECKING:
    from yellowdog_cli.utils.usage_report import UsageGroup

_LOG = logging.getLogger(__name__)

# The private temporary directory the prices are kept in
USAGE_PRICES_DIRECTORY_NAME = "yellowdog-cli-prices"

# The one currency the estimate is given in
COST_CURRENCY = "USD"

_SECONDS_PER_HOUR = 3600

# What a price is for: (provider, region, instance type, pricing), the
# provider as the report names it ('AWS') and the pricing as yd usage's
# 'pricing' key gives it ('on-demand', 'spot')
PriceKey = tuple[str, str, str, str]

_ON_DEMAND = "on-demand"
_SPOT = "spot"


@dataclass
class Prices:
    """
    What list_prices() found: the prices, the places whose prices could not
    be read, in order, and whether that was because the Application may not
    read cloud prices at all.
    """

    prices: dict[PriceKey, float] = field(default_factory=dict)
    unreadable: list[tuple[str, str]] = field(default_factory=list)
    refused: bool = False


def list_prices(ctx: RunContext, places: set[tuple[str, str]]) -> Prices:
    """
    The hourly list prices in US dollars for every instance type in each
    (provider, region), one search per place, the provider as the report
    names it. A place whose search fails is unreadable, its Instances
    unpriced, as are those of a provider the SDK does not know, which is not
    searched; the other places are still priced. A refusal for permission
    stops the searches, every place left unread, since the rest would be
    refused too. An authentication or connection failure is raised as itself.
    """
    from yellowdog_client.model import (
        CloudProvider,
        InstanceTypePriceSearch,
        OperatingSystemLicence,
        UsageType,
    )

    prices: dict[PriceKey, float] = {}
    unreadable: list[tuple[str, str]] = []
    ordered = sorted(places)
    for index, (provider, region) in enumerate(ordered):
        if provider not in CloudProvider.__members__:
            _LOG.debug("no price search for provider %r", provider)
            continue
        try:
            rows = ctx.client.cloud_info_client.get_instance_type_prices(
                InstanceTypePriceSearch(
                    providers=[CloudProvider[provider]],
                    region=region,
                    operatingSystemLicences=[OperatingSystemLicence.NONE],
                )
            ).list_all()
        except Exception as e:
            code = classify(e)
            if code in SESSION_FAILURES:
                raise
            _LOG.debug("no prices for %s %s", provider, region, exc_info=True)
            if code is ExitCode.PERMISSION:
                return Prices(unreadable=unreadable + ordered[index:], refused=True)
            unreadable.append((provider, region))
            continue
        on_demand: dict[PriceKey, float] = {}
        spot: dict[PriceKey, list[float]] = defaultdict(list)
        for row in rows:
            price = row.price
            if (
                # The search matches the region as a substring ('eu-west-2'
                # finds 'eu-west-2-wl1-lon1'), and the licence is checked as
                # cloud_info._price_kept() checks it
                row.region != region
                or row.operatingSystemLicence is not OperatingSystemLicence.NONE
                or price is None
                or price.value is None
                or price.currency is None
                or price.currency.name != COST_CURRENCY
                or not row.instanceType
            ):
                continue
            if row.usageType is UsageType.ON_DEMAND:
                on_demand[(provider, region, row.instanceType, _ON_DEMAND)] = (
                    price.value
                )
            elif row.usageType is UsageType.SPOT:
                spot[(provider, region, row.instanceType, _SPOT)].append(price.value)
        _LOG.debug("searched the prices in %s %s: %d rows", provider, region, len(rows))
        found = dict(on_demand)
        found.update({key: sum(values) / len(values) for key, values in spot.items()})
        _keep(ctx, (provider, region), found)
        prices.update(found)
    return Prices(prices, unreadable)


def _cache_key(ctx: RunContext, place: tuple[str, str]) -> str:
    """
    A region's kept prices, per account and Application, as a kept usage
    report is.
    """
    return cache_key("usage-prices", ctx.config.url, ctx.config.key or "", *place)


def _keep(
    ctx: RunContext, place: tuple[str, str], found: dict[PriceKey, float]
) -> None:
    """
    Keep a region's prices, which may be none, for USAGE_PRICES_KEPT_SECONDS.
    """
    write(
        _cache_key(ctx, place),
        [
            {"instanceType": instance_type, "pricing": pricing, "price": price}
            for (_, _, instance_type, pricing), price in found.items()
        ],
        name=USAGE_PRICES_DIRECTORY_NAME,
        lifetime=USAGE_PRICES_KEPT_SECONDS,
    )


def kept_prices(
    ctx: RunContext, places: set[tuple[str, str]], now: float | None = None
) -> tuple[dict[PriceKey, float], set[tuple[str, str]]]:
    """
    The prices kept from a search within USAGE_PRICES_KEPT_SECONDS, for the
    places that have them, and the places that have none kept.
    """
    prices: dict[PriceKey, float] = {}
    missing: set[tuple[str, str]] = set()
    for place in places:
        items = read(
            _cache_key(ctx, place),
            now,
            name=USAGE_PRICES_DIRECTORY_NAME,
            lifetime=USAGE_PRICES_KEPT_SECONDS,
        )
        try:
            prices.update(
                {
                    (*place, str(item["instanceType"]), str(item["pricing"])): float(
                        item["price"]
                    )
                    for item in items or ()
                }
            )
        except (KeyError, TypeError, ValueError):
            items = None
        if items is None:
            missing.add(place)
    return prices, missing


class Costing:
    """
    Prices each Instance's running time into its group as yd usage groups
    them, keeping the running seconds of those it has no price for.
    """

    def __init__(
        self,
        prices: dict[PriceKey, float],
        unreadable: list[tuple[str, str]] | None = None,
        refused: bool = False,
    ):
        self.prices = prices
        # The places whose prices could not be read (list_prices()), and
        # whether because the Application may not read cloud prices at all
        self.unreadable = unreadable or []
        self.refused = refused
        self.unpriced: dict[PriceKey, float] = defaultdict(float)

    def add(self, group: UsageGroup, instance: dict[str, str]) -> None:
        """
        Add the Instance's running time, priced or not, to its group.
        """
        try:
            running = float(instance.get("Running (s)") or 0)
        except ValueError:
            running = 0.0
        if running <= 0:
            return
        key: PriceKey = (
            instance.get("Provider") or "",
            instance.get("Region") or "",
            instance.get("Instance Type") or "",
            _SPOT if instance.get("Spot") == "true" else _ON_DEMAND,
        )
        price = self.prices.get(key)
        if price is None:
            group.unpriced_seconds += running
            self.unpriced[key] += running
            return
        group.cost += running / _SECONDS_PER_HOUR * price
        group.priced_seconds += running


def estimated_cost(group: UsageGroup) -> float | None:
    """
    The group's estimated cost, or None when it ran and none of its running
    time could be priced.
    """
    if group.unpriced_seconds and not group.priced_seconds:
        return None
    return group.cost


def cost_text(group: UsageGroup) -> str:
    """
    The cost as the table shows it: '12.34', '12.34+' when some of the
    running time had no price (a lower bound), '-' when none had one.
    """
    cost = estimated_cost(group)
    if cost is None:
        return "-"
    return f"{cost:,.2f}" + ("+" if group.unpriced_seconds else "")
