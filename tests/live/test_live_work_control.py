"""
Live: a Work Requirement's state changed with no compute. Each test submits
its own pending Work Requirement (specs/stuck-wr.jsonnet: one Task for
Workers nothing has) and acts on it by ID, never by the run's tag, which the
other modules' work carries too: held, started and cancelled; finished. The
actions pool's lifecycle does the same on running work, and needs a full
run; these take seconds.
"""

import pytest
from harness import work

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-work-control")]

_ACT = ("--yes", "--json", "--quiet")
_MINUTES = 2  # The Platform changes a pending Work Requirement's state at once


def _submitted(live_run, wr: str) -> str:
    return work.submit(live_run.yd, "stuck-wr.jsonnet", wr=wr)["id"]


def _outcome(yd, verb: str, wr_id: str) -> str:
    (record,) = yd("wr", verb, wr_id, *_ACT).records
    assert record["id"] == wr_id, record
    return record["outcome"]


def test_a_pending_work_requirement_is_held_started_and_cancelled(live_run):
    yd = live_run.yd
    wr_id = _submitted(live_run, "control-hold")
    try:
        assert _outcome(yd, "hold", wr_id) == "held"
        assert work.wait_for_status(yd, wr_id, frozenset({"HELD"}), _MINUTES) == "HELD"

        assert _outcome(yd, "start", wr_id) == "started"
        work.wait_for_status(yd, wr_id, frozenset({"PENDING", "RUNNING"}), _MINUTES)

        assert _outcome(yd, "cancel", wr_id) == "cancelled"
        work.wait_for_status(
            yd, wr_id, frozenset({"CANCELLING", "CANCELLED"}), _MINUTES
        )
    finally:
        work.cancel_all(yd, [wr_id])


def test_a_pending_work_requirement_is_finished(live_run):
    yd = live_run.yd
    wr_id = _submitted(live_run, "control-finish")
    try:
        assert _outcome(yd, "finish", wr_id) == "finished"
        # With no Task ever run, it leaves the active states at once
        work.wait_for_status(
            yd, wr_id, frozenset({"FINISHING", "COMPLETING", "COMPLETED"}), _MINUTES
        )
    finally:
        work.cancel_all(yd, [wr_id])
