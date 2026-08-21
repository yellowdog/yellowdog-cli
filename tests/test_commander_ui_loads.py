"""
Smoke test that the Commander UI actually loads. Constructing YellowDogApp runs
loadUi() against commander.ui and wires every action signal to a named widget,
so a successful construction proves the .ui file is compatible with the
installed PyQt6 and that no code-referenced widget is missing. Guards against
Qt-version incompatibilities and accidental .ui edits.
"""

import qt_guard

qt_guard.require_qt()

import gui_harness
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QFrame, QPlainTextEdit, QPushButton

from yellowdog_cli._version import __version__
from yellowdog_cli.commander.commander import YellowDogApp


def test_ui_loads_and_binds_expected_widgets(qapp):
    win = YellowDogApp()

    # loadUi succeeded and the window is the branded Commander window, with the
    # CLI version in the title. Asserted word by word rather than as a phrase:
    # 'YellowDog Commander' became 'YellowDog CLI Commander' without the branding
    # or the version changing, and only this assertion noticed.
    title = win.windowTitle()
    assert title.startswith("YellowDog")
    assert "Commander" in title
    assert __version__ in title

    # A representative sample of code-referenced widgets exist with the right
    # types (loadUi would have failed, or __init__'s signal wiring would have
    # raised AttributeError, if any were missing).
    assert isinstance(win.log_output, QPlainTextEdit)
    assert isinstance(win.name_glob_override, QPlainTextEdit)
    assert isinstance(win.submit_work_requirement, QPushButton)
    assert isinstance(win.create_worker_pool, QPushButton)
    assert isinstance(win.download_results, QPushButton)


def test_a_separator_divides_the_view_row_from_the_run_command_row(qapp):
    # Found by shape and position rather than by name, so it survives whatever
    # Designer calls it, and asserts the thing that matters: that a horizontal
    # rule lies between the two rows rather than merely existing somewhere.
    win = gui_harness.shown(YellowDogApp())

    def top(widget) -> int:
        return widget.mapTo(win, QPoint(0, 0)).y()

    def bottom(widget) -> int:
        return top(widget) + widget.height()

    between = [
        frame
        for frame in win.findChildren(QFrame)
        if frame.frameShape() == QFrame.Shape.HLine
        and bottom(win.view_config_directory) <= top(frame) <= top(win.run_any_command)
    ]

    assert between, "no horizontal separator below the View Config Directory row"
    assert all(
        bottom(separator) <= top(win.run_any_command) for separator in between
    ), "the separator overlaps the row beneath it"
