"""
The work helpers, offline, over canned 'yd' answers.
"""

import json

import pytest
from harness import work
from harness.compute import ComputeTimeout
from live_fake_yd import FakeYd, result

NS, RUN, WR = "ns", "ydst-2610130811-ab12", "ydid:workreq:1"


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _timing() -> dict:
    clock = Clock()
    return {"clock": clock, "sleep": clock.sleep, "poll_seconds": 60}


def test_submit_passes_the_variables_and_returns_the_record():
    yd = FakeYd(lambda args: result(args, document={"id": WR}))
    assert work.submit(yd, "work-wr.jsonnet", "--follow", wr="life", seconds="10") == {
        "id": WR
    }
    (call,) = yd.calls
    assert call[:3] == ("wr", "submit", str(work.SPECS / "work-wr.jsonnet"))
    assert ("--variable", "wr=life") == call[3:5]
    assert "--follow" in call and call[-2:] == ("--json", "--quiet")


def test_tasks_are_those_of_the_work_requirements_task_groups():
    def respond(args):
        if args[:2] == ("wr", "show"):
            return result(
                args, document={"taskGroups": [{"id": "tg-1"}, {"id": "tg-2"}]}
            )
        return result(
            args,
            document=[
                {"id": "t-1", "taskGroupId": "tg-1", "status": "EXECUTING"},
                {"id": "t-2", "taskGroupId": "tg-9", "status": "EXECUTING"},
                {"id": "t-3", "taskGroupId": "tg-2", "status": "READY"},
            ],
        )

    assert [t["id"] for t in work.tasks_of(FakeYd(respond), NS, RUN, WR)] == [
        "t-1",
        "t-3",
    ]


def test_waiting_for_a_task_status_names_what_it_saw():
    def respond(args):
        if args[:2] == ("wr", "show"):
            return result(args, document={"taskGroups": [{"id": "tg-1"}]})
        return result(
            args, document=[{"id": "t-1", "taskGroupId": "tg-1", "status": "READY"}]
        )

    with pytest.raises(ComputeTimeout, match="READY"):
        work.wait_for_task(FakeYd(respond), NS, RUN, WR, "EXECUTING", 1, **_timing())


def test_waiting_for_a_status_returns_the_one_reached():
    states = iter(["RUNNING", "COMPLETED"])
    yd = FakeYd(lambda args: result(args, document={"status": next(states)}))
    assert work.wait_for_status(yd, WR, work.TERMINAL, 5, **_timing()) == "COMPLETED"


def test_follow_events_are_read_as_indented_documents():
    # The CLI prints each event as an indented JSON document of its own
    # (docs/json-output.md), so a document spans lines
    first = {"status": "RUNNING", "taskGroups": [{"name": "first"}]}
    second = {"status": "COMPLETED"}
    stdout = json.dumps(first, indent=2) + "\n" + json.dumps(second, indent=2) + "\n"
    assert work.follow_events(stdout) == [first, second]


def test_follow_events_of_nothing_are_none():
    assert work.follow_events("\n  \n") == []


def test_cancel_all_ignores_what_is_already_finished():
    codes = iter([6, 0])
    yd = FakeYd(lambda args: result(args, exit_code=next(codes), document=[]))
    work.cancel_all(yd, ["a", "b"])
    assert [c[:3] for c in yd.calls] == [("wr", "cancel", "--abort")] * 2


def test_follow_alongside_returns_the_follow_and_fails_when_it_overruns():
    import threading
    import time

    started = threading.Event()

    def respond(args):
        started.set()
        if "slow" in args:
            time.sleep(2)
        return result(args, document={"status": "TERMINATED"})

    yd = FakeYd(respond)
    done = work.follow_alongside(yd, ("cr", "follow", "x"), lambda: started.wait(1), 5)
    assert done.document == {"status": "TERMINATED"}
    with pytest.raises(ComputeTimeout, match="cr follow slow"):
        work.follow_alongside(yd, ("cr", "follow", "slow"), lambda: None, 0.2)


def test_follow_alongside_raises_a_failing_action_without_waiting_for_the_follow():
    import time

    def respond(args):
        time.sleep(3)
        return result(args, document={"status": "TERMINATED"})

    def action():
        raise RuntimeError("the shutdown failed")

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="the shutdown failed"):
        work.follow_alongside(FakeYd(respond), ("wp", "follow", "x"), action, 60)
    assert time.monotonic() - started < 2


def test_a_follow_that_ended_at_a_terminal_status_passes():
    work.ended_with([{"status": "RUNNING"}, {"status": "COMPLETED"}], {"COMPLETED"})


@pytest.mark.parametrize(
    ("events", "message"),
    [
        ([], "no events"),
        ([{"status": "RUNNING"}, {}], "no status"),
        ([{"status": "COMPLETED"}, {"status": "RUNNING"}], "ended at RUNNING"),
    ],
)
def test_a_follow_that_did_not_reach_the_end_fails(events, message):
    with pytest.raises(AssertionError, match=message):
        work.ended_with(events, {"COMPLETED"})


def test_cancelled_after_cancels_what_was_made_when_the_scenario_passes():
    yd = FakeYd(lambda args: result(args, document=[]))
    with work.cancelled_after(yd) as made:
        made.append("a")
    assert yd.calls and yd.calls[0][-1] == "a"


def test_a_failing_clean_up_fails_a_scenario_that_passed():
    def cleanup():
        raise RuntimeError("cancel failed")

    with pytest.raises(RuntimeError, match="cancel failed"):
        with work.cleaned_up(cleanup):
            pass


def test_a_failing_clean_up_never_hides_the_scenarios_failure():
    def cleanup():
        raise RuntimeError("cancel failed")

    with pytest.warns(work.CleanupFailedWarning, match="cancel failed"):
        with pytest.raises(AssertionError, match="the scenario's own"):
            with work.cleaned_up(cleanup):
                raise AssertionError("the scenario's own")


def test_every_node_verb_is_called_with_json_and_its_outcome_checked():
    yd = FakeYd(lambda args: result(args, document=[{"outcome": "terminated"}]))
    for verb in ("restart", "deprovision", "terminate", "shutdown"):
        assert work.act_on_node(yd, verb, "n-1") == [{"outcome": "terminated"}]
    assert all(c[:2][0] == "node" and "--json" in c for c in yd.calls)


@pytest.mark.parametrize(
    "records", [[], [{"outcome": "skipped"}], [{"outcome": "failed"}]]
)
def test_a_node_verb_that_did_nothing_fails(records):
    yd = FakeYd(lambda args: result(args, document=records))
    with pytest.raises(AssertionError):
        work.act_on_node(yd, "terminate", "n-1")
