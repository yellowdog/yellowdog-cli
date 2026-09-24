"""
System tests: error handling behaviour.

Two distinct failure modes exist in the CLI:

  Hard failures (exit code 1):
    Raised by an unhandled exception inside @main_wrapper (e.g. file not
    found, JSON parse error, bad variable syntax). The process exits 1 and
    the error marker appears in stderr.

  Soft failures (exit code 0, the error marker in stderr):
    The command processes a list of items (YDIDs, resource specs) and reports
    individual errors without aborting the overall run. Exit code is 0 even
    though something went wrong. Examples: unknown YDID type, nonexistent
    resource.

Tests that do NOT need platform connectivity are marked with a comment.
Tests that DO need platform connectivity are noted separately.

Run with: pytest --run-system tests/test_system_error_handling.py
"""

import pytest
from cli_test_helpers import shell

from yellowdog_cli.utils.settings import ERROR_MARKER
from yellowdog_cli.utils.ydid_utils import TYPE_KEYRING, YDID


def _output(result) -> str:
    """Combined stdout + stderr — the CLI writes error lines to stderr."""
    return result.stdout + result.stderr


def _has_error(result) -> bool:
    return ERROR_MARKER in _output(result)


# ---------------------------------------------------------------------------
# Hard failures (exit code 1)
# ---------------------------------------------------------------------------


@pytest.mark.system
class TestHardFailures:
    """Commands that raise an exception and exit 1."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "yd-create /this/path/does/not/exist.json",
            "yd-remove -y /this/path/does/not/exist.json",
        ],
    )
    def test_nonexistent_file(self, cmd):
        # No platform needed
        result = shell(cmd)
        assert result.exit_code == 1
        assert _has_error(result)

    def test_create_malformed_json(self, tmp_path):
        # No platform needed
        bad = tmp_path / "bad.json"
        bad.write_text("{ this is not : valid json !!!")
        result = shell(f"yd-create {bad}")
        assert result.exit_code == 1
        assert _has_error(result)

    def test_bad_variable_format(self):
        # No platform needed — variable parsing fails before any API call
        result = shell("yd-submit -D -n=test -t=test -v no_equals_sign")
        assert result.exit_code == 1
        assert _has_error(result)
        assert "no_equals_sign" in _output(result)

    def test_create_unknown_resource_type(self, tmp_path):
        # No platform needed — resource type is checked client-side
        spec = tmp_path / "unknown.json"
        spec.write_text('[{"resource": "WibbleWobbleUnknown", "name": "test"}]')
        result = shell(f"yd-create {spec}")
        assert result.exit_code == 1
        assert _has_error(result)
        assert "WibbleWobbleUnknown" in _output(result)


# ---------------------------------------------------------------------------
# Soft failures (exit code 0, the error marker in stderr)
# ---------------------------------------------------------------------------


@pytest.mark.system
class TestSoftFailures:
    """
    Commands that process a list of items and report per-item errors without
    aborting. The process exits 0 even though errors occurred.
    """

    def test_show_unrecognised_ydid_format(self):
        # No platform needed — YDID type lookup is client-side
        result = shell("yd-show not-a-valid-ydid")
        assert result.exit_code == 0
        assert _has_error(result)
        assert "not-a-valid-ydid" in _output(result)

    def test_show_nonexistent_ydid(self):
        # Needs platform — resource lookup returns 404
        fake = f"{YDID}:{TYPE_KEYRING}:000000:00000000-0000-0000-0000-000000000000"
        result = shell(f"yd-show {fake}")
        assert result.exit_code == 0
        assert _has_error(result)
        assert "not found" in _output(result)

    def test_show_mixed_valid_and_invalid_ydids(self):
        # Needs platform — verifies that one bad YDID doesn't abort the rest
        fake = f"{YDID}:{TYPE_KEYRING}:000000:00000000-0000-0000-0000-000000000000"
        bad_format = "not-a-ydid"
        result = shell(f"yd-show {fake} {bad_format}")
        assert result.exit_code == 0
        # Both errors should be reported
        assert _output(result).count(ERROR_MARKER) >= 2
