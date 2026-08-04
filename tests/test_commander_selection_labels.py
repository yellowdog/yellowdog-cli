"""
Tests for indicating the selected Work Requirement / Worker Pool definition
files on their own 'Select' buttons. The point of showing the selection there
is that it costs no extra space in the left-hand column, so these tests also
guard against a long filename widening that column.
"""

import pytest
import qt_guard

qt_guard.require_qt()

from yellowdog_cli.commander.commander import (
    SELECTED_WP_PREFIX,
    SELECTED_WR_PREFIX,
    YellowDogApp,
)

LONG_NAME = "a_rather_long_work_requirement_definition_name.jsonnet"


@pytest.fixture
def win(qapp):
    window = YellowDogApp()
    window.show()
    qapp.processEvents()
    yield window
    window.close()


def test_buttons_start_with_their_original_labels(win):
    assert win.select_work_requirement.text() == "Select Work Requirement JSON"
    assert win.select_worker_pool.text() == "Select Worker Pool JSON"
    assert win.select_work_requirement.toolTip() == ""
    assert win.select_worker_pool.toolTip() == ""


def test_selected_work_requirement_is_shown_on_its_button(win):
    win._wr_file = "definitions/mytasks.jsonnet"
    win._show_wr_selection()

    assert win.select_work_requirement.text() == f"{SELECTED_WR_PREFIX}mytasks.jsonnet"
    # The full path is available on hover
    assert win.select_work_requirement.toolTip().endswith("definitions/mytasks.jsonnet")
    # The Worker Pool button is untouched
    assert win.select_worker_pool.text() == "Select Worker Pool JSON"


def test_selected_worker_pool_is_shown_on_its_button(win):
    win._wp_file = "definitions/mypool.jsonnet"
    win._show_wp_selection()

    assert win.select_worker_pool.text() == f"{SELECTED_WP_PREFIX}mypool.jsonnet"
    assert win.select_work_requirement.text() == "Select Work Requirement JSON"


def test_only_the_basename_is_shown(win):
    win._wr_file = "some/deep/directory/tree/tasks.json"
    win._show_wr_selection()

    assert win.select_work_requirement.text() == f"{SELECTED_WR_PREFIX}tasks.json"


def test_long_filename_does_not_widen_the_column(win):
    # The column's width is set by its widest button, so the label must not
    # need more room than that one does
    widest = win.cancel_work_requirements_and_abort.sizeHint().width()
    container = win.select_work_requirement.parentWidget()
    baseline = container.sizeHint().width()

    for name in [LONG_NAME, "x" * 200 + ".jsonnet"]:
        win._wr_file = f"definitions/{name}"
        win._show_wr_selection()
        assert win.select_work_requirement.sizeHint().width() <= widest, name
        assert container.sizeHint().width() == baseline, f"column widened for {name}"


def test_long_filename_is_elided_but_still_identifiable(win):
    win._wr_file = f"definitions/{LONG_NAME}"
    win._show_wr_selection()

    text = win.select_work_requirement.text()
    assert text.startswith(SELECTED_WR_PREFIX)
    assert len(text) < len(SELECTED_WR_PREFIX + LONG_NAME)  # elided
    assert text.endswith(".jsonnet")  # extension still visible
    assert win.select_work_requirement.toolTip().endswith(LONG_NAME)  # full name


def test_deselecting_restores_the_original_labels(win, monkeypatch):
    win._wr_file = "definitions/mytasks.jsonnet"
    win._wp_file = "definitions/mypool.jsonnet"
    win._show_wr_selection()
    win._show_wp_selection()

    # Choose everything the dialog offers, without showing it
    monkeypatch.setattr(
        win, "_choose_files_to_deselect", lambda entries: list(range(len(entries)))
    )
    win._deselect_files_action()

    assert win.select_work_requirement.text() == "Select Work Requirement JSON"
    assert win.select_worker_pool.text() == "Select Worker Pool JSON"
    assert win.select_work_requirement.toolTip() == ""
    assert win.select_worker_pool.toolTip() == ""


def test_selection_survives_being_replaced(win):
    win._wr_file = "definitions/first.jsonnet"
    win._show_wr_selection()
    win._wr_file = "definitions/second.json"
    win._show_wr_selection()

    assert win.select_work_requirement.text() == f"{SELECTED_WR_PREFIX}second.json"
    assert win.select_work_requirement.toolTip().endswith("second.json")
