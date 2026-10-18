"""
tests/live/sweep.py: clearing up after dead runs, against a scripted 'yd'.
"""

import importlib.util
import os
from pathlib import Path

import pytest
from harness import config
from live_fake_yd import FakeYd, result
from live_samples import AWS, PLATFORM, write_config

OLD = "ydst-2001011200-aaaa"  # Long ago, so stale whatever the age guard


def _sweep_module():
    path = Path(__file__).parent / "sweep.py"
    spec = importlib.util.spec_from_file_location("live_sweep", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """
    sweep.py reads os.environ: drop the developer's own YDST_* and YD_*
    variables, and never read their real configuration file.
    """
    for name in list(os.environ):
        if name.startswith(("YDST_", "YD_")):
            monkeypatch.delenv(name)
    monkeypatch.setattr(config, "DEFAULT_PATH", tmp_path / "absent.toml")


@pytest.fixture
def configured(monkeypatch, tmp_path):
    for name, value in write_config(tmp_path, PLATFORM + AWS).items():
        monkeypatch.setenv(name, value)


def _platform_with_an_old_run(args):
    if args[:2] == ("list", "keyrings"):
        keyring = {
            "id": "ydid:keyring:1",
            "name": f"{OLD}-keyring",
            "description": f"Live system tests, run {OLD}, namespace yd-cli-system-tests",
        }
        return result(args, document=[keyring])
    return result(args, document=[])


def test_a_dry_run_names_the_stale_run_and_removes_nothing(configured, capsys):
    fake = FakeYd(_platform_with_an_old_run)
    assert _sweep_module().main(["--dry-run"], make_yd=lambda run: fake) == 0
    assert f"Would sweep run {OLD}" in capsys.readouterr().out
    assert not any(call[:2] == ("resource", "remove") for call in fake.calls)


def test_a_sweep_tears_the_stale_run_down(configured):
    fake = FakeYd(_platform_with_an_old_run)
    assert _sweep_module().main([], make_yd=lambda run: fake) == 0
    assert ("resource", "remove", "--ids", "ydid:keyring:1") in [
        c[:4] for c in fake.calls
    ]


def test_a_named_run_is_torn_down_without_discovery(configured):
    fake = FakeYd(_platform_with_an_old_run)
    assert _sweep_module().main(["--run", OLD], make_yd=lambda run: fake) == 0
    assert fake.calls[0][:2] == ("wr", "cancel")


def test_a_name_that_is_not_a_run_id_is_refused(configured, capsys):
    assert _sweep_module().main(["--run", "ydst-nope"], make_yd=FakeYd) == 2
    assert "not a run ID" in capsys.readouterr().err


def test_a_broken_configuration_exits_2(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("YDST_CONFIG", str(tmp_path / "missing.toml"))
    assert _sweep_module().main([], make_yd=FakeYd) == 2
    assert "YDST_CONFIG names" in capsys.readouterr().err


def test_problems_exit_1(configured):
    def respond(args):
        if args[:2] == ("resource", "remove"):
            return result(args, exit_code=1)
        return _platform_with_an_old_run(args)

    assert _sweep_module().main([], make_yd=lambda run: FakeYd(respond)) == 1
