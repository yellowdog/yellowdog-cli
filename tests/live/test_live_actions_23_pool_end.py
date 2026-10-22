"""
Live: the actions pool shown by its name, followed in a thread while it is
shut down and its compute terminated, then waited for by ID and by name.
"""

import pytest
from harness import work

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-actions")]

_ACT = ("--yes", "--json", "--quiet")


def test_the_pool_is_followed_to_its_end_and_waited_for(live_run, actions_pool):
    run, yd = live_run.run, live_run.yd
    seconds = run.config.run["teardown_timeout_minutes"] * 60
    name = run.actions_pool_name()
    shown = yd("wp", "show", name, "--quiet").document
    assert shown["id"] == actions_pool.pool_id, shown
    followed = work.follow_alongside(
        yd,
        ("wp", "follow", actions_pool.pool_id),
        lambda: yd("wp", "shutdown", "--terminate", actions_pool.pool_id, *_ACT),
        seconds,
    )
    work.ended_with(work.follow_events(followed.stdout), {"SHUTDOWN", "TERMINATED"})
    (record,) = yd(
        "wp",
        "wait",
        actions_pool.pool_id,
        "--timeout",
        str(seconds),
        "--json",
        "--quiet",
        ok=(0, 1),
    ).records
    assert record["status"] in {"SHUTDOWN", "TERMINATED"}, record
    (by_name,) = yd("wp", "wait", name, "--json", "--quiet", ok=(0, 1)).records
    assert by_name["id"] == actions_pool.pool_id, by_name
