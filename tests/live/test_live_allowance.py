"""
Live: the run's Allowance listed, shown and boosted.
"""

import pytest

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-allowance")]


def test_the_allowance_is_listed_shown_and_boosted(live_run):
    run, yd = live_run.run, live_run.yd
    listed = yd(
        "allowance", "list", "--namespace", "", "--details", "--json", "--quiet"
    ).records
    (allowance,) = [
        a for a in listed if a.get("description") == run.allowance_description
    ]
    shown = yd("allowance", "show", allowance["id"], "--quiet").document
    assert shown["description"] == run.allowance_description
    boosted = yd(
        "allowance", "boost", "1", allowance["id"], "--yes", "--json", "--quiet"
    ).records
    assert boosted and all(r.get("outcome") != "failed" for r in boosted), boosted
    after = yd("allowance", "show", allowance["id"], "--quiet").document
    # The boost shows as more hours remaining (the run has used next to none)
    before_hours, after_hours = shown.get("remainingHours"), after.get("remainingHours")
    assert before_hours is not None and after_hours is not None, (shown, after)
    assert after_hours > before_hours, (before_hours, after_hours)
