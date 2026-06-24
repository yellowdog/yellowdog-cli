"""
Unit tests for yellowdog_cli/compare.py — pure static methods only.

SDK-dependent methods (_get_cr_from_wp, _match_*, etc.) require too much
live infrastructure to be worth unit-testing here.
"""

from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

from yellowdog_client.model import DoubleRange

from yellowdog_cli.compare import (
    MatchReport,
    MatchType,
    PropertyMatch,
    WorkerPools,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dr(min_: float | None, max_: float | None) -> DoubleRange:
    """
    Build a lightweight DoubleRange stand-in.
    """
    return cast(DoubleRange, cast(object, SimpleNamespace(min=min_, max=max_)))


def _pm(match: MatchType) -> PropertyMatch:
    return PropertyMatch(
        property_name="x",
        task_group_values="",
        worker_pool_values="",
        match=match,
    )


def _make_report(
    instance_types: MatchType = MatchType.YES,
    namespaces: MatchType = MatchType.YES,
    providers: MatchType = MatchType.YES,
    ram: MatchType = MatchType.YES,
    regions: MatchType = MatchType.YES,
    task_types: MatchType = MatchType.YES,
    vcpus: MatchType = MatchType.YES,
    worker_tags: MatchType = MatchType.YES,
) -> MatchReport:
    return MatchReport(
        worker_pool_name="wp",
        worker_pool_id="wp-id",
        worker_pool_status="RUNNING",
        instance_types=_pm(instance_types),
        namespaces=_pm(namespaces),
        providers=_pm(providers),
        ram=_pm(ram),
        regions=_pm(regions),
        task_types=_pm(task_types),
        vcpus=_pm(vcpus),
        worker_tags=_pm(worker_tags),
    )


def _source(type_str: str) -> MagicMock:
    src = MagicMock()
    src.type = type_str
    return src


# ---------------------------------------------------------------------------
# WorkerPools._check_in_range
# ---------------------------------------------------------------------------


class TestCheckInRange:
    def test_value_within_range(self):
        assert WorkerPools._check_in_range(5.0, _dr(1.0, 10.0)) is True

    def test_value_at_min(self):
        assert WorkerPools._check_in_range(1.0, _dr(1.0, 10.0)) is True

    def test_value_at_max(self):
        assert WorkerPools._check_in_range(10.0, _dr(1.0, 10.0)) is True

    def test_value_below_range(self):
        assert WorkerPools._check_in_range(0.5, _dr(1.0, 10.0)) is False

    def test_value_above_range(self):
        assert WorkerPools._check_in_range(10.1, _dr(1.0, 10.0)) is False

    def test_none_value_returns_false(self):
        assert WorkerPools._check_in_range(None, _dr(1.0, 10.0)) is False

    def test_none_min_is_unbounded_below(self):
        # No lower limit: any value at/below the max matches
        assert WorkerPools._check_in_range(5.0, _dr(None, 10.0)) is True

    def test_none_min_above_max_fails(self):
        assert WorkerPools._check_in_range(11.0, _dr(None, 10.0)) is False

    def test_none_max_is_unbounded_above(self):
        # No upper limit: any value at/above the min matches
        assert WorkerPools._check_in_range(5.0, _dr(1.0, None)) is True

    def test_none_max_below_min_fails(self):
        assert WorkerPools._check_in_range(0.5, _dr(1.0, None)) is False

    def test_both_none_matches_any_value(self):
        assert WorkerPools._check_in_range(123.0, _dr(None, None)) is True

    def test_none_value_with_one_sided_range_returns_false(self):
        assert WorkerPools._check_in_range(None, _dr(1.0, None)) is False

    def test_exact_match_single_value_range(self):
        assert WorkerPools._check_in_range(4.0, _dr(4.0, 4.0)) is True

    def test_just_outside_single_value_range(self):
        assert WorkerPools._check_in_range(4.1, _dr(4.0, 4.0)) is False


# ---------------------------------------------------------------------------
# WorkerPools._doublerange_str
# ---------------------------------------------------------------------------


class TestDoublerangeStr:
    def test_equal_min_max_shows_single_value(self):
        assert WorkerPools._doublerange_str(_dr(8.0, 8.0)) == "8.0"

    def test_range_shows_min_to_max(self):
        assert WorkerPools._doublerange_str(_dr(4.0, 16.0)) == "4.0 to 16.0"

    def test_integer_values_formatted_as_float(self):
        assert WorkerPools._doublerange_str(_dr(2.0, 2.0)) == "2.0"

    def test_asymmetric_range(self):
        assert WorkerPools._doublerange_str(_dr(0.5, 3.5)) == "0.5 to 3.5"

    def test_no_upper_limit(self):
        assert WorkerPools._doublerange_str(_dr(2.0, None)) == "2.0 or more"

    def test_no_lower_limit(self):
        assert WorkerPools._doublerange_str(_dr(None, 4.0)) == "up to 4.0"

    def test_both_unset(self):
        assert WorkerPools._doublerange_str(_dr(None, None)) == "any"


# ---------------------------------------------------------------------------
# WorkerPools._get_provider_from_source
# ---------------------------------------------------------------------------


class TestGetProviderFromSource:
    def test_aws_lowercase_type(self):
        assert (
            WorkerPools._get_provider_from_source(_source("awsInstancesComputeSource"))
            == "AWS"
        )

    def test_aws_mixed_case(self):
        assert (
            WorkerPools._get_provider_from_source(_source("SomeAWSProvider")) == "AWS"
        )

    def test_azure(self):
        assert (
            WorkerPools._get_provider_from_source(
                _source("azureInstancesComputeSource")
            )
            == "AZURE"
        )

    def test_gce_returns_google(self):
        assert (
            WorkerPools._get_provider_from_source(_source("gceInstancesComputeSource"))
            == "GOOGLE"
        )

    def test_oci(self):
        assert (
            WorkerPools._get_provider_from_source(_source("ociInstancesComputeSource"))
            == "OCI"
        )

    def test_unknown_returns_none(self):
        assert WorkerPools._get_provider_from_source(_source("unknownProvider")) is None

    def test_empty_type_returns_none(self):
        assert WorkerPools._get_provider_from_source(_source("")) is None


# ---------------------------------------------------------------------------
# MatchReport.summary
# ---------------------------------------------------------------------------


class TestMatchReportSummary:
    def test_all_yes_returns_yes(self):
        assert _make_report().summary() == MatchType.YES

    def test_any_no_returns_no(self):
        assert _make_report(providers=MatchType.NO).summary() == MatchType.NO

    def test_no_overrides_maybe(self):
        assert (
            _make_report(providers=MatchType.NO, ram=MatchType.MAYBE).summary()
            == MatchType.NO
        )

    def test_mix_yes_and_maybe_returns_maybe(self):
        assert _make_report(ram=MatchType.MAYBE).summary() == MatchType.MAYBE

    def test_all_maybe_returns_maybe(self):
        assert (
            _make_report(
                instance_types=MatchType.MAYBE,
                namespaces=MatchType.MAYBE,
                providers=MatchType.MAYBE,
                ram=MatchType.MAYBE,
                regions=MatchType.MAYBE,
                task_types=MatchType.MAYBE,
                vcpus=MatchType.MAYBE,
                worker_tags=MatchType.MAYBE,
            ).summary()
            == MatchType.MAYBE
        )

    def test_single_no_among_yes_returns_no(self):
        assert _make_report(worker_tags=MatchType.NO).summary() == MatchType.NO

    def test_single_maybe_among_yes_returns_maybe(self):
        assert _make_report(task_types=MatchType.MAYBE).summary() == MatchType.MAYBE
