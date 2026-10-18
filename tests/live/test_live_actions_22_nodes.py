"""
Live: the actions pool resized from 2 to 3 nodes; its Nodes and Workers
listed and shown; node actions run and read back; one Node shut down, one
deprovisioned and one terminated. (Not restarted: a Worker Pool takes a
restarted node's instance away, so 'yd node restart' is in NOT_EXERCISED.)
"""

import pytest
from harness import compute, work
from harness.run import SPECS

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-actions")]

_ACT = ("--yes", "--json", "--quiet")
_GONE = frozenset({"TERMINATED", compute.GONE})


def _running_nodes(yd, run, pool_id) -> list[dict]:
    return [
        n
        for n in compute.nodes(yd, run.namespace, run.run_id, pool_id)
        if n.get("status") == "RUNNING"
    ]


def test_resize_nodes_and_workers(live_run, actions_pool):
    run, yd = live_run.run, live_run.yd
    minutes = run.config.run["provision_timeout_minutes"]
    selection = ("--namespace", run.namespace, "--tag", run.run_id, "--json", "--quiet")

    # '--wait' applies to Compute Requirements only; the Workers are waited for
    yd("wp", "resize", actions_pool.pool_id, "3", *_ACT)
    compute.wait_for_workers(
        yd, run.namespace, run.run_id, actions_pool.pool_id, 6, minutes
    )
    nodes = _running_nodes(yd, run, actions_pool.pool_id)
    assert len(nodes) == 3, nodes

    assert actions_pool.pool_id in {
        p["id"] for p in yd("wp", "list", *selection).records
    }
    listed = {n["id"] for n in yd("node", "list", *selection).records}
    assert {n["id"] for n in nodes} <= listed
    assert (
        yd("node", "show", nodes[0]["id"], "--quiet").document["id"] == nodes[0]["id"]
    )
    workers = yd("worker", "list", *selection).records
    assert workers
    assert (
        yd("worker", "show", workers[0]["id"], "--quiet").document["id"]
        == workers[0]["id"]
    )

    yd(
        "node",
        "action",
        "--actions",
        str(SPECS / "node-actions.jsonnet"),
        "--worker-pool",
        run.actions_pool_name(),
        "--node",
        nodes[0]["id"],
        "--follow",
        "--timeout",
        str(minutes * 60),
        "--yes",
        "--json",
        "--quiet",
    )
    # '--follow' exits 0 whether or not the actions succeeded: read the queue
    queues = yd(
        "node",
        "action",
        "--status",
        "--worker-pool",
        run.actions_pool_name(),
        "--node",
        nodes[0]["id"],
        "--yes",
        "--json",
        "--quiet",
    ).records
    # The table shows nothing failed as '-' (live run ydst-2610131642-eb1j)
    assert queues and all(
        q.get("status") == "EMPTY" and q.get("failed") in (0, "-", None) for q in queues
    ), queues

    # Not 'node restart': a Worker Pool takes a restarted node's instance away,
    # as it does a stopped one (see harness/coverage.py's NOT_EXERCISED)
    shut_down, deprovisioned, terminated = nodes

    def instance_of(node: dict) -> str:
        return f"{actions_pool.cr_id}.{node['details']['instanceId']}"

    def deregistered() -> tuple[bool, str]:
        status = yd("node", "show", shut_down["id"], "--quiet").document.get("status")
        return status in {"DEREGISTERED", "TERMINATED"}, str(status)

    work.act_on_node(yd, "shutdown", shut_down["id"])
    compute.wait_for(f"{shut_down['id']} deregistered", deregistered, minutes)

    work.act_on_node(yd, "deprovision", deprovisioned["id"])
    compute.wait_for_instance(yd, instance_of(deprovisioned), _GONE, minutes)
    work.act_on_node(yd, "terminate", terminated["id"])
    compute.wait_for_instance(yd, instance_of(terminated), _GONE, minutes)
