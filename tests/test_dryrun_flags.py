"""
Flag/guard tests for the dry-run mode on yd-cancel / yd-shutdown / yd-terminate.
These exercise argument parsing only (the by-name guard errors at parse time,
before any platform contact), so they need no credentials.
"""

from json import loads as json_loads
from unittest.mock import MagicMock

import pytest
from cli_test_helpers import shell

import yellowdog_cli.cancel as yd_cancel
import yellowdog_cli.delete as yd_delete
import yellowdog_cli.utils.dataclient_wrapper as dcw_module
import yellowdog_cli.utils.printing as printing_module
import yellowdog_cli.utils.results as results_module
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils import entity_utils
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.results import reset_results
from yellowdog_cli.utils.settings import ExitCode


@pytest.mark.parametrize("cmd", ["yd-cancel", "yd-shutdown", "yd-terminate"])
def test_dry_run_flag_in_help(cmd):
    assert "--dry-run" in shell(f"{cmd} --help").stdout


@pytest.mark.parametrize(
    "cmd",
    [
        "yd-cancel -D some-wr-name",
        "yd-shutdown -D some-wp-name",
        "yd-terminate -D some-cr-name",
    ],
)
def test_dry_run_with_explicit_names_errors(cmd):
    # Guard: --dry-run + explicit names/IDs must error at parse time (exit 2),
    # never falling through to the acting path.
    result = shell(cmd)
    assert result.exit_code == 2
    assert "not supported with explicit names" in (result.stderr + result.stdout)


@pytest.mark.parametrize(
    "cmd",
    [
        "yd-cancel",
        "yd-shutdown",
        "yd-terminate",
        # yd-delete and yd-download need a path, so give them one: the point is
        # that --json alone is accepted, not that the arguments are incomplete.
        # '--nc', so that no configured remote is ever reached
        "yd-delete --nc somepath",
        "yd-download somepath",
    ],
)
def test_json_without_dry_run_is_accepted(cmd):
    # '--json' no longer requires '--dry-run': it now also shapes the real,
    # acting path (spec point 4). It must not fail at parse time; whatever it
    # fails on afterwards (missing credentials here) is a different error.
    result = shell(f"{cmd} --json")
    assert result.exit_code != 2
    assert "only valid with --dry-run" not in (result.stderr + result.stdout)


@pytest.mark.parametrize(
    "cmd",
    ["yd-cancel 'proj-*' -D", "yd-shutdown 'wp-*' -D", "yd-terminate 'cr-*' -D"],
)
def test_dry_run_with_glob_is_allowed_at_parse_time(cmd):
    # A glob + --dry-run must NOT fail at parse time (exit 2). It proceeds to
    # main(); without credentials it fails later, but never with the parse
    # error, and never with the "not supported with explicit names" message.
    result = shell(cmd)
    assert "not supported with explicit names" not in (result.stderr + result.stdout)


@pytest.mark.parametrize(
    "cmd",
    [
        "yd-cancel 'proj-*' some-wr",
        "yd-shutdown 'wp-*' some-wp",
        "yd-terminate 'cr-*' some-cr",
    ],
)
def test_mixing_glob_and_literal_errors(cmd):
    result = shell(cmd)
    assert result.exit_code == 2
    assert "cannot mix" in (result.stderr + result.stdout)


@pytest.mark.parametrize(
    "cmd, argv",
    [
        ("yd-cancel", ["--json", "--yes", "x"]),
        ("yd-shutdown", ["--json", "--yes", "x"]),
        ("yd-terminate", ["--json", "--yes", "x"]),
        ("yd-delete", ["--json", "--yes", "x"]),
        # yd-download has no '--yes' of its own to confirm with
        ("yd-download", ["--json", "x"]),
    ],
)
def test_json_without_dry_run_parses(cmd, argv):
    # The parser itself (not a subprocess) no longer refuses '--json' without
    # '--dry-run' on any of the five destructive commands.
    parser = CLIParser(command=cmd, argv=argv)
    assert parser.json_output is True


class TestRealPathRecordsThroughARealParse:
    """
    'command_registry.check_json_requires_dry_run' used to make this
    combination a parse-time error; these drive main() through a real
    CLIParser (not a MagicMock standing in for one) and the real wrapper, to
    prove the lifted restriction reaches the acting path end to end.
    """

    def test_yd_cancel(self, monkeypatch, capsys):
        reset_results()
        args = CLIParser(command="yd-cancel", argv=["--json", "--yes", "nonesuch-wr"])
        for target in (yd_cancel, results_module, printing_module, wrapper_module):
            monkeypatch.setattr(target, "ARGS_PARSER", args)
        monkeypatch.setattr(yd_cancel, "CLIENT", MagicMock())
        monkeypatch.setattr(wrapper_module, "CLIENT", MagicMock())
        monkeypatch.setattr(
            yd_cancel,
            "CONFIG_COMMON",
            MagicMock(namespace="ns", name_tag="tag", url="https://u"),
        )
        # A literal name/ID with no glob chars takes the exact-name path,
        # which looks the Work Requirement up and records a failure when
        # it is not found -- no network mocking needed beyond that lookup.
        monkeypatch.setattr(
            entity_utils, "get_filtered_work_requirement_summaries", lambda *a, **k: []
        )

        with pytest.raises(SystemExit) as exit_info:
            yd_cancel.main()

        out = json_loads(capsys.readouterr().out)
        assert out == [
            {
                "id": None,
                "name": "nonesuch-wr",
                "type": "work-requirements",
                "action": "cancel",
                "outcome": "failed",
                "error": "Cannot find Work Requirement 'nonesuch-wr' in namespace 'ns'",
            }
        ]
        # A recorded 'failed' outcome exits 1 even though main() itself
        # raised nothing (the failed-record rule).
        assert exit_info.value.code == ExitCode.FAILURE
        reset_results()

    def test_yd_delete(self, monkeypatch, capsys):
        reset_results()
        args = CLIParser(command="yd-delete", argv=["--json", "--yes", "loc:some/path"])
        for target in (yd_delete, results_module, printing_module, dcw_module):
            monkeypatch.setattr(target, "ARGS_PARSER", args)
        monkeypatch.setattr(yd_delete, "CONFIG_DATA_CLIENT", MagicMock())
        monkeypatch.setattr(
            yd_delete, "resolve_remote_path", lambda *a, **k: "loc:some/path"
        )

        monkeypatch.setattr(
            yd_delete,
            "deletion_targets",
            lambda config, remote_path, recursive: ([(remote_path, False)], 0),
        )

        def fake_delete_item(config, path, is_dir):
            assert path == "loc:some/path"
            results_module.record({"path": path, "action": "deleted"})
            return True

        monkeypatch.setattr(yd_delete, "delete_item", fake_delete_item)
        monkeypatch.setattr(yd_delete, "confirmed", lambda msg: True)

        with pytest.raises(SystemExit) as exit_info:
            yd_delete.main()

        out = json_loads(capsys.readouterr().out)
        assert out == [{"path": "loc:some/path", "action": "deleted"}]
        assert exit_info.value.code == ExitCode.SUCCESS
        reset_results()
