"""
Flag/guard tests for the dry-run mode on yd-cancel / yd-shutdown / yd-terminate.
These exercise argument parsing only (the by-name guard errors at parse time,
before any platform contact), so they need no credentials.
"""

import pytest
from cli_test_helpers import shell


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
        "yd-delete",
        # yd-download takes a required positional, so give it one: the point is
        # that --json alone is rejected, not that the arguments are incomplete.
        "yd-download somepath",
    ],
)
def test_json_without_dry_run_errors(cmd):
    # --json only shapes the --dry-run output; on its own it must error at parse
    # time rather than be silently ignored (or, for delete, fall through to a
    # real deletion).
    result = shell(f"{cmd} --json")
    assert result.exit_code == 2
    assert "only valid with --dry-run" in (result.stderr + result.stdout)


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
