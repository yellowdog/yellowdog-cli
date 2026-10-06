"""
Unit tests for cancel.py (yd-cancel), against a fake Platform.

Covers:
  - the tag-based listing and glob patterns, which offer CANCELLING Work
    Requirements only with '--abort', and '--dry-run'
  - explicit targets resolved in the order given without duplicates: Work
    Requirement IDs fetched whatever their namespace, names searched for,
    preferring one that can be cancelled, Task IDs fetched for their state
    and name; then confirmed once
  - an already-cancelling Work Requirement cancelled again with '--abort',
    recorded with "abortedTasks"
  - a session failure (authentication, connection) stopping the run, the
    rest recorded as not attempted, and '--follow' given what was cancelled
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import ANY, MagicMock

import pytest
from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError, Response
from yellowdog_client.model import TaskStatus, WorkRequirementStatus

import yellowdog_cli.cancel as yd_cancel
from yellowdog_cli.utils import action_runner, entity_utils
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import SESSION_FAILURES, ReportedFailure, classify
from yellowdog_cli.utils.ydid_utils import get_ydid_type

WR_A = "ydid:workreq:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
WR_B = "ydid:workreq:000000:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
WR_OLD = "ydid:workreq:000000:00000000-0000-0000-0000-000000000000"
TASK = "ydid:task:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:1:1"
NODE = "ydid:node:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

RUNNING = WorkRequirementStatus.RUNNING
CANCELLING = WorkRequirementStatus.CANCELLING
COMPLETED = WorkRequirementStatus.COMPLETED


def _http_error(status_code: int) -> HTTPError:
    response = Response()
    response.status_code = status_code
    return HTTPError(f"{status_code} Client Error", response=response)


def _wr(id_: str, name: str, status=RUNNING, namespace: str = "ns") -> Any:
    return SimpleNamespace(id=id_, name=name, status=status, namespace=namespace)


class FakePlatform:
    def __init__(self):
        self.wrs: dict[str, Any] = {WR_A: _wr(WR_A, "wr-a")}
        self.tasks: dict[str, Any] = {
            TASK: SimpleNamespace(id=TASK, name="t1", status=TaskStatus.EXECUTING)
        }
        self.calls: list[tuple] = []
        self.records: list[dict] = []
        self.failures: dict[str, Exception] = {}

        client = MagicMock()
        work = client.work_client
        work.get_work_requirement_by_id.side_effect = self._get(self.wrs)
        work.get_task_by_id.side_effect = self._get(self.tasks)
        work.cancel_work_requirement_by_id.side_effect = self._act(
            "cancel_work_requirement_by_id"
        )
        work.cancel_task_by_id.side_effect = self._act("cancel_task_by_id")
        self.client = client

    def _get(self, table):
        def get(entity_id):
            if "get" in self.failures:
                raise self.failures["get"]
            if entity_id not in table:
                raise _http_error(404)
            return table[entity_id]

        return get

    def _act(self, method):
        def act(entity_id, abort):
            if method in self.failures:
                raise self.failures[method]
            self.calls.append((method, entity_id, abort))
            return None

        return act

    def search(self, client=None, name=None, namespace=None, tag=None, **kwargs):
        statuses = kwargs.get("include_filter")
        return [
            wr
            for wr in self.wrs.values()
            if wr.namespace == namespace
            and (name is None or name in wr.name)
            and (tag is None or tag in wr.name)
            and (statuses is None or wr.status in statuses)
        ]

    def outcomes(self) -> list[tuple]:
        return [(r["id"], r["type"], r["outcome"]) for r in self.records]


@pytest.fixture
def platform(monkeypatch):
    fake = FakePlatform()
    fake.config = SimpleNamespace(namespace="ns", name_tag="wr", url="https://api.x")
    monkeypatch.setattr(action_runner, "confirmed", lambda message: True)
    monkeypatch.setattr(yd_cancel, "select", lambda client, objects: objects)
    monkeypatch.setattr(yd_cancel, "follow_ids", MagicMock())
    monkeypatch.setattr(
        yd_cancel, "get_filtered_work_requirement_summaries", fake.search
    )
    monkeypatch.setattr(
        entity_utils, "get_filtered_work_requirement_summaries", fake.search
    )

    def record_action(entity, entity_type, action, outcome, error=None, **extra):
        if isinstance(entity, str):
            is_ydid = get_ydid_type(entity) is not None
            entity = {
                "id": entity if is_ydid else None,
                "name": None if is_ydid else entity,
            }
        else:
            entity = {"id": entity.id, "name": entity.name}
        fake.records.append(
            {**entity, "type": entity_type, "outcome": outcome, "error": error, **extra}
        )

    monkeypatch.setattr(yd_cancel, "record_action", record_action)
    return fake


def _run(
    platform,
    targets: list[str],
    abort: bool = False,
    follow: bool = False,
    dry_run: bool = False,
):
    yd_cancel.cancel(
        RunContext(
            args=SimpleNamespace(
                abort=abort, follow=follow, dry_run=dry_run, json_output=False
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
    def test_the_tag_path_cancels_what_can_be_cancelled(self, platform, monkeypatch):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b", COMPLETED)
        _run(platform, [])
        assert platform.calls == [("cancel_work_requirement_by_id", WR_A, False)]

    @pytest.mark.parametrize("targets", [[], ["wr-*"]])
    def test_cancelling_ones_are_offered_only_with_abort(
        self, platform, monkeypatch, targets
    ):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b", CANCELLING)
        _run(platform, targets)
        assert [c[1] for c in platform.calls] == [WR_A]
        platform.calls.clear()
        platform.records.clear()
        _run(platform, targets, abort=True)
        assert [c[1] for c in platform.calls] == [WR_A, WR_B]
        assert platform.records[1]["abortedTasks"] is True
        assert "abortedTasks" not in platform.records[0]

    def test_a_dry_run_leaves_out_cancelling_ones_without_abort(
        self, platform, monkeypatch
    ):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b", CANCELLING)
        report = MagicMock()
        monkeypatch.setattr(yd_cancel, "report_dry_run", report)
        _run(platform, [], dry_run=True)
        assert platform.calls == []
        assert [s.id for s in report.call_args.args[1]] == [WR_A]

    def test_declining_skips_everything(self, platform, monkeypatch):
        monkeypatch.setattr(action_runner, "confirmed", lambda message: False)
        _run(platform, [])
        assert platform.calls == []
        assert platform.outcomes() == [(WR_A, "work-requirements", "skipped")]

    @pytest.mark.parametrize(
        "error", [_http_error(401), RequestsConnectionError("reset")]
    )
    def test_a_session_failure_stops(self, platform, monkeypatch, error):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b")
        platform.failures["cancel_work_requirement_by_id"] = error
        with pytest.raises(ReportedFailure) as raised:
            _run(platform, [])
        assert classify(raised.value) in SESSION_FAILURES
        assert [r["outcome"] for r in platform.records] == ["failed", "skipped"]
        assert platform.records[1]["error"].startswith("not attempted:")

    def test_follow_is_given_only_what_was_cancelled(self, platform, monkeypatch):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b")
        cancel = platform.client.work_client.cancel_work_requirement_by_id

        def failing_b(wr_id, abort):
            if wr_id == WR_B:
                raise _http_error(500)
            platform.calls.append(("cancel_work_requirement_by_id", wr_id, abort))

        cancel.side_effect = failing_b
        _run(platform, [], follow=True)
        yd_cancel.follow_ids.assert_called_once_with(ANY, [WR_A])


# ---------------------------------------------------------------------------
# Explicit Work Requirements and Tasks
# ---------------------------------------------------------------------------


class TestExplicit:
    def test_an_id_in_another_namespace_is_found(self, platform, monkeypatch):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b", namespace="elsewhere")
        _run(platform, [WR_B])
        assert platform.calls == [("cancel_work_requirement_by_id", WR_B, False)]

    def test_a_reused_name_prefers_one_that_can_be_cancelled(
        self, platform, monkeypatch
    ):
        platform.wrs = {
            WR_OLD: _wr(WR_OLD, "wr-a", COMPLETED),
            WR_A: _wr(WR_A, "wr-a"),
        }
        _run(platform, ["wr-a"])
        assert platform.calls == [("cancel_work_requirement_by_id", WR_A, False)]

    def test_two_that_can_be_cancelled_are_ambiguous(self, platform, monkeypatch):
        platform.wrs[WR_B] = _wr(WR_B, "wr-a")
        _run(platform, ["wr-a"])
        assert platform.calls == []
        assert "please supply the ID" in platform.records[0]["error"]

    def test_a_finished_one_is_skipped(self, platform, monkeypatch):
        platform.wrs[WR_A].status = COMPLETED
        _run(platform, ["wr-a"])
        assert platform.outcomes() == [(WR_A, "work-requirements", "skipped")]

    def test_a_cancelling_one_is_skipped_without_abort_saying_why(
        self, platform, monkeypatch
    ):
        platform.wrs[WR_A].status = CANCELLING
        _run(platform, [WR_A])
        assert platform.outcomes() == [(WR_A, "work-requirements", "skipped")]
        assert "--abort" in platform.records[0]["error"]

    def test_a_cancelling_one_is_cancelled_again_with_abort(
        self, platform, monkeypatch
    ):
        platform.wrs[WR_A].status = CANCELLING
        _run(platform, [WR_A], abort=True)
        assert platform.calls == [("cancel_work_requirement_by_id", WR_A, True)]
        assert platform.records[0]["abortedTasks"] is True

    def test_a_task_is_cancelled_and_named(self, platform, monkeypatch):
        _run(platform, [TASK], abort=True)
        assert platform.calls == [("cancel_task_by_id", TASK, True)]
        assert (platform.records[0]["name"], platform.records[0]["type"]) == (
            "t1",
            "tasks",
        )

    def test_a_finished_task_is_skipped(self, platform, monkeypatch):
        platform.tasks[TASK].status = TaskStatus.COMPLETED
        _run(platform, [TASK])
        assert platform.calls == []
        assert platform.outcomes() == [(TASK, "tasks", "skipped")]

    @pytest.mark.parametrize("target", [WR_B, "nope", NODE])
    def test_not_found_or_not_a_wr_or_task_fails(self, platform, monkeypatch, target):
        _run(platform, [target])
        assert platform.calls == []
        assert platform.records[0]["outcome"] == "failed"

    def test_in_the_order_given_without_duplicates(self, platform, monkeypatch):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b")
        _run(platform, ["wr-b", WR_A, "wr-a", TASK, TASK])
        assert [c[1] for c in platform.calls] == [WR_B, WR_A, TASK]

    def test_one_confirmation_names_everything(self, platform, monkeypatch):
        prompts = []
        monkeypatch.setattr(
            action_runner, "confirmed", lambda message: prompts.append(message) or True
        )
        _run(platform, [WR_A, TASK], abort=True)
        assert prompts == [
            f"Cancel 1 Work Requirement(s) ('ns/wr-a') and 1 Task(s) ('t1' ({TASK}))"
            " and abort their executing Tasks?"
        ]

    def test_declining_skips_everything(self, platform, monkeypatch):
        monkeypatch.setattr(action_runner, "confirmed", lambda message: False)
        _run(platform, [WR_A, TASK])
        assert platform.calls == []
        assert [r["outcome"] for r in platform.records] == ["skipped", "skipped"]

    def test_a_session_failure_while_resolving_stops(self, platform, monkeypatch):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b")
        get = platform.client.work_client.get_work_requirement_by_id
        calls = {"n": 0}

        def failing_second(wr_id):
            calls["n"] += 1
            if calls["n"] == 2:
                raise _http_error(401)
            return platform.wrs[wr_id]

        get.side_effect = failing_second
        with pytest.raises(ReportedFailure) as raised:
            _run(platform, [WR_A, WR_B, TASK])
        assert classify(raised.value) in SESSION_FAILURES
        assert platform.calls == []
        assert [(r["id"], r["outcome"]) for r in platform.records] == [
            (WR_B, "failed"),
            (WR_A, "skipped"),  # resolved, not attempted
            (TASK, "skipped"),  # not resolved
        ]

    def test_a_session_failure_while_cancelling_stops(self, platform, monkeypatch):
        platform.failures["cancel_work_requirement_by_id"] = _http_error(401)
        with pytest.raises(ReportedFailure) as raised:
            _run(platform, [WR_A, TASK])
        assert classify(raised.value) in SESSION_FAILURES
        assert [r["outcome"] for r in platform.records] == ["failed", "skipped"]
