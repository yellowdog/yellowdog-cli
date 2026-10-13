"""
Polling the run's compute through 'yd': a Worker Pool's Nodes and Workers,
a Compute Requirement's Instances, and their states. Every wait is bounded:
one that runs out raises ComputeTimeout naming what it last saw, and a wait
for a Worker to register carries the Compute Requirement's source report and
exhaustion, masked, since those say why nothing came up. A 'yd' failure while
polling is raised at once, not waited out.

An Instance is named 'cr_id.instance_id', as the commands acting on one take
it; 'yd list instances' gives that form only with '--ids-only', and the
statuses only with '--json', so both are read.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from harness.yd import Yd

NOT_FOUND = 6  # ExitCode.NOT_FOUND
POLL_SECONDS = 15
GONE = "GONE"  # An Instance the Platform no longer reports
_TRANSITIONAL = frozenset({"PENDING", "STOPPING", "TERMINATING"})
_ENDED_WORKERS = frozenset({"SHUTDOWN", "LOST"})


class ComputeTimeout(AssertionError):
    """
    A wait for compute ran out of time.
    """


def worker_pool(yd: Yd, pool_id: str) -> dict:
    return yd("wp", "show", pool_id, "--quiet").document


def compute_requirement(yd: Yd, cr_id: str) -> dict:
    return yd("cr", "show", cr_id, "--quiet").document


def instance_status(yd: Yd, instance: str) -> str:
    """
    An Instance's status, GONE when the Platform no longer has it.
    """
    shown = yd("instance", "show", instance, "--quiet", ok=(0, NOT_FOUND))
    if shown.exit_code == NOT_FOUND or shown.document is None:
        return GONE
    return shown.document.get("status") or "UNKNOWN"


def instances(yd: Yd, namespace: str, run_id: str, cr_id: str) -> dict[str, str]:
    """
    The Compute Requirement's Instances, as 'cr_id.instance_id' to status.
    """
    listing = (
        "list",
        "instances",
        "--namespace",
        namespace,
        "--tag",
        run_id,
        "--quiet",
    )
    names = yd(*listing, "--ids-only", ok=(0, NOT_FOUND)).stdout.split()
    statuses = {
        (record.get("id") or {}).get("instanceId"): record.get("status") or "UNKNOWN"
        for record in yd(*listing, "--json", ok=(0, NOT_FOUND)).records
    }
    return {
        name: statuses.get(name.split(".", 1)[1], "UNKNOWN")
        for name in names
        if name.startswith(f"{cr_id}.")
    }


def nodes(yd: Yd, namespace: str, run_id: str, pool_id: str) -> list[dict]:
    """
    The Worker Pool's Nodes; '--tag' selects the run's pools by name.
    """
    listed = yd(
        "list",
        "nodes",
        "--namespace",
        namespace,
        "--tag",
        run_id,
        "--json",
        "--quiet",
        ok=(0, NOT_FOUND),
    ).records
    return [node for node in listed if node.get("workerPoolId") == pool_id]


def diagnostics(yd: Yd, cr_id: str) -> str:
    """
    Why a Compute Requirement may not have come up: its source report and
    exhaustion, masked.
    """
    parts = []
    for option in ("--show-source-report", "--show-exhaustion"):
        shown = yd("cr", "show", cr_id, option, "--quiet", check=False)
        parts.append(f"--- yd cr show {option} ---\n{shown.stdout}{shown.stderr}")
    return yd.mask("\n".join(parts))


def wait_for(
    what: str,
    probe: Callable[[], tuple[bool, str]],
    timeout_minutes: float,
    *,
    diagnose: Callable[[], str] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    poll_seconds: float = POLL_SECONDS,
) -> None:
    """
    Poll until 'probe' holds, or raise ComputeTimeout with what it last saw
    (and 'diagnose''s text) when the time is up.
    """
    deadline = clock() + timeout_minutes * 60
    while True:
        done, seen = probe()
        if done:
            return
        if clock() >= deadline:
            detail = f"\n{diagnose()}" if diagnose is not None else ""
            raise ComputeTimeout(
                f"{what}: not reached after {timeout_minutes:g} minutes;"
                f" last seen: {seen}{detail}"
            )
        sleep(poll_seconds)


def wait_for_worker(
    yd: Yd,
    namespace: str,
    run_id: str,
    pool_id: str,
    timeout_minutes: float,
    *,
    instance_id: str | None = None,
    cr_id: str | None = None,
    excluding: frozenset[str] = frozenset(),
    **timing,
) -> None:
    """
    Wait for a RUNNING Node of the pool with a Worker that has not ended,
    on the named cloud instance when one is given, and not one of the
    Workers 'excluding' names (a restarted Node's Worker is a new one). With
    'cr_id', a timeout carries that Compute Requirement's diagnostics.
    """

    def probe() -> tuple[bool, str]:
        found = [
            node
            for node in nodes(yd, namespace, run_id, pool_id)
            if instance_id is None
            or (node.get("details") or {}).get("instanceId") == instance_id
        ]
        ready = [
            node
            for node in found
            if node.get("status") == "RUNNING"
            and any(
                worker.get("status") not in _ENDED_WORKERS
                and worker.get("id") not in excluding
                for worker in node.get("workers") or []
            )
        ]
        shown = ", ".join(
            f"{(n.get('details') or {}).get('instanceId')} {n.get('status')}"
            f" ({len(n.get('workers') or [])} Workers)"
            for n in found
        )
        return bool(ready), f"{len(found)} Nodes: {shown}" if found else "no Nodes"

    on = f" on {instance_id}" if instance_id else ""
    wait_for(
        f"a Worker of {pool_id}{on}",
        probe,
        timeout_minutes,
        diagnose=(lambda: diagnostics(yd, cr_id)) if cr_id else None,
        **timing,
    )


def wait_for_workers(
    yd: Yd,
    namespace: str,
    run_id: str,
    pool_id: str,
    count: int,
    timeout_minutes: float,
    *,
    cr_id: str | None = None,
    **timing,
) -> None:
    """
    Wait for at least 'count' Workers, not ended, on the pool's RUNNING
    Nodes; with 'cr_id', a timeout carries its diagnostics.
    """

    def probe() -> tuple[bool, str]:
        live = sum(
            1
            for node in nodes(yd, namespace, run_id, pool_id)
            if node.get("status") == "RUNNING"
            for worker in node.get("workers") or []
            if worker.get("status") not in _ENDED_WORKERS
        )
        return live >= count, f"{live} Workers"

    wait_for(
        f"{count} Workers of {pool_id}",
        probe,
        timeout_minutes,
        diagnose=(lambda: diagnostics(yd, cr_id)) if cr_id else None,
        **timing,
    )


def wait_for_instance(
    yd: Yd, instance: str, states: frozenset[str], timeout_minutes: float, **timing
) -> str:
    """
    Wait for an Instance to reach one of the states (GONE among them for one
    expected to leave); returns the state reached.
    """
    seen = {"status": "UNKNOWN"}

    def probe() -> tuple[bool, str]:
        seen["status"] = instance_status(yd, instance)
        return seen["status"] in states, seen["status"]

    wait_for(f"{instance} {'/'.join(sorted(states))}", probe, timeout_minutes, **timing)
    return seen["status"]


def wait_until_settled(
    yd: Yd, namespace: str, run_id: str, cr_id: str, timeout_minutes: float, **timing
) -> dict[str, str]:
    """
    Wait for the Compute Requirement to be RUNNING with as many RUNNING
    Instances as its target and none in transition; returns its Instances.
    """
    seen: dict = {"instances": {}}

    def probe() -> tuple[bool, str]:
        requirement = compute_requirement(yd, cr_id)
        current = instances(yd, namespace, run_id, cr_id)
        seen["instances"] = current
        running = sum(1 for status in current.values() if status == "RUNNING")
        target = requirement.get("targetInstanceCount")
        settled = (
            requirement.get("status") == "RUNNING"
            and running == target
            and not any(status in _TRANSITIONAL for status in current.values())
        )
        return settled, (
            f"{requirement.get('status')}, target {target}, Instances {current}"
        )

    wait_for(f"{cr_id} settled", probe, timeout_minutes, **timing)
    return seen["instances"]


def wait_for_requirement(
    yd: Yd, cr_id: str, statuses: frozenset[str], timeout_minutes: float, **timing
) -> str:
    """
    Wait for a Compute Requirement to reach one of the statuses; returns it.
    """
    seen = {"status": "UNKNOWN"}

    def probe() -> tuple[bool, str]:
        seen["status"] = compute_requirement(yd, cr_id).get("status") or "UNKNOWN"
        return seen["status"] in statuses, seen["status"]

    wait_for(f"{cr_id} {'/'.join(sorted(statuses))}", probe, timeout_minutes, **timing)
    return seen["status"]
