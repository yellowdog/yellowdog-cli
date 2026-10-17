"""
Live: listing Tasks as the Platform sends them, with no compute. A pending
Work Requirement of six Tasks in two Task Groups (specs/listing-wr.jsonnet)
is listed with '--within' (by name, 'wr/tg' and ID), '--limit' (one past it
read, the warning on stderr only when more match, '--count' never limited),
a '--name' glob the Platform matches as a substring, and '--status' sent with
the search. The Instance, Node and Worker listings are the provider chain's
('listing' in test_live_providers.py), which has compute to list.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from harness import work

pytestmark = [pytest.mark.live]

_JSON = ("--json", "--quiet")
_MORE = "more match"


@pytest.fixture(scope="module")
def listing_wr(live_run) -> Iterator[dict]:
    yd = live_run.yd
    submitted = work.submit(yd, "listing-wr.jsonnet")
    yield submitted
    work.cancel_all(yd, [submitted["id"]])


def _names(result) -> list[str]:
    return sorted(task["name"] for task in result.records)


def test_tasks_within_by_name_and_id(live_run, listing_wr):
    yd = live_run.yd
    every = ["other-1", "other-2", "row-1", "row-2", "row-3", "xrow-1"]
    for target in (listing_wr["name"], listing_wr["id"]):
        assert _names(yd("task", "list", "--within", target, *_JSON)) == every
    second = yd("task", "list", "--within", f"{listing_wr['name']}/second", *_JSON)
    assert _names(second) == ["other-1", "other-2", "row-3"]


def test_the_limit_and_its_warning(live_run, listing_wr):
    yd = live_run.yd
    within = ("task", "list", "--within", listing_wr["name"])
    limited = yd(*within, "--limit", "4", *_JSON)
    assert len(limited.records) == 4
    assert "Listed the first 4 Tasks; more match" in limited.stderr
    exactly = yd(*within, "--limit", "6", *_JSON)
    assert len(exactly.records) == 6
    assert _MORE not in exactly.stderr
    one = yd(*within, "--limit", "1", "--ids-only", "--quiet")
    assert len(one.stdout.split()) == 1
    assert "Listed the first Task; more match" in one.stderr
    assert yd(*within, "--count", "--quiet").stdout.strip() == "6"


def test_a_limit_across_task_groups(live_run, listing_wr):
    # Three Tasks in the first Task Group, so the fourth is the second's
    limited = live_run.yd(
        "task", "list", "--within", listing_wr["name"], "--limit", "4", *_JSON
    )
    groups = sorted(task["taskGroupId"].rsplit(":", 1)[1] for task in limited.records)
    assert groups == ["1", "1", "1", "2"]


def test_a_name_glob_is_limited_by_its_matches(live_run, listing_wr):
    # The Platform's substring match on 'row-' also sends 'xrow-1', which the
    # glob drops without counting it
    yd = live_run.yd
    within = ("task", "list", "--within", listing_wr["name"], "--name", "row-*")
    assert _names(yd(*within, *_JSON)) == ["row-1", "row-2", "row-3"]
    limited = yd(*within, "--limit", "2", *_JSON)
    assert _names(limited) == ["row-1", "row-2"]
    assert _MORE in limited.stderr


def test_a_status_is_sent_with_the_search(live_run, listing_wr):
    yd = live_run.yd
    within = ("task", "list", "--within", listing_wr["name"])
    statuses = {task["status"] for task in yd(*within, *_JSON).records}
    (status,) = statuses
    assert len(yd(*within, "--status", status.lower(), *_JSON).records) == 6
    assert yd(*within, "--status", "completed,failed", *_JSON).records == []
    assert (
        yd(*within, "--status", "completed", "--count", "--quiet").stdout.strip() == "0"
    )
