"""
The shell Commander's command box hands a non-'yd-' command to
(host.shell_command()): by full path, since started as the bare 'cmd' it failed
on Windows with 'Access is denied'. Qt-free.
"""

import os

import pytest

from yellowdog_cli.commander import host


@pytest.fixture
def on_windows(monkeypatch):
    monkeypatch.setattr(host, "WINDOWS", True)


def test_windows_uses_comspec(on_windows, monkeypatch, tmp_path):
    comspec = tmp_path / "cmd.exe"
    comspec.write_text("")
    monkeypatch.setenv("ComSpec", str(comspec))
    assert host.shell_command() == (str(comspec), "/c")


def test_windows_falls_back_to_system32(on_windows, monkeypatch, tmp_path):
    system32 = tmp_path / "System32"
    system32.mkdir()
    (system32 / "cmd.exe").write_text("")
    monkeypatch.delenv("ComSpec", raising=False)
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    assert host.shell_command() == (
        os.path.join(str(tmp_path), "System32", "cmd.exe"),
        "/c",
    )


def test_a_comspec_that_is_not_a_file_is_not_used(on_windows, monkeypatch, tmp_path):
    # A directory is exactly what 'Access is denied' is made of
    monkeypatch.setenv("ComSpec", str(tmp_path))
    monkeypatch.setenv("SystemRoot", str(tmp_path / "nowhere"))
    assert host.shell_command() == ("cmd", "/c")


def test_elsewhere_the_shell_is_bin_sh(monkeypatch):
    monkeypatch.setattr(host, "WINDOWS", False)
    shell, flag = host.shell_command()
    assert flag == "-c"
    assert shell == ("/bin/sh" if os.path.isfile("/bin/sh") else "sh")
