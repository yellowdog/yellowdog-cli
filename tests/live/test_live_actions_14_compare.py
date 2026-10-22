"""
Live: a Work Requirement and its Task Group compared with the actions pool,
which matches; the run's Work Requirements, Task Groups and Tasks listed
and shown; and the comparisons and the shows again by name ('wr', 'wr/tg',
'wr/tg/task', the pool's name), each finding what its ID found.
"""

import pytest
from harness import work

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-actions")]

_SCOPE = ("--json", "--quiet")


def test_compare_and_read(live_run, actions_pool):
    run, yd = live_run.run, live_run.yd
    minutes = run.config.run["provision_timeout_minutes"]
    selection = ("--namespace", run.namespace, "--tag", run.run_id)
    with work.cancelled_after(yd) as made:
        wr = work.submit(
            yd,
            "work-wr.jsonnet",
            wr="compare",
            worker_tag=actions_pool.worker_tag,
            seconds="10",
        )
        made.append(wr["id"])
        work.wait_for_status(yd, wr["id"], work.TERMINAL, minutes)

        records = yd("wr", "compare", wr["id"], actions_pool.pool_id, *_SCOPE).records
        assert records and all(r["workerPoolMatch"] == "YES" for r in records), records
        group_id = work.work_requirement(yd, wr["id"])["taskGroups"][0]["id"]
        (record,) = yd("tg", "compare", group_id, actions_pool.pool_id, *_SCOPE).records
        assert record["workerPoolMatch"] == "YES", record

        listed = yd("wr", "list", *selection, *_SCOPE).records
        assert wr["id"] in {r["id"] for r in listed}
        groups = yd("tg", "list", *selection, *_SCOPE).records
        assert group_id in {g["id"] for g in groups}
        assert yd("tg", "show", group_id, "--quiet").document["id"] == group_id
        tasks = work.tasks_of(yd, run.namespace, run.run_id, wr["id"])
        assert len(tasks) == 4
        assert (
            yd("task", "show", tasks[0]["id"], "--quiet").document["id"]
            == tasks[0]["id"]
        )

        # By name, in the configured namespace
        wr_name = work.work_requirement(yd, wr["id"])["name"]
        group = (
            f"{wr_name}/{work.work_requirement(yd, wr['id'])['taskGroups'][0]['name']}"
        )
        pool = run.actions_pool_name()
        by_name = yd("wr", "compare", wr_name, pool, *_SCOPE).records
        assert by_name and all(r["workerPoolMatch"] == "YES" for r in by_name), by_name
        (record,) = yd("tg", "compare", group, pool, *_SCOPE).records
        assert record["workerPoolMatch"] == "YES", record
        assert yd("tg", "show", group, "--quiet").document["id"] == group_id
        task = f"{group}/{tasks[0]['name']}"
        assert yd("task", "show", task, "--quiet").document["id"] == tasks[0]["id"]
