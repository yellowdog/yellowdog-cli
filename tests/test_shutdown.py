"""
Unit tests for shutdown.py (yd-shutdown), against a fake Platform.

Covers:
  - the tag-based and glob listings, which leave out finished Worker Pools,
    and '--dry-run', with '--terminate' reporting the Compute Requirements
  - explicit Worker Pool IDs and names and Node IDs, resolved in the order
    given (not found: failed; already finished: skipped), confirmed once
  - '--terminate': a Provisioned Worker Pool's Compute Requirement terminated
    and recorded with its pool's ID; a Configured one noted, not recorded,
    and never stopping the run
  - a session failure (authentication, connection) stopping the run, the
    rest recorded as not attempted
  - '--follow', given only the Worker Pools shut down
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError, Response
from yellowdog_client.model import (
    ConfiguredWorkerPool,
    NodeStatus,
    ProvisionedWorkerPool,
    WorkerPoolStatus,
    WorkerPoolSummary,
)

import yellowdog_cli.shutdown as yd_shutdown
from yellowdog_cli.utils import action_runner
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_utils import get_worker_pool_by_id
from yellowdog_cli.utils.exit_codes import SESSION_FAILURES, ReportedFailure, classify
from yellowdog_cli.utils.ydid_utils import get_ydid_type

WP_A = "ydid:wrkrpool:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
WP_B = "ydid:wrkrpool:000000:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
WP_C = "ydid:wrkrpool:000000:cccccccc-cccc-cccc-cccc-cccccccccccc"
CR_A = "ydid:compreq:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
NODE = "ydid:node:000000:dddddddd-dddd-dddd-dddd-dddddddddddd"


def _http_error(status_code: int) -> HTTPError:
    response = Response()
    response.status_code = status_code
    return HTTPError(f"{status_code} Client Error", response=response)


def _provisioned(id_, name, status=WorkerPoolStatus.RUNNING, cr_id=CR_A):
    pool = ProvisionedWorkerPool(id=id_, name=name, status=status, namespace="ns")
    pool.computeRequirementId = cr_id
    return pool


def _configured(id_, name, status=WorkerPoolStatus.RUNNING):
    return ConfiguredWorkerPool(id=id_, name=name, status=status, namespace="ns")


def _summary(pool) -> WorkerPoolSummary:
    return WorkerPoolSummary(
        id=pool.id, name=pool.name, namespace=pool.namespace, status=pool.status
    )


class FakePlatform:
    def __init__(self):
        self.pools: dict[str, Any] = {WP_A: _provisioned(WP_A, "wp-tag-a")}
        self.nodes: dict[str, Any] = {
            NODE: SimpleNamespace(id=NODE, status=NodeStatus.RUNNING)
        }
        self.calls: list[tuple] = []
        self.records: list[dict] = []
        self.failures: dict[str, Exception] = {}

        client = MagicMock()
        pools = client.worker_pool_client
        pools.get_worker_pool_by_id.side_effect = self._get(self.pools)
        pools.get_node_by_id.side_effect = self._get(self.nodes)
        pools.get_worker_pool_by_name.side_effect = self._by_name
        for method in ("shutdown_worker_pool_by_id", "shutdown_node_by_id"):
            getattr(pools, method).side_effect = self._act(method)
        client.compute_client.terminate_compute_requirement_by_id.side_effect = (
            self._act("terminate_compute_requirement_by_id")
        )
        self.client = client

    def _get(self, table):
        def get(entity_id=None, worker_pool_id=None):
            entity_id = entity_id or worker_pool_id
            if "get" in self.failures:
                raise self.failures["get"]
            if entity_id not in table:
                raise _http_error(404)
            return table[entity_id]

        return get

    def _by_name(self, namespace, name):
        for pool in self.pools.values():
            if pool.namespace == namespace and pool.name == name:
                return pool
        raise _http_error(404)

    def _act(self, method):
        def act(entity_id):
            if method in self.failures:
                raise self.failures[method]
            self.calls.append((method, entity_id))
            return SimpleNamespace(name="cr-a")

        return act

    def outcomes(self) -> list[tuple]:
        return [(r["id"], r["type"], r["action"], r["outcome"]) for r in self.records]


@pytest.fixture
def platform(monkeypatch):
    fake = FakePlatform()
    fake.config = SimpleNamespace(namespace="ns", name_tag="tag", url="https://api.x")
    monkeypatch.setattr(action_runner, "confirmed", lambda message: True)
    monkeypatch.setattr(yd_shutdown, "select", lambda client, objects: objects)
    monkeypatch.setattr(yd_shutdown, "follow_ids", MagicMock())
    monkeypatch.setattr(
        yd_shutdown,
        "get_worker_pool_summaries",
        lambda client, namespace, name=None, partial_name_matches=True: [
            _summary(pool)
            for pool in fake.pools.values()
            if pool.namespace == namespace and (name is None or name in pool.name)
        ],
    )

    def record_action(entity, entity_type, action, outcome, error=None, **extra):
        if isinstance(entity, str):
            is_ydid = get_ydid_type(entity) is not None
            entity = {
                "id": entity if is_ydid else None,
                "name": None if is_ydid else entity,
            }
        elif not isinstance(entity, dict):
            entity = {"id": entity.id, "name": getattr(entity, "name", None)}
        fake.records.append(
            {
                **entity,
                "type": entity_type,
                "action": action,
                "outcome": outcome,
                "error": error,
                **extra,
            }
        )

    monkeypatch.setattr(yd_shutdown, "record_action", record_action)
    get_worker_pool_by_id.cache_clear()
    yield fake
    get_worker_pool_by_id.cache_clear()


def _run(
    platform,
    targets: list[str],
    terminate: bool = False,
    follow: bool = False,
    dry_run: bool = False,
):
    yd_shutdown.shut_down(
        RunContext(
            args=SimpleNamespace(
                terminate=terminate,
                follow=follow,
                auto_cr=False,
                dry_run=dry_run,
                json_output=False,
            ),
            config=platform.config,
            client=platform.client,
        ),
        targets,
    )


# ---------------------------------------------------------------------------
# Listing: by tag, or by glob pattern
# ---------------------------------------------------------------------------


class TestListing:
    def test_the_tag_path_leaves_out_finished_and_untagged_pools(
        self, platform, monkeypatch
    ):
        platform.pools[WP_B] = _provisioned(WP_B, "wp-tag-b", WorkerPoolStatus.SHUTDOWN)
        platform.pools[WP_C] = _provisioned(WP_C, "other")
        _run(platform, [])
        assert platform.calls == [("shutdown_worker_pool_by_id", WP_A)]

    def test_a_glob_leaves_out_finished_and_unmatched_pools(
        self, platform, monkeypatch
    ):
        platform.pools[WP_B] = _provisioned(
            WP_B, "wp-tag-b", WorkerPoolStatus.TERMINATED
        )
        platform.pools[WP_C] = _provisioned(WP_C, "other")
        _run(platform, ["wp-*"])
        assert platform.calls == [("shutdown_worker_pool_by_id", WP_A)]

    def test_a_dry_run_reports_and_does_nothing(self, platform, monkeypatch):
        report = MagicMock()
        monkeypatch.setattr(yd_shutdown, "report_dry_run", report)
        _run(platform, ["wp-*"], dry_run=True)
        assert platform.calls == []
        assert [s.id for s in report.call_args.args[1]] == [WP_A]
        assert platform.records == []

    def test_a_dry_run_with_terminate_reports_the_compute_requirements(
        self, platform, monkeypatch
    ):
        monkeypatch.setattr(yd_shutdown, "report_dry_run", MagicMock())
        platform.pools[WP_B] = _configured(WP_B, "wp-tag-b")
        _run(platform, [], dry_run=True, terminate=True)
        assert platform.calls == []
        assert platform.outcomes() == [
            (CR_A, "compute-requirements", "terminate", "would terminate")
        ]
        assert platform.records[0]["workerPoolId"] == WP_A

    def test_follow_is_given_only_the_pools_shut_down(self, platform, monkeypatch):
        platform.pools[WP_B] = _provisioned(WP_B, "wp-tag-b")
        failing = {WP_B}
        act = platform.client.worker_pool_client.shutdown_worker_pool_by_id

        def shutdown(pool_id):
            if pool_id in failing:
                raise _http_error(500)
            platform.calls.append(("shutdown_worker_pool_by_id", pool_id))

        act.side_effect = shutdown
        _run(platform, [], follow=True)
        yd_shutdown.follow_ids.assert_called_once_with([WP_A], auto_cr=False)


# ---------------------------------------------------------------------------
# Explicit Worker Pools and Nodes
# ---------------------------------------------------------------------------


class TestExplicit:
    def test_by_id_and_name_in_the_order_given(self, platform, monkeypatch):
        platform.pools[WP_B] = _provisioned(WP_B, "wp-b")
        _run(platform, ["wp-b", NODE, WP_A])
        assert platform.calls == [
            ("shutdown_worker_pool_by_id", WP_B),
            ("shutdown_worker_pool_by_id", WP_A),
            ("shutdown_node_by_id", NODE),
        ]
        assert platform.records[0]["name"] == "wp-b"

    def test_a_pool_by_name_and_by_id_is_one_target(self, platform, monkeypatch):
        _run(platform, ["wp-tag-a", WP_A, WP_A])
        assert platform.calls == [("shutdown_worker_pool_by_id", WP_A)]

    def test_one_confirmation_names_everything(self, platform, monkeypatch):
        prompts = []
        monkeypatch.setattr(
            action_runner, "confirmed", lambda message: prompts.append(message) or True
        )
        _run(platform, [WP_A, NODE], terminate=True)
        assert prompts == [
            f"Shut down 1 Worker Pool(s) ('wp-tag-a') and 1 Node(s) ({NODE}),"
            " immediately terminating their Compute Requirements?"
        ]

    def test_declining_skips_everything(self, platform, monkeypatch):
        monkeypatch.setattr(action_runner, "confirmed", lambda message: False)
        _run(platform, [WP_A, NODE])
        assert platform.calls == []
        assert [r["outcome"] for r in platform.records] == ["skipped", "skipped"]

    @pytest.mark.parametrize("target", [WP_B, "nope", NODE.replace("dddd", "eeee")])
    def test_not_found_fails(self, platform, monkeypatch, target):
        _run(platform, [target])
        assert platform.calls == []
        assert platform.records[0]["outcome"] == "failed"

    @pytest.mark.parametrize(
        "status", [WorkerPoolStatus.SHUTDOWN, WorkerPoolStatus.TERMINATED]
    )
    def test_a_finished_pool_is_skipped(self, platform, monkeypatch, status):
        platform.pools[WP_A] = _provisioned(WP_A, "wp-tag-a", status)
        _run(platform, [WP_A])
        assert platform.calls == []
        assert platform.outcomes() == [(WP_A, "worker-pools", "shutdown", "skipped")]
        assert platform.records[0]["name"] == "wp-tag-a"

    def test_a_terminated_node_is_skipped(self, platform, monkeypatch):
        platform.nodes[NODE].status = NodeStatus.TERMINATED
        _run(platform, [NODE])
        assert platform.outcomes() == [(NODE, "nodes", "shutdown", "skipped")]

    def test_a_failure_carries_on(self, platform, monkeypatch):
        platform.failures["shutdown_worker_pool_by_id"] = _http_error(500)
        _run(platform, [WP_A, NODE])
        assert platform.calls == [("shutdown_node_by_id", NODE)]
        assert [r["outcome"] for r in platform.records] == ["failed", "shut down"]


# ---------------------------------------------------------------------------
# --terminate
# ---------------------------------------------------------------------------


class TestTerminate:
    def test_a_provisioned_pools_compute_requirement(self, platform, monkeypatch):
        _run(platform, [WP_A], terminate=True)
        assert platform.calls == [
            ("shutdown_worker_pool_by_id", WP_A),
            ("terminate_compute_requirement_by_id", CR_A),
        ]
        cr_record = platform.records[1]
        assert (cr_record["id"], cr_record["name"], cr_record["outcome"]) == (
            CR_A,
            "cr-a",
            "terminated",
        )
        assert cr_record["workerPoolId"] == WP_A

    def test_a_configured_pool_is_noted_and_the_run_carries_on(
        self, platform, monkeypatch
    ):
        # The bug: a Configured Worker Pool has no computeRequirementId, and
        # reading it stopped the run, leaving the rest not shut down
        warnings = []
        monkeypatch.setattr(yd_shutdown, "print_warning", warnings.append)
        monkeypatch.setattr(action_runner, "print_warning", warnings.append)
        platform.pools[WP_B] = _configured(WP_B, "wp-b")
        _run(platform, [WP_B, WP_A, NODE], terminate=True)
        assert platform.calls == [
            ("shutdown_worker_pool_by_id", WP_B),
            ("shutdown_worker_pool_by_id", WP_A),
            ("terminate_compute_requirement_by_id", CR_A),
            ("shutdown_node_by_id", NODE),
        ]
        assert "Configured Worker Pool" in warnings[0]
        assert [r["type"] for r in platform.records].count("compute-requirements") == 1

    def test_a_listed_pool_whose_lookup_fails_records_no_wrong_id(
        self, platform, monkeypatch
    ):
        def shutdown(pool_id):
            platform.calls.append(("shutdown_worker_pool_by_id", pool_id))
            platform.failures["get"] = _http_error(500)

        platform.client.worker_pool_client.shutdown_worker_pool_by_id.side_effect = (
            shutdown
        )
        _run(platform, [], terminate=True)
        cr_record = platform.records[1]
        assert cr_record["type"] == "compute-requirements"
        assert cr_record["id"] is None  # never the Worker Pool's ID
        assert cr_record["workerPoolId"] == WP_A
        assert cr_record["outcome"] == "failed"

    def test_a_failed_termination_is_recorded(self, platform, monkeypatch):
        platform.failures["terminate_compute_requirement_by_id"] = _http_error(500)
        _run(platform, [WP_A], terminate=True)
        assert platform.outcomes()[1] == (
            CR_A,
            "compute-requirements",
            "terminate",
            "failed",
        )


# ---------------------------------------------------------------------------
# A session failure stops the run
# ---------------------------------------------------------------------------


class TestSessionFailures:
    @pytest.mark.parametrize(
        "error", [_http_error(401), RequestsConnectionError("reset")]
    )
    def test_while_shutting_down(self, platform, monkeypatch, error):
        platform.pools[WP_B] = _provisioned(WP_B, "wp-b")
        platform.failures["shutdown_worker_pool_by_id"] = error
        with pytest.raises(ReportedFailure) as raised:
            _run(platform, [WP_A, WP_B, NODE])
        assert classify(raised.value) in SESSION_FAILURES
        assert platform.calls == []
        assert [r["outcome"] for r in platform.records] == [
            "failed",
            "skipped",
            "skipped",
        ]
        assert platform.records[1]["error"].startswith("not attempted:")

    def test_while_terminating(self, platform, monkeypatch):
        platform.pools[WP_B] = _provisioned(WP_B, "wp-b")
        platform.failures["terminate_compute_requirement_by_id"] = _http_error(401)
        with pytest.raises(ReportedFailure) as raised:
            _run(platform, [WP_A, WP_B], terminate=True)
        assert classify(raised.value) in SESSION_FAILURES
        assert platform.calls == [("shutdown_worker_pool_by_id", WP_A)]
        assert [(r["type"], r["outcome"]) for r in platform.records] == [
            ("worker-pools", "shut down"),
            ("compute-requirements", "failed"),
            ("worker-pools", "skipped"),
        ]

    def test_while_resolving(self, platform, monkeypatch):
        platform.pools[WP_B] = _provisioned(WP_B, "wp-b")
        calls = {"n": 0}
        get = platform.client.worker_pool_client.get_worker_pool_by_id

        def failing_second(pool_id=None, worker_pool_id=None):
            pool_id = pool_id or worker_pool_id
            calls["n"] += 1
            if calls["n"] == 2:
                raise _http_error(401)
            return platform.pools[pool_id]

        get.side_effect = failing_second
        with pytest.raises(ReportedFailure) as raised:
            _run(platform, [WP_A, WP_B, NODE])
        assert classify(raised.value) in SESSION_FAILURES
        assert platform.calls == []
        assert [(r["id"], r["outcome"]) for r in platform.records] == [
            (WP_B, "failed"),
            (WP_A, "skipped"),  # resolved, not attempted
            (NODE, "skipped"),  # not resolved
        ]
