"""
Unit tests for the Commander LineBuffer, which reassembles subprocess output
read from a pipe. Guards against spurious line breaks in the log pane where a
read boundary falls part-way through a line.
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")  # commander imports QtWidgets at module top

from yellowdog_cli.commander.commander import LineBuffer


def test_complete_lines_are_returned():
    buffer = LineBuffer()
    assert buffer.feed(b"one\ntwo\n") == ["one", "two"]


def test_partial_final_line_is_held_back():
    buffer = LineBuffer()
    assert buffer.feed(b"one\ntw") == ["one"]
    assert buffer.feed(b"o\n") == ["two"]


def test_line_split_across_reads_is_reassembled():
    # The exact failure seen in a large dry-run Work Requirement: a read
    # boundary inside '"-c"' produced '["-' / 'c",' on separate lines
    buffer = LineBuffer()
    lines = buffer.feed(b'          "arguments": ["-')
    lines += buffer.feed(b'c", "sleep 1.0 && echo \'Done!\'"]\n')
    assert lines == ['          "arguments": ["-c", "sleep 1.0 && echo \'Done!\'"]']


def test_blank_lines_are_preserved():
    buffer = LineBuffer()
    assert buffer.feed(b"one\n\ntwo\n") == ["one", "", "two"]


def test_leading_whitespace_is_preserved():
    buffer = LineBuffer()
    assert buffer.feed(b"    indented\n") == ["    indented"]


def test_carriage_returns_are_stripped():
    buffer = LineBuffer()
    assert buffer.feed(b"one\r\ntwo\r\n") == ["one", "two"]


def test_multibyte_character_split_across_reads():
    buffer = LineBuffer()
    encoded = "café\n".encode()  # 'é' is two bytes
    assert buffer.feed(encoded[:4]) == []  # split mid-character
    assert buffer.feed(encoded[4:]) == ["café"]


def test_flush_returns_unterminated_final_line():
    buffer = LineBuffer()
    assert buffer.feed(b"one\ntwo") == ["one"]
    assert buffer.flush() == ["two"]


def test_flush_returns_nothing_when_output_ends_with_a_newline():
    buffer = LineBuffer()
    assert buffer.feed(b"one\n") == ["one"]
    assert buffer.flush() == []


def test_flush_is_idempotent():
    buffer = LineBuffer()
    buffer.feed(b"one")
    assert buffer.flush() == ["one"]
    assert buffer.flush() == []


def test_log_pane_text_matches_the_original_output(qapp):
    """
    End-to-end: chunked reads appended to a QPlainTextEdit must reproduce the
    original text exactly.
    """
    from PyQt6.QtWidgets import QPlainTextEdit

    output = (
        '        {\n          "name": "task_29996",\n          "taskType": "bash",\n'
        '          "arguments": ["-c", "sleep 1.0 && echo \'Done!\'"]\n        },\n'
    )
    encoded = output.encode()
    chunk_size = 26  # a boundary inside '["-c"'

    log_pane = QPlainTextEdit()
    buffer = LineBuffer()
    for start in range(0, len(encoded), chunk_size):
        for line in buffer.feed(encoded[start : start + chunk_size]):
            log_pane.appendPlainText(line)
    for line in buffer.flush():
        log_pane.appendPlainText(line)

    assert log_pane.toPlainText() == output.rstrip("\n")
