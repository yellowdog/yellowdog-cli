"""
Live: on every configured provider, a Worker Pool's instance registers a
Worker and runs a Task, takes each cloud action in turn, and is shut down
(Section 3 of the design). Stop, start and restart act instead on a Compute
Requirement no pool manages, since a pool takes a stopped node's instance
away. Each provider's steps are a chain (live_chain.py) in its own xdist
group, so they run in order on one worker while providers run in parallel:

    pytest --run-live -n 4 tests/live/test_live_providers.py

An action the capability table records as unsupported must be refused
cleanly instead, and one recorded as a known fault must show its symptom
(harness/capabilities.py).
"""

from __future__ import annotations

import time

import pytest
from harness import compute
from harness.capabilities import PROVIDERS, known_fault, perform, unsupported
from harness.run import INSTALLER, SPECS
from live_chain import Chain

pytestmark = [pytest.mark.live]

_ACT = ("--yes", "--json", "--quiet")
_GONE = frozenset({"TERMINATED", compute.GONE})


@pytest.fixture(
    scope="module",
    params=[
        pytest.param(p, marks=pytest.mark.xdist_group(f"ydst-{p}")) for p in PROVIDERS
    ],
)
def chain(request, live_run) -> Chain:
    provider = request.param
    if provider not in live_run.run.config.providers:
        pytest.skip(f"{provider} is not configured")
    return Chain(provider)


def _minutes(live_run, key: str = "provision_timeout_minutes") -> int:
    return live_run.run.config.run[key]


def _settle(chain: Chain, live_run) -> dict[str, str]:
    """
    Wait for the requirement to settle at its target, and act next on the
    first of its RUNNING Instances.
    """
    run = live_run.run
    states = compute.wait_until_settled(
        live_run.yd, run.namespace, run.run_id, chain.cr_id, _minutes(live_run)
    )
    running = sorted(name for name, status in states.items() if status == "RUNNING")
    chain.instance = running[0] if running else None
    return states


def test_provision(chain, live_run):
    run, yd = live_run.run, live_run.yd
    with chain.step("provision"):
        provisioned = yd(
            "wp",
            "provision",
            str(SPECS / "pool.jsonnet"),
            "--variable",
            f"provider={chain.provider}",
            "--property",
            f"workerPool.userDataFile={INSTALLER}",
            "--json",
            "--quiet",
        ).document
        chain.pool_id = provisioned["id"]
        chain.cr_id = compute.worker_pool(yd, chain.pool_id)["computeRequirementId"]
        compute.wait_for_worker(
            yd,
            run.namespace,
            run.run_id,
            chain.pool_id,
            _minutes(live_run),
            cr_id=chain.cr_id,
        )
        _settle(chain, live_run)


def test_smoke(chain, live_run):
    yd = live_run.yd
    with chain.step("smoke"):
        submitted = yd(
            "wr",
            "submit",
            str(SPECS / "smoke-wr.jsonnet"),
            "--variable",
            f"provider={chain.provider}",
            "--follow",
            "--exit-on-failure",
            "--json",
            "--quiet",
            timeout=_minutes(live_run) * 60,
        ).document
        shown = yd("wr", "show", submitted["id"], "--quiet").document
        assert shown["status"] == "COMPLETED", shown["status"]


def _cr_seconds(live_run) -> str:
    return str(_minutes(live_run) * 60)


def test_resize_up(chain, live_run):
    with chain.step("resize-up"):
        if perform(
            live_run.yd,
            chain.provider,
            "resize-up",
            "cr",
            "resize",
            chain.cr_id,
            "2",
            "--wait",
            "--timeout",
            _cr_seconds(live_run),
            *_ACT,
        ):
            states = _settle(chain, live_run)
            assert sum(s == "RUNNING" for s in states.values()) == 2, states
        else:
            _settle(chain, live_run)


# 'yd list --provider' as each chain's provider is named
_CLI_PROVIDER = {"aws": "aws", "azure": "azure", "gcp": "google", "oci": "oci"}


def _within(yd, noun: str, target: str, *extra: str):
    return yd(noun, "list", "--within", target, *extra, "--json", "--quiet")


def _limited_to_one(yd, noun: str, target: str, total: int, singular: str) -> None:
    """
    '--limit 1' lists one of the 'total' (none of none), and warns, on
    stderr, only when there are more.
    """
    result = _within(yd, noun, target, "--limit", "1")
    assert len(result.records) == min(1, total), result.records
    warned = f"Listed the first {singular}; more match" in result.stderr
    assert warned == (total > 1), result.stderr


def _agree(expected, listed, attempts: int = 12, pause: float = 10) -> None:
    """
    Hold what 'listed' reads to what 'expected' reads, reading both again
    until they agree: a Node can still be registering just after a resize,
    and appear between the two reads.
    """
    for _ in range(attempts - 1):
        if expected() == listed():
            return
        time.sleep(pause)
    assert listed() == expected()


def test_listing(chain, live_run):
    """
    The pool's Instances, Nodes and Workers listed '--within' their parent,
    by ID and by name, as the namespace-wide listings list them; '--limit'
    and its warning; '--status' and '--provider' sent with the search.
    """
    run, yd = live_run.run, live_run.yd
    provider = _CLI_PROVIDER[chain.provider]
    with chain.step("listing"):

        def instances() -> dict[str, str]:
            return compute.instances(yd, run.namespace, run.run_id, chain.cr_id)

        def nodes() -> list[dict]:
            return compute.nodes(yd, run.namespace, run.run_id, chain.pool_id)

        cr_name = compute.compute_requirement(yd, chain.cr_id)["name"]
        for target in (chain.cr_id, cr_name, f"{run.namespace}/{cr_name}"):
            _agree(
                lambda: sorted(name.split(".", 1)[1] for name in instances()),
                lambda target=target: sorted(
                    i["id"]["instanceId"]
                    for i in _within(yd, "instance", target, "--limit", "0").records
                ),
            )
        _limited_to_one(yd, "instance", chain.cr_id, len(instances()), "Instance")
        _agree(
            lambda: sum(status == "RUNNING" for status in instances().values()),
            lambda: len(
                _within(
                    yd,
                    "instance",
                    chain.cr_id,
                    "--status",
                    "running",
                    "--provider",
                    provider,
                ).records
            ),
        )
        assert (
            _within(yd, "instance", chain.cr_id, "--provider", "on-premise").records
            == []
        )

        for target in (chain.pool_id, run.pool_name(chain.provider)):
            _agree(
                lambda: sorted(node["id"] for node in nodes()),
                lambda target=target: sorted(
                    node["id"]
                    for node in _within(yd, "node", target, "--limit", "0").records
                ),
            )
        _limited_to_one(yd, "node", chain.pool_id, len(nodes()), "Node")
        _agree(
            lambda: sum(node.get("status") == "RUNNING" for node in nodes()),
            lambda: len(
                _within(
                    yd,
                    "node",
                    chain.pool_id,
                    "--status",
                    "running",
                    "--provider",
                    provider,
                ).records
            ),
        )

        workers = _within(yd, "worker", chain.pool_id, "--limit", "0").records
        assert workers, "the pool has no Workers"
        _limited_to_one(yd, "worker", chain.pool_id, len(workers), "Worker")
        node = next(node for node in nodes() if node.get("workers"))
        _agree(
            lambda: sorted(w["id"] for w in node["workers"]),
            lambda: sorted(
                w["id"]
                for w in _within(yd, "worker", node["id"], "--limit", "0").records
            ),
        )


def test_instantiate_standalone(chain, live_run):
    """
    A Compute Requirement of one instance that no Worker Pool manages, for
    stop, start and restart: a pool takes a stopped node's instance away.
    """
    run, yd = live_run.run, live_run.yd
    with chain.step("instantiate-standalone"):
        created = yd(
            "cr",
            "instantiate",
            "--property",
            f"workerPool.templateId={run.namespace}/{run.requirement_template(chain.provider)}",
            "--property",
            f"workerPool.name={run.standalone_name(chain.provider)}",
            "--target",
            "1",
            "--json",
            "--quiet",
        ).document
        chain.standalone_cr = created["id"]
        states = compute.wait_until_settled(
            yd, run.namespace, run.run_id, chain.standalone_cr, _minutes(live_run)
        )
        (chain.standalone,) = [n for n, s in states.items() if s == "RUNNING"]


def test_stop(chain, live_run):
    yd = live_run.yd
    with chain.step("stop"):
        if perform(
            yd, chain.provider, "stop", "instance", "stop", chain.standalone, *_ACT
        ):
            compute.wait_for_instance(
                yd, chain.standalone, frozenset({"STOPPED"}), _minutes(live_run)
            )
        else:
            assert compute.instance_status(yd, chain.standalone) == "RUNNING"


def test_start(chain, live_run):
    yd = live_run.yd
    with chain.step("start"):
        if unsupported(chain.provider, "stop"):
            pytest.skip(f"{chain.provider} cannot stop an instance, so none to start")
        if perform(
            yd, chain.provider, "start", "instance", "start", chain.standalone, *_ACT
        ):
            compute.wait_for_instance(
                yd, chain.standalone, frozenset({"RUNNING"}), _minutes(live_run)
            )
        else:
            assert compute.instance_status(yd, chain.standalone) == "STOPPED"


def test_restart(chain, live_run):
    yd = live_run.yd
    with chain.step("restart"):
        if perform(
            yd,
            chain.provider,
            "restart",
            "instance",
            "restart",
            chain.standalone,
            *_ACT,
        ):
            compute.wait_for_instance(
                yd, chain.standalone, frozenset({"RUNNING"}), _minutes(live_run)
            )
        else:
            assert compute.instance_status(yd, chain.standalone) == "RUNNING"


def _wait_for_counts(live_run, cr_id: str, **counts: int) -> None:
    """
    Wait for a Compute Requirement's counts ('targetInstanceCount',
    'expectedInstanceCount') to reach the values given.
    """
    yd = live_run.yd

    def probe() -> tuple[bool, str]:
        shown = compute.compute_requirement(yd, cr_id)
        seen = {key: shown.get(key) for key in counts}
        return seen == counts, str(seen)

    compute.wait_for(f"{cr_id} {counts}", probe, _minutes(live_run))


def test_terminate_instance(chain, live_run):
    """
    The standalone requirement's instance terminated, and not replaced. The
    Platform lowers neither the target nor (at once) the expected count, so
    neither is asserted.
    """
    yd = live_run.yd
    with chain.step("terminate-instance"):
        leaving = chain.standalone
        if perform(
            yd,
            chain.provider,
            "terminate-instance",
            "instance",
            "terminate",
            leaving,
            *_ACT,
        ):
            compute.wait_for_instance(yd, leaving, _GONE, _minutes(live_run))
            run = live_run.run
            left = compute.instances(yd, run.namespace, run.run_id, chain.standalone_cr)
            assert not any(v in {"RUNNING", "PENDING"} for v in left.values()), left
        else:
            assert compute.instance_status(yd, leaving) == "RUNNING"


def test_reprovision(chain, live_run):
    with chain.step("reprovision"):
        perform(
            live_run.yd,
            chain.provider,
            "reprovision",
            "cr",
            "reprovision",
            chain.cr_id,
            "--wait",
            "--timeout",
            _cr_seconds(live_run),
            *_ACT,
        )
        states = _settle(chain, live_run)
        assert any(s == "RUNNING" for s in states.values()), states


def test_resize_down(chain, live_run):
    """
    Down to one instance; where that is a known fault (its target drops to 0
    with an instance left RUNNING), the next step acts on that instance.
    """
    fault = known_fault(chain.provider, "resize-down")
    with chain.step("resize-down"):
        if perform(
            live_run.yd,
            chain.provider,
            "resize-down",
            "cr",
            "resize",
            chain.cr_id,
            "1",
            "--wait",
            "--timeout",
            str(fault.wait_seconds) if fault else _cr_seconds(live_run),
            *_ACT,
        ):
            states = _settle(chain, live_run)
            assert sum(s == "RUNNING" for s in states.values()) == 1, states
        else:
            run = live_run.run
            states = compute.instances(
                live_run.yd, run.namespace, run.run_id, chain.cr_id
            )
            running = sorted(n for n, s in states.items() if s == "RUNNING")
            assert len(running) == 1, states
            chain.instance = running[0]


def test_deprovision(chain, live_run):
    """
    The pool's last instance deprovisioned: it leaves, and the target drops
    with it, to 0.
    """
    yd = live_run.yd
    with chain.step("deprovision"):
        leaving = chain.instance
        if perform(
            yd, chain.provider, "deprovision", "instance", "deprovision", leaving, *_ACT
        ):
            compute.wait_for_instance(yd, leaving, _GONE, _minutes(live_run))
            _wait_for_counts(live_run, chain.cr_id, targetInstanceCount=0)
        else:
            assert compute.instance_status(yd, leaving) == "RUNNING"


def test_shutdown(chain, live_run):
    """
    The standalone Compute Requirement terminated, and the pool shut down
    and its compute terminated; run whatever failed before.
    """
    yd = live_run.yd
    teardown_minutes = _minutes(live_run, "teardown_timeout_minutes")
    with chain.step("shutdown", always=True):
        if chain.standalone_cr is None and chain.pool_id is None:
            pytest.skip(f"{chain.provider}: nothing was provisioned")
        if chain.standalone_cr is not None:
            yd("cr", "terminate", chain.standalone_cr, *_ACT)
        if chain.pool_id is not None:
            yd("wp", "shutdown", "--terminate", chain.pool_id, *_ACT)
        for cr_id in (chain.standalone_cr, chain.cr_id):
            if cr_id is not None:
                compute.wait_for_requirement(
                    yd, cr_id, frozenset({"TERMINATED"}), teardown_minutes
                )
        if chain.pool_id is not None:
            status = compute.worker_pool(yd, chain.pool_id)["status"]
            assert status in {"SHUTDOWN", "TERMINATED"}, status
