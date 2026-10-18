"""
tests/live/check_config.py: the configuration loaded as a run loads it, with
nothing remote: its summary and warnings, or every problem.
"""

import importlib.util
import os
from pathlib import Path

import pytest
from harness import config
from live_samples import AWS, PLATFORM, write_config


def _check_module():
    path = Path(__file__).parent / "check_config.py"
    spec = importlib.util.spec_from_file_location("live_check_config", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """
    check_config.py reads os.environ: drop the developer's own YDST_*
    variables, and never read their real configuration file.
    """
    for name in list(os.environ):
        if name.startswith("YDST_"):
            monkeypatch.delenv(name)
    monkeypatch.setattr(config, "DEFAULT_PATH", tmp_path / "absent.toml")


def _configure(monkeypatch, tmp_path, text):
    for name, value in write_config(tmp_path, text).items():
        monkeypatch.setenv(name, value)


def test_a_sound_configuration_is_summarised(monkeypatch, tmp_path, capsys):
    _configure(monkeypatch, tmp_path, PLATFORM + AWS)
    assert _check_module().main() == 0
    out = capsys.readouterr().out
    assert out.startswith("live config: ")
    assert "providers: aws (primary aws)" in out


def test_its_warnings_are_shown(monkeypatch, tmp_path, capsys):
    _configure(monkeypatch, tmp_path, PLATFORM + AWS + '[run]\nnamespace = "x"\n')
    assert _check_module().main() == 0
    assert "warning: [run] namespace is no longer used" in capsys.readouterr().out


def test_every_problem_is_listed_and_exits_2(monkeypatch, tmp_path, capsys):
    text = PLATFORM + AWS.replace("region", "regoin") + "[azur]\n"
    _configure(monkeypatch, tmp_path, text)
    assert _check_module().main() == 2
    err = capsys.readouterr().err
    assert "unknown section [azur]" in err
    assert "[aws] has no key 'regoin'" in err


def test_no_secret_is_shown(monkeypatch, tmp_path, capsys):
    _configure(monkeypatch, tmp_path, PLATFORM + AWS)
    _check_module().main()
    shown = capsys.readouterr()
    for secret in config.load_live_config().secrets():
        assert secret not in shown.out + shown.err
