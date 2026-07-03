"""
Tests for the shared rclone version helpers (utils/rclone_version): the lookup
order, parsing of `rclone --version` output, and not-installed handling.
"""

from types import SimpleNamespace
from unittest.mock import patch

import yellowdog_cli.utils.rclone_version as rv


def _run(stdout: str):
    return SimpleNamespace(stdout=stdout)


def test_parses_version_from_system_path():
    with (
        patch("shutil.which", return_value="/usr/bin/rclone"),
        patch("subprocess.run", return_value=_run("rclone v1.74.3\n- os/version: ...")),
    ):
        assert rv.rclone_version() == "1.74.3"


def test_strips_leading_v():
    with (
        patch("shutil.which", return_value="/usr/bin/rclone"),
        patch("subprocess.run", return_value=_run("rclone v1.68.2")),
    ):
        assert rv.rclone_version() == "1.68.2"


def test_version_without_v_prefix_kept():
    with (
        patch("shutil.which", return_value="/usr/bin/rclone"),
        patch("subprocess.run", return_value=_run("rclone 1.70.0")),
    ):
        assert rv.rclone_version() == "1.70.0"


def test_empty_output_is_unknown():
    with (
        patch("shutil.which", return_value="/usr/bin/rclone"),
        patch("subprocess.run", return_value=_run("")),
    ):
        assert rv.rclone_version() == "unknown"


def test_binary_exec_failure_is_unknown():
    with (
        patch("shutil.which", return_value="/usr/bin/rclone"),
        patch("subprocess.run", side_effect=OSError("boom")),
    ):
        assert rv.rclone_version() == "unknown"


def test_falls_back_to_rclone_api_cache_when_not_on_path():
    fake_exe = SimpleNamespace(exists=lambda: True)
    with (
        patch("shutil.which", return_value=None),
        patch("rclone_api.util._RCLONE_EXE", fake_exe),
        patch("subprocess.run", return_value=_run("rclone v1.74.3")) as run,
    ):
        assert rv.rclone_version() == "1.74.3"
        # It should have invoked the cached binary path, not a PATH lookup.
        assert run.call_args.args[0][0] == str(fake_exe)


def test_not_installed_when_absent_everywhere():
    fake_exe = SimpleNamespace(exists=lambda: False)
    with (
        patch("shutil.which", return_value=None),
        patch("rclone_api.util._RCLONE_EXE", fake_exe),
    ):
        assert rv.rclone_version() == "Not installed"


def test_find_rclone_reports_system_path_source():
    with patch("shutil.which", return_value="/usr/bin/rclone"):
        assert rv.find_rclone() == ("/usr/bin/rclone", "system PATH")


def test_find_rclone_reports_cache_source():
    fake_exe = SimpleNamespace(exists=lambda: True)
    with (
        patch("shutil.which", return_value=None),
        patch("rclone_api.util._RCLONE_EXE", fake_exe),
    ):
        assert rv.find_rclone() == (str(fake_exe), "rclone_api cache")


def test_rclone_version_line_returns_first_line():
    with patch("subprocess.run", return_value=_run("rclone v1.74.3\nmore\n")):
        assert rv.rclone_version_line("/usr/bin/rclone") == "rclone v1.74.3"
