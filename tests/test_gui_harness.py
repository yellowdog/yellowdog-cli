"""
Self-tests for the GUI harness. It exists to make dialog failures visible, so a
harness that swallowed them would be worse than none — these check that it does
not, and that the geometry helper measures what it claims to.
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

import gui_harness
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


def _wired_dialog(connected: bool = True) -> tuple[QDialog, QPushButton]:
    """A minimal dialog, optionally with the button box left unconnected."""
    dialog = QDialog()
    dialog.setWindowTitle("Probe")
    layout = QVBoxLayout(dialog)
    box = QDialogButtonBox(dialog)
    box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
    ok = box.addButton("OK", QDialogButtonBox.ButtonRole.AcceptRole)
    assert ok is not None
    ok.setDefault(True)
    if connected:
        box.accepted.connect(dialog.accept)
        box.rejected.connect(dialog.reject)
    layout.addWidget(box)
    return dialog, ok


def test_a_real_exec_returns_when_a_connected_button_is_clicked(qapp):
    dialog, ok = _wired_dialog()
    result = gui_harness.run_modal(dialog, lambda _d: ok.click())
    assert result == QDialog.DialogCode.Accepted.value


def test_cancel_rejects(qapp):
    dialog, _ok = _wired_dialog()
    result = gui_harness.run_modal(
        dialog, lambda d: gui_harness.button_labelled(d, "Cancel").click()
    )
    assert result == QDialog.DialogCode.Rejected.value


def test_an_unconnected_button_is_reported_as_a_hang(qapp):
    # This is the bug the harness exists for: the button box never wired to
    # accept/reject, so clicking does nothing and exec() never returns. It must
    # surface as a named failure, not as a suite that stops responding.
    dialog, ok = _wired_dialog(connected=False)
    with pytest.raises(gui_harness.DialogHung, match="did not close"):
        gui_harness.run_modal(dialog, lambda _d: ok.click(), watchdog_ms=250)


def test_an_assertion_inside_the_interaction_surfaces(qapp):
    # Raised inside a Qt callback, an exception would otherwise be printed and
    # discarded, leaving the test green.
    dialog, _ok = _wired_dialog()

    def interact(_dialog):
        raise AssertionError("deliberate")

    with pytest.raises(AssertionError, match="deliberate"):
        gui_harness.run_modal(dialog, interact, watchdog_ms=250)


def test_an_armed_dialog_reports_its_hang_through_the_conftest_guard(qapp):
    # arm_modal is for dialogs the code under test execs itself, so there is no
    # return value; the autouse guard is what makes a hang visible. Checked here by
    # calling the guard's check() directly rather than by failing this test.
    dialog, ok = _wired_dialog(connected=False)
    gui_harness.arm_modal(dialog, lambda _d: ok.click(), watchdog_ms=250)
    dialog.exec()  # as production would
    with pytest.raises(gui_harness.DialogHung):
        gui_harness.check()


def test_an_armed_dialog_reports_an_assertion_through_the_conftest_guard(qapp):
    dialog, _ok = _wired_dialog()

    def interact(_dialog):
        raise AssertionError("deliberate, armed")

    gui_harness.arm_modal(dialog, interact, watchdog_ms=250)
    dialog.exec()
    with pytest.raises(AssertionError, match="deliberate, armed"):
        gui_harness.check()


def test_an_interaction_that_never_ran_is_reported(qapp, monkeypatch):
    # If exec() returns without ever running an event loop, the queued interaction
    # is never delivered — and a test whose assertions all live in that interaction
    # would assert nothing while looking green. Reproduced by replacing exec()
    # here, which is the one place stubbing it is the point rather than the flaw.
    dialog, _ok = _wired_dialog()
    monkeypatch.setattr(dialog, "exec", lambda: QDialog.DialogCode.Rejected.value)
    with pytest.raises(AssertionError, match="never ran"):
        gui_harness.run_modal(dialog, lambda _d: None, watchdog_ms=250)


def test_visible_rows_counts_what_fits_not_what_exists(qapp):
    listing = QListWidget()
    for n in range(20):
        listing.addItem(QListWidgetItem(f"row {n}"))
    gui_harness.shown(listing)
    row_height = listing.sizeHintForRow(0)
    listing.setFixedHeight(row_height * 4 + 2 * listing.frameWidth())

    assert listing.count() == 20
    assert gui_harness.visible_rows(listing) == 4


def test_visible_rows_is_zero_when_a_list_is_squeezed_flat(qapp):
    # The Windows failure: the list still held its rows and its arithmetic still
    # looked right, but nothing could be seen.
    listing = QListWidget()
    listing.addItem(QListWidgetItem("row"))
    gui_harness.shown(listing)
    listing.setFixedHeight(2 * listing.frameWidth())

    assert gui_harness.visible_rows(listing) == 0


def test_default_button_and_button_labelled(qapp):
    dialog, ok = _wired_dialog()
    gui_harness.shown(dialog)
    assert gui_harness.default_button(dialog) is ok
    assert gui_harness.button_labelled(dialog, "Cancel").text() == "Cancel"
    with pytest.raises(AssertionError, match="no button labelled"):
        gui_harness.button_labelled(dialog, "Nope")
