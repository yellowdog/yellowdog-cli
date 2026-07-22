import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from yellowdog_cli.utils.dryrun_utils import report_dry_run


def test_human_non_empty_delegates_to_table(capsys):
    # The human (non-JSON) path prints a dry-run summary line and delegates the
    # listing to yd-list's table renderer (print_numbered_object_list).
    client = MagicMock()
    summaries = [SimpleNamespace(name="wr-1"), SimpleNamespace(name="wr-2")]
    with patch(
        "yellowdog_cli.utils.dryrun_utils.print_numbered_object_list"
    ) as mock_table:
        report_dry_run(
            client, summaries, "Work Requirement", "cancelled", as_json=False
        )
    assert (
        "Dry run: 2 Work Requirement(s) would be cancelled" in capsys.readouterr().out
    )
    mock_table.assert_called_once_with(
        client, summaries, object_type_name="Work Requirement"
    )


def test_human_empty(capsys):
    with patch(
        "yellowdog_cli.utils.dryrun_utils.print_numbered_object_list"
    ) as mock_table:
        report_dry_run(MagicMock(), [], "Worker Pool", "shut down", as_json=False)
    assert "No Worker Pools would be shut down" in capsys.readouterr().out
    mock_table.assert_not_called()  # empty set -> no table


def test_json_array(capsys):
    report_dry_run(
        MagicMock(),
        [{"name": "cr-1"}],
        "Compute Requirement",
        "terminated",
        as_json=True,
    )
    assert json.loads(capsys.readouterr().out) == [{"name": "cr-1"}]


def test_json_empty(capsys):
    report_dry_run(MagicMock(), [], "Work Requirement", "cancelled", as_json=True)
    assert json.loads(capsys.readouterr().out) == []
