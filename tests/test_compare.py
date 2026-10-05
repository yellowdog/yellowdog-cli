"""
Unit tests for yellowdog_cli/compare.py: the static helpers, the summary,
and each property's matching rule, with the Compute Requirement and Node
fetches stubbed. The '--json' document is tested in test_json_output.py.
"""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError, Response
from yellowdog_client.model import CloudProvider, DoubleRange, NodeStatus

import yellowdog_cli.compare as compare_module
from yellowdog_cli.compare import (
    UNKNOWN_STRING,
    FailedComparison,
    MatchReport,
    MatchType,
    PropertyMatch,
    WorkerPools,
)
from yellowdog_cli.utils.exit_codes import NotFoundError, classify
from yellowdog_cli.utils.settings import ExitCode

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


def _source(type_str: str, provider: CloudProvider | None = None) -> Any:
    return SimpleNamespace(type=type_str, provider=provider)


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
    def test_the_platforms_provider_is_used(self):
        source = _source("co.yellowdog.platform.model.X", CloudProvider.AZURE)
        assert WorkerPools._get_provider_from_source(source) == "AZURE"

    @pytest.mark.parametrize(
        "type_name, expected",
        [
            ("AwsInstancesComputeSource", "AWS"),
            ("AwsFleetComputeSource", "AWS"),
            ("AzureScaleSetComputeSource", "AZURE"),
            ("GceInstanceGroupComputeSource", "GOOGLE"),
            ("OciInstancePoolComputeSource", "OCI"),
        ],
    )
    def test_else_the_type_names_it(self, type_name, expected):
        source = _source(f"co.yellowdog.platform.model.{type_name}")
        assert WorkerPools._get_provider_from_source(source) == expected

    @pytest.mark.parametrize(
        "type_str",
        ["co.yellowdog.platform.model.SimulatorComputeSource", "", "SomeAWSThing"],
    )
    def test_else_it_is_unknown(self, type_str):
        assert WorkerPools._get_provider_from_source(_source(type_str)) == "UNKNOWN"


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


# ---------------------------------------------------------------------------
# The matching rules, with the Platform stubbed
# ---------------------------------------------------------------------------


def _run_spec(**kwargs) -> Any:
    fields = {
        "workerTags": None,
        "instanceTypes": None,
        "taskTypes": ["bash"],
        "providers": None,
        "regions": None,
        "namespaces": None,
        "ram": None,
        "vcpus": None,
    }
    fields.update(kwargs)
    return SimpleNamespace(
        name="tg",
        id="ydid:taskgrp:000000:x:1",
        runSpecification=SimpleNamespace(**fields),
    )


def _pool(worker_tag: str | None = "wt", namespace: str = "ns") -> Any:
    return SimpleNamespace(
        id="ydid:wrkrpool:000000:x",
        name="pool",
        status="RUNNING",
        namespace=namespace,
        computeRequirementId="ydid:cr:000000:x",
        properties=SimpleNamespace(workerTag=worker_tag),
    )


def _aws(instance_type="t3.small", region="eu-west-2", overrides=None) -> Any:
    return SimpleNamespace(
        type="co.yellowdog.platform.model.AwsFleetComputeSource",
        provider=CloudProvider.AWS,
        region=region,
        instanceType=instance_type,
        instanceOverrides=overrides,
    )


def _node(
    status=NodeStatus.RUNNING, ram=8.0, vcpus=2.0, task_types=("bash",), details=True
) -> Any:
    return SimpleNamespace(
        status=status,
        details=(
            SimpleNamespace(ram=ram, vcpus=vcpus, supportedTaskTypes=list(task_types))
            if details
            else None
        ),
    )


@pytest.fixture
def platform(monkeypatch):
    """
    Stub the Compute Requirement and Node fetches; the test fills in the
    sources and nodes, and reads how often each was fetched.
    """
    state = SimpleNamespace(sources=[_aws()], nodes=[_node()], cr_fetches=0)

    def get_cr(cr_id):
        state.cr_fetches += 1
        return SimpleNamespace(provisionStrategy=SimpleNamespace(sources=state.sources))

    client = MagicMock()
    client.compute_client.get_compute_requirement_by_id.side_effect = get_cr
    client.worker_pool_client.get_nodes.side_effect = lambda search: SimpleNamespace(
        list_all=lambda: state.nodes
    )
    monkeypatch.setattr(compare_module, "CLIENT", client)
    monkeypatch.setattr(
        compare_module, "ARGS_PARSER", SimpleNamespace(running_nodes_only=False)
    )
    WorkerPools._get_compute_requirement.cache_clear()
    WorkerPools._get_all_nodes_in_worker_pool_cached.cache_clear()
    yield state
    WorkerPools._get_compute_requirement.cache_clear()
    WorkerPools._get_all_nodes_in_worker_pool_cached.cache_clear()


def _rows(task_group, pool=None) -> dict[str, list[str]]:
    (report,) = WorkerPools(
        [pool or _pool()]
    ).check_task_group_for_matching_worker_pools(task_group)
    return {row[0]: row[1:] for row in report.detail_rows()}


class TestMatching:
    def test_a_fully_matching_pool(self, platform):
        rows = _rows(_run_spec(providers=[CloudProvider.AWS], regions=["eu-west-2"]))
        assert {row[2] for row in rows.values()} == {"YES"}

    def test_the_compute_requirement_is_fetched_once_per_pool(self, platform):
        pools = WorkerPools([_pool()])
        for _ in range(3):
            pools.check_task_group_for_matching_worker_pools(_run_spec())
        assert platform.cr_fetches == 1

    def test_fleet_overrides_are_instance_types(self, platform):
        platform.sources = [_aws(overrides=[SimpleNamespace(instanceType="t3.large")])]
        rows = _rows(_run_spec(instanceTypes=["t3.small"]))
        assert rows["Instance Type(s)"] == ["t3.small", "t3.large, t3.small", "NO"]

    def test_an_unknown_provider_fails_a_provider_constraint(self, platform):
        platform.sources = [
            SimpleNamespace(
                type="co.yellowdog.platform.model.SimulatorComputeSource",
                provider=None,
                region="r",
                instanceType="sim",
            )
        ]
        rows = _rows(_run_spec(providers=[CloudProvider.AWS]))
        assert rows["Provider(s)"] == ["AWS", "UNKNOWN", "NO"]

    @pytest.mark.parametrize("worker_tags", [None, []])
    def test_no_worker_tags_is_no_constraint(self, platform, worker_tags):
        assert _rows(_run_spec(workerTags=worker_tags))["Worker Tag(s)"][2] == "YES"

    @pytest.mark.parametrize("namespaces", [None, []])
    def test_no_namespaces_is_no_constraint(self, platform, namespaces):
        assert _rows(_run_spec(namespaces=namespaces))["Namespace(s)"][2] == "YES"

    def test_worker_tags_are_shown_sorted(self, platform):
        rows = _rows(_run_spec(workerTags=["wt", "b", "a"]))
        assert rows["Worker Tag(s)"] == ["a, b, wt", "wt", "YES"]

    def test_no_task_types_is_yes_without_nodes(self, platform):
        platform.nodes = []
        assert _rows(_run_spec(taskTypes=[]))["Task Type(s)"][2] == "YES"

    def test_task_types_without_nodes_are_maybe(self, platform):
        platform.nodes = []
        assert _rows(_run_spec())["Task Type(s)"] == [
            "bash",
            UNKNOWN_STRING,
            "MAYBE (no Nodes available)",
        ]

    def test_task_types_come_from_a_running_node(self, platform):
        platform.nodes = [
            _node(status=NodeStatus.TERMINATED, task_types=()),
            _node(task_types=("bash", "docker")),
        ]
        assert _rows(_run_spec())["Task Type(s)"] == ["bash", "bash, docker", "YES"]

    def test_a_node_without_details_is_not_a_non_match(self, platform):
        platform.nodes = [_node(details=False)]
        rows = _rows(_run_spec(ram=_dr(4.0, None), vcpus=_dr(1.0, 4.0)))
        assert rows["RAM (GB)"][1:] == [UNKNOWN_STRING, "MAYBE (no Nodes available)"]
        assert rows["vCPUs Count"][2] == "MAYBE (no Nodes available)"
        assert rows["Task Type(s)"][2] == "MAYBE (no Nodes available)"

    def test_nodes_without_details_are_left_out_of_the_range(self, platform):
        platform.nodes = [_node(details=False), _node(ram=8.0)]
        assert _rows(_run_spec(ram=_dr(4.0, None)))["RAM (GB)"] == [
            "4.0 or more",
            "8.0",
            "YES",
        ]

    def test_any_node_out_of_range_is_no(self, platform):
        platform.nodes = [_node(ram=16.0), _node(ram=2.0), _node(ram=8.0)]
        assert _rows(_run_spec(ram=_dr(4.0, None)))["RAM (GB)"] == [
            "4.0 or more",
            "2.0, 8.0, 16.0",
            "NO",
        ]

    def test_running_nodes_only(self, platform, monkeypatch):
        monkeypatch.setattr(
            compare_module, "ARGS_PARSER", SimpleNamespace(running_nodes_only=True)
        )
        platform.nodes = [_node(status=NodeStatus.TERMINATED, ram=2.0), _node()]
        assert _rows(_run_spec(ram=_dr(4.0, None)))["RAM (GB)"][2] == "YES"

    def test_a_pool_that_cannot_be_compared_fails_in_its_place(self, platform):
        # The other pools are still compared
        broken = _pool()
        broken.computeRequirementId = None
        broken.id, broken.name = "ydid:wrkrpool:000000:broken", "broken"
        reports = WorkerPools(
            [broken, _pool()]
        ).check_task_group_for_matching_worker_pools(_run_spec())
        assert isinstance(reports[0], FailedComparison)
        assert "has no Compute Requirement" in str(reports[0].error)
        assert reports[1].summary() == MatchType.YES

    def test_a_session_failure_stops_the_comparison(self, platform):
        platform_client = compare_module.CLIENT
        platform_client.compute_client.get_compute_requirement_by_id.side_effect = (
            RequestsConnectionError("reset")
        )
        with pytest.raises(RequestsConnectionError):
            WorkerPools([_pool()]).check_task_group_for_matching_worker_pools(
                _run_spec()
            )


# ---------------------------------------------------------------------------
# Lookup failures keep their exit codes
# ---------------------------------------------------------------------------


def _http_error(status_code: int) -> HTTPError:
    response = Response()
    response.status_code = status_code
    return HTTPError(f"{status_code} Client Error", response=response)


class TestLookupFailures:
    @pytest.fixture
    def client(self, monkeypatch):
        client = MagicMock()
        monkeypatch.setattr(compare_module, "CLIENT", client)
        return client

    def test_a_missing_work_requirement_is_not_found(self, client):
        client.work_client.get_work_requirement_by_id.side_effect = _http_error(404)
        with pytest.raises(NotFoundError) as raised:
            compare_module._get_work_requirement_by_id("ydid:workreq:000000:x")
        assert (
            str(raised.value) == "Work Requirement ID 'ydid:workreq:000000:x' not found"
        )
        assert classify(raised.value) == ExitCode.NOT_FOUND

    def test_a_missing_task_group_is_not_found(self, monkeypatch):
        def missing(client, task_group_id):
            raise _http_error(404)

        monkeypatch.setattr(compare_module, "get_task_group_by_id", missing)
        with pytest.raises(NotFoundError) as raised:
            compare_module._get_task_group_by_id("ydid:taskgrp:000000:x:1")
        assert str(raised.value) == "Task Group ID 'ydid:taskgrp:000000:x:1' not found"
        assert classify(raised.value) == ExitCode.NOT_FOUND

    def test_a_missing_worker_pool_is_not_found(self, monkeypatch):
        def missing(client, worker_pool_id):
            raise _http_error(404)

        monkeypatch.setattr(compare_module, "get_worker_pool_by_id", missing)
        with pytest.raises(NotFoundError) as raised:
            compare_module._get_provisioned_worker_pool_by_id("ydid:wrkrpool:000000:x")
        assert classify(raised.value) == ExitCode.NOT_FOUND

    @pytest.mark.parametrize(
        "error, code",
        [
            (RequestsConnectionError("reset"), ExitCode.CONNECTION),
            (_http_error(503), ExitCode.PLATFORM),
        ],
    )
    def test_other_failures_keep_their_exit_codes(self, client, error, code):
        client.work_client.get_work_requirement_by_id.side_effect = error
        with pytest.raises(RuntimeError) as raised:
            compare_module._get_work_requirement_by_id("ydid:workreq:000000:x")
        assert classify(raised.value) == code
