"""
The 'live' marker: a live test is skipped without '--run-live'.
"""

import pytest


@pytest.mark.live
def test_a_live_test_runs_only_with_run_live(request):
    """
    Reaching this body means '--run-live' was given.
    """
    assert request.config.getoption("--run-live")
