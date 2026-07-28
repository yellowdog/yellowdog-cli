"""
Tests for the Commander's Deselect Files action, which asks which of the
currently-selected files to deselect rather than deselecting all of them.
The dialog is built and inspected directly; the action itself is driven with
the chooser stubbed out, so no test blocks on a modal dialog.
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QCheckBox, QDialogButtonBox, QLabel, QPushButton

from yellowdog_cli.commander.commander import YellowDogApp

CONFIG = "configs/config.toml"
WR = "definitions/mytasks.jsonnet"
WP = "definitions/mypool.jsonnet"


@pytest.fixture
def win(qapp):
    window = YellowDogApp()
    yield window
    window.close()


@pytest.fixture
def all_selected(win):
    """
    A window with a configuration file and both definition files selected.
    """
    win._config_file = CONFIG
    win._wr_file = WR
    win._wp_file = WP
    return win


def _chooser(selection):
    """
    Stand in for the dialog, recording the entries it was offered.
    """
    offered = []

    def choose(entries):
        offered.extend(entries)
        return selection

    return choose, offered


# --- The dialog itself -----------------------------------------------------


def test_dialog_offers_one_checkbox_per_selected_file(all_selected):
    entries = [("Configuration", CONFIG), ("Work Requirement", WR)]
    dialog, checkboxes = all_selected._build_deselect_dialog(entries)

    assert dialog.windowTitle() == "Deselect Files"
    assert len(checkboxes) == 2
    assert checkboxes[0].text() == f"Deselect Configuration: {CONFIG}"
    assert checkboxes[1].text() == f"Deselect Work Requirement: {WR}"


def test_dialog_rows_are_phrased_as_actions_not_state(all_selected):
    """
    A checked row stating only the file reads as 'this file is selected',
    inviting the user to uncheck the one they want deselected — the opposite
    of what a checked box means here. Every row must name the action.
    """
    dialog, checkboxes = all_selected._build_deselect_dialog(
        [("Configuration", CONFIG), ("Work Requirement", WR), ("Worker Pool", WP)]
    )

    assert all(checkbox.text().startswith("Deselect ") for checkbox in checkboxes)
    header = next(
        label
        for label in dialog.findChildren(QLabel)
        if "deselect" in label.text().lower()
    )
    assert header.text() == "Check the files to deselect:"


def test_dialog_checkboxes_start_checked(all_selected):
    _, checkboxes = all_selected._build_deselect_dialog(
        [("Configuration", CONFIG), ("Work Requirement", WR), ("Worker Pool", WP)]
    )
    assert all(checkbox.isChecked() for checkbox in checkboxes)


def test_dialog_checkboxes_carry_the_full_path_as_a_tooltip(all_selected):
    _, checkboxes = all_selected._build_deselect_dialog([("Work Requirement", WR)])
    assert checkboxes[0].toolTip().endswith(WR)
    assert checkboxes[0].toolTip().startswith("/")  # absolute


def test_dialog_elides_a_very_long_path(all_selected):
    long_path = "/".join(["a_long_directory_name"] * 6) + "/definition.jsonnet"
    _, checkboxes = all_selected._build_deselect_dialog(
        [("Work Requirement", long_path)]
    )

    text = checkboxes[0].text()
    assert len(text) < len(f"Deselect Work Requirement: {long_path}")
    assert text.endswith("definition.jsonnet")
    assert checkboxes[0].toolTip().endswith(long_path)  # full path still available


def test_dialog_offers_cancel_and_deselect_with_deselect_default(all_selected):
    dialog, _ = all_selected._build_deselect_dialog([("Work Requirement", WR)])

    box = dialog.findChild(QDialogButtonBox)
    # Order is platform-dependent, so compare as a set
    assert {button.text() for button in box.buttons()} == {"Cancel", "Deselect"}

    deselect = next(b for b in box.buttons() if b.text() == "Deselect")
    assert isinstance(deselect, QPushButton)
    assert deselect.isDefault()


def test_dialog_has_no_checkbox_for_an_unselected_file(win):
    win._wr_file = WR  # nothing else selected
    _, checkboxes = win._build_deselect_dialog([("Work Requirement", WR)])
    assert [c.text() for c in checkboxes] == [f"Deselect Work Requirement: {WR}"]
    assert isinstance(checkboxes[0], QCheckBox)


# --- The action ------------------------------------------------------------


def test_nothing_selected_does_not_ask(win, monkeypatch):
    def fail(entries):
        raise AssertionError("the dialog should not be shown")

    monkeypatch.setattr(win, "_choose_files_to_deselect", fail)
    win._deselect_files_action()  # must not raise

    assert (
        "No configuration or definition files to deselect"
        in win.log_output.toPlainText()
    )


def test_only_selected_files_are_offered(all_selected, monkeypatch):
    all_selected._wp_file = None  # no Worker Pool definition selected
    choose, offered = _chooser([])
    monkeypatch.setattr(all_selected, "_choose_files_to_deselect", choose)

    all_selected._deselect_files_action()

    assert offered == [("Configuration", CONFIG), ("Work Requirement", WR)]


def test_choosing_everything_deselects_everything(all_selected, monkeypatch):
    choose, _ = _chooser([0, 1, 2])
    monkeypatch.setattr(all_selected, "_choose_files_to_deselect", choose)

    all_selected._deselect_files_action()

    assert all_selected._config_file is None
    assert all_selected._wr_file is None
    assert all_selected._wp_file is None


def test_choosing_one_file_leaves_the_others_selected(all_selected, monkeypatch):
    choose, offered = _chooser([1])  # the Work Requirement only
    monkeypatch.setattr(all_selected, "_choose_files_to_deselect", choose)

    all_selected._deselect_files_action()

    assert offered[1] == ("Work Requirement", WR)
    assert all_selected._wr_file is None
    assert all_selected._config_file == CONFIG
    assert all_selected._wp_file == WP


def test_deselecting_a_definition_restores_its_button_label(all_selected, monkeypatch):
    all_selected._show_wp_selection()
    choose, _ = _chooser([2])  # the Worker Pool only
    monkeypatch.setattr(all_selected, "_choose_files_to_deselect", choose)

    all_selected._deselect_files_action()

    assert all_selected.select_worker_pool.text() == "Select Worker Pool JSON"
    assert all_selected.select_worker_pool.toolTip() == ""


def test_cancelling_deselects_nothing(all_selected, monkeypatch):
    monkeypatch.setattr(all_selected, "_choose_files_to_deselect", lambda entries: None)

    all_selected._deselect_files_action()

    assert all_selected._config_file == CONFIG
    assert all_selected._wr_file == WR
    assert all_selected._wp_file == WP
    assert "Cancelled: no files deselected" in all_selected.log_output.toPlainText()


def test_accepting_with_nothing_checked_deselects_nothing(all_selected, monkeypatch):
    monkeypatch.setattr(all_selected, "_choose_files_to_deselect", lambda entries: [])

    all_selected._deselect_files_action()

    assert all_selected._wr_file == WR
    assert (
        "No files chosen: nothing deselected" in all_selected.log_output.toPlainText()
    )


def test_dialog_is_shown_even_with_confirmations_disabled(qapp, monkeypatch):
    """
    '--yes' suppresses the destructive-action confirmations, but not this
    dialog: it is the only way to deselect one file and not the others.
    """
    win = YellowDogApp(disable_confirmations=True)
    win._config_file = CONFIG
    win._wr_file = WR
    win._wp_file = WP

    choose, offered = _chooser([1])  # the Work Requirement only
    monkeypatch.setattr(win, "_choose_files_to_deselect", choose)
    win._deselect_files_action()

    assert offered, "the dialog must still be shown with --yes"
    assert win._wr_file is None
    assert win._config_file == CONFIG
    assert win._wp_file == WP
    win.close()


def test_cancelling_with_confirmations_disabled_deselects_nothing(qapp, monkeypatch):
    win = YellowDogApp(disable_confirmations=True)
    win._config_file = CONFIG
    win._wr_file = WR

    monkeypatch.setattr(win, "_choose_files_to_deselect", lambda entries: None)
    win._deselect_files_action()

    assert win._config_file == CONFIG
    assert win._wr_file == WR
    win.close()
