"""
'yd init': a starter configuration file, written to config.toml in the
current directory or, with --user, the user's own; the [common] values asked
for, the environment's offered, or taken without asking under --yes; an
existing file replaced only with --overwrite; a file holding a secret
readable by its owner alone.
"""

import os
import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib

from yellowdog_cli import init as yd_init
from yellowdog_cli.utils import invocation
from yellowdog_cli.utils.exit_codes import ExitCode
from yellowdog_cli.utils.invocation import select_command

_ENVIRONMENT = ("YD_KEY", "YD_SECRET", "YD_NAMESPACE", "YD_TAG", "YD_URL")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    # The dispatcher's selection, which _run() makes, is the process's: put
    # back after each test, or a later test's parser would be yd init's
    monkeypatch.setattr(invocation, "_SELECTED", None)
    for name in _ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)


def _run(monkeypatch, *args: str, answers: list[str] | None = None) -> None:
    select_command("yd-init", "yd init")
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/yd", *args])
    if answers is not None:
        remaining = list(answers)
        asked = []

        def ask(prompt: str, secret: bool = False) -> str:
            asked.append((prompt, secret))
            return remaining.pop(0)

        monkeypatch.setattr(yd_init, "ask", ask)
        yd_init.main()
        assert not remaining
    else:
        monkeypatch.setattr(
            yd_init, "ask", lambda *_a, **_k: pytest.fail("asked without a terminal")
        )
        yd_init.main()


def _common(path: str | Path = "config.toml") -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)["common"]


def test_yes_takes_the_environments_values(monkeypatch):
    monkeypatch.setenv("YD_KEY", "a-key")
    monkeypatch.setenv("YD_SECRET", "a-secret")
    monkeypatch.setenv("YD_NAMESPACE", "my-ns")
    monkeypatch.setenv("YD_TAG", "my-tag")
    _run(monkeypatch, "--yes")
    assert _common() == {
        "key": "a-key",
        "secret": "a-secret",
        "namespace": "my-ns",
        "tag": "my-tag",
    }


def test_the_answers_are_written(monkeypatch):
    _run(
        monkeypatch,
        answers=["the-key", "the-secret", "ns", "tg", "https://example.com/api"],
    )
    assert _common() == {
        "key": "the-key",
        "secret": "the-secret",
        "namespace": "ns",
        "tag": "tg",
        "url": "https://example.com/api",
    }


def test_enter_keeps_the_environments_value(monkeypatch):
    monkeypatch.setenv("YD_KEY", "env-key")
    monkeypatch.setenv("YD_NAMESPACE", "env-ns")
    _run(monkeypatch, answers=["", "typed-secret", "", "", ""])
    assert _common() == {
        "key": "env-key",
        "secret": "typed-secret",
        "namespace": "env-ns",
    }


def test_the_secret_is_asked_for_hidden(monkeypatch):
    asked = []

    def ask(prompt: str, secret: bool = False) -> str:
        asked.append(secret)
        return ""

    select_command("yd-init", "yd init")
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/yd"])
    monkeypatch.setattr(yd_init, "ask", ask)
    yd_init.main()
    assert asked == [False, True, False, False, False]


def test_a_value_not_given_is_left_commented_out(monkeypatch):
    _run(monkeypatch, "--yes")
    text = Path("config.toml").read_text(encoding="utf-8")
    assert _common() == {}
    assert '# key = ""' in text
    assert '# url = "https://api.yellowdog.ai"' in text


def test_awkward_text_is_written_as_toml_reads_it(monkeypatch):
    monkeypatch.setenv("YD_TAG", 'a "quoted" \\ tag')
    _run(monkeypatch, "--yes")
    assert _common()["tag"] == 'a "quoted" \\ tag'


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_a_file_holding_a_secret_is_the_owners_alone(monkeypatch):
    monkeypatch.setenv("YD_SECRET", "s")
    _run(monkeypatch, "--yes")
    assert os.stat("config.toml").st_mode & 0o777 == 0o600


def test_an_existing_file_is_refused_before_anything_is_asked(monkeypatch, capsys):
    Path("config.toml").write_text("# mine\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exit_:
        _run(monkeypatch, "--yes")
    assert exit_.value.code == ExitCode.FAILURE
    assert "--overwrite" in capsys.readouterr().err
    assert Path("config.toml").read_text(encoding="utf-8") == "# mine\n"


def test_overwrite_replaces_it(monkeypatch):
    Path("config.toml").write_text("# mine\n", encoding="utf-8")
    monkeypatch.setenv("YD_NAMESPACE", "ns")
    _run(monkeypatch, "--yes", "--overwrite")
    assert _common() == {"namespace": "ns"}


def test_user_writes_the_users_own_file(monkeypatch, tmp_path):
    monkeypatch.setenv("YD_NAMESPACE", "ns")
    _run(monkeypatch, "--yes", "--user")
    user_file = tmp_path / "xdg" / "yellowdog" / "config.toml"
    assert _common(user_file) == {"namespace": "ns"}
    assert not Path("config.toml").exists()


def test_writing_the_users_own_says_a_local_file_comes_first(monkeypatch, capsys):
    Path("config.toml").write_text("", encoding="utf-8")
    _run(monkeypatch, "--yes", "--user")
    out = capsys.readouterr()
    assert "config.toml in this directory is read in its place" in (
        out.out + out.err
    ).replace("\n", " ")


def test_it_says_what_to_run_next(monkeypatch, capsys):
    _run(monkeypatch, "--yes")
    assert "yd doctor" in capsys.readouterr().out
