"""
The live system tests' fixtures, over the plugin that owns the run
(live_session.py, registered by the root conftest.py under '--run-live').
Only a test marked 'live', run with '--run-live', reaches these.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from harness import compute, coverage
from harness.config import LiveConfig
from harness.run import INSTALLER, SPECS
from live_session import PLUGIN_NAME, LiveRun, LiveSession


@pytest.fixture(autouse=True)
def _offline_tests_record_nowhere(request, monkeypatch):
    """
    A test not marked 'live' runs with the coverage record off, and whatever
    it sets the record to is put back after it: offline tests share the
    processes of a live session, and must neither redirect its record nor
    earn a verb credit through a stand-in 'yd'.
    """
    if request.node.get_closest_marker("live") is None:
        monkeypatch.setattr(coverage, "_DIRECTORY", None)


@pytest.fixture(scope="session")
def live_session(request: pytest.FixtureRequest) -> LiveSession:
    session = request.config.pluginmanager.get_plugin(PLUGIN_NAME)
    assert session is not None, "the live session plugin needs '--run-live'"
    return session


@pytest.fixture(scope="session")
def live_config(live_session: LiveSession) -> LiveConfig:
    return live_session.live_config()


@pytest.fixture(scope="session")
def live_run(live_session: LiveSession) -> LiveRun:
    return live_session.live_run()


@dataclass(frozen=True)
class ActionsPool:
    """
    The primary's actions pool: its IDs and its Workers' tag.
    """

    pool_id: str
    cr_id: str
    worker_tag: str


@pytest.fixture(scope="session")
def actions_pool(live_run) -> ActionsPool:
    """
    The primary's actions pool, provisioned on first use (on the worker
    running the 'ydst-actions' group) once its four Workers are up; left for
    plan 3c and teardown to shut down.
    """
    run, yd = live_run.run, live_run.yd
    minutes = run.config.run["provision_timeout_minutes"]
    provisioned = yd(
        "wp",
        "provision",
        str(SPECS / "actions-pool.jsonnet"),
        "--variable",
        f"provider={run.config.primary}",
        "--property",
        f"workerPool.userDataFile={INSTALLER}",
        "--json",
        "--quiet",
    ).document
    pool_id = provisioned["id"]
    cr_id = compute.worker_pool(yd, pool_id)["computeRequirementId"]
    compute.wait_for_workers(
        yd, run.namespace, run.run_id, pool_id, 4, minutes, cr_id=cr_id
    )
    return ActionsPool(pool_id, cr_id, run.actions_worker_tag())
