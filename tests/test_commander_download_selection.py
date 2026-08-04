"""
Tests for choosing which objects a Commander download fetches. The chooser is a
non-destructive dialog, so it deliberately differs from the destructive
confirmation: no warning icon and no 'Don't Ask Again'. It IS skipped by '--yes',
like the confirmations, since an unattended session cannot answer a chooser either.
What matters here is which paths reach yd-download.
"""

import pytest
import qt_guard

qt_guard.require_qt()

import commander_dialogs
import gui_harness
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QPushButton,
)

from yellowdog_cli.commander.commander import (
    RESULTS_DIR,
    ObjectSummary,
    YellowDogApp,
    object_rows,
)


@pytest.fixture
def window(qapp):
    return YellowDogApp()


@pytest.fixture
def captured(window, monkeypatch):
    """Capture (command, args, kwargs) an action would run, without spawning it."""
    calls: list[tuple[str, list[str], dict]] = []
    monkeypatch.setattr(
        window,
        "_run_command_in_subprocess",
        lambda command, args, **kwargs: calls.append((command, args, kwargs)),
    )
    return calls


def objects() -> list[ObjectSummary]:
    return [
        ObjectSummary(path="S3:b/pfx/pyex-001", name="pyex-001", is_dir=False),
        ObjectSummary(path="S3:b/pfx/pyex-logs", name="pyex-logs/", is_dir=True),
    ]


def drive_chooser(window, monkeypatch, accept: bool, uncheck: tuple = ()):
    """
    Arm the next chooser to untick the given rows and then press Download or Cancel.

    Delegates to commander_dialogs, which lets the dialog run its REAL exec() with
    the interaction queued into it, rather than replacing exec() with a stub that
    returns a chosen result code.
    """
    commander_dialogs.drive_chooser(
        window,
        monkeypatch,
        commander_dialogs.ACCEPT if accept else commander_dialogs.CANCEL,
        untick_rows=uncheck,
    )


def stub_enumeration(window, monkeypatch, enumerated):
    seen: list = []
    monkeypatch.setattr(
        window,
        "_capture_dry_run_objects",
        lambda command, extra_args: seen.append((command, extra_args)) or enumerated,
    )
    return seen


# --- The chooser dialog itself -----------------------------------------------


def test_chooser_has_no_warning_icon_and_no_dont_ask_again(window):
    # A chooser is not a confirmation: nothing it does is irreversible.
    dialog, accept_btn = window._build_chooser_dialog(
        "Download Objects", "Downloading objects.", "Download", object_rows(objects())
    )
    box = dialog.findChild(QDialogButtonBox)
    assert {b.text() for b in box.buttons()} == {"Cancel", "Download"}
    assert accept_btn.text() == "Download"
    assert accept_btn.isDefault() is True


def test_chooser_lists_every_object_ticked_with_a_count(window):
    dialog, _accept = window._build_chooser_dialog(
        "Download Objects", "Downloading objects.", "Download", object_rows(objects())
    )
    listing = dialog.findChild(QListWidget, "selection_list")
    assert [listing.item(i).text() for i in range(2)] == ["pyex-001", "pyex-logs/"]
    assert dialog.findChild(QLabel, "selection_count").text() == "2 of 2 selected"


def test_chooser_accept_button_is_gated_on_a_selection(window):
    dialog, accept_btn = window._build_chooser_dialog(
        "Download Objects", "Downloading objects.", "Download", object_rows(objects())
    )
    listing = dialog.findChild(QListWidget, "selection_list")
    dialog.findChild(QPushButton, "select_none").click()
    assert accept_btn.isEnabled() is False
    dialog.findChild(QPushButton, "select_all").click()
    assert accept_btn.isEnabled() is True
    assert listing.count() == 2


def test_the_buttons_actually_resolve_the_dialog(window):
    # Regression: the button box was never connected to accept/reject, so both
    # buttons did nothing and exec() never returned. Every other test in this file
    # stubs exec(), which is exactly what hid the bug — so drive the real buttons.
    dialog, accept_btn = window._build_chooser_dialog(
        "Download Objects", "Downloading objects.", "Download", object_rows(objects())
    )
    accept_btn.click()
    assert dialog.result() == QDialog.DialogCode.Accepted.value

    dialog, _accept = window._build_chooser_dialog(
        "Download Objects", "Downloading objects.", "Download", object_rows(objects())
    )
    cancel_btn = next(
        b for b in dialog.findChildren(QPushButton) if b.text() == "Cancel"
    )
    cancel_btn.click()
    assert dialog.result() == QDialog.DialogCode.Rejected.value


def test_the_accept_button_is_the_dialogs_default(window):
    # Regression: All / None are the first focusable widgets, and an autoDefault
    # QPushButton that gains focus takes over as the dialog's default — leaving
    # 'All' highlighted and making Return tick everything instead of accepting.
    dialog, accept_btn = window._build_chooser_dialog(
        "Download Objects", "Downloading objects.", "Download", object_rows(objects())
    )
    dialog.show()
    assert accept_btn.isDefault() is True
    assert dialog.findChild(QPushButton, "select_all").autoDefault() is False
    assert dialog.findChild(QPushButton, "select_none").autoDefault() is False


# --- What reaches yd-download ------------------------------------------------


def test_only_the_ticked_objects_are_downloaded(window, captured, monkeypatch):
    # The end-to-end guarantee, with the real dialog in the loop: an unticked row
    # must not reach the command line, and the glob must be replaced by the paths.
    stub_enumeration(window, monkeypatch, objects())
    drive_chooser(window, monkeypatch, accept=True, uncheck=(0,))
    window._config_file = None
    window._tag = "pyex"

    window._download_results_action()

    command, args, _kwargs = captured[0]
    assert command == "yd-download"
    assert args[-1] == "S3:b/pfx/pyex-logs"
    assert "S3:b/pfx/pyex-001" not in args
    assert "pyex*" not in args
    assert args[0] == "--into" and args[1].endswith(RESULTS_DIR)


def test_dismissing_the_chooser_downloads_nothing(window, captured, monkeypatch):
    stub_enumeration(window, monkeypatch, objects())
    drive_chooser(window, monkeypatch, accept=False)
    window._tag = "pyex"

    window._download_results_action()

    assert captured == []


def test_nothing_matching_logs_and_shows_no_chooser(window, captured, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("the chooser must not open when nothing matched")

    stub_enumeration(window, monkeypatch, [])
    monkeypatch.setattr(window, "_build_chooser_dialog", fail)
    window._tag = "pyex"
    window.log_output.setPlainText("")

    window._download_results_action()

    assert captured == []
    assert "No objects match 'pyex*'" in window.log_output.toPlainText()


def test_enumeration_failure_downloads_the_whole_pattern(window, captured, monkeypatch):
    # Preserves the behaviour this action had before selection existed.
    def fail(*args, **kwargs):
        raise AssertionError(
            "there is nothing to choose between when enumeration fails"
        )

    stub_enumeration(window, monkeypatch, None)
    monkeypatch.setattr(window, "_build_chooser_dialog", fail)
    window._tag = "pyex"
    window.log_output.setPlainText("")

    window._download_results_action()

    _command, args, _kwargs = captured[0]
    assert args[-1] == "pyex*"
    assert "downloading them all instead" in window.log_output.toPlainText()


def test_yes_skips_the_chooser_and_fetches_everything(qapp, monkeypatch):
    # '--yes' asks for unattended operation, so it skips the chooser and downloads
    # the whole pattern — consistent with the five destructive confirmations.
    win = YellowDogApp(disable_confirmations=True)
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        win,
        "_run_command_in_subprocess",
        lambda command, args, **kwargs: calls.append((command, args)),
    )

    def fail(*args, **kwargs):
        raise AssertionError("with --yes there is nothing to enumerate or ask about")

    monkeypatch.setattr(win, "_capture_dry_run_objects", fail)
    monkeypatch.setattr(win, "_build_chooser_dialog", fail)
    win._tag = "pyex"
    win.log_output.setPlainText("")

    win._download_results_action()

    _command, args = calls[0]
    assert args[-1] == "pyex*"
    assert "Selection suppressed by '--yes'" in win.log_output.toPlainText()


def test_the_dry_run_checkbox_skips_the_chooser(window, captured, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("a dry-run preview fetches nothing; do not ask")

    monkeypatch.setattr(window, "_capture_dry_run_objects", fail)
    monkeypatch.setattr(window, "_build_chooser_dialog", fail)
    window._tag = "pyex"
    window.dry_run_objects.setChecked(True)

    window._download_results_action()

    _command, args, _kwargs = captured[0]
    assert args[-2:] == ["pyex*", "-D"]


def test_the_chooser_enumerates_with_yd_download(window, captured, monkeypatch):
    # The enumeration must ask yd-download, not yd-delete: their dry-run listings
    # agree in shape but not necessarily in what they match.
    seen = stub_enumeration(window, monkeypatch, objects())
    drive_chooser(window, monkeypatch, accept=True)
    window._tag = "pyex"

    window._download_results_action()

    assert seen == [("yd-download", ["pyex*"])]


def test_a_directory_match_adds_the_recursion_note(window, captured, monkeypatch):
    bodies: list[str] = []
    real_build = window._build_chooser_dialog

    def build(title, message, accept_text, rows):
        bodies.append(message)
        dialog, accept_btn = real_build(title, message, accept_text, rows)
        gui_harness.arm_modal(dialog, lambda open_dialog: open_dialog.reject())
        return dialog, accept_btn

    monkeypatch.setattr(window, "_build_chooser_dialog", build)
    window._tag = "pyex"

    stub_enumeration(window, monkeypatch, objects())
    window._download_results_action()
    assert "everything inside it" in bodies[0]
    assert "pyex*" in bodies[0]
    assert RESULTS_DIR in bodies[0]

    stub_enumeration(window, monkeypatch, [objects()[0]])
    window._download_results_action()
    assert "everything inside it" not in bodies[1]


def test_a_wildcard_named_object_is_refused(window, captured, monkeypatch):
    # yd-download applies is_glob to each path exactly as yd-delete does, so a
    # name like 'a[1].txt' would be expanded and fetch the sibling 'a1.txt'.
    unsafe = [ObjectSummary(path="S3:b/pfx/a[1].txt", name="a[1].txt", is_dir=False)]
    stub_enumeration(window, monkeypatch, unsafe)
    drive_chooser(window, monkeypatch, accept=True)
    window._tag = "pyex"
    window.log_output.setPlainText("")

    window._download_results_action()

    assert captured == []
    logged = window.log_output.toPlainText()
    assert "Cannot download by path" in logged
    assert "a[1].txt" in logged


def test_a_substitution_placeholder_is_refused(window, captured, monkeypatch):
    unsafe = [
        ObjectSummary(path="S3:b/pfx/x_{{user}}", name="x_{{user}}", is_dir=False)
    ]
    stub_enumeration(window, monkeypatch, unsafe)
    drive_chooser(window, monkeypatch, accept=True)
    window._tag = "pyex"
    window.log_output.setPlainText("")

    window._download_results_action()

    assert captured == []
    assert "Cannot download by path" in window.log_output.toPlainText()


def test_a_large_selection_is_echoed_as_a_count(window, captured, monkeypatch):
    many = [
        ObjectSummary(path=f"S3:b/pfx/o{n}", name=f"o{n}", is_dir=False)
        for n in range(4)
    ]
    stub_enumeration(window, monkeypatch, many)
    drive_chooser(window, monkeypatch, accept=True)
    window._tag = "pyex"

    window._download_results_action()

    _command, args, kwargs = captured[0]
    assert args[2:] == [obj.path for obj in many]
    assert kwargs["log_args"][-1] == "<4 objects>"
