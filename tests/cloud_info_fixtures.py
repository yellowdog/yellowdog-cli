"""
Fixtures for the yd-cloud-info tests: Cloud Info service results shaped as
the live service returned them on 2026-10-07 (a Wavelength zone named after
its region, 't3' and 't3a' types, on-demand prices for the whole region as
'N/A', spot prices per zone, a Windows price, a type with no prices and a
price with no value), and a fake client that returns all of them whatever
it is asked, as a service whose filters only ever narrow would at worst.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from yellowdog_client.model import (
    CloudProvider,
    Currency,
    InstanceType,
    InstanceTypePrice,
    InstanceTypeRegion,
    OperatingSystemLicence,
    Price,
    ProcessorArchitecture,
    Region,
    SubRegion,
    UsageType,
)

from yellowdog_cli.utils.context import RunContext

AWS = CloudProvider.AWS
AZURE = CloudProvider.AZURE
X86 = ProcessorArchitecture.X86_64
ARM = ProcessorArchitecture.ARM64
OD = UsageType.ON_DEMAND
SPOT = UsageType.SPOT
NONE = OperatingSystemLicence.NONE
WINDOWS = OperatingSystemLicence.WINDOWS

EU_WEST_2_ZONES = ["eu-west-2a", "eu-west-2b", "eu-west-2c"]
WAVELENGTH = "eu-west-2-wl1-lon1"

REGIONS = [
    Region(provider=AWS, name="eu-west-2"),
    Region(provider=AWS, name=WAVELENGTH),
    Region(provider=AWS, name="us-east-1"),
    Region(provider=AZURE, name="uksouth"),
]

SUB_REGIONS = [
    SubRegion(provider=AWS, region="eu-west-2", name="eu-west-2a"),
    SubRegion(provider=AWS, region="eu-west-2", name="eu-west-2b"),
    SubRegion(provider=AWS, region=WAVELENGTH, name=f"{WAVELENGTH}-wlz-1"),
    SubRegion(provider=AWS, region="us-east-1", name="us-east-1a"),
]


def _type(
    name: str,
    vcpus: float | None,
    ram_mib: int | None,
    arch: ProcessorArchitecture | None = X86,
    regions: dict[str, list[str]] | None = None,
    gpus: dict[str, int] | None = None,
    provider: CloudProvider = AWS,
) -> InstanceType:
    zones = {"eu-west-2": EU_WEST_2_ZONES} if regions is None else regions
    return InstanceType(
        provider=provider,
        name=name,
        processorArchitecture=arch,
        defaultVcpus=vcpus,
        defaultGpus=gpus or {},
        ramInMib=ram_mib,
        regions=[
            InstanceTypeRegion(name=region, subRegions=subs)
            for region, subs in zones.items()
        ],
    )


TYPES = [
    _type("t3.micro", 2, 1024),
    _type("t3a.micro", 2, 1024),
    _type("t3.xlarge", 4, 16384),
    _type("t4g.xlarge", 4, 16384, arch=ARM),
    _type(
        "g4dn.xlarge",
        4,
        16384,
        gpus={"T4": 1},
        regions={"eu-west-2": ["eu-west-2a", "eu-west-2b"]},
    ),
    _type("c5.2xlarge", 8, 16384, regions={"us-east-1": ["us-east-1a"]}),
    _type(
        "Standard_D4s_v5",
        4,
        16384,
        provider=AZURE,
        regions={"uksouth": ["1", "2", "3"]},
    ),
    InstanceType(provider=AWS, name="u-unknown", regions=None),
]


def _price(
    instance_type: str,
    usage: UsageType,
    value: float | None,
    region: str = "eu-west-2",
    sub_region: str = "N/A",
    os_licence: OperatingSystemLicence = NONE,
) -> InstanceTypePrice:
    return InstanceTypePrice(
        provider=AWS,
        region=region,
        subRegion=sub_region,
        instanceType=instance_type,
        usageType=usage,
        operatingSystemLicence=os_licence,
        price=Price(currency=Currency.USD, value=value),
    )


PRICES = [
    _price("t3.xlarge", OD, 0.188),
    _price("t3.xlarge", OD, 0.376, os_licence=WINDOWS),
    _price("t3.xlarge", SPOT, 0.07, sub_region="eu-west-2a"),
    _price("t3.xlarge", SPOT, 0.05, sub_region="eu-west-2b"),
    _price("t3.xlarge", SPOT, 0.06, sub_region="eu-west-2c"),
    _price("t3.xlarge", SPOT, 0.09, sub_region="eu-west-2b", os_licence=WINDOWS),
    _price("t3.xlarge", OD, 0.2, region=WAVELENGTH),
    _price(
        "t3.xlarge", SPOT, 0.01, region=WAVELENGTH, sub_region=f"{WAVELENGTH}-wlz-1"
    ),
    _price("t3a.micro", OD, 0.0118),
    _price("t4g.xlarge", SPOT, 0.04, sub_region="eu-west-2a"),
    _price("t3.micro", SPOT, None, sub_region="eu-west-2a"),
]


class FakeCloudInfo:
    """
    A Platform client whose cloud_info_client returns every fixture for
    every search, keeping the searches for the tests to inspect.
    """

    def __init__(self) -> None:
        client = MagicMock()
        self.info = client.cloud_info_client
        self.info.get_regions.side_effect = self._search(REGIONS)
        self.info.get_sub_regions.side_effect = self._search(SUB_REGIONS)
        self.info.get_instance_types.side_effect = self._search(TYPES)
        self.info.get_instance_type_prices.side_effect = self._search(PRICES)
        self.ctx = RunContext(
            args=SimpleNamespace(),  # type: ignore[arg-type]
            config=SimpleNamespace(),  # type: ignore[arg-type]
            client=client,
        )

    @staticmethod
    def _search(items: list[Any]):
        def search(_query: Any) -> SimpleNamespace:
            return SimpleNamespace(list_all=lambda: list(items))

        return search


def last_search(method: MagicMock) -> Any:
    """
    The search object the last call of a cloud_info_client method was given.
    """
    return method.call_args.args[0]
