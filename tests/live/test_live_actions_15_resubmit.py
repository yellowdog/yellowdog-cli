"""
Live: a Work Requirement with failing and completing Tasks, run on the
actions pool, resubmitted ('yd wr resubmit'): the new Work Requirement holds
exactly the failed Tasks, each matching its original in the fields a copy
keeps.
"""

import pytest
from harness import work

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-actions")]

_ACT = ("--yes", "--json", "--quiet")
_COPIED = ("name", "taskType", "arguments", "environment", "timeout", "taskData")
_FAILING = {"bad-1", "bad-2", "bad-3"}


def _tasks_by_name(yd, namespace, run_id, wr_id) -> dict[str, dict]:
    """
    The Work Requirement's Tasks in full, by Task Group and name, as
    'yd show' reads them.
    """
    tasks = work.tasks_of(yd, namespace, run_id, wr_id)
    groups = {
        g["id"]: g["name"] for g in work.work_requirement(yd, wr_id)["taskGroups"]
    }
    return {
        f"{groups[task['taskGroupId']]}/{task['name']}": yd(
            "show", task["id"], "--quiet"
        ).document
        for task in tasks
    }


def test_the_failed_tasks_are_resubmitted_as_a_new_work_requirement(
    live_run, actions_pool
):
    run, yd = live_run.run, live_run.yd
    minutes = run.config.run["provision_timeout_minutes"]
    with work.cancelled_after(yd) as made:
        original = work.submit(
            yd,
            "resubmit-wr.jsonnet",
            wr="resubmit",
            worker_tag=actions_pool.worker_tag,
        )
        made.append(original["id"])
        # The Tasks end, three of them FAILED; the Work Requirement is then
        # finished, to a terminal state
        work.wait_for_task(
            yd, run.namespace, run.run_id, original["id"], "FAILED", minutes
        )
        yd("wr", "finish", original["id"], *_ACT)
        work.wait_for_status(yd, original["id"], work.TERMINAL, minutes)
        before = _tasks_by_name(yd, run.namespace, run.run_id, original["id"])
        failed = {key for key, task in before.items() if task["status"] == "FAILED"}
        assert {key.split("/")[1] for key in failed} == _FAILING, before

        (resubmitted,) = yd(
            "wr", "resubmit", original["id"], "--json", "--quiet"
        ).records
        made.append(resubmitted["id"])
        assert resubmitted["name"] == f"{original['name']}-resubmit-1", resubmitted

        after = _tasks_by_name(yd, run.namespace, run.run_id, resubmitted["id"])
        assert set(after) == failed, after
        for key in failed:
            for field in _COPIED:
                assert before[key].get(field), (key, field, before[key])
                assert after[key].get(field) == before[key].get(field), (key, field)
        # The original is as it was
        unchanged = _tasks_by_name(yd, run.namespace, run.run_id, original["id"])
        assert {k: t["status"] for k, t in unchanged.items()} == {
            k: t["status"] for k, t in before.items()
        }
