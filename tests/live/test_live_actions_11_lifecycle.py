"""
Live: a Work Requirement held, started, reprioritized (and a Task Group),
one running Task aborted, a Task Group added, and the Work Requirement
finished, its running Tasks completing.
"""

import pytest
from harness import work

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-actions")]

_ACT = ("--yes", "--json", "--quiet")


def test_the_lifecycle(live_run, actions_pool):
    run, yd = live_run.run, live_run.yd
    minutes = run.config.run["provision_timeout_minutes"]
    with work.cancelled_after(yd) as made:
        wr = work.submit(
            yd,
            "work-wr.jsonnet",
            wr="lifecycle",
            worker_tag=actions_pool.worker_tag,
            seconds="120",
        )
        wr_id = wr["id"]
        made.append(wr_id)

        yd("wr", "hold", wr_id, *_ACT)
        assert work.wait_for_status(yd, wr_id, frozenset({"HELD"}), minutes) == "HELD"
        yd("wr", "start", wr_id, *_ACT)
        assert (
            work.wait_for_status(yd, wr_id, frozenset({"RUNNING"}), minutes)
            == "RUNNING"
        )

        (record,) = yd("wr", "priority", "10", wr_id, *_ACT).records
        assert record["priority"] == 10 and "previousPriority" in record
        (record,) = yd(
            "tg",
            "priority",
            "5",
            f"{wr['name']}/first",
            "--namespace",
            run.namespace,
            *_ACT,
        ).records
        assert record["priority"] == 5 and "previousPriority" in record

        executing = work.wait_for_task(
            yd, run.namespace, run.run_id, wr_id, "EXECUTING", minutes
        )
        yd("task", "abort", executing["id"], *_ACT)
        aborted = work.wait_for_task(
            yd, run.namespace, run.run_id, wr_id, "ABORTED", minutes
        )
        assert aborted["id"] == executing["id"]

        yd(
            "wr",
            "submit",
            str(work.SPECS / "add-wr.jsonnet"),
            "--add-to",
            wr_id,
            "--variable",
            f"worker_tag={actions_pool.worker_tag}",
            "--variable",
            "seconds=10",
            "--json",
            "--quiet",
        )
        yd("wr", "finish", wr_id, *_ACT)
        status = work.wait_for_status(yd, wr_id, work.TERMINAL, minutes)
        shown = work.work_requirement(yd, wr_id)
        groups = {g["name"]: g for g in shown["taskGroups"]}
        assert set(groups) == {"first", "second", "third"}
        assert groups["third"]["status"] == "COMPLETED", groups["third"]
        assert status == "COMPLETED", shown
