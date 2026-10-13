"""
Live: on every configured provider, a Worker Pool's instance registers a
Worker and runs a Task, takes each cloud action in turn, and is shut down
(Section 3 of the design). Stop, start and restart act instead on a Compute
Requirement no pool manages, since a pool takes a stopped node's instance
away. Each provider's steps are a chain (live_chain.py) in its own xdist
group, so they run in order on one worker while providers run in parallel:

    pytest --run-live -n 4 tests/live/test_live_providers.py

An action the capability table records as unsupported must be refused
cleanly instead (harness/capabilities.py).
"""

from __future__ import annotations

import pytest
from harness import compute
from harness.capabilities import PROVIDERS, perform, unsupported
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
            _cr_seconds(live_run),
            *_ACT,
        ):
            states = _settle(chain, live_run)
            assert sum(s == "RUNNING" for s in states.values()) == 1, states


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
