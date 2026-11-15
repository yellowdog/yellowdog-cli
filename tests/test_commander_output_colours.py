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
from yellowdog_cli.commander.output_model import (
    JSON_BRACKET,
    JSON_KEY,
    JSON_LITERAL,
    JSON_NUMBER,
    JSON_STRING,
    json_tokens,
)
from yellowdog_cli.commander.output_pane import (
    ERROR_RGB_DARK,
    ERROR_RGB_LIGHT,
    JSON_STYLES,
    STATE_STYLES,
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


# --- JSON ------------------------------------------------------------------


@pytest.mark.parametrize(
    "line, pieces",
    [
        ("{", [("{", JSON_BRACKET)]),
        (
            '  "namespace": "yd-demo",',
            [('"namespace"', JSON_KEY), ('"yd-demo"', JSON_STRING)],
        ),
        ('  "priority": 0,', [('"priority"', JSON_KEY), ("0", JSON_NUMBER)]),
        (
            '  "maxRetries": -1.5e3',
            [('"maxRetries"', JSON_KEY), ("-1.5e3", JSON_NUMBER)],
        ),
        ('  "starved": false,', [('"starved"', JSON_KEY), ("false", JSON_LITERAL)]),
        (
            '  "dependencies": null',
            [('"dependencies"', JSON_KEY), ("null", JSON_LITERAL)],
        ),
        ('  "taskGroups": [', [('"taskGroups"', JSON_KEY), ("[", JSON_BRACKET)]),
        ('    "bash",', [('"bash"', JSON_STRING)]),
        ("  ],", [("]", JSON_BRACKET)]),
        ("[]", [("[", JSON_BRACKET), ("]", JSON_BRACKET)]),
        (
            '{"id": "x", "n": 3}',
            [
                ("{", JSON_BRACKET),
                ('"id"', JSON_KEY),
                ('"x"', JSON_STRING),
                ('"n"', JSON_KEY),
                ("3", JSON_NUMBER),
                ("}", JSON_BRACKET),
            ],
        ),
        # Brackets and numbers inside a string are the string's
        (
            '  "x": "a {b} [c] 42",',
            [('"x"', JSON_KEY), ('"a {b} [c] 42"', JSON_STRING)],
        ),
        # Not JSON: a message, prose, a table, YAML-like text
        ("2026-11-15 11:30:01 (012345) : Generated {x}", []),
        ("Generated Work Requirement 'render'", []),
        ("| name | status |", []),
        ("name: value", []),
    ],
)
def test_json_pieces(line, pieces):
    assert [(line[s : s + n], kind) for s, n, kind in json_tokens(line)] == pieces


def colours_of(window, text: str) -> dict[str, tuple[int, int, int]]:
    """
    The colour of each coloured piece of the line holding 'text', by piece.
    """
    document = window.log_output.document()
    assert isinstance(document, QTextDocument)
    block = document.find(text).block()
    assert block.isValid(), f"{text!r} is not shown"
    layout = block.layout()
    assert layout is not None
    result = {}
    for piece in layout.formats():
        colour = piece.format.foreground().color()
        segment = block.text()[piece.start : piece.start + piece.length]
        result[segment] = (colour.red(), colour.green(), colour.blue())
    return result


def json_colour(kind: str, dark: bool = False) -> tuple[int, int, int] | None:
    light_colour, dark_colour, _bold, _italic = JSON_STYLES[kind]
    return dark_colour if dark else light_colour


JSON_LINE = '  "starved": false, "priority": 3, "name": "render"'


@pytest.fixture
def with_json(window):
    for line in ("{", JSON_LINE, "}"):
        window._output.log(line, prefix=False)
    QApplication.processEvents()
    return window


def test_json_is_coloured_as_the_cli_colours_it(with_json):
    colours = colours_of(with_json, JSON_LINE)
    assert colours['"starved"'] == json_colour(JSON_KEY)
    assert colours["false"] == json_colour(JSON_LITERAL)
    assert colours["3"] == json_colour(JSON_NUMBER)
    assert colours['"render"'] == json_colour(JSON_STRING)


def test_json_in_dark_mode(with_json):
    try:
        with_json._dark_mode_action(Qt.CheckState.Checked)
        QApplication.processEvents()
        colours = colours_of(with_json, JSON_LINE)
        assert colours['"starved"'] == json_colour(JSON_KEY, dark=True)
        assert colours['"render"'] == json_colour(JSON_STRING, dark=True)
    finally:
        with_json._dark_mode_action(Qt.CheckState.Unchecked)
        QApplication.processEvents()


def test_a_json_line_shown_alone_by_the_filter_is_still_coloured(with_json):
    # Judged by its shape, not by the document around it
    with_json.output_text_filter.setText("starved")
    with_json._output._apply_text_filter()
    QApplication.processEvents()
    assert with_json.log_output.toPlainText() == JSON_LINE
    assert colours_of(with_json, JSON_LINE)['"starved"'] == json_colour(JSON_KEY)


def test_false_is_not_the_error_red(qapp):
    assert json_colour(JSON_LITERAL) != ERROR_RGB_LIGHT
    assert json_colour(JSON_LITERAL, dark=True) != ERROR_RGB_DARK


# --- Status words ----------------------------------------------------------


def state_colour(style: str, dark: bool = False) -> tuple[int, int, int]:
    light_colour, dark_colour, _bold, _italic = STATE_STYLES[style]
    return dark_colour if dark else light_colour


def test_status_words_are_coloured_as_the_cli_colours_them(window):
    events = (
        "2026-11-15 12:01:20 (089570) : Work Requirement 'render' is RUNNING",
        "2026-11-15 12:01:52 (089570) :   Task 'frame-0003' is FAILED",
        "│   3 │ render-261113 │ COMPLETED │",
        "2026-11-15 12:01:53 (089570) :   Task 'frame-0004' is CANCELLED",
    )
    for line in events:
        window._output.log(line, prefix=False)
    QApplication.processEvents()
    assert colours_of(window, events[0])["RUNNING"] == state_colour("active")
    assert colours_of(window, events[1])["FAILED"] == ERROR_RGB_LIGHT
    assert colours_of(window, events[2])["COMPLETED"] == state_colour("completed")
    assert colours_of(window, events[3])["CANCELLED"] == state_colour("cancelled")


def test_every_style_the_cli_highlights_has_a_colour():
    from yellowdog_cli.utils.output_style import HIGHLIGHTED_STATES

    styles = {name for p in HIGHLIGHTED_STATES for name in p.groupindex}
    assert styles <= set(STATE_STYLES)


def test_a_status_word_in_a_json_string_takes_its_colour(window):
    line = '  "status": "RUNNING",'
    window._output.log(line, prefix=False)
    QApplication.processEvents()
    colours = colours_of(window, line)
    assert colours["RUNNING"] == state_colour("active")
    assert colours['"'] == json_colour(JSON_STRING), "its quotes stay the string's"


def test_lower_case_words_are_not_status_words(window):
    line = "2026-11-15 12:02:00 (089570) : the upload failed and was cancelled"
    window._output.log(line, prefix=False)
    QApplication.processEvents()
    assert colour_of(window, line) is None


def test_dark_mode_status_colours(window):
    line = "2026-11-15 12:01:20 (089570) : Work Requirement 'render' is RUNNING"
    window._output.log(line, prefix=False)
    QApplication.processEvents()
    try:
        window._dark_mode_action(Qt.CheckState.Checked)
        QApplication.processEvents()
        assert colours_of(window, line)["RUNNING"] == state_colour("active", True)
    finally:
        window._dark_mode_action(Qt.CheckState.Unchecked)
        QApplication.processEvents()
