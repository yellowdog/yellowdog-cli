"""
The 'yd' command (yellowdog_cli/yd.py): the word after it selects a noun,
whose verb is run, or a command, run with its prog 'yd <word>'.
"""

import sys
from types import SimpleNamespace

import pytest

from yellowdog_cli import yd
from yellowdog_cli.utils import invocation, noun_dispatch
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.exit_codes import ExitCode


@pytest.fixture(autouse=True)
def _no_selection(monkeypatch):
    monkeypatch.setattr(invocation, "_SELECTED", None)


@pytest.fixture
def ran(monkeypatch):
    """
    What the dispatcher ran: the module, the command line handed on and the
    selection, with stand-ins for the modules.
    """
    record = SimpleNamespace(module=None, argv=None, selected=None)

    def main():
        record.argv = list(sys.argv)
        record.selected = invocation.selected()

    def import_module(name):
        record.module = name
        return SimpleNamespace(main=main)

    monkeypatch.setattr(yd, "import_module", import_module)
    monkeypatch.setattr(noun_dispatch, "import_module", import_module)
    return record


def _run(monkeypatch, *words: str, argv0: str = "/usr/local/bin/yd") -> None:
    monkeypatch.setattr(sys, "argv", [argv0, *words])
    yd.main()


def test_a_noun_runs_its_verb(monkeypatch, ran):
    _run(monkeypatch, "wr", "submit", "-y", "wr.json")
    assert ran.module == "yellowdog_cli.submit"
    assert ran.selected == ("yd workrequirement submit", "yd wr submit")
    assert ran.argv == ["/usr/local/bin/yd", "-y", "wr.json"]


def test_windows_exe(monkeypatch, ran):
    _run(monkeypatch, "list", "wr", argv0=r"C:\Python\Scripts\yd.exe")
    assert ran.selected == ("yd-list", "yd list")


def test_a_command_runs_with_its_prog(monkeypatch, ran):
    _run(monkeypatch, "list", "work-requirements")
    assert ran.module == "yellowdog_cli.list"
    assert ran.selected == ("yd-list", "yd list")
    assert ran.argv == ["/usr/local/bin/yd", "work-requirements"]


def test_an_other_command(monkeypatch, ran):
    _run(monkeypatch, "commander", "config.toml")
    assert ran.module == "yellowdog_cli.commander.launcher"
    assert ran.selected == ("yd-commander", "yd commander")


def test_no_word_prints_the_listing_on_stderr(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exit_:
        _run(monkeypatch)
    assert exit_.value.code == ExitCode.USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "yd workrequirement" in captured.err


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_prints_the_listing_on_stdout(monkeypatch, capsys, flag):
    with pytest.raises(SystemExit) as exit_:
        _run(monkeypatch, flag)
    assert exit_.value.code == ExitCode.SUCCESS
    assert "yd workrequirement" in capsys.readouterr().out


def test_an_unknown_word_is_a_usage_error(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exit_:
        _run(monkeypatch, "frob")
    assert exit_.value.code == ExitCode.USAGE
    err = capsys.readouterr().err
    assert "usage: yd <command>" in err
    assert "unknown command 'frob'" in err and "wr" in err and "list" in err


def test_an_option_before_the_word_is_a_usage_error(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exit_:
        _run(monkeypatch, "-q", "list")
    assert exit_.value.code == ExitCode.USAGE
    assert "a command must come before '-q'" in capsys.readouterr().err


def test_a_noun_with_no_verb_shows_the_noun_as_typed(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exit_:
        _run(monkeypatch, "wr")
    assert exit_.value.code == ExitCode.USAGE
    assert "usage: yd wr <verb>" in capsys.readouterr().err


def test_a_nouns_help(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exit_:
        _run(monkeypatch, "wr", "--help")
    assert exit_.value.code == ExitCode.SUCCESS
    assert "usage: yd wr <verb>" in capsys.readouterr().out


def test_a_verbs_parser_shows_its_prog(monkeypatch, ran):
    _run(monkeypatch, "wr", "submit")
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/yd", "wr.json"])
    assert CLIParser().parser.prog == "yd wr submit"


def test_a_commands_parser_shows_its_prog(monkeypatch, ran):
    _run(monkeypatch, "list", "work-requirements")
    assert CLIParser().parser.prog == "yd list"


@pytest.mark.parametrize(
    "word", ["help", "version", "format-json", "jsonnet2json", "commander", "mcp"]
)
def test_a_standalone_parser_shows_its_prog(monkeypatch, capsys, word):
    if word == "mcp":
        pytest.importorskip("mcp")
    with pytest.raises(SystemExit) as exit_:
        _run(monkeypatch, word, "--help")
    assert exit_.value.code == ExitCode.SUCCESS
    assert f"usage: yd {word}" in capsys.readouterr().out
