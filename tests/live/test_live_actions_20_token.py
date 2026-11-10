"""
Live: a Configured Worker Pool's token refreshed, regenerated, and shown;
and the pool planned again failing, as creating it again fails (the Platform
refuses a second pool of the name).
Each token is registered as a secret as it is learned, so the pool shown
without --show-token, and every later call on this worker, fails
(SecretInOutput) if its output holds one; the calls that show a token on
purpose say so.
"""

import pytest
from harness.lifecycle import owned
from harness.run import SPECS

from yellowdog_cli.utils.resource_planners import CONFIGURED_POOL_EXISTS

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-actions")]

_ACT = ("--yes", "--json", "--quiet")


def test_the_token_is_refreshed_regenerated_and_shown(live_run):
    run, yd = live_run.run, live_run.yd
    created = yd(
        "resource",
        "create",
        str(SPECS / "configured-pool.jsonnet"),
        *_ACT,
        expect_secret=True,
    ).records
    _learned(yd, created)
    (pool,) = owned(yd, "configured-worker-pools", run.namespace, run.run_id)

    # A plan of the pool again fails, as creating it again does: the Platform
    # refuses a second pool of the name
    pool_spec = str(SPECS / "configured-pool.jsonnet")
    plan = ("resource", "plan", pool_spec, "--json", "--quiet")
    (planned,) = yd(*plan, ok=(1,), expected_failure=True).records
    assert planned["action"] == "failed", planned
    assert planned["error"] == CONFIGURED_POOL_EXISTS, planned
    again = yd("resource", "create", pool_spec, *_ACT, ok=(1,), expected_failure=True)
    (refused,) = again.records
    assert refused["action"] == "failed", refused
    assert "already exists" in refused["error"], refused
    assert len(owned(yd, "configured-worker-pools", run.namespace, run.run_id)) == 1

    # Without --ttl-hours a token has no expiry (live run ydst-2610131557-88e3)
    token = ("wp", "token", pool["id"], "--ttl-hours", "1", *_ACT)
    (first,) = _learned(yd, yd(*token, expect_secret=True).records)
    (refreshed,) = _learned(yd, yd(*token, expect_secret=True).records)
    assert first["expiryTime"] and refreshed["expiryTime"], (first, refreshed)
    assert refreshed["expiryTime"] >= first["expiryTime"], (first, refreshed)
    (regenerated,) = _learned(
        yd, yd(*token, "--regenerate", expect_secret=True).records
    )
    assert regenerated["token"] != refreshed["token"]

    yd("wp", "show", pool["id"], "--quiet")  # Fails if it holds a token
    shown = yd("wp", "show", pool["id"], "--show-token", "--quiet", expect_secret=True)
    assert regenerated["token"] in shown.stdout


def _learned(yd, records: list[dict]) -> list[dict]:
    """
    The records, each token in them registered as a secret.
    """
    for record in records:
        if record.get("token"):
            yd.add_secret("a Configured Worker Pool's token", record["token"])
    return records
