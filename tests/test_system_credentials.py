"""
The Platform credentials '--run-system' runs with: conftest.py's
_use_system_test_credentials() takes them from the live system tests'
configuration ([platform], or YDST_PLATFORM_*), never from the shell, so
every test that talks to the Platform does so as the one Application.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

PLATFORM = """
[platform]
key = "app-key-1234567890"
secret = "app-secret-abcdefghijklmnop"
"""


def _root_conftest():
    """
    The repository's conftest.py, loaded by its path: 'import conftest'
    finds whichever conftest pytest imported last.
    """
    path = Path(__file__).resolve().parents[1] / "conftest.py"
    spec = importlib.util.spec_from_file_location("root_conftest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config(*, run_system: bool):
    return SimpleNamespace(getoption=lambda name: run_system and name == "--run-system")


def _environ(tmp_path, text: str, **extra: str) -> dict[str, str]:
    path = tmp_path / "system-tests.toml"
    path.write_text(text, encoding="utf-8")
    return {"YDST_CONFIG": str(path), **extra}


def test_run_system_takes_the_platform_from_the_live_configuration(tmp_path):
    environ = _environ(
        tmp_path,
        PLATFORM,
        YD_KEY="shell-key",
        YD_SECRET="shell-secret",
        YD_URL="https://shell.example",
    )
    _root_conftest()._use_system_test_credentials(_config(run_system=True), environ)
    assert environ["YD_KEY"] == "app-key-1234567890"
    assert environ["YD_SECRET"] == "app-secret-abcdefghijklmnop"
    # The file names no URL, so the shell's is not left to stand in for one
    assert "YD_URL" not in environ


def test_a_configured_url_is_used(tmp_path):
    environ = _environ(tmp_path, PLATFORM + 'url = "https://file.example"\n')
    _root_conftest()._use_system_test_credentials(_config(run_system=True), environ)
    assert environ["YD_URL"] == "https://file.example"


def test_missing_credentials_stop_the_session_naming_the_problem(tmp_path):
    environ = _environ(tmp_path, '[platform]\nkey = "k"\n', YD_SECRET="shell")
    with pytest.raises(pytest.UsageError, match=r"\[platform\] needs secret"):
        _root_conftest()._use_system_test_credentials(_config(run_system=True), environ)


def test_without_run_system_nothing_is_touched(tmp_path):
    environ = _environ(tmp_path, PLATFORM, YD_KEY="shell-key")
    before = dict(environ)
    _root_conftest()._use_system_test_credentials(_config(run_system=False), environ)
    assert environ == before
