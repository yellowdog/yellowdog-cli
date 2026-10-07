"""
Unit tests for utils/cloud_info.py (yd-cloud-info's library), against a fake
Cloud Info service that returns everything it holds whatever it is asked.

Covers:
  - the server hints sent: providers, a glob's literal prefix, ranges in the
    service's units, the OS licence, and no sub-region for prices
  - exact local filtering, since the service's text filters match
    substrings: a region never includes a Wavelength zone named after it,
    't3.*' never includes 't3a', a literal name is exact
  - the '--prices' join: on-demand and lowest spot price per type, the
    spot price's zone, a sub-region, Windows prices, missing prices
  - sorting: each key, '--reverse', values missing last both ways
  - PricedInstanceType's JSON record
"""

import pytest
from yellowdog_client.model import (
    CloudProvider,
    DoubleRange,
    OperatingSystemLicence,
    ProcessorArchitecture,
    UsageType,
)

from tests.cloud_info_fixtures import WAVELENGTH, FakeCloudInfo, last_search
from yellowdog_cli.utils.cloud_info import (
    CloudInfoQuery,
    instance_types,
    instance_types_with_prices,
    prices,
    regions,
    sub_regions,
)


@pytest.fixture
def fake() -> FakeCloudInfo:
    return FakeCloudInfo()


def _names(items) -> list[str]:
    return [item.name for item in items]


class TestRegions:
    def test_a_name_without_wildcards_is_exact(self, fake):
        found = regions(fake.ctx, CloudInfoQuery(name_glob="eu-west-2"))
        assert _names(found) == ["eu-west-2"]
        assert last_search(fake.info.get_regions).name == "eu-west-2"

    def test_a_glob_matches_and_sends_its_literal_prefix(self, fake):
        found = regions(fake.ctx, CloudInfoQuery(name_glob="eu-west-2*"))
        assert _names(found) == ["eu-west-2", WAVELENGTH]
        assert last_search(fake.info.get_regions).name == "eu-west-2"

    def test_a_leading_wildcard_sends_no_name(self, fake):
        found = regions(fake.ctx, CloudInfoQuery(name_glob="*-1"))
        assert _names(found) == ["us-east-1"]
        assert last_search(fake.info.get_regions).name is None

    def test_providers_are_sent_and_applied(self, fake):
        found = regions(fake.ctx, CloudInfoQuery(providers=("azure",)))
        assert _names(found) == ["uksouth"]
        assert last_search(fake.info.get_regions).providers == [CloudProvider.AZURE]


class TestSubRegions:
    def test_the_region_is_exact(self, fake):
        found = sub_regions(fake.ctx, CloudInfoQuery(region="eu-west-2"))
        assert _names(found) == ["eu-west-2a", "eu-west-2b"]
        assert last_search(fake.info.get_sub_regions).region == "eu-west-2"


class TestInstanceTypes:
    def test_a_glob_excludes_a_longer_family(self, fake):
        found = instance_types(fake.ctx, CloudInfoQuery(name_glob="t3.*"))
        assert _names(found) == ["t3.micro", "t3.xlarge"]
        assert last_search(fake.info.get_instance_types).name == "t3."

    def test_a_literal_name_is_exact(self, fake):
        found = instance_types(fake.ctx, CloudInfoQuery(name_glob="t3.micro"))
        assert _names(found) == ["t3.micro"]

    def test_vcpus_are_a_range_sent_and_applied(self, fake):
        found = instance_types(fake.ctx, CloudInfoQuery(vcpus=(4.0, 4.0)))
        assert _names(found) == [
            "Standard_D4s_v5",
            "g4dn.xlarge",
            "t3.xlarge",
            "t4g.xlarge",
        ]
        assert last_search(fake.info.get_instance_types).defaultVcpus == DoubleRange(
            min=4.0, max=4.0
        )

    def test_ram_is_in_gib_and_sent_in_mib(self, fake):
        found = instance_types(fake.ctx, CloudInfoQuery(ram_gib=(16.0, None)))
        assert _names(found) == [
            "Standard_D4s_v5",
            "c5.2xlarge",
            "g4dn.xlarge",
            "t3.xlarge",
            "t4g.xlarge",
        ]
        assert last_search(fake.info.get_instance_types).ramInMib == DoubleRange(
            min=16384.0, max=None
        )

    def test_the_architecture_is_sent_and_applied(self, fake):
        found = instance_types(fake.ctx, CloudInfoQuery(arch="arm64"))
        assert _names(found) == ["t4g.xlarge"]
        assert last_search(fake.info.get_instance_types).processorArchitectures == [
            ProcessorArchitecture.ARM64
        ]

    def test_a_region_keeps_the_types_offered_there(self, fake):
        found = instance_types(fake.ctx, CloudInfoQuery(region="us-east-1"))
        assert _names(found) == ["c5.2xlarge"]

    def test_a_sub_region_keeps_the_types_offered_in_it(self, fake):
        found = instance_types(
            fake.ctx, CloudInfoQuery(region="eu-west-2", sub_region="eu-west-2c")
        )
        assert _names(found) == ["t3.micro", "t3.xlarge", "t3a.micro", "t4g.xlarge"]

    def test_sorting_by_vcpus_puts_a_missing_value_last(self, fake):
        query = CloudInfoQuery(providers=("aws",), sort="vcpus")
        assert _names(instance_types(fake.ctx, query)) == [
            "t3.micro",
            "t3a.micro",
            "g4dn.xlarge",
            "t3.xlarge",
            "t4g.xlarge",
            "c5.2xlarge",
            "u-unknown",
        ]

    def test_reversing_keeps_ties_ascending_and_a_missing_value_last(self, fake):
        query = CloudInfoQuery(providers=("aws",), sort="vcpus", reverse=True)
        assert _names(instance_types(fake.ctx, query)) == [
            "c5.2xlarge",
            "g4dn.xlarge",
            "t3.xlarge",
            "t4g.xlarge",
            "t3.micro",
            "t3a.micro",
            "u-unknown",
        ]


class TestPrices:
    def test_the_region_is_exact(self, fake):
        found = prices(fake.ctx, CloudInfoQuery(region="eu-west-2"))
        assert {p.region for p in found} == {"eu-west-2"}
        assert len(found) == 7

    def test_the_os_licence_defaults_to_none(self, fake):
        found = prices(fake.ctx, CloudInfoQuery(region="eu-west-2"))
        assert {p.operatingSystemLicence for p in found} == {
            OperatingSystemLicence.NONE
        }
        search = last_search(fake.info.get_instance_type_prices)
        assert search.operatingSystemLicences == [OperatingSystemLicence.NONE]

    def test_windows_prices_on_request(self, fake):
        found = prices(
            fake.ctx, CloudInfoQuery(region="eu-west-2", os_licence="windows")
        )
        assert [(p.usageType, p.price.value) for p in found] == [
            (UsageType.ON_DEMAND, 0.376),
            (UsageType.SPOT, 0.09),
        ]

    def test_one_usage_type_is_sent_and_applied(self, fake):
        found = prices(fake.ctx, CloudInfoQuery(region="eu-west-2", usage="spot"))
        assert {p.usageType for p in found} == {UsageType.SPOT}
        search = last_search(fake.info.get_instance_type_prices)
        assert search.usageTypes == [UsageType.SPOT]

    def test_a_sub_region_keeps_the_regions_on_demand_prices(self, fake):
        found = prices(
            fake.ctx, CloudInfoQuery(region="eu-west-2", sub_region="eu-west-2a")
        )
        assert sorted((p.instanceType, p.subRegion) for p in found) == [
            ("t3.micro", "eu-west-2a"),
            ("t3.xlarge", "N/A"),
            ("t3.xlarge", "eu-west-2a"),
            ("t3a.micro", "N/A"),
            ("t4g.xlarge", "eu-west-2a"),
        ]
        # The service would drop the 'N/A' rows, so the zone is not sent
        assert last_search(fake.info.get_instance_type_prices).subRegion is None

    def test_sorting_by_price_puts_a_missing_one_last(self, fake):
        query = CloudInfoQuery(region="eu-west-2", sort="price")
        assert [p.price.value for p in prices(fake.ctx, query)] == [
            0.0118,
            0.04,
            0.05,
            0.06,
            0.07,
            0.188,
            None,
        ]

    def test_reversing_by_price_still_puts_a_missing_one_last(self, fake):
        query = CloudInfoQuery(region="eu-west-2", sort="price", reverse=True)
        assert [p.price.value for p in prices(fake.ctx, query)] == [
            0.188,
            0.07,
            0.06,
            0.05,
            0.04,
            0.0118,
            None,
        ]


def _priced(fake: FakeCloudInfo, **query) -> dict:
    found = instance_types_with_prices(
        fake.ctx, CloudInfoQuery(region="eu-west-2", providers=("aws",), **query)
    )
    return {p.instance_type.name: p for p in found}


def _value(price) -> float | None:
    return None if price is None else price.value


class TestJoin:
    def test_the_lowest_spot_price_ignores_a_wavelength_zone(self, fake):
        t3 = _priced(fake)["t3.xlarge"]
        assert _value(t3.on_demand) == 0.188
        assert _value(t3.spot) == 0.05
        assert t3.spot_sub_region == "eu-west-2b"

    def test_only_types_offered_in_the_region_are_listed(self, fake):
        assert sorted(_priced(fake)) == [
            "g4dn.xlarge",
            "t3.micro",
            "t3.xlarge",
            "t3a.micro",
            "t4g.xlarge",
        ]

    def test_a_type_without_prices_is_still_listed(self, fake):
        g4dn = _priced(fake)["g4dn.xlarge"]
        assert (g4dn.on_demand, g4dn.spot, g4dn.spot_sub_region) == (None, None, None)

    def test_a_price_without_a_value_is_no_price(self, fake):
        assert _priced(fake)["t3.micro"].spot is None

    def test_a_sub_region_restricts_spot_but_not_on_demand(self, fake):
        t3 = _priced(fake, sub_region="eu-west-2a")["t3.xlarge"]
        assert (_value(t3.on_demand), _value(t3.spot)) == (0.188, 0.07)
        assert t3.spot_sub_region == "eu-west-2a"

    def test_windows_prices_on_request(self, fake):
        t3 = _priced(fake, os_licence="windows")["t3.xlarge"]
        assert (_value(t3.on_demand), _value(t3.spot)) == (0.376, 0.09)

    def test_one_price_search_covers_every_type(self, fake):
        _priced(fake)
        assert fake.info.get_instance_type_prices.call_count == 1

    def test_sorting_by_spot_puts_types_without_one_last(self, fake):
        found = instance_types_with_prices(
            fake.ctx,
            CloudInfoQuery(region="eu-west-2", providers=("aws",), sort="spot"),
        )
        assert [p.instance_type.name for p in found] == [
            "t4g.xlarge",
            "t3.xlarge",
            "g4dn.xlarge",
            "t3.micro",
            "t3a.micro",
        ]

    def test_reversing_by_spot_still_puts_them_last(self, fake):
        found = instance_types_with_prices(
            fake.ctx,
            CloudInfoQuery(
                region="eu-west-2", providers=("aws",), sort="spot", reverse=True
            ),
        )
        assert [p.instance_type.name for p in found] == [
            "t3.xlarge",
            "t4g.xlarge",
            "g4dn.xlarge",
            "t3.micro",
            "t3a.micro",
        ]

    def test_the_record_adds_the_prices_to_the_type(self, fake):
        record = _priced(fake)["t3.xlarge"].as_record()
        assert record["provider"] == "AWS"
        assert record["name"] == "t3.xlarge"
        assert record["ramInMib"] == 16384
        assert record["onDemandPrice"] == {"currency": "USD", "value": 0.188}
        assert record["spotPrice"] == {"currency": "USD", "value": 0.05}
        assert record["spotSubRegion"] == "eu-west-2b"

    def test_the_record_of_a_type_without_prices_has_nulls(self, fake):
        record = _priced(fake)["g4dn.xlarge"].as_record()
        assert (
            record["onDemandPrice"],
            record["spotPrice"],
            record["spotSubRegion"],
        ) == (None, None, None)
