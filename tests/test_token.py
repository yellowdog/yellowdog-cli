"""
Unit tests for token.py (yd-token), against a fake Platform.

Covers:
  - refreshing by default and regenerating with '--regenerate', by ID and by
    name, in the order given, each pool once, with '--ttl-hours' passed on
    as a timedelta
  - the new token and its expiry recorded for '--json', and shown with its
    time zone, or as 'never' for a token without one
  - a target that is not found, or not a Configured Worker Pool: failed; a
    pool already shut down: skipped
  - a glob pattern taking only the active Configured Worker Pools it matches
  - a refresh and a regeneration each confirmed once, saying what the
    expiry will be, and nothing done if declined
  - '--dry-run' recording what would be done and doing nothing
  - a session failure (authentication, connection) stopping the run, the
    rest recorded as not attempted
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError, Response
from yellowdog_client.model import (
    ConfiguredWorkerPool,
    ProvisionedWorkerPool,
    WorkerPoolStatus,
    WorkerPoolSummary,
    WorkerPoolToken,
)

import yellowdog_cli.token as yd_token
from yellowdog_cli.utils import action_runner
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_utils import get_worker_pool_by_id
from yellowdog_cli.utils.exit_codes import ReportedFailure
from yellowdog_cli.utils.ydid_utils import get_ydid_type

WP_A = "ydid:wrkrpool:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
WP_B = "ydid:wrkrpool:000000:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
WP_C = "ydid:wrkrpool:000000:cccccccc-cccc-cccc-cccc-cccccccccccc"
EXPIRY = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)

REFRESH = "refresh_configured_worker_pool_token_by_id"
REGENERATE = "regenerate_configured_worker_pool_token_by_id"


def _http_error(status_code: int) -> HTTPError:
    response = Response()
    response.status_code = status_code
    return HTTPError(f"{status_code} Client Error", response=response)


def _configured(id_, name, status=WorkerPoolStatus.RUNNING):
    return ConfiguredWorkerPool(id=id_, name=name, status=status, namespace="ns")


def _provisioned(id_, name):
    return ProvisionedWorkerPool(
        id=id_, name=name, status=WorkerPoolStatus.RUNNING, namespace="ns"
    )


class FakePlatform:
    def __init__(self):
        self.pools: dict[str, Any] = {WP_A: _configured(WP_A, "wp-a")}
        self.calls: list[tuple] = []
        self.records: list[dict] = []
        self.failures: dict[str, Exception] = {}
        self.config = SimpleNamespace(namespace="ns")
        self.confirm = MagicMock(return_value=True)

        client = MagicMock()
        pools = client.worker_pool_client
        pools.get_worker_pool_by_id.side_effect = self._get
        pools.get_worker_pool_by_name.side_effect = self._by_name
        for method in (REFRESH, REGENERATE):
            getattr(pools, method).side_effect = self._act(method)
        self.client = client

    def _get(self, worker_pool_id):
        if worker_pool_id not in self.pools:
            raise _http_error(404)
        return self.pools[worker_pool_id]

    def _by_name(self, namespace, name):
        for pool in self.pools.values():
            if pool.namespace == namespace and pool.name == name:
                return pool
        raise _http_error(404)

    def _act(self, method):
        def act(worker_pool_id, token_ttl=None):
            if method in self.failures:
                raise self.failures[method]
            self.calls.append((method, worker_pool_id, token_ttl))
            return WorkerPoolToken(
                secret=f"secret-{worker_pool_id[-4:]}", expiryTime=EXPIRY
            )

        return act

    def outcomes(self) -> list[tuple]:
        return [(r["id"], r["action"], r["outcome"]) for r in self.records]


@pytest.fixture
def platform(monkeypatch):
    fake = FakePlatform()
    monkeypatch.setattr(action_runner, "confirmed", fake.confirm)
    monkeypatch.setattr(
        yd_token,
        "get_worker_pool_summaries",
        lambda client, namespace, name=None, partial_name_matches=True: [
            WorkerPoolSummary(
                id=pool.id,
                name=pool.name,
                namespace=pool.namespace,
                status=pool.status,
                type=pool.type,
            )
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

    monkeypatch.setattr(yd_token, "record_action", record_action)
    get_worker_pool_by_id.cache_clear()
    yield fake
    get_worker_pool_by_id.cache_clear()


def _run(
    platform,
    targets: list[str],
    regenerate: bool = False,
    ttl_hours: int | None = None,
    dry_run: bool = False,
):
    yd_token.act_on_tokens(
        RunContext(
            args=SimpleNamespace(
                regenerate=regenerate, ttl_hours=ttl_hours, dry_run=dry_run
            ),
            config=platform.config,
            client=platform.client,
        ),
        targets,
    )


class TestActing:
    def test_refresh_is_the_default_and_is_confirmed(self, platform):
        _run(platform, [WP_A])
        assert platform.calls == [(REFRESH, WP_A, None)]
        platform.confirm.assert_called_once()
        assert "never to expire" in platform.confirm.call_args.args[0]
        assert platform.outcomes() == [(WP_A, "refresh", "refreshed")]

    def test_declining_a_refresh_does_nothing(self, platform):
        platform.confirm.return_value = False
        _run(platform, [WP_A], ttl_hours=24)
        assert platform.calls == []
        assert platform.outcomes() == [(WP_A, "refresh", "skipped")]

    @pytest.mark.parametrize(
        "regenerate, ttl_hours, words",
        [
            (False, None, "Refresh the tokens of 1 Configured Worker Pool(s)"),
            (False, None, "setting them never to expire?"),
            (False, 1000, "setting them to expire in 1,000 hour(s)?"),
            (True, None, "invalidating their current tokens, the new ones never"),
            (True, 24, "the new ones to expire in 24 hour(s)?"),
        ],
    )
    def test_the_confirmation_says_what_the_expiry_will_be(
        self, platform, regenerate, ttl_hours, words
    ):
        _run(platform, [WP_A], regenerate=regenerate, ttl_hours=ttl_hours)
        assert words in platform.confirm.call_args.args[0]

    def test_regenerate_is_confirmed_once(self, platform):
        platform.pools[WP_B] = _configured(WP_B, "wp-b")
        _run(platform, [WP_A, WP_B], regenerate=True)
        assert [call[:2] for call in platform.calls] == [
            (REGENERATE, WP_A),
            (REGENERATE, WP_B),
        ]
        platform.confirm.assert_called_once()
        assert platform.outcomes() == [
            (WP_A, "regenerate", "regenerated"),
            (WP_B, "regenerate", "regenerated"),
        ]

    def test_declining_regenerate_does_nothing(self, platform):
        platform.confirm.return_value = False
        _run(platform, [WP_A], regenerate=True)
        assert platform.calls == []
        assert platform.outcomes() == [(WP_A, "regenerate", "skipped")]

    def test_the_ttl_is_passed_as_a_timedelta(self, platform):
        _run(platform, [WP_A], ttl_hours=720)
        assert platform.calls == [(REFRESH, WP_A, timedelta(hours=720))]

    def test_the_token_and_expiry_are_recorded(self, platform):
        _run(platform, [WP_A])
        record = platform.records[0]
        assert record["token"] == "secret-aaaa"
        assert record["expiryTime"] == EXPIRY.isoformat()
        assert record["type"] == "worker-pools"

    def test_a_token_without_an_expiry_is_recorded_and_shown_as_such(
        self, platform, monkeypatch
    ):
        shown: list[str] = []
        monkeypatch.setattr(yd_token, "print_info", shown.append)
        refresh = platform.client.worker_pool_client.refresh_configured_worker_pool_token_by_id
        refresh.side_effect = lambda worker_pool_id, token_ttl=None: WorkerPoolToken(
            secret="s"
        )
        _run(platform, [WP_A])
        assert platform.records[0]["expiryTime"] is None
        assert shown[-1].endswith("Worker Pool Expiry Time = never")

    def test_an_expiry_is_shown_with_its_time_zone(self, platform, monkeypatch):
        shown: list[str] = []
        monkeypatch.setattr(yd_token, "print_info", shown.append)
        _run(platform, [WP_A])
        assert shown[-1].endswith("Expiry Time = 2026-11-01 12:00:00+00:00")

    def test_by_name_and_id_in_the_order_given_each_once(self, platform):
        platform.pools[WP_B] = _configured(WP_B, "wp-b")
        _run(platform, ["wp-b", WP_A, "ns/wp-a"])
        assert [call[1] for call in platform.calls] == [WP_B, WP_A]


class TestUnresolved:
    def test_a_missing_pool_fails_and_the_rest_go_ahead(self, platform):
        _run(platform, ["nope", WP_C, WP_A])
        assert [call[1] for call in platform.calls] == [WP_A]
        assert platform.outcomes() == [
            (None, "refresh", "failed"),
            (WP_C, "refresh", "failed"),
            (WP_A, "refresh", "refreshed"),
        ]

    def test_a_provisioned_pool_fails(self, platform):
        platform.pools[WP_B] = _provisioned(WP_B, "wp-b")
        _run(platform, [WP_B])
        assert platform.calls == []
        assert platform.outcomes() == [(WP_B, "refresh", "failed")]
        assert "not a Configured Worker Pool" in platform.records[0]["error"]

    def test_a_shut_down_pool_is_skipped(self, platform):
        platform.pools[WP_B] = _configured(WP_B, "wp-b", WorkerPoolStatus.SHUTDOWN)
        _run(platform, [WP_B])
        assert platform.calls == []
        assert platform.outcomes() == [(WP_B, "refresh", "skipped")]


class TestGlobs:
    def test_a_glob_takes_only_active_configured_pools(self, platform):
        platform.pools[WP_B] = _provisioned(WP_B, "wp-b")
        platform.pools[WP_C] = _configured(WP_C, "wp-c", WorkerPoolStatus.SHUTDOWN)
        _run(platform, ["wp-*"])
        assert [call[1] for call in platform.calls] == [WP_A]
        assert platform.outcomes() == [(WP_A, "refresh", "refreshed")]

    def test_a_glob_matching_nothing_does_nothing(self, platform):
        _run(platform, ["other-*"])
        assert platform.calls == []
        assert platform.records == []


class TestDryRun:
    def test_a_dry_run_records_and_does_nothing(self, platform):
        _run(platform, [WP_A], regenerate=True, dry_run=True)
        assert platform.calls == []
        platform.confirm.assert_not_called()
        assert platform.outcomes() == [(WP_A, "regenerate", "would regenerate")]


class TestSessionFailure:
    def test_a_session_failure_stops_the_run(self, platform):
        platform.pools[WP_B] = _configured(WP_B, "wp-b")
        platform.failures[REFRESH] = RequestsConnectionError("down")
        with pytest.raises(ReportedFailure):
            _run(platform, [WP_A, WP_B])
        assert platform.outcomes() == [
            (WP_A, "refresh", "failed"),
            (WP_B, "refresh", "skipped"),
        ]
        assert platform.records[1]["error"].startswith("not attempted")

    def test_another_failure_does_not_stop_the_run(self, platform):
        platform.pools[WP_B] = _configured(WP_B, "wp-b")
        act = platform.client.worker_pool_client.refresh_configured_worker_pool_token_by_id

        def refresh(worker_pool_id, token_ttl=None):
            if worker_pool_id == WP_A:
                raise _http_error(400)
            platform.calls.append((REFRESH, worker_pool_id, token_ttl))
            return WorkerPoolToken(secret="s", expiryTime=EXPIRY)

        act.side_effect = refresh
        _run(platform, [WP_A, WP_B])
        assert platform.outcomes() == [
            (WP_A, "refresh", "failed"),
            (WP_B, "refresh", "refreshed"),
        ]
