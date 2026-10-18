"""
Live: Cloud Info for the primary: its region, sub-regions, instance types
and prices.
"""

import json

import pytest

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-cloud-info")]

_PROVIDER = {"aws": "aws", "azure": "azure", "gcp": "google", "oci": "oci"}
_TYPE_KEY = {
    "aws": "instance_type",
    "azure": "vm_size",
    "gcp": "machine_type",
    "oci": "shape",
}


def _context(live_run) -> tuple[str, str, str]:
    config = live_run.run.config
    section = config.providers[config.primary]
    return (
        _PROVIDER[config.primary],
        section["region"],
        section[_TYPE_KEY[config.primary]],
    )


def test_the_primarys_region_is_listed(live_run):
    provider, region, _ = _context(live_run)
    records = live_run.yd(
        "cloudinfo", "regions", "--provider", provider, "--json", "--quiet"
    ).records
    assert region in json.dumps(records)


def test_the_region_has_sub_regions(live_run):
    provider, region, _ = _context(live_run)
    records = live_run.yd(
        "cloudinfo",
        "sub-regions",
        "--provider",
        provider,
        "--region",
        region,
        "--json",
        "--quiet",
    ).records
    assert records


@pytest.mark.parametrize("verb", ["instance-types", "prices"])
def test_the_instance_type_is_listed_and_priced(live_run, verb):
    provider, region, instance_type = _context(live_run)
    records = live_run.yd(
        "cloudinfo",
        verb,
        "--provider",
        provider,
        "--region",
        region,
        "--name",
        instance_type,
        "--json",
        "--quiet",
    ).records
    assert instance_type in json.dumps(records)
