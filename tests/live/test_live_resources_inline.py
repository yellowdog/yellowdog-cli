"""
Live: resources given on the command line rather than in a file, with no
compute. Two run-named Keyrings are created, one with '--type' and '--set'
(a variable substituted in its values) and one read from standard input
('-'); shown by name and by ID ('yd resource show --type'); removed by name
and by ID in one call ('yd resource remove --type'), and removing one again
skipped; and what is refused as parsed, before the Platform is asked. The
cases run in order on one worker.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from harness.yd import Yd

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-resources-inline")]

_JSON = ("--json", "--quiet")
_ACT = ("--yes", *_JSON)


def _description(live_run) -> str:
    run = live_run.run
    # Named for the run and its namespace, so that teardown removes it
    return f"Live system tests, run {run.run_id}, namespace {run.namespace}"


def _keyrings(yd: Yd, run) -> dict[str, str]:
    """
    The run's Keyrings made here, by name, with their IDs.
    """
    found = yd(
        "resource",
        "list",
        "keyrings",
        "--namespace",
        "",
        "--name",
        f"{run.run_id}-inline-*",
        *_JSON,
        ok=(0, 6),
    )
    return {keyring["name"]: keyring["id"] for keyring in found.records}


@pytest.fixture(scope="module")
def names(live_run) -> Iterator[tuple[str, str]]:
    run, yd = live_run.run, live_run.yd
    yield run.name("inline-a"), run.name("inline-b")
    for name in _keyrings(yd, run):
        yd("resource", "remove", "--type", "Keyring", name, *_ACT, check=False)


def test_created_with_type_and_set(live_run, names):
    first, _ = names
    created = live_run.yd(
        "resource",
        "create",
        "--type",
        "keyring",
        "--set",
        "name={{run_id}}-inline-a",
        "--set",
        f"description={_description(live_run)}",
        *_ACT,
    )
    assert [(r["resource"], r["name"], r["action"]) for r in created.records] == [
        ("Keyring", first, "created")
    ]


def test_created_from_standard_input(live_run, names):
    _, second = names
    specification = {
        "resource": "Keyring",
        "name": second,
        "description": _description(live_run),
    }
    created = live_run.yd(
        "resource", "create", "-", *_ACT, input=json.dumps(specification)
    )
    assert [(r["name"], r["action"]) for r in created.records] == [(second, "created")]


def test_shown_by_name_and_by_id(live_run, names):
    yd = live_run.yd
    first, second = names
    second_id = _keyrings(yd, live_run.run)[second]
    shown = yd("resource", "show", "--type", "Keyring", first, second_id, "--quiet")
    assert [keyring["name"] for keyring in shown.records] == [first, second]


def test_a_name_that_names_nothing_is_not_found(live_run):
    missing = live_run.run.name("inline-missing")
    result = live_run.yd(
        "resource",
        "show",
        "--type",
        "Keyring",
        missing,
        "--quiet",
        check=False,
        ok=(6,),
        expected_failure=True,
    )
    assert missing in result.stderr


@pytest.mark.parametrize(
    "argv, message",
    [
        (
            ["remove", "--type", "Allowance", "gpu-hours", *_ACT],
            "an Allowance has no name",
        ),
        (
            ["remove", "--type", "Keyring", "k", "--set", "name=x", *_ACT],
            "not both",
        ),
        (["show", "--type", "Namespace", "dev", "--quiet"], "cannot be shown by name"),
        (["show", "a-name", "--quiet"], "give --type"),
    ],
)
def test_refused_as_parsed(live_run, argv, message):
    result = live_run.yd("resource", *argv, check=False, ok=(2,), expected_failure=True)
    assert message in result.stderr


def test_removed_by_name_and_by_id(live_run, names):
    yd, run = live_run.yd, live_run.run
    first, second = names
    second_id = _keyrings(yd, run)[second]
    removed = yd("resource", "remove", "--type", "Keyring", first, second_id, *_ACT)
    assert [(r["name"], r["action"]) for r in removed.records] == [
        (first, "removed"),
        (second, "removed"),
    ]
    assert _keyrings(yd, run) == {}
    again = yd("resource", "remove", "--type", "Keyring", first, *_ACT)
    assert [(r["name"], r["action"]) for r in again.records] == [(first, "skipped")]
