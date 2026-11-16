"""
Tests for Commander's file viewer (file_viewer.py): Show Config, Show WR JSON
and Show WP JSON open a modeless window of their own, one per file, coloured
as TOML or JSON line by line, reloaded when the file changes on disk, with
Find and Open in Editor, following Dark Mode and the output's text size.
"""

import os
import time

import pytest
import qt_guard

qt_guard.require_qt()

import gui_harness
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QTextDocument
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPlainTextEdit, QPushButton

from yellowdog_cli.commander.commander import YellowDogApp
from yellowdog_cli.commander.file_viewer import (
    FILE_STYLES,
    JSON,
    JSONNET,
    NOT_FOUND,
    TOML,
    VIEWER_SIZE,
    language_of,
)
from yellowdog_cli.commander.output_model import (
    JSON_BRACKET,
    JSON_KEY,
    JSON_LITERAL,
    JSON_NUMBER,
    JSON_STRING,
    JSONNET_IN_COMMENT,
    JSONNET_IN_TEXT_BLOCK,
    JSONNET_KEYWORD,
    JSONNET_NORMAL,
    TOML_COMMENT,
    TOML_TABLE,
    jsonnet_tokens,
    toml_tokens,
)
from yellowdog_cli.commander.output_pane import JSON_STYLES

# --- The TOML tokenizer ----------------------------------------------------


@pytest.mark.parametrize(
    "line, pieces",
    [
        ("# A comment", [("# A comment", TOML_COMMENT)]),
        ("[common]", [("[common]", TOML_TABLE)]),
        (
            "[[workRequirement.taskGroups]]  # each group",
            [
                ("[[workRequirement.taskGroups]]", TOML_TABLE),
                ("# each group", TOML_COMMENT),
            ],
        ),
        (
            'namespace = "team-a"  # where # it runs',
            [
                ("namespace", JSON_KEY),
                ('"team-a"', JSON_STRING),
                ("# where # it runs", TOML_COMMENT),
            ],
        ),
        ("tag = 'x#y'", [("tag", JSON_KEY), ("'x#y'", JSON_STRING)]),
        ('"a.b" = 1_000', [('"a.b"', JSON_KEY), ("1_000", JSON_NUMBER)]),
        ("a.b.c = -3.5e2", [("a.b.c", JSON_KEY), ("-3.5e2", JSON_NUMBER)]),
        ("flag = false", [("flag", JSON_KEY), ("false", JSON_LITERAL)]),
        (
            "when = 2026-11-16T10:00:00Z",
            [("when", JSON_KEY), ("2026-11-16T10:00:00Z", JSON_NUMBER)],
        ),
        (
            'sizes = [1, "two", 0x1F]',
            [
                ("sizes", JSON_KEY),
                ("[", JSON_BRACKET),
                ("1", JSON_NUMBER),
                ('"two"', JSON_STRING),
                ("0x1F", JSON_NUMBER),
                ("]", JSON_BRACKET),
            ],
        ),
        (
            'pool = { name = "n", count = 2 }',
            [
                ("pool", JSON_KEY),
                ("{", JSON_BRACKET),
                ("name", JSON_KEY),
                ('"n"', JSON_STRING),
                ("count", JSON_KEY),
                ("2", JSON_NUMBER),
                ("}", JSON_BRACKET),
            ],
        ),
        # A multi-line array's lines, and a multi-line string's quotes
        ('    "render",', [('"render"', JSON_STRING)]),
        ("]", [("]", JSON_BRACKET)]),
        ('script = """', [("script", JSON_KEY), ('"""', JSON_STRING)]),
        # An '=' or '#' in a string is the string's
        (
            'url = "https://example.com/?x=1#top"',
            [("url", JSON_KEY), ('"https://example.com/?x=1#top"', JSON_STRING)],
        ),
        ("", []),
    ],
)
def test_toml_pieces(line, pieces):
    assert [(line[s : s + n], kind) for s, n, kind in toml_tokens(line)] == pieces


def test_the_toml_colours_are_jsons_where_they_share_a_kind():
    for kind in (JSON_KEY, JSON_STRING, JSON_NUMBER, JSON_LITERAL, JSON_BRACKET):
        assert FILE_STYLES[kind] == JSON_STYLES[kind]


@pytest.mark.parametrize(
    "path, is_config, language",
    [
        ("config.toml", True, TOML),
        ("settings.cfg", True, TOML),
        ("wr.toml", False, TOML),
        ("WR.TOML", False, TOML),
        ("wr.json", False, JSON),
        ("wr.jsonnet", False, JSONNET),
        ("lib/base.libsonnet", False, JSONNET),
    ],
)
def test_the_language_a_file_is_coloured_as(path, is_config, language):
    assert language_of(path, is_config) == language


# --- The viewer ------------------------------------------------------------

CONFIG_TEXT = """\
# The team's settings
[common]
namespace = "team-a"
tag = "render"

[workRequirement]
taskCount = 3
"""
WR_TEXT = '{\n  "name": "render",\n  "priority": 3\n}\n'


@pytest.fixture
def window(qapp):
    window = YellowDogApp()
    gui_harness.shown(window)
    # The deferred start-up selection of the configuration file runs first,
    # or it would replace the one a test selects
    QApplication.processEvents()
    yield window
    window.shutdown()
    window.close()


@pytest.fixture
def config(window, tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG_TEXT, encoding="utf-8")
    monkeypatch.setattr(window, "_config_file", str(path))
    return path


def show_config(window):
    window._show_config_action()
    QApplication.processEvents()
    (viewer,) = window._file_viewers.values()
    return viewer


def colours_of(view: QPlainTextEdit, text: str) -> dict[str, tuple]:
    """
    The colour and boldness of each coloured piece of the line holding 'text'.
    """
    document = view.document()
    assert isinstance(document, QTextDocument)
    block = document.find(text).block()
    assert block.isValid(), f"{text!r} is not shown"
    layout = block.layout()
    assert layout is not None
    result = {}
    for piece in layout.formats():
        colour = piece.format.foreground().color()
        segment = block.text()[piece.start : piece.start + piece.length]
        result[segment] = (
            (colour.red(), colour.green(), colour.blue()),
            piece.format.fontWeight() == QFont.Weight.Bold,
        )
    return result


def style(kind: str, dark: bool = False):
    light, dark_colour, _bold, _italic = FILE_STYLES[kind]
    return dark_colour if dark else light


def wait_for(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        QApplication.processEvents()
        time.sleep(0.02)


def test_show_config_opens_a_viewer_and_not_the_output(window, config):
    viewer = show_config(window)
    assert viewer.isVisible() and not viewer.isModal()
    assert viewer.text.toPlainText() == CONFIG_TEXT
    assert viewer.text.isReadOnly()
    assert viewer.windowTitle() == "config.toml — configuration file"
    assert viewer.path_label.toolTip() == str(config)
    assert viewer.path_label.text().endswith("config.toml")
    output = window.log_output.toPlainText()
    assert f"Showing configuration file '{config}' in its own window" in output
    assert "namespace" not in output


def test_the_config_is_coloured_as_toml(window, config):
    viewer = show_config(window)
    colours = colours_of(viewer.text, 'namespace = "team-a"')
    assert colours["namespace"][0] == style(JSON_KEY)
    assert colours['"team-a"'][0] == style(JSON_STRING)
    assert colours_of(viewer.text, "taskCount")["3"][0] == style(JSON_NUMBER)
    assert colours_of(viewer.text, "# The team's")["# The team's settings"][0] == (
        style(TOML_COMMENT)
    )
    assert colours_of(viewer.text, "[workRequirement]")["[workRequirement]"][1]


def test_a_definition_file_is_coloured_as_json(window, tmp_path, monkeypatch):
    path = tmp_path / "wr.json"
    path.write_text(WR_TEXT, encoding="utf-8")
    monkeypatch.setattr(window, "_wr_file", str(path))
    window._show_wr_json_action()
    (viewer,) = window._file_viewers.values()
    assert viewer.windowTitle() == "wr.json — Work Requirement file"
    colours = colours_of(viewer.text, '"name"')
    assert colours['"name"'][0] == style(JSON_KEY)
    assert colours['"render"'][0] == style(JSON_STRING)


def test_showing_it_again_raises_the_same_viewer(window, config):
    viewer = show_config(window)
    config.write_text(CONFIG_TEXT + "# more\n", encoding="utf-8")
    window._show_config_action()
    assert list(window._file_viewers.values()) == [viewer]
    # Read again as it is raised, whether or not the change was seen
    assert viewer.text.toPlainText().endswith("# more\n")


def test_a_closed_viewer_is_forgotten_and_opens_anew(window, config):
    viewer = show_config(window)
    viewer.close()
    QApplication.processEvents()
    assert window._file_viewers == {}
    assert show_config(window) is not viewer


def test_a_change_on_disk_is_reloaded(window, config):
    viewer = show_config(window)
    config.write_text(CONFIG_TEXT.replace("team-a", "team-b"), encoding="utf-8")
    wait_for(lambda: "team-b" in viewer.text.toPlainText())


def test_a_file_replaced_by_an_editor_is_still_watched(window, config, tmp_path):
    viewer = show_config(window)
    for team in ("team-b", "team-c"):
        replacement = tmp_path / "config.toml.new"
        replacement.write_text(CONFIG_TEXT.replace("team-a", team), encoding="utf-8")
        replace_as_an_editor_does(replacement, config)
        wait_for(lambda team=team: team in viewer.text.toPlainText())


def replace_as_an_editor_does(source, destination, timeout: float = 5.0) -> None:
    """
    Replace 'destination' with 'source', trying again for a while where
    Windows refuses (another process, such as a virus scanner, has the file
    open for a moment), as an editor saving does.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if time.monotonic() > deadline:
                raise
            QApplication.processEvents()
            time.sleep(0.05)


def test_a_file_gone_is_said_and_its_text_kept(window, config):
    viewer = show_config(window)
    config.unlink()
    wait_for(lambda: viewer.status.isVisible())
    assert viewer.status.text().startswith(f"Cannot read '{config}'")
    assert viewer.text.toPlainText() == CONFIG_TEXT


def test_find_goes_round_both_ways(window, config):
    viewer = show_config(window)
    viewer.find_field.setText("team")
    assert viewer.find_next()
    first = viewer.text.textCursor().selectionStart()
    assert viewer.find_next()  # "team-a"
    second = viewer.text.textCursor().selectionStart()
    assert second > first
    assert viewer.find_next()  # round to the comment again
    assert viewer.text.textCursor().selectionStart() == first
    assert viewer.find_previous()
    assert viewer.text.textCursor().selectionStart() == second
    assert not viewer.status.isVisible()


def test_find_says_when_there_is_none(window, config):
    viewer = show_config(window)
    viewer.find_field.setText("nowhere")
    assert not viewer.find_next()
    assert viewer.status.isVisible() and viewer.status.text() == NOT_FOUND


def test_no_button_takes_return(window, config):
    viewer = show_config(window)
    for button in viewer.findChildren(QPushButton):
        assert not button.autoDefault() and not button.isDefault(), button.text()


def test_open_in_editor_opens_the_file(window, config, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(
        window._file_dialogs, "open_with_default_application", opened.append
    )
    viewer = show_config(window)
    viewer.open_button.click()
    assert opened == [str(config)]


def test_dark_mode_recolours_an_open_viewer(window, config):
    viewer = show_config(window)
    try:
        window.dark_mode.setChecked(True)
        QApplication.processEvents()
        colours = colours_of(viewer.text, 'namespace = "team-a"')
        assert colours["namespace"][0] == style(JSON_KEY, dark=True)
    finally:
        window.dark_mode.setChecked(False)
        QApplication.processEvents()


def test_a_viewer_opens_in_the_dark_when_dark(window, config):
    try:
        window.dark_mode.setChecked(True)
        QApplication.processEvents()
        viewer = show_config(window)
        colours = colours_of(viewer.text, 'namespace = "team-a"')
        assert colours["namespace"][0] == style(JSON_KEY, dark=True)
    finally:
        window.dark_mode.setChecked(False)
        QApplication.processEvents()


def test_the_output_text_size_applies_to_viewers(window, config):
    viewer = show_config(window)
    before = viewer.text.font().pointSize()
    window._zoom_output(1)
    assert viewer.text.font().pointSize() == before + 1
    window._zoom_output(0)
    assert viewer.text.font().pointSize() == window._output_font.pointSize()


def test_a_long_path_is_elided_rather_than_widening_the_window(
    window, tmp_path, monkeypatch
):
    deep = tmp_path.joinpath(*(["a-rather-long-directory-name"] * 12))
    deep.mkdir(parents=True)
    path = deep / "config.toml"
    path.write_text(CONFIG_TEXT, encoding="utf-8")
    monkeypatch.setattr(window, "_config_file", str(path))
    viewer = show_config(window)
    assert viewer.width() == VIEWER_SIZE[0]
    assert viewer.path_label.text().startswith("…")
    assert viewer.path_label.text().endswith(f"{os.sep}config.toml")
    assert viewer.path_label.toolTip() == str(path)


@pytest.mark.parametrize(
    "key, modifier",
    [
        (Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier),
        (Qt.Key.Key_Enter, Qt.KeyboardModifier.KeypadModifier),
        (Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier),
    ],
)
def test_return_in_find_finds_and_keeps_the_window_open(window, config, key, modifier):
    viewer = show_config(window)
    viewer.find_field.setFocus()
    QTest.keyClicks(viewer.find_field, "team")
    QTest.keyClick(viewer.find_field, key, modifier)
    QApplication.processEvents()
    assert viewer.isVisible()
    assert viewer.text.textCursor().selectedText().lower() == "team"


def test_return_in_the_text_keeps_the_window_open(window, config):
    viewer = show_config(window)
    viewer.text.setFocus()
    QTest.keyClick(viewer.text, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert viewer.isVisible()


def test_escape_closes_it(window, config):
    viewer = show_config(window)
    QTest.keyClick(viewer.text, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert window._file_viewers == {}


def test_a_viewer_is_not_kept_above_the_main_window(window, config):
    # On Windows and Linux a window with a parent is kept above it, as a
    # dialog is; macOS does not, so only the parent can be tested here
    viewer = show_config(window)
    assert viewer.parent() is None
    handle = viewer.windowHandle()
    assert handle is not None and handle.transientParent() is None


def test_closing_the_main_window_closes_the_viewers(window, config, tmp_path):
    first = show_config(window)
    other = tmp_path / "wr.json"
    other.write_text(WR_TEXT, encoding="utf-8")
    window._wr_file = str(other)
    window._show_wr_json_action()
    viewers = list(window._file_viewers.values())
    assert first in viewers and len(viewers) == 2
    window.shutdown()
    QApplication.processEvents()
    assert window._file_viewers == {}
    # Closed, and so deleted (WA_DeleteOnClose)
    assert all(sip.isdeleted(viewer) for viewer in viewers)


# --- Jsonnet ---------------------------------------------------------------


@pytest.mark.parametrize(
    "line, pieces",
    [
        (
            "local base = import 'lib/base.libsonnet';  // the base",
            [
                ("local", JSONNET_KEYWORD),
                ("import", JSONNET_KEYWORD),
                ("'lib/base.libsonnet'", JSON_STRING),
                ("// the base", TOML_COMMENT),
            ],
        ),
        ("  name: 'render',", [("name", JSON_KEY), ("'render'", JSON_STRING)]),
        ('  "taskType": "bash",', [('"taskType"', JSON_KEY), ('"bash"', JSON_STRING)]),
        (
            "  arguments+: ['-c', code],",
            [
                ("arguments", JSON_KEY),
                ("[", JSON_BRACKET),
                ("'-c'", JSON_STRING),
                ("]", JSON_BRACKET),
            ],
        ),
        ("  hidden:: true,", [("hidden", JSON_KEY), ("true", JSON_LITERAL)]),
        ("  timeout: 30.5,", [("timeout", JSON_KEY), ("30.5", JSON_NUMBER)]),
        (
            "  ok: if self.x then $.y else null,",
            [
                ("ok", JSON_KEY),
                ("if", JSONNET_KEYWORD),
                ("self", JSONNET_KEYWORD),
                ("then", JSONNET_KEYWORD),
                ("$", JSONNET_KEYWORD),
                ("else", JSONNET_KEYWORD),
                ("null", JSON_LITERAL),
            ],
        ),
        # A ':' or '//' in a string is the string's
        (
            "  url: 'https://example.com',",
            [("url", JSON_KEY), ("'https://example.com'", JSON_STRING)],
        ),
        ("  # a hash comment", [("# a hash comment", TOML_COMMENT)]),
        ("", []),
    ],
)
def test_jsonnet_pieces(line, pieces):
    tokens, state = jsonnet_tokens(line, JSONNET_NORMAL)
    assert [(line[s : s + n], kind) for s, n, kind in tokens] == pieces
    assert state == JSONNET_NORMAL


def _pieces_over(lines):
    state = JSONNET_NORMAL
    shown = []
    for line in lines:
        tokens, state = jsonnet_tokens(line, state)
        shown.append(([(line[s : s + n], kind) for s, n, kind in tokens], state))
    return shown


def test_a_comment_over_lines_is_coloured_throughout():
    assert _pieces_over(["  /* a comment", "  still it", "  ends */ priority: 1,"]) == [
        ([("/* a comment", TOML_COMMENT)], JSONNET_IN_COMMENT),
        ([("  still it", TOML_COMMENT)], JSONNET_IN_COMMENT),
        (
            [("  ends */", TOML_COMMENT), ("priority", JSON_KEY), ("1", JSON_NUMBER)],
            JSONNET_NORMAL,
        ),
    ]


def test_a_text_block_is_a_string_throughout():
    # Its text is not read as Jsonnet: 'hello: world' is no field
    assert _pieces_over(
        ["  script: |||", '    echo "hello: world"', "", "  |||,", "  x: 1,"]
    ) == [
        ([("script", JSON_KEY), ("|||", JSON_STRING)], JSONNET_IN_TEXT_BLOCK),
        ([('    echo "hello: world"', JSON_STRING)], JSONNET_IN_TEXT_BLOCK),
        ([], JSONNET_IN_TEXT_BLOCK),
        ([("|||", JSON_STRING)], JSONNET_NORMAL),
        ([("x", JSON_KEY), ("1", JSON_NUMBER)], JSONNET_NORMAL),
    ]


JSONNET_TEXT = """\
// The render tasks
local task(name) = {
  name: name,
  script: |||
    echo "hello: world"
  |||,
};
{ tasks: [task('t1')] }
"""


@pytest.fixture
def shown_jsonnet(window, tmp_path, monkeypatch):
    path = tmp_path / "wr.jsonnet"
    path.write_text(JSONNET_TEXT, encoding="utf-8")
    monkeypatch.setattr(window, "_wr_file", str(path))
    window._show_wr_json_action()
    QApplication.processEvents()
    (viewer,) = window._file_viewers.values()
    return viewer, path


def test_a_jsonnet_file_is_coloured_as_jsonnet(shown_jsonnet):
    viewer, _ = shown_jsonnet
    assert colours_of(viewer.text, "local task")["local"][0] == style(JSONNET_KEYWORD)
    assert colours_of(viewer.text, "  name: name")["name"][0] == style(JSON_KEY)
    assert colours_of(viewer.text, "// The render")["// The render tasks"][0] == (
        style(TOML_COMMENT)
    )
    # The text block's line is a string, not a field
    line = '    echo "hello: world"'
    assert colours_of(viewer.text, line) == {line: (style(JSON_STRING), False)}


def test_a_text_block_opened_by_an_edit_recolours_the_lines_after(shown_jsonnet):
    viewer, path = shown_jsonnet
    path.write_text(
        JSONNET_TEXT.replace("// The render tasks", "/* The render tasks"),
        encoding="utf-8",
    )
    wait_for(lambda: "/* The render" in viewer.text.toPlainText())
    QApplication.processEvents()
    # The comment now never closes: every line after it is a comment
    assert colours_of(viewer.text, "local task")["local task(name) = {"][0] == (
        style(TOML_COMMENT)
    )


def test_jsonnet_keywords_are_not_the_literals_colour():
    assert style(JSONNET_KEYWORD) != style(JSON_LITERAL)
    assert style(JSONNET_KEYWORD, dark=True) != style(JSON_LITERAL, dark=True)
