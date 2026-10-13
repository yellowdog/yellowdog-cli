"""
Live: a Configured Worker Pool's token refreshed, regenerated, and shown.
"""

import pytest
from harness.lifecycle import owned
from harness.run import SPECS

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-actions")]

_ACT = ("--yes", "--json", "--quiet")


def test_the_token_is_refreshed_regenerated_and_shown(live_run):
    run, yd = live_run.run, live_run.yd
    yd("resource", "create", str(SPECS / "configured-pool.jsonnet"), *_ACT)
    (pool,) = owned(yd, "configured-worker-pools", run.namespace, run.run_id)

    # Without --ttl-hours a token has no expiry (live run ydst-2610131557-88e3)
    ttl = ("--ttl-hours", "1")
    (first,) = yd("wp", "token", pool["id"], *ttl, *_ACT).records
    (refreshed,) = yd("wp", "token", pool["id"], *ttl, *_ACT).records
    assert first["expiryTime"] and refreshed["expiryTime"], (first, refreshed)
    assert refreshed["expiryTime"] >= first["expiryTime"], (first, refreshed)
    (regenerated,) = yd("wp", "token", pool["id"], "--regenerate", *ttl, *_ACT).records
    assert regenerated["token"] != refreshed["token"]

    shown = yd("wp", "show", pool["id"], "--show-token", "--quiet").stdout
    assert regenerated["token"] in shown
