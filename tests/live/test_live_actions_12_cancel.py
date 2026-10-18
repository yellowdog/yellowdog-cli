"""
Live: cancelling a Work Requirement whose Tasks wait (on a Worker tag no
Worker has), and one whose Tasks run, with --abort.
"""

import pytest
from harness import work

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-actions")]

_ACT = ("--yes", "--json", "--quiet")


def test_a_waiting_work_requirement_is_cancelled(live_run):
    run, yd = live_run.run, live_run.yd
    minutes = run.config.run["provision_timeout_minutes"]
    made: list[str] = []
    try:
        wr = work.submit(
            yd,
            "work-wr.jsonnet",
            wr="cancel-waiting",
            worker_tag=run.name("nobody"),
            seconds="10",
        )
        made.append(wr["id"])
        records = yd("wr", "cancel", wr["id"], *_ACT).records
        assert records and all(r.get("outcome") != "failed" for r in records), records
        assert work.wait_for_status(yd, wr["id"], work.TERMINAL, minutes) == "CANCELLED"
    finally:
        work.cancel_all(yd, made)


def test_a_running_work_requirement_is_cancelled_with_its_tasks_aborted(
    live_run, actions_pool
):
    run, yd = live_run.run, live_run.yd
    minutes = run.config.run["provision_timeout_minutes"]
    made: list[str] = []
    try:
        wr = work.submit(
            yd,
            "work-wr.jsonnet",
            wr="cancel-running",
            worker_tag=actions_pool.worker_tag,
            seconds="120",
        )
        made.append(wr["id"])
        work.wait_for_task(
            yd, run.namespace, run.run_id, wr["id"], "EXECUTING", minutes
        )
        yd("wr", "cancel", "--abort", wr["id"], *_ACT)
        assert work.wait_for_status(yd, wr["id"], work.TERMINAL, minutes) == "CANCELLED"
        statuses = {
            t["status"] for t in work.tasks_of(yd, run.namespace, run.run_id, wr["id"])
        }
        assert "ABORTED" in statuses, statuses
    finally:
        work.cancel_all(yd, made)
