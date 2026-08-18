"""
Tests for Commander's notice dialog: a modal that says what a click did not do,
for cases where the output window's log line is easy to miss.

Applied so far to one case — View Results Directory with no results directory
yet, the case a user missed on Windows. The other dead-end notices deliberately
remain log-only, and one of the tests here holds that line, so extending the
dialog to them stays a decision rather than a side effect.
"""

import pytest
import qt_guard

qt_guard.require_qt()

from os.path import join

import commander_dialogs
import gui_harness
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton

from yellowdog_cli.commander.commander import RESULTS_DIR, YellowDogApp


@pytest.fixture
def window(qapp, tmp_path):
    win = YellowDogApp()
    # Anchor the working directory: _view_results_action looks for 'results'
    # beside the selected configuration file.
    config_file = tmp_path / "config.toml"
    config_file.write_text('[common]\nnamespace = "yd-demo"\n')
    win._config_file = str(config_file)
    win.log_output.setPlainText("")
    return win


@pytest.fixture
def never_browses(window, monkeypatch):
    """Fail loudly if a browse dialog is opened; these tests are about not opening one."""

    def refuse(*_args, **_kwargs):
        raise AssertionError("a browse dialog was opened for a missing directory")

    monkeypatch.setattr(window, "_browse_with_preview", refuse)


def test_a_missing_results_directory_is_reported_in_a_dialog(
    window, monkeypatch, never_browses, tmp_path
):
    shown = commander_dialogs.drive_notice(window, monkeypatch)

    window._view_results_action()

    assert shown["count"] == 1
    expected = join(str(tmp_path), RESULTS_DIR)
    assert expected in (shown["message"] or "")
    assert "does not (yet) exist" in (shown["message"] or "")


def test_the_notice_is_logged_as_well_as_shown(window, monkeypatch, never_browses):
    commander_dialogs.drive_notice(window, monkeypatch)

    window._view_results_action()

    # The output window keeps the whole narrative, timestamps and all; the dialog
    # is there so the notice is not only in a window nobody is watching.
    assert "does not (yet) exist" in window.log_output.toPlainText()


def test_the_notice_carries_one_ok_button_that_closes_it(window, monkeypatch):
    seen: dict = {}

    def inspect(dialog):
        buttons = dialog.findChildren(QPushButton)
        seen["labels"] = [button.text().replace("&", "") for button in buttons]
        seen["parent"] = dialog.parent()

    dialog = window._build_notice_dialog("Directory 'x' does not (yet) exist")
    gui_harness.run_modal(
        dialog,
        lambda open_dialog: (
            inspect(open_dialog),
            gui_harness.button_labelled(open_dialog, "OK").click(),
        ),
    )

    assert seen["labels"] == ["OK"], "a notice asks nothing, so it needs one button"
    assert seen["parent"] is window


def test_a_windows_path_is_not_interpreted_as_markup(window, monkeypatch):
    # A real report: 'C:\\Users\\Peter Toft\\...\\results'. Rich text would eat the
    # backslashes, and a name containing <...> would vanish entirely.
    message = r"Directory 'C:\Users\Peter Toft\<demo>\results' does not (yet) exist"
    dialog = window._build_notice_dialog(message)

    assert dialog.text() == message
    assert dialog.textFormat() == Qt.TextFormat.PlainText


def test_an_existing_results_directory_browses_instead_of_notifying(
    window, monkeypatch, tmp_path
):
    (tmp_path / RESULTS_DIR).mkdir()
    browsed: list[str] = []
    monkeypatch.setattr(
        window,
        "_browse_with_preview",
        lambda caption, directory: browsed.append(directory) or None,
    )
    shown = commander_dialogs.drive_notice(window, monkeypatch)

    window._view_results_action()

    assert browsed == [join(str(tmp_path), RESULTS_DIR)]
    assert shown["count"] == 0


def test_an_unattended_session_logs_the_notice_without_a_dialog(
    window, monkeypatch, never_browses
):
    # '--yes' means nobody is there to press OK; a modal would hang the session.
    window._confirmations_disabled = True
    shown = commander_dialogs.drive_notice(window, monkeypatch)

    window._view_results_action()

    assert shown["count"] == 0
    assert "does not (yet) exist" in window.log_output.toPlainText()


def test_shutting_down_logs_the_notice_without_a_dialog(
    window, monkeypatch, never_browses
):
    window._shutting_down = True
    shown = commander_dialogs.drive_notice(window, monkeypatch)

    window._view_results_action()

    assert shown["count"] == 0


def test_the_config_directory_button_stays_log_only(window, monkeypatch, tmp_path):
    # Deliberately out of scope for now: only the results directory notifies.
    window._config_file = str(tmp_path / "gone" / "config.toml")
    shown = commander_dialogs.drive_notice(window, monkeypatch)

    window._view_config_directory_action()

    assert shown["count"] == 0
    assert "does not (yet) exist" in window.log_output.toPlainText()
