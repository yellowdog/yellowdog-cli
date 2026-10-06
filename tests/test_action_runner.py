"""
utils/action_runner.py, the rules the action commands share: targets
resolved in the order given and each once; one that cannot be acted on
reported and recorded as failed or skipped; a session failure (here, a
connection error) stopping the run with the rest recorded as not attempted
and ReportedFailure raised with its cause; a declined confirmation recording
everything as skipped; a failed unit recorded and the next one done. And
main_wrapper's RunContext, given to a main() that takes one.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from requests import ConnectionError as RequestsConnectionError

from yellowdog_cli.utils import action_runner
from yellowdog_cli.utils.action_runner import (
    Item,
    SessionStop,
    Unit,
    Unresolved,
    by_type,
    carry_out,
    confirm_items,
    resolve_targets,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import ExitCode, ReportedFailure, classify


@pytest.fixture
def records():
    return []


@pytest.fixture
def record(records):
    def _record(entity, entity_type, outcome, error):
        records.append((entity, entity_type, outcome, error))

    return _record


@pytest.fixture(autouse=True)
def printed(monkeypatch):
    lines = []
    monkeypatch.setattr(action_runner, "print_error", lambda m: lines.append(m))
    monkeypatch.setattr(action_runner, "print_warning", lambda m: lines.append(m))
    return lines


def _item(name, entity_type="a"):
    return Item(name, entity_type, name, name)


def _resolve(target):
    if target == "missing":
        raise Unresolved("Cannot find missing")
    if target == "done":
        raise Unresolved("done is finished", "skipped", "done-entity")
    if target == "offline":
        raise RequestsConnectionError("no route")
    if target == "broken":
        raise RuntimeError("lookup failed")
    return _item(target, "b" if target.startswith("b") else "a")


def _resolve_all(targets, record):
    return resolve_targets(
        targets,
        resolve=_resolve,
        describe=lambda target: (target, "a"),
        record=record,
        verb="act on",
        order=by_type("a", "b"),
    )


class TestResolve:
    def test_each_once_grouped_by_type_in_the_order_given(self, record):
        items = _resolve_all(["b1", "x", "b2", "y", "x"], record)
        assert [item.key for item in items] == ["x", "y", "b1", "b2"]

    def test_what_cannot_be_acted_on_is_recorded_and_left_out(
        self, record, records, printed
    ):
        items = _resolve_all(["missing", "x", "done", "broken"], record)
        assert [item.key for item in items] == ["x"]
        assert records == [
            ("missing", "a", "failed", "Cannot find missing"),
            ("done-entity", "a", "skipped", "done is finished"),
            ("broken", "a", "failed", "lookup failed"),
        ]
        assert "Unable to act on 'broken': lookup failed" in printed

    def test_a_session_failure_stops_and_records_the_rest(
        self, record, records, printed
    ):
        with pytest.raises(ReportedFailure) as raised:
            _resolve_all(["b1", "x", "offline", "y"], record)
        assert classify(raised.value) == ExitCode.CONNECTION
        assert [(r[0], r[2]) for r in records] == [
            ("offline", "failed"),
            ("x", "skipped"),  # resolved, in their order
            ("b1", "skipped"),
            ("y", "skipped"),  # not yet resolved
        ]
        assert records[1][3] == "not attempted: no route"
        assert any("remaining 3 item(s)" in line for line in printed)


class TestConfirm:
    def test_declining_records_everything_as_skipped(
        self, monkeypatch, record, records
    ):
        monkeypatch.setattr(action_runner, "confirmed", lambda question: False)
        items = [_item("x"), _item("b1", "b")]
        assert not confirm_items("Act?", items, record)
        assert records == [("x", "a", "skipped", None), ("b1", "b", "skipped", None)]

    def test_confirming_records_nothing(self, monkeypatch, record, records):
        monkeypatch.setattr(action_runner, "confirmed", lambda question: True)
        assert confirm_items("Act?", [_item("x")], record)
        assert records == []


def _unit(name, act):
    return Unit([_item(name)], act=act, failure=lambda e: f"Failed on {name}: {e}")


def _fail(error):
    def act():
        raise error

    return act


class TestCarryOut:
    def test_a_failed_unit_is_recorded_and_the_next_done(
        self, record, records, printed
    ):
        done = carry_out(
            [
                _unit("x", _fail(RuntimeError("boom"))),
                _unit("y", lambda: None),
            ],
            record,
        )
        assert [unit.items[0].key for unit in done] == ["y"]
        assert records == [("x", "a", "failed", "boom")]
        assert printed == ["Failed on x: boom"]

    def test_a_session_failure_stops_the_run(self, record, records):
        act = MagicMock()
        with pytest.raises(ReportedFailure) as raised:
            carry_out(
                [
                    _unit("x", _fail(RequestsConnectionError("no route"))),
                    _unit("y", act),
                    _unit("z", act),
                ],
                record,
            )
        act.assert_not_called()
        assert classify(raised.value) == ExitCode.CONNECTION
        assert [(r[0], r[2]) for r in records] == [
            ("x", "failed"),
            ("y", "skipped"),
            ("z", "skipped"),
        ]

    def test_a_unit_that_recorded_its_own_failure_stops_by_session_stop(
        self, record, records
    ):
        cause = RequestsConnectionError("no route")
        with pytest.raises(ReportedFailure) as raised:
            carry_out(
                [_unit("x", _fail(SessionStop(cause))), _unit("y", lambda: None)],
                record,
            )
        assert classify(raised.value) == ExitCode.CONNECTION
        # The unit's own failure is its to record; only the rest are recorded
        assert records == [("y", "a", "skipped", "not attempted: no route")]


def test_main_wrapper_gives_main_a_run_context(monkeypatch):
    from yellowdog_cli.utils import wrapper

    args = MagicMock(debug=False, print_pid=False, json_output=None, quiet=False)
    config = SimpleNamespace(namespace="ns", name_tag="t", url="https://u")
    client = MagicMock()
    monkeypatch.setattr(wrapper, "ARGS_PARSER", args)
    monkeypatch.setattr(wrapper, "CONFIG_COMMON", config)
    monkeypatch.setattr(wrapper, "CLIENT", client)
    monkeypatch.setattr(wrapper, "set_proxy", lambda: None)
    given = []

    @wrapper.main_wrapper
    def main(ctx: RunContext):
        given.append(ctx)

    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 0
    assert given == [RunContext(args, config, client)]  # type: ignore[arg-type]
