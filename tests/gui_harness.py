"""
A harness for testing Commander's dialogs as dialogs.

Four bugs reached the user in the work this exists to guard: dialog buttons that
did nothing, a default button silently stolen by another button, a list collapsed
to a scrollbar on Windows, and a lost prefix hierarchy. Every one of them lived in
a seam the tests stubbed or asserted around — they checked arguments and
arithmetic, never outcomes.

The central idea is therefore that a dialog under test runs its **real** exec().
The interaction is queued with QTimer.singleShot(0, ...) beforehand, which cannot
fire until some event loop runs, so it lands inside that real modal loop. A click
must then travel the real button-box -> accepted -> accept() path for exec() to
return at all, which is precisely what the stubbing approach could not see.

Everything here works under QT_QPA_PLATFORM=offscreen with no display, so it runs
on a headless CI node; nodes without a usable Qt skip via conftest's 'qapp'.

Two rules worth keeping:

- Assert geometric *relationships*, never pixel counts. CI nodes have different
  fonts from a developer's machine — offscreen Qt will tell you it is substituting
  for a missing 'Sans Serif' — so row heights differ. 'viewport fits three rows'
  travels; 'the viewport is 57px' does not.
- A dialog that never closes would block the suite until the CI job times out,
  which is worse than a red test. Every modal run here is watchdogged.
"""

import qt_guard

# Guards its own Qt import, so that importing this helper from a test module skips
# that module rather than failing its collection when Qt is unusable — whatever
# order the module's imports happen to be sorted into.
qt_guard.require_qt()

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QListWidget, QPushButton, QWidget

# Generous enough not to trip on a slow CI node, short enough that a genuine hang
# is reported as a test failure rather than a job timeout.
MODAL_WATCHDOG_MS = 5000


class DialogHung(AssertionError):
    """A dialog's exec() had to be broken open by the watchdog."""


# Dialogs armed with arm_modal() are recorded here, because the code under test —
# not the test — calls their exec(), so there is no return value for the test to
# inspect. conftest's autouse guard resets this before each test and checks it
# afterwards, which is what turns a swallowed hang or a swallowed assertion into a
# visible failure.
_armed: list[dict] = []


def reset() -> None:
    """Forget any armed dialogs. Called before each test by conftest."""
    _armed.clear()


def check() -> None:
    """
    Re-raise anything an armed dialog's interaction hit, or report a hang. Called
    after each test by conftest, so a failure inside a Qt callback cannot vanish.
    """
    # Cleared even when raising, so a failure a test has already inspected is not
    # reported a second time at teardown. Found by this module's own self-tests.
    try:
        for record in _armed:
            if record["error"] is not None:
                raise record["error"]
            if record["hung"]:
                raise DialogHung(
                    f"{record['title']!r} did not close: its exec() ran on after"
                    f" the interaction and had to be rejected by the watchdog."
                    f" Usually the button box is not connected to accept/reject,"
                    f" so clicking does nothing."
                )
    finally:
        _armed.clear()


def _natural_height(widget: QWidget) -> int:
    """
    A widget's preferred height, falling back to its current one. Wrapped because
    the Qt stubs type sizeHint() as optional.
    """
    hint = widget.sizeHint()
    return hint.height() if hint is not None else widget.height()


def _install(dialog: QDialog, interact, watchdog_ms: int) -> dict:
    """
    Queue 'interact' into whichever event loop next runs, and arm a watchdog.
    Returns the record used to report what happened.
    """
    record: dict = {
        "title": dialog.windowTitle(),
        "hung": False,
        "error": None,
        "ran": False,
        "closed": False,
    }

    def _run_interaction():
        record["ran"] = True
        # The watchdog's clock starts here rather than at arming, so that it times
        # the dialog and not whatever else the loop was busy with first. A
        # YellowDogApp defers its config parse with singleShot(0); that parse spawns
        # yd-show and blocks in a nested loop, it is queued before this callback, and
        # a zero-interval timer is only delivered once the queue is otherwise empty —
        # so it runs inside the dialog's exec() and ahead of the interaction. On a
        # small CI node it consumed the whole budget, and four dialogs that closed
        # correctly were convicted of hanging. Nothing is lost by waiting: the
        # watchdog's only lever is rejecting the dialog, which would not have
        # released a nested loop held open by something else anyway.
        watchdog.start(watchdog_ms)
        try:
            interact(dialog)
        except BaseException as error:
            # An exception raised inside a Qt callback would otherwise be printed
            # and discarded, leaving the test passing.
            record["error"] = error
            dialog.reject()

    def _on_timeout():
        if record["closed"]:
            return  # a stale timer firing in a later loop, not a hang
        record["hung"] = True
        dialog.reject()

    def _on_closed(_result: int):
        # done() — and so exec() returning — stops the watchdog, so it cannot
        # convict this dialog once some later event loop runs.
        record["closed"] = True
        watchdog.stop()

    watchdog = QTimer(dialog)
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(_on_timeout)
    dialog.finished.connect(_on_closed)

    # singleShot(0) cannot fire until an event loop runs, and the test itself runs
    # none — so this is delivered inside the dialog's own exec(), not before it.
    QTimer.singleShot(0, _run_interaction)
    return record


def arm_modal(dialog: QDialog, interact, watchdog_ms: int = MODAL_WATCHDOG_MS) -> None:
    """
    Prepare a dialog whose exec() the *code under test* will call.

    Use this when production code builds and shows the dialog itself — the test
    only gets to see it at build time. 'interact(dialog)' runs inside the real
    modal loop. Whatever it hits, and any hang, surfaces via conftest's check().
    """
    _armed.append(_install(dialog, interact, watchdog_ms))


def run_modal(
    dialog: QDialog,
    interact,
    width: int | None = None,
    watchdog_ms: int = MODAL_WATCHDOG_MS,
) -> int:
    """
    Show a dialog, run its real exec(), and interact from inside the modal loop.
    Returns exec()'s result — QDialog.DialogCode.Accepted.value on acceptance.

    Use this when the test owns the dialog. With 'width', the dialog is resized
    first, which is how the narrow-window geometry cases are driven.
    """
    if width is not None:
        dialog.resize(width, _natural_height(dialog))

    record = _install(dialog, interact, watchdog_ms)
    result = dialog.exec()

    if record["error"] is not None:
        raise record["error"]
    if record["hung"]:
        raise DialogHung(
            f"{dialog.windowTitle()!r} did not close after the interaction; the"
            f" watchdog rejected it. Usually the button box is not connected to"
            f" accept/reject, so clicking does nothing."
        )
    if not record["ran"]:
        raise AssertionError(
            f"the interaction for {dialog.windowTitle()!r} never ran — exec()"
            f" returned before the queued callback was delivered"
        )
    return result


def shown(widget: QWidget, width: int | None = None) -> QWidget:
    """
    Show a widget offscreen so its geometry is real, optionally at a given width.
    Geometry is meaningless until a widget has been shown and laid out.
    """
    if width is not None:
        widget.resize(width, _natural_height(widget))
    widget.show()
    return widget


def visible_rows(listing: QListWidget) -> int:
    """
    How many rows of 'listing' can actually be seen — a ratio, deliberately, so
    it survives the font differences between a CI node and a developer's machine.

    This is the measurement that catches a list squeezed to nothing, or one whose
    height was eaten by a scrollbar: both leave the arithmetic looking correct
    while showing the user no rows at all.
    """
    row_height = listing.sizeHintForRow(0)
    if row_height <= 0:
        return 0
    return listing.viewport().height() // row_height


def default_button(dialog: QDialog) -> QPushButton | None:
    """
    The dialog's default button — the one Return activates — or None.

    Worth asking about explicitly: an autoDefault QPushButton that gains focus
    takes the role over from whichever button was given it, which is how a
    confirmation dialog stopped defaulting to 'No'.
    """
    for button in dialog.findChildren(QPushButton):
        if button.isDefault():
            return button
    return None


def button_labelled(dialog: QDialog, text: str) -> QPushButton:
    """The dialog's button with this exact label; fails loudly if absent."""
    for button in dialog.findChildren(QPushButton):
        if button.text() == text:
            return button
    labels = sorted(b.text() for b in dialog.findChildren(QPushButton))
    raise AssertionError(f"no button labelled {text!r}; found {labels}")
