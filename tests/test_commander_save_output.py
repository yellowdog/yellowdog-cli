"""
Tests for saving the Commander command-output window to a file. The file dialog
itself is stubbed — what matters is what gets written, what happens when the user
dismisses the dialog, and that a failure to write is reported rather than swallowed.
"""

import pytest
import qt_guard

qt_guard.require_qt()

from PyQt6.QtWidgets import QPushButton

from yellowdog_cli.commander.commander import (
    SAVED_OUTPUT_NAME_FORMAT,
    YellowDogApp,
)


@pytest.fixture
def window(qapp):
    return YellowDogApp()


def test_save_button_exists_and_is_wired(window):
    assert isinstance(window.save_command_output, QPushButton)
    assert window.save_command_output.text() == "Save Command Output"


def test_saves_the_output_to_the_chosen_file(window, tmp_path, monkeypatch):
    target = tmp_path / "chosen.txt"
    monkeypatch.setattr(window, "_save_file", lambda **kwargs: str(target))
    window.log_output.setPlainText("first line\nsecond line")

    window._save_output_action()

    assert target.read_text(encoding="utf-8") == "first line\nsecond line\n"
    assert f"Saved command output to '{target}'" in window.log_output.toPlainText()


def test_does_not_double_up_a_trailing_newline(window, tmp_path, monkeypatch):
    target = tmp_path / "chosen.txt"
    monkeypatch.setattr(window, "_save_file", lambda **kwargs: str(target))
    window.log_output.setPlainText("already newline-terminated\n")

    window._save_output_action()

    assert target.read_text(encoding="utf-8") == "already newline-terminated\n"


def test_non_ascii_output_survives_the_round_trip(window, tmp_path, monkeypatch):
    # yd-* commands emit non-ASCII (the '—' in Commander's own messages, entity
    # names, remote paths), and Windows would default to a narrower encoding.
    target = tmp_path / "chosen.txt"
    monkeypatch.setattr(window, "_save_file", lambda **kwargs: str(target))
    window.log_output.setPlainText("cannot delete by path — wildcard: pyex-ünïcode")

    window._save_output_action()

    assert "— wildcard: pyex-ünïcode" in target.read_text(encoding="utf-8")


def test_empty_output_writes_nothing_and_never_opens_the_dialog(window, monkeypatch):
    def fail(**kwargs):
        raise AssertionError("the dialog must not open when there is no output")

    monkeypatch.setattr(window, "_save_file", fail)
    window.log_output.setPlainText("")

    window._save_output_action()

    assert "No command output to save" in window.log_output.toPlainText()


def test_dismissing_the_dialog_writes_nothing(window, tmp_path, monkeypatch):
    target = tmp_path / "untouched.txt"
    monkeypatch.setattr(window, "_save_file", lambda **kwargs: None)
    window.log_output.setPlainText("some output")

    window._save_output_action()

    assert not target.exists()
    assert "Saved command output" not in window.log_output.toPlainText()


def test_a_write_failure_is_reported_not_swallowed(window, tmp_path, monkeypatch):
    # A directory that does not exist: open() raises OSError. The user must be
    # told, rather than being left believing the save succeeded.
    target = tmp_path / "no-such-dir" / "out.txt"
    monkeypatch.setattr(window, "_save_file", lambda **kwargs: str(target))
    window.log_output.setPlainText("some output")

    window._save_output_action()

    logged = window.log_output.toPlainText()
    assert f"Could not save command output to '{target}'" in logged
    assert "Saved command output" not in logged


def test_the_dialog_is_prefilled_with_a_timestamped_name_in_the_working_dir(
    window, monkeypatch
):
    seen: dict = {}
    monkeypatch.setattr(
        window, "_save_file", lambda **kwargs: seen.update(kwargs) or None
    )
    window.log_output.setPlainText("some output")

    window._save_output_action()

    assert seen["directory"].startswith(window._working_dir())
    assert seen["directory"].endswith(".txt")
    # a colon would be an invalid filename character on Windows
    assert ":" not in seen["directory"].removeprefix(window._working_dir())
    assert "commander-output-" in seen["directory"]


def test_the_name_format_is_filename_safe():
    # Guards the constant itself: the output-window line prefix uses a
    # ':'-separated time, which cannot be reused here.
    assert ":" not in SAVED_OUTPUT_NAME_FORMAT
    assert SAVED_OUTPUT_NAME_FORMAT.endswith(".txt")
