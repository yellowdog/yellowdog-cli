"""
The '--json' result accumulator (yellowdog_cli/utils/results.py), and the
stderr routing of warnings and prompts under '--json'.

A command records its outcomes as it goes; the wrapper prints them once, as
one JSON document, when the command returns or fails. Without '--json' nothing
is printed. These tests parse stdout rather than asserting what was handed to
a printer, since a well-formed document is the contract.
"""

import io
from json import loads as json_loads
from unittest.mock import MagicMock

import pytest
from yellowdog_client.model import KeyringSummary

import yellowdog_cli.utils.interactive as interactive_module
import yellowdog_cli.utils.printing as printing_module
import yellowdog_cli.utils.results as results_module
from yellowdog_cli.utils.results import (
    any_failed,
    flush_results,
    record,
    record_document,
    reset_results,
)


def _args(json_output: bool | None, **overrides) -> MagicMock:
    values = {
        "json_output": json_output,
        "strip_ids": False,
        "quiet": False,
        "no_format": True,
        "count_only": False,
        "print_pid": False,
        "output_file": None,
    }
    values.update(overrides)
    return MagicMock(**values)


@pytest.fixture()
def json_mode(monkeypatch):
    """Patch both modules' ARGS_PARSER; return a setter for the mode."""

    def set_mode(json_output: bool | None, **overrides) -> MagicMock:
        args = _args(json_output, **overrides)
        monkeypatch.setattr(results_module, "ARGS_PARSER", args)
        monkeypatch.setattr(printing_module, "ARGS_PARSER", args)
        return args

    reset_results()
    yield set_mode
    reset_results()


class TestFlush:
    def test_recorded_items_are_one_array(self, json_mode, capsys):
        json_mode(True)
        record({"id": "a", "outcome": "cancelled"})
        record({"id": "b", "outcome": "skipped"})
        flush_results()
        assert json_loads(capsys.readouterr().out) == [
            {"id": "a", "outcome": "cancelled"},
            {"id": "b", "outcome": "skipped"},
        ]

    def test_an_sdk_object_is_serialised_as_its_dict(self, json_mode, capsys):
        json_mode(True)
        record(KeyringSummary(id="i", name="n", description="d"))
        flush_results()
        [item] = json_loads(capsys.readouterr().out)
        assert item["id"] == "i"
        assert item["name"] == "n"
        assert item["description"] == "d"

    def test_strip_ids_applies(self, json_mode, capsys):
        json_mode(True, strip_ids=True)
        record(KeyringSummary(id="i", name="n", description="d"))
        flush_results()
        [item] = json_loads(capsys.readouterr().out)
        assert "id" not in item and item["name"] == "n"

    def test_a_document_is_printed_as_itself(self, json_mode, capsys):
        json_mode(True)
        record_document({"a": 1})
        flush_results()
        assert json_loads(capsys.readouterr().out) == {"a": 1}

    def test_a_document_wins_over_items(self, json_mode, capsys):
        json_mode(True)
        record({"x": 1})
        record_document({"a": 1})
        flush_results()
        assert json_loads(capsys.readouterr().out) == {"a": 1}

    def test_an_sdk_document_is_serialised(self, json_mode, capsys):
        json_mode(True)
        record_document(KeyringSummary(id="i", name="n", description="d"))
        flush_results()
        assert json_loads(capsys.readouterr().out)["name"] == "n"

    def test_nothing_recorded_is_an_empty_array(self, json_mode, capsys):
        json_mode(True)
        flush_results()
        assert json_loads(capsys.readouterr().out) == []

    def test_without_json_nothing_is_printed(self, json_mode, capsys):
        json_mode(False)
        record({"id": "a"})
        flush_results()
        assert capsys.readouterr().out == ""

    def test_a_command_without_the_option_prints_nothing(self, json_mode, capsys):
        # ARGS_PARSER.json_output is None where the option is not registered
        json_mode(None)
        flush_results()
        assert capsys.readouterr().out == ""

    def test_flushed_once(self, json_mode, capsys):
        json_mode(True)
        record({"id": "a"})
        flush_results()
        capsys.readouterr()
        flush_results()
        assert capsys.readouterr().out == ""

    def test_reset_clears(self, json_mode, capsys):
        json_mode(True)
        record({"id": "a"})
        flush_results()
        capsys.readouterr()
        reset_results()
        flush_results()
        assert json_loads(capsys.readouterr().out) == []

    def test_a_command_that_printed_its_own_document_is_not_doubled(
        self, json_mode, capsys
    ):
        # yd-list and the '--dry-run --json' listings print their own JSON
        # today; the wrapper's flush must not add a second document after it
        json_mode(True)
        printing_module.print_objects_as_json([{"id": "a"}])
        flush_results()
        assert json_loads(capsys.readouterr().out) == [{"id": "a"}]

    def test_printing_its_own_document_and_recording_is_refused(
        self, json_mode, capsys
    ):
        json_mode(True)
        printing_module.print_objects_as_json([{"id": "a"}])
        record({"id": "b"})
        with pytest.raises(RuntimeError, match="its own JSON document"):
            flush_results()
        # The command's own document stands alone on stdout
        assert json_loads(capsys.readouterr().out) == [{"id": "a"}]

    def test_printing_its_own_document_and_a_recorded_document_is_refused(
        self, json_mode
    ):
        json_mode(True)
        printing_module.print_json({"a": 1})
        record_document({"b": 2})
        with pytest.raises(RuntimeError):
            flush_results()


class TestAnyFailed:
    def test_false_when_nothing_recorded(self, json_mode):
        json_mode(True)
        assert any_failed() is False

    def test_false_when_all_succeeded(self, json_mode):
        json_mode(True)
        record({"id": "a", "outcome": "cancelled"})
        record({"id": "b", "action": "created"})
        assert any_failed() is False

    def test_true_on_a_failed_outcome(self, json_mode):
        json_mode(True)
        record({"id": "a", "outcome": "failed"})
        assert any_failed() is True

    def test_true_on_a_failed_action(self, json_mode):
        json_mode(True)
        record({"id": "a", "action": "failed"})
        assert any_failed() is True

    def test_true_amongst_successes(self, json_mode):
        json_mode(True)
        record({"id": "a", "outcome": "cancelled"})
        record({"id": "b", "outcome": "failed"})
        assert any_failed() is True

    def test_reset_clears_it(self, json_mode):
        json_mode(True)
        record({"id": "a", "outcome": "failed"})
        reset_results()
        assert any_failed() is False


class TestWarningsUnderJson:
    def test_a_warning_goes_to_stderr(self, json_mode, capsys):
        json_mode(True)
        printing_module.print_warning("careful")
        out, err = capsys.readouterr()
        assert out == ""
        assert "careful" in err

    def test_a_warning_goes_to_stderr_with_formatting(self, json_mode, capsys):
        json_mode(True, no_format=False)
        printing_module.print_warning("careful")
        out, err = capsys.readouterr()
        assert out == ""
        assert "careful" in err

    def test_quiet_still_suppresses_it(self, json_mode, capsys):
        json_mode(True, quiet=True)
        printing_module.print_warning("careful")
        assert capsys.readouterr() == ("", "")

    def test_without_json_it_stays_on_stdout(self, json_mode, capsys):
        json_mode(False)
        printing_module.print_warning("careful")
        out, err = capsys.readouterr()
        assert "careful" in out and err == ""


class TestPromptUnderJson:
    def test_the_prompt_goes_to_stderr(self, json_mode, monkeypatch, capsys):
        args = json_mode(True)
        monkeypatch.setattr(interactive_module, "ARGS_PARSER", args)
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")
        assert interactive_module._get_user_input("Proceed? ") == "y"
        out, err = capsys.readouterr()
        assert out == ""
        assert "Proceed?" in err

    def test_without_json_the_prompt_is_unchanged(self, json_mode, monkeypatch, capsys):
        args = json_mode(False)
        monkeypatch.setattr(interactive_module, "ARGS_PARSER", args)
        prompts: list[str] = []
        monkeypatch.setattr(
            "builtins.input", lambda prompt="": prompts.append(prompt) or "n"
        )
        assert interactive_module._get_user_input("Proceed? ") == "n"
        assert prompts == ["Proceed? "]


class TestPromptAtEndOfInput:
    """
    A prompt whose stdin is at end of input — a script that forgot '--yes',
    or a redirect from /dev/null — must fail with a message that says what
    to do, not Python's 'EOF when reading a line'.
    """

    @staticmethod
    def _stdin_at_eof(prompt=""):
        raise EOFError("EOF when reading a line")

    @pytest.mark.parametrize("json_output", [True, False, None])
    def test_the_error_names_the_remedy(self, json_mode, monkeypatch, json_output):
        args = json_mode(json_output)
        monkeypatch.setattr(interactive_module, "ARGS_PARSER", args)
        monkeypatch.setattr("builtins.input", self._stdin_at_eof)
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        with pytest.raises(interactive_module.NoAnswerToPrompt) as excinfo:
            interactive_module._get_user_input("Proceed? ")
        message = str(excinfo.value)
        assert "--yes" in message and "terminal" in message
        assert "EOF when reading a line" not in message

    def test_under_json_stdout_stays_empty(self, json_mode, monkeypatch, capsys):
        args = json_mode(True)
        monkeypatch.setattr(interactive_module, "ARGS_PARSER", args)
        monkeypatch.setattr("builtins.input", self._stdin_at_eof)
        with pytest.raises(interactive_module.NoAnswerToPrompt):
            interactive_module._get_user_input("Proceed? ")
        out, err = capsys.readouterr()
        assert out == ""
        assert "Proceed?" in err
