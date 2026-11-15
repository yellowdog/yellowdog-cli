"""
Tests for colouring the CLI's error and warning lines in Commander's output
window: the colour each line is displayed in, read from the document's
layout, in both appearances and through the filters.
"""

import pytest
import qt_guard

qt_guard.require_qt()

import gui_harness
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QTextDocument
from PyQt6.QtWidgets import QApplication

from yellowdog_cli.commander.commander import YellowDogApp
from yellowdog_cli.commander.output_pane import (
    ERROR_RGB_DARK,
    ERROR_RGB_LIGHT,
    WARNING_RGB_DARK,
    WARNING_RGB_LIGHT,
)

PLAIN = "2026-11-15 11:30:01 (012345) : Generated Work Requirement 'render'"
WARNING = "2026-11-15 11:30:01 (012345) : WARNING : 2 DISCARDED Tasks"
ERROR = "2026-11-15 11:30:02 (012345) : ERROR : Cannot find 'rendr'"


@pytest.fixture
def window(qapp):
    window = YellowDogApp()
    gui_harness.shown(window)
    for line in (PLAIN, WARNING, ERROR):
        window._output.log(line, prefix=False)
    QApplication.processEvents()
    yield window
    window.shutdown()
    window.close()


def colour_of(window, text: str) -> tuple[int, int, int] | None:
    """
    The colour the whole of the line holding 'text' is displayed in, or None
    where it is given none of its own.
    """
    document = window.log_output.document()
    assert isinstance(document, QTextDocument)
    block = document.find(text).block()
    assert block.isValid(), f"{text!r} is not shown"
    layout = block.layout()
    assert layout is not None
    ranges = layout.formats()
    if not ranges:
        return None
    (whole,) = ranges
    assert (whole.start, whole.length) == (0, len(block.text()))
    colour: QColor = whole.format.foreground().color()
    return colour.red(), colour.green(), colour.blue()


def test_error_and_warning_lines_are_coloured(window):
    assert colour_of(window, ERROR) == ERROR_RGB_LIGHT
    assert colour_of(window, WARNING) == WARNING_RGB_LIGHT
    assert colour_of(window, PLAIN) is None


def test_dark_mode_recolours_them_and_back(window):
    try:
        window._dark_mode_action(Qt.CheckState.Checked)
        QApplication.processEvents()
        assert colour_of(window, ERROR) == ERROR_RGB_DARK
        assert colour_of(window, WARNING) == WARNING_RGB_DARK
    finally:
        window._dark_mode_action(Qt.CheckState.Unchecked)
        QApplication.processEvents()
    assert colour_of(window, ERROR) == ERROR_RGB_LIGHT


def test_the_colour_survives_filtering(window):
    window.output_text_filter.setText("ERROR")
    window._output._apply_text_filter()
    QApplication.processEvents()
    assert window.log_output.toPlainText() == ERROR
    assert colour_of(window, ERROR) == ERROR_RGB_LIGHT


def test_the_text_itself_stays_plain(window):
    # What Copy and Save take, and the filters read
    assert window.log_output.toPlainText().splitlines() == [PLAIN, WARNING, ERROR]


def test_a_marker_only_counts_at_the_start_of_the_message(window):
    # An 'Executing:' line echoing a command, or a task's output, holding the
    # marker's text is not an error line; one without a prefix is
    echo = "2026-11-15 11:30:03 (012345) : Executing: 'echo ERROR : not really'"
    bare = "WARNING : a message without a prefix"
    for line in (echo, bare):
        window._output.log(line, prefix=False)
    QApplication.processEvents()
    assert colour_of(window, echo) is None
    assert colour_of(window, bare) == WARNING_RGB_LIGHT
