"""
Live: a run's setup makes what it should, teardown leaves nothing, and the
run's Keyring and Credentials can provision (Open Question 1 of the design).

    pytest --run-live tests/live/test_live_setup.py
"""

import time

import pytest
from harness.lifecycle import REMOVAL_ORDER, owned, setup, teardown
from harness.run import Run
from harness.yd import Yd

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst")]

_POLL_SECONDS = 15
_SETTLED = {"RUNNING", "TERMINATED", "TERMINATING", "STOPPED"}


def _names(entities: list[dict], key: str = "name") -> list[str]:
    return sorted(entity[key] for entity in entities)


def test_setup_made_the_keyring_templates_and_allowance(live_run):
    run, yd = live_run.run, live_run.yd
    providers = list(run.config.providers)
    assert _names(owned(yd, "keyrings", run.namespace, run.run_id)) == [run.keyring]
    assert _names(owned(yd, "compute-source-templates", run.namespace, run.run_id)) == (
        sorted(run.source_template(p) for p in providers)
    )
    assert _names(
        owned(yd, "compute-requirement-templates", run.namespace, run.run_id)
    ) == sorted(run.requirement_template(p) for p in providers)
    assert _names(
        owned(yd, "allowances", run.namespace, run.run_id), key="description"
    ) == [run.allowance_description]


def test_the_keyring_holds_a_credential_per_provider(live_run):
    run, yd = live_run.run, live_run.yd
    (keyring,) = owned(yd, "keyrings", run.namespace, run.run_id)
    shown = yd("resource", "show", keyring["id"], "--quiet").document
    assert sorted(c["name"] for c in shown["credentials"]) == sorted(
        run.credential_name(p) for p in run.config.providers
    )


def test_a_run_torn_down_leaves_nothing(live_config, tmp_path):
    run = Run.start(live_config, tmp_path)
    yd = Yd(run)
    try:
        setup(run, yd)
        assert owned(yd, "keyrings", run.namespace, run.run_id)
    finally:
        problems = teardown(
            yd, run.namespace, run.run_id, live_config.run["teardown_timeout_minutes"]
        )
    assert problems == []
    for entity_type in REMOVAL_ORDER:
        assert owned(yd, entity_type, run.namespace, run.run_id) == [], entity_type


def test_the_primary_provisions_with_the_runs_credential(live_run):
    """
    One instance from the primary's static template: proves the Application
    can use the Keyring it created without its being claimed in the Portal,
    and that the primary's credential, network and image work. Terminated
    whatever happens.
    """
    run, yd = live_run.run, live_run.yd
    primary = run.config.primary
    created = yd(
        "cr",
        "instantiate",
        "--property",
        f"workerPool.templateId={run.namespace}/{run.requirement_template(primary)}",
        "--property",
        f"workerPool.name={run.name('probe')}",
        "--target",
        "1",
        "--json",
        "--quiet",
    ).document
    requirement = created["id"]
    try:
        status = _settled(yd, requirement, run.config.run["provision_timeout_minutes"])
        if status != "RUNNING":
            report = yd(
                "cr",
                "show",
                requirement,
                "--show-source-report",
                "--quiet",
                check=False,
            )
            pytest.fail(
                f"{requirement} reached {status}, not RUNNING:\n"
                + yd.mask(report.stdout),
                pytrace=False,
            )
    finally:
        yd("cr", "terminate", requirement, "--yes", "--json", "--quiet", ok=(0, 6))


def _settled(yd: Yd, requirement: str, timeout_minutes: int) -> str:
    """
    Poll a Compute Requirement until its status settles, or the time is up.
    """
    deadline = time.monotonic() + timeout_minutes * 60
    status = "UNKNOWN"
    while time.monotonic() < deadline:
        status = yd("cr", "show", requirement, "--quiet").document["status"]
        if status in _SETTLED:
            return status
        time.sleep(_POLL_SECONDS)
    return status
