"""
A misspelt word is answered with the word meant, where one is close enough:
a command after 'yd', a noun's verb, an option, a sort key and a resource
type. With nothing close, the choices are listed as before.
"""

import sys
from argparse import ArgumentTypeError

import pytest

from yellowdog_cli import yd
from yellowdog_cli.utils.command_registry import (
    build_parser,
    parse_sort_keys,
    resolve_resource_type,
)
from yellowdog_cli.utils.exit_codes import ExitCode
from yellowdog_cli.utils.noun_registry import command_named
from yellowdog_cli.utils.suggestions import did_you_mean


def _refused(monkeypatch, capsys, *words: str) -> str:
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/yd", *words])
    with pytest.raises(SystemExit) as exit_:
        yd.main()
    assert exit_.value.code == ExitCode.USAGE
    return capsys.readouterr().err


class TestDidYouMean:
    def test_the_closest_word(self):
        assert did_you_mean("submti", ["submit", "cancel"]) == "did you mean 'submit'?"

    def test_nothing_close(self):
        assert did_you_mean("frob", ["submit", "cancel"]) is None

    def test_only_the_closest_of_several_close_words(self):
        assert did_you_mean("star", ["start", "stop", "status"]) == (
            "did you mean 'start'?"
        )

    def test_words_equally_close(self):
        assert did_you_mean("cat", ["bat", "hat", "dog"]) == (
            "did you mean 'bat' or 'hat'?"
        )


def test_a_misspelt_command(monkeypatch, capsys):
    err = _refused(monkeypatch, capsys, "workrequirment", "list")
    assert "unknown command 'workrequirment'; did you mean 'workrequirement'?" in err
    assert "choose from" not in err


def test_an_unknown_command_with_nothing_close_lists_the_commands(monkeypatch, capsys):
    err = _refused(monkeypatch, capsys, "frob")
    assert "unknown command 'frob'; choose from:" in err


def test_a_misspelt_verb(monkeypatch, capsys):
    err = _refused(monkeypatch, capsys, "wr", "submti")
    assert "unknown verb 'submti'; did you mean 'submit'?" in err


def test_an_unknown_verb_with_nothing_close_lists_the_verbs(monkeypatch, capsys):
    err = _refused(monkeypatch, capsys, "wr", "frob")
    assert "unknown verb 'frob'; choose from: submit, cancel" in err


def _option_error(capsys, name: str, *argv: str) -> str:
    parser = build_parser(command_named(name), prog=name)
    with pytest.raises(SystemExit) as exit_:
        parser.parse_args(list(argv))
    assert exit_.value.code == ExitCode.USAGE
    return capsys.readouterr().err


def test_a_misspelt_option(capsys):
    err = _option_error(capsys, "yd list", "work-requirements", "--namepsace", "x")
    assert "unrecognized arguments: --namepsace x" in err
    assert "'--namepsace': did you mean '--namespace'?" in err


def test_a_misspelt_option_given_a_value_with_equals(capsys):
    err = _option_error(capsys, "yd list", "work-requirements", "--namepsace=x")
    assert "'--namepsace': did you mean '--namespace'?" in err


def test_an_unknown_option_with_nothing_close(capsys):
    err = _option_error(capsys, "yd wr cancel", "--frobnicate")
    assert "unrecognized arguments: --frobnicate" in err
    assert "did you mean" not in err


def test_a_hidden_option_is_never_suggested(capsys):
    # 'yd data list' hides '--dry-run' (noun_registry.py)
    err = _option_error(capsys, "yd data list", "--dry-rn")
    assert "--dry-run" not in err.split("error:")[1]


def test_a_misspelt_sort_key():
    with pytest.raises(ArgumentTypeError, match="did you mean 'created'"):
        parse_sort_keys("craeted", ("name", "created", "status"))


def test_a_misspelt_resource_type():
    with pytest.raises(ArgumentTypeError, match="did you mean 'Keyring'"):
        resolve_resource_type("Keyrnig")
