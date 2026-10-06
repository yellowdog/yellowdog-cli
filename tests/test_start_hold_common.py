"""
Unit tests for start_hold_common.py (yd-start and yd-hold), against a fake
Platform.

Covers:
  - the tag-based listing and glob patterns, each filtered to the state the
    action applies to
  - explicit targets resolved in the order given without duplicates: an ID
    fetched directly whatever its namespace, a name looked up by name (not
    by listing the namespace), preferring the Work Requirement in the
    required state where a name has been reused, and refusing to guess
    between two; then confirmed once
  - what each outcome records, and a session failure (authentication,
    connection) stopping the run, the rest recorded as not attempted
  - '--follow', given only the Work Requirements actioned
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import ANY, MagicMock

import pytest
from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError, Response
from yellowdog_client.model import WorkRequirementStatus

import yellowdog_cli.utils.start_hold_common as shc_module
from yellowdog_cli.utils import action_runner, entity_utils
from yellowdog_cli.utils.command_registry import (
    COMMANDS,
    check_glob_and_literal_names,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import SESSION_FAILURES, ReportedFailure, classify
from yellowdog_cli.utils.start_hold_common import FINISH, HOLD, START
from yellowdog_cli.utils.ydid_utils import get_ydid_type

WR_A = "ydid:workreq:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
WR_B = "ydid:workreq:000000:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
WR_OLD = "ydid:workreq:000000:00000000-0000-0000-0000-000000000000"
TASK = "ydid:task:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:1:1"

HELD = WorkRequirementStatus.HELD
RUNNING = WorkRequirementStatus.RUNNING
COMPLETED = WorkRequirementStatus.COMPLETED
FINISHING = WorkRequirementStatus.FINISHING
CANCELLING = WorkRequirementStatus.CANCELLING


def _http_error(status_code: int) -> HTTPError:
    response = Response()
    response.status_code = status_code
    return HTTPError(f"{status_code} Client Error", response=response)


def _wr(id_: str, name: str, status=HELD, namespace: str = "ns") -> Any:
    return SimpleNamespace(id=id_, name=name, status=status, namespace=namespace)


class FakePlatform:
    def __init__(self):
        self.wrs: dict[str, Any] = {WR_A: _wr(WR_A, "wr-a")}
        self.calls: list[tuple] = []
        self.searches: list[dict] = []
        self.records: list[dict] = []
        self.failures: dict[str, Exception] = {}

        client = MagicMock()
        work = client.work_client
        work.get_work_requirement_by_id.side_effect = self._get
        for method in (
            "start_work_requirement_by_id",
            "hold_work_requirement_by_id",
            "finish_work_requirement_by_id",
        ):
            getattr(work, method).side_effect = self._act(method)
        self.client = client

    def _get(self, wr_id):
        if "get" in self.failures:
            raise self.failures["get"]
        if wr_id not in self.wrs:
            raise _http_error(404)
        return self.wrs[wr_id]

    def _act(self, method):
        def act(wr_id):
            if method in self.failures:
                raise self.failures[method]
            self.calls.append((method, wr_id))
            return None

        return act

    def search(self, client=None, name=None, namespace=None, tag=None, **kwargs):
        self.searches.append({"name": name, "namespace": namespace, "tag": tag})
        if "search" in self.failures:
            raise self.failures["search"]
        statuses = kwargs.get("include_filter")
        return [
            wr
            for wr in self.wrs.values()
            if (namespace is None or wr.namespace == namespace)
            and (name is None or name in wr.name)
            and (tag is None or tag in wr.name)
            and (statuses is None or wr.status in statuses)
        ]


@pytest.fixture
def platform(monkeypatch):
    fake = FakePlatform()
    fake.config = SimpleNamespace(namespace="ns", name_tag="wr", url="https://api.x")
    monkeypatch.setattr(action_runner, "confirmed", lambda message: True)
    monkeypatch.setattr(shc_module, "select", lambda client, objects: objects)
    monkeypatch.setattr(shc_module, "follow_ids", MagicMock())
    monkeypatch.setattr(
        shc_module, "get_filtered_work_requirement_summaries", fake.search
    )
    monkeypatch.setattr(
        entity_utils, "get_filtered_work_requirement_summaries", fake.search
    )

    def record_action(entity, entity_type, action, outcome, error=None):
        if isinstance(entity, str):
            is_ydid = get_ydid_type(entity) is not None
            entity = {
                "id": entity if is_ydid else None,
                "name": None if is_ydid else entity,
            }
        else:
            entity = {"id": entity.id, "name": entity.name}
        fake.records.append(
            {**entity, "action": action, "outcome": outcome, "error": error}
        )

    monkeypatch.setattr(shc_module, "record_action", record_action)
    return fake


def _run(platform, action, targets: list[str], follow: bool = False):
    shc_module.apply_work_requirement_action(
        RunContext(
            args=SimpleNamespace(work_requirement_names=targets, follow=follow),
            config=platform.config,
            client=platform.client,
        ),
        action,
    )


def _outcomes(platform) -> list[tuple]:
    return [(r["id"], r["outcome"]) for r in platform.records]


# ---------------------------------------------------------------------------
# Listing: by tag, or by glob pattern
# ---------------------------------------------------------------------------


class TestListing:
    @pytest.mark.parametrize(
        "action, status, method",
        [
            (START, HELD, "start_work_requirement_by_id"),
            (HOLD, RUNNING, "hold_work_requirement_by_id"),
        ],
    )
    def test_the_tag_path_acts_in_the_required_state(
        self, platform, monkeypatch, action, status, method
    ):
        platform.wrs = {
            WR_A: _wr(WR_A, "wr-a", status),
            WR_B: _wr(WR_B, "wr-b", COMPLETED),
        }
        _run(platform, action, [])
        assert platform.calls == [(method, WR_A)]
        assert _outcomes(platform) == [(WR_A, action.past_tense.lower())]

    def test_a_glob_selects_matching_names_in_the_required_state(
        self, platform, monkeypatch
    ):
        platform.wrs = {
            WR_A: _wr(WR_A, "proj-1"),
            WR_B: _wr(WR_B, "proj-2", RUNNING),
            WR_OLD: _wr(WR_OLD, "other"),
        }
        _run(platform, START, ["proj-*"])
        assert platform.calls == [("start_work_requirement_by_id", WR_A)]

    def test_declining_skips_everything(self, platform, monkeypatch):
        monkeypatch.setattr(action_runner, "confirmed", lambda message: False)
        _run(platform, START, [])
        assert platform.calls == []
        assert _outcomes(platform) == [(WR_A, "skipped")]

    def test_a_failure_carries_on(self, platform, monkeypatch):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b")
        platform.failures["start_work_requirement_by_id"] = _http_error(500)
        _run(platform, START, [])
        assert [r["outcome"] for r in platform.records] == ["failed", "failed"]

    @pytest.mark.parametrize(
        "error", [_http_error(401), RequestsConnectionError("reset")]
    )
    def test_a_session_failure_stops(self, platform, monkeypatch, error):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b")
        platform.failures["start_work_requirement_by_id"] = error
        with pytest.raises(ReportedFailure) as raised:
            _run(platform, START, [])
        assert classify(raised.value) in SESSION_FAILURES
        assert [r["outcome"] for r in platform.records] == ["failed", "skipped"]
        assert platform.records[1]["error"].startswith("not attempted:")

    def test_follow_is_given_only_what_was_actioned(self, platform, monkeypatch):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b")
        work = platform.client.work_client

        def start(wr_id):
            if wr_id == WR_B:
                raise _http_error(500)
            platform.calls.append(("start_work_requirement_by_id", wr_id))

        work.start_work_requirement_by_id.side_effect = start
        _run(platform, START, [], follow=True)
        shc_module.follow_ids.assert_called_once_with(ANY, [WR_A])


# ---------------------------------------------------------------------------
# Explicit names and IDs
# ---------------------------------------------------------------------------


class TestExplicit:
    def test_an_id_in_another_namespace_is_found(self, platform, monkeypatch):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b", namespace="elsewhere")
        _run(platform, START, [WR_B])
        assert platform.calls == [("start_work_requirement_by_id", WR_B)]
        assert platform.searches == []  # fetched, not looked for

    def test_a_name_is_searched_for_not_listed(self, platform, monkeypatch):
        _run(platform, START, ["wr-a"])
        assert platform.searches == [{"name": "wr-a", "namespace": "ns", "tag": None}]
        assert platform.calls == [("start_work_requirement_by_id", WR_A)]

    def test_a_namespaced_name(self, platform, monkeypatch):
        platform.wrs[WR_B] = _wr(WR_B, "wr-a", namespace="other")
        _run(platform, START, ["other/wr-a"])
        assert platform.calls == [("start_work_requirement_by_id", WR_B)]

    def test_a_partial_name_is_not_a_match(self, platform, monkeypatch):
        _run(platform, START, ["wr"])
        assert platform.calls == []
        assert platform.records[0]["outcome"] == "failed"

    def test_a_reused_name_prefers_the_one_in_the_required_state(
        self, platform, monkeypatch
    ):
        platform.wrs = {
            WR_OLD: _wr(WR_OLD, "wr-a", COMPLETED),
            WR_A: _wr(WR_A, "wr-a", HELD),
        }
        _run(platform, START, ["wr-a"])
        assert platform.calls == [("start_work_requirement_by_id", WR_A)]

    def test_two_in_the_required_state_are_ambiguous(self, platform, monkeypatch):
        platform.wrs[WR_B] = _wr(WR_B, "wr-a")
        _run(platform, START, ["wr-a"])
        assert platform.calls == []
        assert platform.records[0]["outcome"] == "failed"
        assert "please supply the ID" in platform.records[0]["error"]

    @pytest.mark.parametrize("target", [WR_A, "wr-a"])
    def test_the_wrong_state_is_skipped_saying_which(
        self, platform, monkeypatch, target
    ):
        _run(platform, HOLD, [target])  # wr-a is HELD
        assert platform.calls == []
        assert _outcomes(platform) == [(WR_A, "skipped")]
        assert "is HELD, not RUNNING" in platform.records[0]["error"]

    @pytest.mark.parametrize("target", [WR_B, "nope", TASK])
    def test_not_found_or_not_a_wr_fails(self, platform, monkeypatch, target):
        _run(platform, START, [target])
        assert platform.calls == []
        assert platform.records[0]["outcome"] == "failed"

    def test_in_the_order_given_without_duplicates(self, platform, monkeypatch):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b")
        _run(platform, START, ["wr-b", WR_A, "wr-a", "wr-b"])
        assert platform.calls == [
            ("start_work_requirement_by_id", WR_B),
            ("start_work_requirement_by_id", WR_A),
        ]

    def test_one_confirmation_names_them_all(self, platform, monkeypatch):
        prompts = []
        monkeypatch.setattr(
            action_runner, "confirmed", lambda message: prompts.append(message) or True
        )
        platform.wrs[WR_B] = _wr(WR_B, "wr-b")
        _run(platform, START, [WR_A, "wr-b"])
        assert prompts == ["Start 2 Work Requirement(s) ('ns/wr-a', 'ns/wr-b')?"]

    def test_declining_skips_everything(self, platform, monkeypatch):
        monkeypatch.setattr(action_runner, "confirmed", lambda message: False)
        _run(platform, START, [WR_A])
        assert platform.calls == []
        assert _outcomes(platform) == [(WR_A, "skipped")]

    def test_a_session_failure_while_resolving_stops(self, platform, monkeypatch):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b")
        platform.failures["search"] = _http_error(401)
        with pytest.raises(ReportedFailure) as raised:
            _run(platform, START, [WR_A, "wr-b", WR_B])
        assert classify(raised.value) in SESSION_FAILURES
        assert platform.calls == []
        assert _outcomes(platform) == [
            (None, "failed"),  # 'wr-b', by name
            (WR_A, "skipped"),  # resolved, not attempted
            (WR_B, "skipped"),  # not resolved
        ]

    def test_a_session_failure_while_acting_stops(self, platform, monkeypatch):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b")
        platform.failures["start_work_requirement_by_id"] = _http_error(401)
        with pytest.raises(ReportedFailure) as raised:
            _run(platform, START, [WR_A, WR_B])
        assert classify(raised.value) in SESSION_FAILURES
        assert [r["outcome"] for r in platform.records] == ["failed", "skipped"]


# ---------------------------------------------------------------------------
# Finishing: yd-finish
# ---------------------------------------------------------------------------


class TestFinish:
    def test_running_and_held_ones_are_finished_finishing_ones_left_out(
        self, platform, monkeypatch
    ):
        platform.wrs = {
            WR_A: _wr(WR_A, "wr-a", RUNNING),
            WR_B: _wr(WR_B, "wr-b", HELD),
            WR_OLD: _wr(WR_OLD, "wr-c", FINISHING),
        }
        _run(platform, FINISH, [], follow=True)
        assert platform.calls == [
            ("finish_work_requirement_by_id", WR_A),
            ("finish_work_requirement_by_id", WR_B),
        ]
        assert [r["outcome"] for r in platform.records] == ["finished", "finished"]
        # Only those this run finished are followed
        shc_module.follow_ids.assert_called_once_with(ANY, [WR_A, WR_B])

    def test_a_glob(self, platform, monkeypatch):
        platform.wrs = {
            WR_A: _wr(WR_A, "proj-1", RUNNING),
            WR_B: _wr(WR_B, "proj-2", FINISHING),
        }
        _run(platform, FINISH, ["proj-*"])
        assert platform.calls == [("finish_work_requirement_by_id", WR_A)]

    def test_a_finishing_one_named_is_skipped_and_not_followed(
        self, platform, monkeypatch
    ):
        platform.wrs[WR_A] = _wr(WR_A, "wr-a", FINISHING)
        _run(platform, FINISH, ["wr-a"], follow=True)
        assert platform.calls == []
        assert platform.records[0]["outcome"] == "skipped"
        assert "is FINISHING, not RUNNING or HELD" in platform.records[0]["error"]
        shc_module.follow_ids.assert_not_called()

    def test_a_name_shared_with_a_cancelling_one_is_not_ambiguous(
        self, platform, monkeypatch
    ):
        platform.wrs = {
            WR_OLD: _wr(WR_OLD, "wr-a", CANCELLING),
            WR_A: _wr(WR_A, "wr-a", RUNNING),
        }
        _run(platform, FINISH, ["wr-a"])
        assert platform.calls == [("finish_work_requirement_by_id", WR_A)]

    def test_a_running_and_a_held_one_of_a_name_are_ambiguous(
        self, platform, monkeypatch
    ):
        platform.wrs = {WR_A: _wr(WR_A, "wr-a", RUNNING), WR_B: _wr(WR_B, "wr-a")}
        _run(platform, FINISH, ["wr-a"])
        assert platform.calls == []
        assert "please supply the ID" in platform.records[0]["error"]

    def test_the_command_is_the_action(self, monkeypatch):
        import yellowdog_cli.finish as yd_finish

        apply = MagicMock()
        monkeypatch.setattr(shc_module, "apply_work_requirement_action", apply)
        monkeypatch.setattr(
            "yellowdog_cli.utils.wrapper.ARGS_PARSER",
            MagicMock(debug=True, print_pid=True),
        )
        with pytest.raises(SystemExit):
            yd_finish.main()
        (ctx, action), _ = apply.call_args
        assert isinstance(ctx, RunContext) and action == FINISH


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["yd-start", "yd-hold", "yd-finish"])
def test_globs_and_explicit_names_do_not_mix(command):
    assert check_glob_and_literal_names in COMMANDS[command].validators
