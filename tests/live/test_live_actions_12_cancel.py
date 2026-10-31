"""
Live: cancelling a Work Requirement whose Tasks wait (on a Worker tag no
Worker has), and one whose Tasks run, with --abort; and waiting Tasks
cancelled alone ('yd task cancel'), by 'wr/tg/task' and by a pattern.
"""

import pytest
from harness import work
from harness.compute import wait_for

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-actions")]

_ACT = ("--yes", "--json", "--quiet")


def test_a_waiting_work_requirement_is_cancelled(live_run):
    run, yd = live_run.run, live_run.yd
    minutes = run.config.run["provision_timeout_minutes"]
    with work.cancelled_after(yd) as made:
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


def test_a_running_work_requirement_is_cancelled_with_its_tasks_aborted(
    live_run, actions_pool
):
    run, yd = live_run.run, live_run.yd
    minutes = run.config.run["provision_timeout_minutes"]
    with work.cancelled_after(yd) as made:
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


def test_waiting_tasks_are_cancelled_by_name_and_by_pattern(live_run):
    run, yd = live_run.run, live_run.yd
    minutes = run.config.run["provision_timeout_minutes"]
    with work.cancelled_after(yd) as made:
        wr = work.submit(
            yd,
            "work-wr.jsonnet",
            wr="cancel-tasks",
            worker_tag=run.name("nobody"),
            seconds="10",
        )
        made.append(wr["id"])
        name = wr["name"]
        # One Task by its name, and a Task Group's by a pattern
        records = yd(
            "task",
            "cancel",
            f"{name}/first/first-1",
            f"{name}/second/second-*",
            "--namespace",
            run.namespace,
            *_ACT,
        ).records
        assert sorted(r.get("name") for r in records) == [
            "first-1",
            "second-1",
            "second-2",
        ], records
        assert all(r.get("outcome") == "cancelled" for r in records), records
        cancelled = {r["id"] for r in records}

        def probe() -> tuple[bool, str]:
            tasks = work.tasks_of(yd, run.namespace, run.run_id, wr["id"])
            statuses = {t["id"]: t.get("status") for t in tasks}
            done = all(statuses.get(task_id) == "CANCELLED" for task_id in cancelled)
            return done, ", ".join(f"{t.get('name')}={t.get('status')}" for t in tasks)

        wait_for("the Tasks named CANCELLED", probe, minutes)
        # The Task not named is left alone, and its Work Requirement runs on
        (left,) = [
            t
            for t in work.tasks_of(yd, run.namespace, run.run_id, wr["id"])
            if t["id"] not in cancelled
        ]
        assert left["name"] == "first-2" and left["status"] != "CANCELLED", left
        assert work.work_requirement(yd, wr["id"])["status"] != "CANCELLED"
