"""
Enumeration tests for Commander's '-D --json' entity listings: the parse must
retain YDIDs so a user's selection can be targeted exactly, and must refuse a
listing that lacks them rather than falling back to name-based targeting.
"""

import pytest
import qt_guard

qt_guard.require_qt()

from yellowdog_cli.commander.commander import YellowDogApp
from yellowdog_cli.commander.selection import EntitySummary, parse_entity_summaries


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


def test_dry_run_records_carry_the_status_commander_shows(monkeypatch, capsys):
    # The confirmation lists 'name  status'; the status comes from the CLI's
    # own '-D --json' records, so build the rows from what report_dry_run()
    # actually emits rather than hand-writing one.
    from json import loads as json_loads
    from unittest.mock import MagicMock

    from yellowdog_client.model import (
        WorkRequirementStatus,
        WorkRequirementSummary,
    )

    import yellowdog_cli.utils.results as results_module
    from yellowdog_cli.utils import output_settings
    from yellowdog_cli.utils.dryrun_utils import report_dry_run

    output_settings.configure_output(
        MagicMock(json_output=True, no_format=True, quiet=False, strip_ids=False)
    )
    results_module.reset_results()
    wr_id = "ydid:workreq:000000:11111111-1111-1111-1111-111111111111"
    summary = WorkRequirementSummary(
        id=wr_id, name="wr-a", namespace="ns", status=WorkRequirementStatus.HELD
    )
    report_dry_run(
        MagicMock(),
        [summary],
        "Work Requirement",
        "cancelled",
        "work-requirements",
        "cancel",
        as_json=True,
    )
    results_module.flush_results()
    parsed = json_loads(capsys.readouterr().out)
    assert parse_entity_summaries(parsed) == [
        EntitySummary(id=wr_id, name="wr-a", status="HELD")
    ]
