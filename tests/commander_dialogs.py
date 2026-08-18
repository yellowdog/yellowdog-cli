"""
Drivers for Commander's own dialogs, built on gui_harness.

Production builds and execs these dialogs itself, so a test cannot hold one before
it opens. Each driver wraps the builder, arms the dialog that comes out, and lets
the real code call the real exec() — so the interaction lands inside the real modal
loop and a click has to travel the real wiring to have any effect.

These replace three near-identical hand-rolled helpers, each of which replaced
exec() with a stub returning a chosen result code. That approach could not see a
button box that was never connected, which is one of the bugs that reached a user.

Note the two builders are not symmetrical. _build_chooser_dialog connects its own
button box, so a dialog from it resolves on its own. _build_destructive_dialog does
not: _confirm_destructive attaches a 'clicked' handler afterwards, because it needs
to know *which* button was pressed rather than merely accept-or-reject. A dialog
straight from that builder therefore has buttons that do nothing, and its result
code is not meaningful — drive it through _confirm_destructive, as here.
"""

import qt_guard

# As in gui_harness: guard before importing Qt, so a node without Qt skips.
qt_guard.require_qt()

import gui_harness
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidget

# Which button a driver should press.
YES = "yes"
NO = "no"
SKIP = "skip"
ACCEPT = "accept"
CANCEL = "cancel"
DISMISS = "dismiss"  # close without pressing anything


def listing(dialog) -> QListWidget:
    """The dialog's checkable listing; fails loudly when there is none."""
    found = dialog.findChild(QListWidget, "selection_list")
    assert found is not None, "the dialog has no selectable listing"
    return found


def untick(dialog, indexes) -> None:
    """Untick rows by index, as a user clicking their checkboxes would."""
    rows = listing(dialog)
    for index in indexes:
        item = rows.item(index)
        assert item is not None, f"no row at index {index}"
        item.setCheckState(Qt.CheckState.Unchecked)


def drive_confirmation(
    window,
    monkeypatch,
    press: str,
    untick_rows: tuple = (),
    inspect=None,
) -> None:
    """
    Arm the next destructive confirmation so that, inside its real exec(), the
    given rows are unticked and 'press' is pressed. 'inspect(dialog)' runs first if
    given, for assertions that only hold while the dialog is open.

    Press DISMISS to close without pressing a button, which is what closing the
    window does: _confirm_destructive reads which button was clicked, so no button
    means no proceed.
    """
    real_build = window._build_destructive_dialog

    def build(title, message, *, rows=None):
        dialog, yes_btn, skip_btn = real_build(title, message, rows=rows)

        def interact(open_dialog):
            if untick_rows:
                untick(open_dialog, untick_rows)
            if inspect is not None:
                inspect(open_dialog)
            if press == YES:
                yes_btn.click()
            elif press == SKIP:
                skip_btn.click()
            elif press == NO:
                gui_harness.button_labelled(open_dialog, "No").click()
            else:
                # No button pressed. _confirm_destructive's 'clicked' handler is
                # what closes this dialog, so nothing else will — close it here or
                # the watchdog would report a hang that is not one.
                open_dialog.reject()

        gui_harness.arm_modal(dialog, interact)
        return dialog, yes_btn, skip_btn

    monkeypatch.setattr(window, "_build_destructive_dialog", build)


def drive_chooser(
    window,
    monkeypatch,
    press: str,
    untick_rows: tuple = (),
    inspect=None,
) -> None:
    """
    Arm the next chooser so that, inside its real exec(), the given rows are
    unticked and 'press' is pressed. Unlike the confirmation, this dialog wires its
    own button box, so a click resolves it and DISMISS is a plain reject.
    """
    real_build = window._build_chooser_dialog

    def build(title, message, accept_text, rows):
        dialog, accept_btn = real_build(title, message, accept_text, rows)

        def interact(open_dialog):
            if untick_rows:
                untick(open_dialog, untick_rows)
            if inspect is not None:
                inspect(open_dialog)
            if press == ACCEPT:
                accept_btn.click()
            elif press == CANCEL:
                gui_harness.button_labelled(open_dialog, "Cancel").click()
            else:
                open_dialog.reject()

        gui_harness.arm_modal(dialog, interact)
        return dialog, accept_btn

    monkeypatch.setattr(window, "_build_chooser_dialog", build)


def drive_notice(window, monkeypatch, inspect=None) -> dict:
    """
    Arm the next notice dialog so that, inside its real exec(), 'inspect(dialog)'
    runs (if given) and OK is pressed. Returns a dict recording how many notices
    were shown and the message of the last one, since a notice has no result for
    the caller to inspect afterwards.

    A test asserting that NO notice appears can use the same dict: production
    builds the dialog, so an unexpected notice shows up as a count of one.
    """
    shown: dict = {"count": 0, "message": None}
    real_build = window._build_notice_dialog

    def build(message):
        dialog = real_build(message)
        shown["count"] += 1
        shown["message"] = message

        def interact(open_dialog):
            if inspect is not None:
                inspect(open_dialog)
            gui_harness.button_labelled(open_dialog, "OK").click()

        gui_harness.arm_modal(dialog, interact)
        return dialog

    monkeypatch.setattr(window, "_build_notice_dialog", build)
    return shown
