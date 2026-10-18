"""
Live: following a Work Requirement's events as JSON (yd wr follow, yd
follow), waiting for it (yd wr wait, yd wait), and a failing one: 'yd wr
submit -E' exits 1, and waiting for it records it as not succeeded.
"""

import pytest
from harness import work

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-actions")]


def test_following_and_waiting_for_a_completed_work_requirement(live_run, actions_pool):
    run, yd = live_run.run, live_run.yd
    minutes = run.config.run["provision_timeout_minutes"]
    made: list[str] = []
    try:
        wr = work.submit(
            yd,
            "work-wr.jsonnet",
            wr="follow",
            worker_tag=actions_pool.worker_tag,
            seconds="20",
        )
        made.append(wr["id"])
        followed = yd(
            "wr", "follow", wr["id"], "--json", "--quiet", timeout=minutes * 60
        )
        events = work.follow_events(followed.stdout)
        assert events, "no events"
        assert work.work_requirement(yd, wr["id"])["status"] == "COMPLETED"
        again = yd("follow", wr["id"], "--json", "--quiet", timeout=minutes * 60)
        work.follow_events(again.stdout)  # parses, whatever it holds for a finished one
        for words in (("wr", "wait"), ("wait",)):
            (record,) = yd(*words, wr["id"], "--json", "--quiet").records
            assert record["succeeded"] is True and record["status"] == "COMPLETED", (
                record
            )
    finally:
        work.cancel_all(yd, made)


def test_a_failing_work_requirement_exits_1_and_waits_as_failed(live_run, actions_pool):
    run, yd = live_run.run, live_run.yd
    made: list[str] = []
    try:
        submitted = yd(
            "wr",
            "submit",
            str(work.SPECS / "work-wr.jsonnet"),
            "--variable",
            "wr=failing",
            "--variable",
            f"worker_tag={actions_pool.worker_tag}",
            "--variable",
            "seconds=5",
            "--variable",
            "exit_code=1",
            "--follow",
            "--exit-on-failure",
            "--json",
            "--quiet",
            check=False,
            timeout=run.config.run["provision_timeout_minutes"] * 60,
        )
        if submitted.document:
            made.append(submitted.document["id"])
        assert submitted.exit_code == 1, yd.describe(submitted)
        waited = yd("wr", "wait", made[0], "--json", "--quiet", ok=(1,))
        (record,) = waited.records
        assert record["succeeded"] is False and record["status"] == "FAILED", record
    finally:
        work.cancel_all(yd, made)
