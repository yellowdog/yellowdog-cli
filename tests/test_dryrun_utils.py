import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from yellowdog_cli.utils import output_settings
from yellowdog_cli.utils.dryrun_utils import report_dry_run
from yellowdog_cli.utils.output_style import DRY_RUN_MARKER
from yellowdog_cli.utils.results import flush_results, reset_results


@pytest.fixture()
def json_mode(monkeypatch):
    """
    Under '--json', with nothing recorded before or after.
    """
    args = MagicMock(json_output=True, strip_ids=False, no_format=True)
    output_settings.configure_output(args)
    output_settings.configure_output(args)
    reset_results()
    yield
    reset_results()


def test_human_non_empty_delegates_to_table(capsys):
    # The human (non-JSON) path prints a dry-run summary line and delegates the
    # listing to yd-list's table renderer (print_numbered_object_list).
    client = MagicMock()
    summaries = [SimpleNamespace(name="wr-1"), SimpleNamespace(name="wr-2")]
    with patch(
        "yellowdog_cli.utils.dryrun_utils.print_numbered_object_list"
    ) as mock_table:
        report_dry_run(
            client,
            summaries,
            "Work Requirement",
            "cancelled",
            "work-requirements",
            "cancel",
            as_json=False,
        )
    assert (
        f"{DRY_RUN_MARKER}2 Work Requirement(s) would be cancelled"
        in capsys.readouterr().out
    )
    mock_table.assert_called_once_with(
        client, summaries, object_type_name="Work Requirement"
    )
    reset_results()


def test_human_empty(capsys):
    with patch(
        "yellowdog_cli.utils.dryrun_utils.print_numbered_object_list"
    ) as mock_table:
        report_dry_run(
            MagicMock(),
            [],
            "Worker Pool",
            "shut down",
            "worker-pools",
            "shutdown",
            as_json=False,
        )
    assert "No Worker Pools would be shut down" in capsys.readouterr().out
    mock_table.assert_not_called()  # empty set -> no table


def test_json_records_what_would_be_done(json_mode, capsys):
    # Under '--json' each entity is recorded as the real action records it,
    # with 'would <action>', and the wrapper's flush prints the array
    report_dry_run(
        MagicMock(),
        [
            SimpleNamespace(id="ydid:compreq:000000:1", name="cr-1", status="RUNNING"),
            SimpleNamespace(id="ydid:compreq:000000:2", name="cr-2"),
        ],
        "Compute Requirement",
        "terminated",
        "compute-requirements",
        "terminate",
        as_json=True,
    )
    assert capsys.readouterr().out == ""  # nothing printed by itself
    flush_results()
    # With the status Commander's confirmation shows, null when there is none
    assert json.loads(capsys.readouterr().out) == [
        {
            "id": "ydid:compreq:000000:1",
            "name": "cr-1",
            "type": "compute-requirements",
            "action": "terminate",
            "outcome": "would terminate",
            "status": "RUNNING",
        },
        {
            "id": "ydid:compreq:000000:2",
            "name": "cr-2",
            "type": "compute-requirements",
            "action": "terminate",
            "outcome": "would terminate",
            "status": None,
        },
    ]


def test_json_empty(json_mode, capsys):
    report_dry_run(
        MagicMock(),
        [],
        "Work Requirement",
        "cancelled",
        "work-requirements",
        "cancel",
        as_json=True,
    )
    flush_results()
    assert json.loads(capsys.readouterr().out) == []


def test_entries_to_names_marks_dirs():
    from yellowdog_cli.utils.dataclient.operations import entries_to_names

    entries = [
        {"Name": "file.txt", "IsDir": False},
        {"Name": "subdir", "IsDir": True},
    ]
    assert entries_to_names(entries) == ["file.txt", "subdir/"]
