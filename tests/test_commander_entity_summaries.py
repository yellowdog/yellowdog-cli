"""
Enumeration tests for Commander's '-D --json' entity listings: the parse must
retain YDIDs so a user's selection can be targeted exactly, and must refuse a
listing that lacks them rather than falling back to name-based targeting.
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from yellowdog_cli.commander.commander import (
    EntitySummary,
    YellowDogApp,
    parse_entity_summaries,
)


@pytest.fixture
def window(qapp):
    return YellowDogApp()


def test_parse_reads_id_name_and_status():
    parsed = [
        {"id": "ydid:workreq:1", "name": "wr-a", "status": "RUNNING"},
        {"id": "ydid:workreq:2", "name": "wr-b", "status": "HELD"},
    ]
    assert parse_entity_summaries(parsed) == [
        EntitySummary(id="ydid:workreq:1", name="wr-a", status="RUNNING"),
        EntitySummary(id="ydid:workreq:2", name="wr-b", status="HELD"),
    ]


def test_parse_tolerates_missing_status():
    assert parse_entity_summaries([{"id": "ydid:workreq:1", "name": "wr-a"}]) == [
        EntitySummary(id="ydid:workreq:1", name="wr-a", status=None)
    ]


def test_parse_rejects_row_without_id():
    # Without a YDID the entity cannot be targeted individually. Returning None
    # sends the caller to the scope-level confirmation rather than silently
    # falling back to names, which are not guaranteed unique.
    parsed = [{"id": "ydid:workreq:1", "name": "wr-a"}, {"name": "wr-b"}]
    assert parse_entity_summaries(parsed) is None


def test_parse_rejects_row_without_name():
    assert parse_entity_summaries([{"id": "ydid:workreq:1"}]) is None


def test_parse_rejects_non_dict_row():
    assert parse_entity_summaries(["wr-a"]) is None


def test_parse_empty_list():
    assert parse_entity_summaries([]) == []


def test_capture_summaries_parses_enumeration(window, monkeypatch):
    monkeypatch.setattr(
        window,
        "_capture_dry_run_json",
        lambda command, extra_args=None: [
            {"id": "ydid:compreq:9", "name": "cr-1", "status": "RUNNING"}
        ],
    )
    assert window._capture_dry_run_summaries("yd-terminate") == [
        EntitySummary(id="ydid:compreq:9", name="cr-1", status="RUNNING")
    ]


def test_capture_summaries_passes_extra_args(window, monkeypatch):
    seen: list = []
    monkeypatch.setattr(
        window,
        "_capture_dry_run_json",
        lambda command, extra_args=None: seen.append((command, extra_args)) or [],
    )
    window._capture_dry_run_summaries("yd-cancel", extra_args=["job-*"])
    assert seen == [("yd-cancel", ["job-*"])]


def test_capture_summaries_none_on_enumeration_failure(window, monkeypatch):
    monkeypatch.setattr(
        window, "_capture_dry_run_json", lambda command, extra_args=None: None
    )
    assert window._capture_dry_run_summaries("yd-terminate") is None


def test_capture_summaries_logs_when_ydids_missing(window, monkeypatch):
    monkeypatch.setattr(
        window,
        "_capture_dry_run_json",
        lambda command, extra_args=None: [{"name": "cr-1"}],
    )
    window.log_output.setPlainText("")
    assert window._capture_dry_run_summaries("yd-terminate") is None
    assert "did not include YDIDs" in window.log_output.toPlainText()


def test_capture_entities_still_returns_names_only(window, monkeypatch):
    # The names-only helper is unchanged: Delete Objects enumerates object
    # paths, whose rows carry a name but no id.
    monkeypatch.setattr(
        window,
        "_capture_dry_run_json",
        lambda command, extra_args=None: [{"name": "a.txt"}, {"name": "sub/"}],
    )
    assert window._capture_dry_run_entities("yd-delete") == ["a.txt", "sub/"]


def test_capture_entities_none_on_enumeration_failure(window, monkeypatch):
    monkeypatch.setattr(
        window, "_capture_dry_run_json", lambda command, extra_args=None: None
    )
    assert window._capture_dry_run_entities("yd-delete") is None


def test_capture_entities_robust_to_non_dict_rows(window, monkeypatch):
    # _capture_dry_run_entities is called directly from a UI action handler
    # (_delete_objects_action) without surrounding try/except, so it must be
    # robust to malformed enumeration rows (non-dict elements in the JSON array).
    # It should skip them rather than raise AttributeError on .get().
    monkeypatch.setattr(
        window,
        "_capture_dry_run_json",
        lambda command, extra_args=None: [
            {"name": "a.txt"},
            "not-a-dict",
            {"name": "b.txt"},
        ],
    )
    assert window._capture_dry_run_entities("yd-delete") == ["a.txt", "b.txt"]
