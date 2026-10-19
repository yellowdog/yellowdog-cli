"""
Live: a Configured Worker Pool's token refreshed, regenerated, and shown.
Each token is registered as a secret as it is learned, so the pool shown
without --show-token, and every later call on this worker, fails
(SecretInOutput) if its output holds one; the calls that show a token on
purpose say so.
"""

import pytest
from harness.lifecycle import owned
from harness.run import SPECS

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
