"""
yd-cloud-info as a library: the Platform's Cloud Info service (regions,
sub-regions, instance types and their prices) searched, filtered exactly and
sorted, and the '--prices' join of instance types to a region's prices.

Every text filter the service offers matches substrings ('eu-west-2' finds
'eu-west-2-wl1-lon1', 't3' finds 't3a.micro') and none takes a glob, so what
is sent is only a hint that narrows the fetch: every filter is applied again
here, exactly, and the order is decided here too. Each function takes the
RunContext for its client and a CloudInfoQuery for what to fetch; none reads
the command line.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING, Any, TypeVar, cast

from yellowdog_client.common.json import Json
from yellowdog_client.model import (
    CloudProvider,
    DoubleRange,
    InstanceType,
    InstanceTypePrice,
    InstanceTypePriceSearch,
    InstanceTypeSearch,
    OperatingSystemLicence,
    Price,
    ProcessorArchitecture,
    Region,
    RegionSearch,
    SubRegion,
    SubRegionSearch,
    UsageType,
)

from yellowdog_cli.utils.entity_names import (
    CI_INSTANCE_TYPES,
    CI_PRICES,
    CI_REGIONS,
    CI_SUB_REGIONS,
)
from yellowdog_cli.utils.glob_utils import glob_search_prefix
from yellowdog_cli.utils.settings import CLOUD_INFO_NO_SUB_REGION, MIB_PER_GIB

if TYPE_CHECKING:
    from yellowdog_cli.utils.context import RunContext

_T = TypeVar("_T")

# A '--vcpus' or '--ram' range: either end may be open
Range = tuple[float | None, float | None]


@dataclass(frozen=True)
class CloudInfoQuery:
    """
    What to fetch: the command line's filters, in the command line's terms
    (lower-case providers, GiB of RAM), and the order to put them in.
    """

    providers: tuple[str, ...] = ()
    region: str | None = None
    sub_region: str | None = None
    name_glob: str | None = None
    vcpus: Range | None = None
    ram_gib: Range | None = None
    arch: str | None = None
    usage: str | None = None
    os_licence: str = "none"
    sort: tuple[str, ...] = ("name",)
    reverse: bool = False


@dataclass(frozen=True)
class PricedInstanceType:
    """
    An instance type with its on-demand price in a region and its lowest spot
    price there, and the sub-region that spot price is found in; None for a
    price the service does not give.
    """

    instance_type: InstanceType
    on_demand: Price | None
    spot: Price | None
    spot_sub_region: str | None

    def as_record(self) -> dict[str, Any]:
        """
        The '--json' record: the instance type's own fields, then the prices
        under the names the SDK's InstanceTypeWithPrices gives them.
        """
        # Json.dump() is typed as returning an object; an SDK model is a dict
        record = cast(dict[str, Any], Json.dump(self.instance_type))
        record["onDemandPrice"] = (
            None if self.on_demand is None else Json.dump(self.on_demand)
        )
        record["spotPrice"] = None if self.spot is None else Json.dump(self.spot)
        record["spotSubRegion"] = self.spot_sub_region
        return record


def _provider_name(item: Any) -> str:
    return "" if item.provider is None else item.provider.name


def _enum_name(value: Any) -> str:
    return "" if value is None else value.name


def _price_value(price: Price | None) -> float | None:
    return None if price is None else price.value


# Each type's sort keys: a function giving an item's value, None for one
# without a value, which _ordered() puts last
_SortKey = Callable[[Any], Any]

_REGION_SORTS: dict[str, _SortKey] = {"name": lambda r: r.name or ""}
_SUB_REGION_SORTS: dict[str, _SortKey] = {
    "name": lambda s: (s.region or "", s.name or "")
}
_INSTANCE_TYPE_SORTS: dict[str, _SortKey] = {
    "name": lambda t: t.name or "",
    "vcpus": lambda t: t.defaultVcpus,
    "ram": lambda t: t.ramInMib,
}
_PRICED_SORTS: dict[str, _SortKey] = {
    "name": lambda p: p.instance_type.name or "",
    "vcpus": lambda p: p.instance_type.defaultVcpus,
    "ram": lambda p: p.instance_type.ramInMib,
    "spot": lambda p: _price_value(p.spot),
    "on-demand": lambda p: _price_value(p.on_demand),
}
_PRICE_SORTS: dict[str, _SortKey] = {
    "name": lambda p: (
        p.instanceType or "",
        p.region or "",
        p.subRegion or "",
        _enum_name(p.usageType),
    ),
    "price": lambda p: _price_value(p.price),
}

# The sort keys each type offers, which the registry's '--sort' validation
# must match (tests/test_cloud_info_command.py)
SORT_KEYS: dict[str, tuple[str, ...]] = {
    CI_REGIONS: tuple(_REGION_SORTS),
    CI_SUB_REGIONS: tuple(_SUB_REGION_SORTS),
    CI_INSTANCE_TYPES: tuple(_INSTANCE_TYPE_SORTS),
    CI_PRICES: tuple(_PRICE_SORTS),
}
PRICED_SORT_KEYS: tuple[str, ...] = tuple(_PRICED_SORTS)


def _region_tie(region: Region) -> tuple[str, ...]:
    return (_provider_name(region), region.name or "")


def _sub_region_tie(sub_region: SubRegion) -> tuple[str, ...]:
    return (_provider_name(sub_region), sub_region.region or "", sub_region.name or "")


def _instance_type_tie(instance_type: InstanceType) -> tuple[str, ...]:
    return (_provider_name(instance_type), instance_type.name or "")


def _priced_tie(priced: PricedInstanceType) -> tuple[str, ...]:
    return _instance_type_tie(priced.instance_type)


def _price_tie(price: InstanceTypePrice) -> tuple[str, ...]:
    return (
        _provider_name(price),
        price.instanceType or "",
        price.region or "",
        price.subRegion or "",
        _enum_name(price.usageType),
        _enum_name(price.operatingSystemLicence),
    )


def _ordered(
    items: list[_T],
    sorts: dict[str, _SortKey],
    query: CloudInfoQuery,
    tie: Callable[[_T], Any],
) -> list[_T]:
    """
    'items' sorted by each of the query's sort keys in turn, the first the
    most significant, those without a value for a key after those with one
    whichever the direction, and ties broken by 'tie', ascending: one stable
    sort per key, from the least significant to the most.
    """
    ordered = sorted(items, key=tie)
    for name in reversed(query.sort):
        key = sorts[name]
        present = [item for item in ordered if key(item) is not None]
        present.sort(key=key, reverse=query.reverse)
        ordered = present + [item for item in ordered if key(item) is None]
    return ordered


def _providers(query: CloudInfoQuery) -> list[CloudProvider] | None:
    return [CloudProvider[provider.upper()] for provider in query.providers] or None


def _provider_kept(item: Any, query: CloudInfoQuery) -> bool:
    return not query.providers or _provider_name(item).lower() in query.providers


def _name_hint(query: CloudInfoQuery) -> str | None:
    """
    The literal start of the '--name' glob, which the service matches as a
    substring; None, to fetch every name, when there is none.
    """
    if query.name_glob is None:
        return None
    return glob_search_prefix(query.name_glob) or None


def _name_kept(name: str | None, query: CloudInfoQuery) -> bool:
    return query.name_glob is None or (
        name is not None and fnmatchcase(name, query.name_glob)
    )


def _in_range(value: float | None, bounds: Range | None) -> bool:
    if bounds is None:
        return True
    if value is None:
        return False
    low, high = bounds
    return (low is None or value >= low) and (high is None or value <= high)


def _double_range(bounds: Range | None, scale: float = 1.0) -> DoubleRange | None:
    if bounds is None:
        return None
    low, high = bounds
    return DoubleRange(
        min=None if low is None else low * scale,
        max=None if high is None else high * scale,
    )


def _arch(query: CloudInfoQuery) -> ProcessorArchitecture | None:
    return None if query.arch is None else ProcessorArchitecture[query.arch.upper()]


def _usage(query: CloudInfoQuery) -> UsageType | None:
    if query.usage is None:
        return None
    return UsageType[query.usage.upper().replace("-", "_")]


def _os_licence(query: CloudInfoQuery) -> OperatingSystemLicence:
    return OperatingSystemLicence[query.os_licence.upper()]


def _offered_in(
    instance_type: InstanceType, region: str | None, sub_region: str | None
) -> bool:
    if region is None:
        return True
    for entry in instance_type.regions or []:
        if entry.name == region:
            return sub_region is None or sub_region in (entry.subRegions or [])
    return False


def regions(ctx: RunContext, query: CloudInfoQuery) -> list[Region]:
    """
    The regions the query names.
    """
    found = ctx.client.cloud_info_client.get_regions(
        RegionSearch(providers=_providers(query), name=_name_hint(query))
    ).list_all()
    kept = [
        region
        for region in found
        if _provider_kept(region, query) and _name_kept(region.name, query)
    ]
    return _ordered(kept, _REGION_SORTS, query, _region_tie)


def sub_regions(ctx: RunContext, query: CloudInfoQuery) -> list[SubRegion]:
    """
    The sub-regions the query names, in its region when it has one.
    """
    found = ctx.client.cloud_info_client.get_sub_regions(
        SubRegionSearch(
            providers=_providers(query), region=query.region, name=_name_hint(query)
        )
    ).list_all()
    kept = [
        sub_region
        for sub_region in found
        if _provider_kept(sub_region, query)
        and (query.region is None or sub_region.region == query.region)
        and _name_kept(sub_region.name, query)
    ]
    return _ordered(kept, _SUB_REGION_SORTS, query, _sub_region_tie)


def _instance_type_kept(
    instance_type: InstanceType,
    query: CloudInfoQuery,
    arch: ProcessorArchitecture | None,
) -> bool:
    ram_gib = (
        None if instance_type.ramInMib is None else instance_type.ramInMib / MIB_PER_GIB
    )
    return (
        _provider_kept(instance_type, query)
        and _name_kept(instance_type.name, query)
        and (arch is None or instance_type.processorArchitecture is arch)
        and _in_range(instance_type.defaultVcpus, query.vcpus)
        and _in_range(ram_gib, query.ram_gib)
        and _offered_in(instance_type, query.region, query.sub_region)
    )


def instance_types(ctx: RunContext, query: CloudInfoQuery) -> list[InstanceType]:
    """
    The instance types the query names, offered in its region (and
    sub-region) when it has one.
    """
    arch = _arch(query)
    found = ctx.client.cloud_info_client.get_instance_types(
        InstanceTypeSearch(
            providers=_providers(query),
            name=_name_hint(query),
            processorArchitectures=None if arch is None else [arch],
            defaultVcpus=_double_range(query.vcpus),
            ramInMib=_double_range(query.ram_gib, MIB_PER_GIB),
            region=query.region,
            subRegion=query.sub_region,
        )
    ).list_all()
    kept = [t for t in found if _instance_type_kept(t, query, arch)]
    return _ordered(kept, _INSTANCE_TYPE_SORTS, query, _instance_type_tie)


def _price_kept(
    price: InstanceTypePrice, query: CloudInfoQuery, usage: UsageType | None
) -> bool:
    return (
        _provider_kept(price, query)
        and _name_kept(price.instanceType, query)
        and (query.region is None or price.region == query.region)
        and (
            query.sub_region is None
            or price.subRegion in (query.sub_region, CLOUD_INFO_NO_SUB_REGION)
        )
        and (usage is None or price.usageType is usage)
        and price.operatingSystemLicence is _os_licence(query)
    )


def prices(ctx: RunContext, query: CloudInfoQuery) -> list[InstanceTypePrice]:
    """
    The prices the query names, for its OS licence. With a sub-region, that
    sub-region's prices and the region's on-demand prices, which the service
    gives for the whole region (sub-region 'N/A'): so the sub-region is not
    sent, since the service would drop those.
    """
    usage = _usage(query)
    found = ctx.client.cloud_info_client.get_instance_type_prices(
        InstanceTypePriceSearch(
            providers=_providers(query),
            region=query.region,
            instanceType=_name_hint(query),
            usageTypes=None if usage is None else [usage],
            operatingSystemLicences=[_os_licence(query)],
        )
    ).list_all()
    kept = [price for price in found if _price_kept(price, query, usage)]
    return _ordered(kept, _PRICE_SORTS, query, _price_tie)


def _cheapest(
    rows: list[InstanceTypePrice], usage: UsageType
) -> dict[tuple[str, str], InstanceTypePrice]:
    """
    The cheapest row of one usage type for each (provider, instance type),
    ignoring a row without a price.
    """
    cheapest: dict[tuple[str, str], tuple[float, InstanceTypePrice]] = {}
    for row in rows:
        value = _price_value(row.price)
        if row.usageType is not usage or value is None or row.instanceType is None:
            continue
        key = (_provider_name(row), row.instanceType)
        if key not in cheapest or value < cheapest[key][0]:
            cheapest[key] = (value, row)
    return {key: row for key, (_, row) in cheapest.items()}


def instance_types_with_prices(
    ctx: RunContext, query: CloudInfoQuery
) -> list[PricedInstanceType]:
    """
    The instance types the query names, each with its on-demand price in the
    query's region and its lowest spot price there (or in the query's
    sub-region), from one price search for them all. A type without a price
    of a kind has None for it, and is still listed.
    """
    by_name = replace(query, sort=("name",), reverse=False)
    types = instance_types(ctx, by_name)
    rows = prices(ctx, replace(by_name, usage=None))
    on_demand = _cheapest(rows, UsageType.ON_DEMAND)
    spot = _cheapest(rows, UsageType.SPOT)

    priced: list[PricedInstanceType] = []
    for instance_type in types:
        key = (_provider_name(instance_type), instance_type.name or "")
        on_demand_row = on_demand.get(key)
        spot_row = spot.get(key)
        priced.append(
            PricedInstanceType(
                instance_type=instance_type,
                on_demand=None if on_demand_row is None else on_demand_row.price,
                spot=None if spot_row is None else spot_row.price,
                spot_sub_region=None if spot_row is None else spot_row.subRegion,
            )
        )
    return _ordered(priced, _PRICED_SORTS, query, _priced_tie)
