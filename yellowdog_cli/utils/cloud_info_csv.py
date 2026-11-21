"""
yd cloudinfo's '--csv': each type's listing as the rows of a CSV file, the
table's columns with snake_case names and raw values, for a spreadsheet: a
number as the service gives it (a whole one without '.0', a worked-out price
rounded to 6 places, a saving to 1), a missing value empty, an enum by its
name, GPUs as a count and sub-regions separated by spaces.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from yellowdog_cli.utils.cloud_info import PricedInstanceType, gpu_count
from yellowdog_cli.utils.entity_names import (
    CI_INSTANCE_TYPES,
    CI_PRICES,
    CI_REGIONS,
    CI_SUB_REGIONS,
)
from yellowdog_cli.utils.settings import CLOUD_INFO_NO_SUB_REGION, MIB_PER_GIB

if TYPE_CHECKING:
    from yellowdog_client.model import InstanceType, InstanceTypePrice, Price


def _name(value: Any) -> str | None:
    return None if value is None else value.name


def _provider(item: Any) -> str | None:
    return None if item.provider is None else item.provider.display_name


def _number(value: float | None) -> float | int | None:
    """
    A whole number without its '.0' (the service gives vCPUs as 4.0).
    """
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _rounded(value: float | None, places: int) -> float | None:
    return None if value is None else round(value, places)


def _price(price: Price | None) -> float | None:
    return None if price is None else price.value


def _currency(price: Price | None) -> str | None:
    return None if price is None else _name(price.currency)


def _sub_region(sub_region: str | None) -> str | None:
    return None if sub_region == CLOUD_INFO_NO_SUB_REGION else sub_region


def _regions(instance_type: InstanceType, region: str | None) -> Any:
    """
    The number of regions the type is offered in, or its sub-regions in the
    region asked for.
    """
    if region is None:
        return len(instance_type.regions or [])
    for entry in instance_type.regions or []:
        if entry.name == region:
            return " ".join(entry.subRegions or []) or None
    return None


def _instance_type_row(instance_type: InstanceType, region: str | None) -> list:
    ram_mib = instance_type.ramInMib
    return [
        _provider(instance_type),
        instance_type.name,
        _name(instance_type.processorArchitecture),
        _number(instance_type.defaultVcpus),
        _number(None if ram_mib is None else ram_mib / MIB_PER_GIB),
        gpu_count(instance_type),
        _regions(instance_type, region),
    ]


_INSTANCE_TYPE_HEADERS = ["provider", "name", "arch", "vcpus", "ram_gib", "gpus"]


def _priced_row(priced: PricedInstanceType, region: str | None) -> list:
    return [
        *_instance_type_row(priced.instance_type, region),
        _price(priced.on_demand),
        _price(priced.spot),
        _sub_region(priced.spot_sub_region),
        _rounded(priced.on_demand_per_vcpu, 6),
        _rounded(priced.spot_per_vcpu, 6),
        _rounded(priced.spot_saving, 1),
        _currency(priced.on_demand or priced.spot),
    ]


def _price_row(price: InstanceTypePrice) -> list:
    return [
        _provider(price),
        price.region,
        _sub_region(price.subRegion),
        price.instanceType,
        _name(price.usageType),
        _name(price.operatingSystemLicence),
        _price(price.price),
        _currency(price.price),
    ]


_ROWS: dict[str, tuple[list[str], Callable[[Any, str | None], list]]] = {
    CI_REGIONS: (["provider", "name"], lambda r, _: [_provider(r), r.name]),
    CI_SUB_REGIONS: (
        ["provider", "region", "name"],
        lambda s, _: [_provider(s), s.region, s.name],
    ),
    CI_PRICES: (
        [
            "provider",
            "region",
            "sub_region",
            "instance_type",
            "usage",
            "os_licence",
            "price",
            "currency",
        ],
        lambda p, _: _price_row(p),
    ),
}


def csv_table(
    info_type: str, items: list[Any], region: str | None, with_prices: bool
) -> tuple[list[str], list[list]]:
    """
    The header and rows '--csv' writes for a listing of 'info_type'.
    """
    if info_type == CI_INSTANCE_TYPES:
        if with_prices:
            headers = [
                *_INSTANCE_TYPE_HEADERS,
                "sub_regions",
                "on_demand",
                "spot",
                "spot_zone",
                "on_demand_per_vcpu",
                "spot_per_vcpu",
                "spot_saving_percent",
                "currency",
            ]
            return headers, [_priced_row(p, region) for p in items]
        headers = [
            *_INSTANCE_TYPE_HEADERS,
            "regions" if region is None else "sub_regions",
        ]
        return headers, [_instance_type_row(t, region) for t in items]
    headers, row = _ROWS[info_type]
    return headers, [row(item, region) for item in items]
