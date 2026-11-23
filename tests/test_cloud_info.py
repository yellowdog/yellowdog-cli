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
  - sorting: each key, several keys in turn, '--reverse', values missing
    last both ways
  - PricedInstanceType's JSON record, and its per-vCPU prices and spot
    saving (None, never a division by zero, where a side is missing)
  - '--gpus': the count summed over the models, a type without any as 0
"""

import pytest
from yellowdog_client.model import (
    CloudProvider,
    DoubleRange,
    InstanceType,
    OperatingSystemLicence,
    Price,
    ProcessorArchitecture,
    UsageType,
)

from tests.cloud_info_fixtures import WAVELENGTH, FakeCloudInfo, last_search
from yellowdog_cli.utils.cloud_info import (
    CloudInfoQuery,
    PricedInstanceType,
    gpu_count,
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
        query = CloudInfoQuery(providers=("aws",), sort=("vcpus",))
        assert _names(instance_types(fake.ctx, query)) == [
            "t3.micro",
            "t3a.micro",
            "g4dn.xlarge",
            "t3.xlarge",
            "t4g.xlarge",
            "c5.2xlarge",
            "u-unknown",
        ]

    def test_sorting_by_several_keys_sorts_by_each_in_turn(self, fake):
        by_vcpus = CloudInfoQuery(
            providers=("aws",), sort=("ram", "vcpus"), reverse=True
        )
        by_name = CloudInfoQuery(providers=("aws",), sort=("ram", "name"), reverse=True)
        assert _names(instance_types(fake.ctx, by_vcpus)) == [
            "c5.2xlarge",
            "g4dn.xlarge",
            "t3.xlarge",
            "t4g.xlarge",
            "t3.micro",
            "t3a.micro",
            "u-unknown",
        ]
        assert _names(instance_types(fake.ctx, by_name)) == [
            "t4g.xlarge",
            "t3.xlarge",
            "g4dn.xlarge",
            "c5.2xlarge",
            "t3a.micro",
            "t3.micro",
            "u-unknown",
        ]

    def test_reversing_keeps_ties_ascending_and_a_missing_value_last(self, fake):
        query = CloudInfoQuery(providers=("aws",), sort=("vcpus",), reverse=True)
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
        query = CloudInfoQuery(region="eu-west-2", sort=("price",))
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
        query = CloudInfoQuery(region="eu-west-2", sort=("price",), reverse=True)
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
            CloudInfoQuery(region="eu-west-2", providers=("aws",), sort=("spot",)),
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
                region="eu-west-2", providers=("aws",), sort=("spot",), reverse=True
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


def _one(
    vcpus: float | None, on_demand: float | None, spot: float | None
) -> PricedInstanceType:
    return PricedInstanceType(
        InstanceType(name="x", defaultVcpus=vcpus),
        None if on_demand is None else Price(value=on_demand),
        None if spot is None else Price(value=spot),
        "a",
    )


class TestDerivedPrices:
    def test_per_vcpu_prices_and_the_saving(self, fake):
        t3 = _priced(fake)["t3.xlarge"]
        assert t3.on_demand_per_vcpu == pytest.approx(0.047)
        assert t3.spot_per_vcpu == pytest.approx(0.0125)
        assert t3.spot_saving == pytest.approx((1 - 0.05 / 0.188) * 100)

    def test_a_missing_price_gives_none(self, fake):
        t4g = _priced(fake)["t4g.xlarge"]
        assert t4g.on_demand_per_vcpu is None
        assert t4g.spot_saving is None
        assert t4g.spot_per_vcpu == pytest.approx(0.01)

    @pytest.mark.parametrize("vcpus", [None, 0])
    def test_no_vcpus_gives_no_per_vcpu_price(self, vcpus):
        priced = _one(vcpus, 0.1, 0.05)
        assert (priced.on_demand_per_vcpu, priced.spot_per_vcpu) == (None, None)
        assert priced.spot_saving == pytest.approx(50.0)

    def test_a_zero_on_demand_price_gives_no_saving(self):
        assert _one(4, 0.0, 0.05).spot_saving is None

    def test_a_dearer_spot_price_is_a_negative_saving(self):
        assert _one(4, 0.1, 0.12).spot_saving == pytest.approx(-20.0)

    def test_sorting_by_spot_per_vcpu(self, fake):
        found = instance_types_with_prices(
            fake.ctx,
            CloudInfoQuery(
                region="eu-west-2", providers=("aws",), sort=("spot-per-vcpu",)
            ),
        )
        assert [p.instance_type.name for p in found] == [
            "t4g.xlarge",
            "t3.xlarge",
            "g4dn.xlarge",
            "t3.micro",
            "t3a.micro",
        ]

    def test_sorting_by_on_demand_per_vcpu(self, fake):
        found = instance_types_with_prices(
            fake.ctx,
            CloudInfoQuery(
                region="eu-west-2", providers=("aws",), sort=("on-demand-per-vcpu",)
            ),
        )
        assert [p.instance_type.name for p in found] == [
            "t3a.micro",
            "t3.xlarge",
            "g4dn.xlarge",
            "t3.micro",
            "t4g.xlarge",
        ]

    def test_sorting_by_saving(self, fake):
        found = instance_types_with_prices(
            fake.ctx,
            CloudInfoQuery(region="eu-west-2", providers=("aws",), sort=("saving",)),
        )
        assert found[0].instance_type.name == "t3.xlarge"

    def test_the_record_adds_the_derived_prices(self, fake):
        record = _priced(fake)["t3.xlarge"].as_record()
        assert record["onDemandPricePerVcpu"] == pytest.approx(0.047)
        assert record["spotPricePerVcpu"] == pytest.approx(0.0125)
        assert record["spotSavingPercent"] == 73.4
        none = _priced(fake)["g4dn.xlarge"].as_record()
        assert (
            none["onDemandPricePerVcpu"],
            none["spotPricePerVcpu"],
            none["spotSavingPercent"],
        ) == (None, None, None)


class TestGpus:
    def test_at_least_one_gpu(self, fake):
        found = instance_types(fake.ctx, CloudInfoQuery(gpus=(1.0, None)))
        assert _names(found) == ["g4dn.xlarge"]

    def test_no_gpus_includes_a_type_without_a_gpu_field(self, fake):
        names = _names(instance_types(fake.ctx, CloudInfoQuery(gpus=(0.0, 0.0))))
        assert "u-unknown" in names
        assert "g4dn.xlarge" not in names

    def test_the_join_honours_gpus(self, fake):
        assert sorted(_priced(fake, gpus=(1.0, None))) == ["g4dn.xlarge"]

    def test_the_count_sums_the_models(self):
        assert gpu_count(InstanceType(defaultGpus={"T4": 2, "A10G": 1})) == 3
        assert gpu_count(InstanceType()) == 0
