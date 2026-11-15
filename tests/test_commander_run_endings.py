"""
Tests for the line Commander logs when a command ends, saying how it went
(OutputRun.ending_text): its wording for each outcome, and, with real child
processes, its place as the command's last line and its colour.
"""

import sys

import pytest
import qt_guard

qt_guard.require_qt()

import gui_harness
from PyQt6.QtCore import QProcess
from PyQt6.QtGui import QTextDocument
from PyQt6.QtTest import QTest

from yellowdog_cli.commander.commander import YellowDogApp
from yellowdog_cli.commander.output_model import COMMANDER_RUN, OutputRun
from yellowdog_cli.commander.output_pane import (
    ERROR_RGB_LIGHT,
    OK_RGB_LIGHT,
    WARNING_RGB_LIGHT,
)

WAIT_MS = 10_000


@pytest.mark.parametrize(
    "outcome, text",
    [
        (None, None),
        ("did not start", None),
        ("exit 0", "✓ Process 000042 (yd list) finished (exit 0)"),
        ("exit 6", "✗ Process 000042 (yd list) failed (exit 6)"),
        ("crashed", "✗ Process 000042 (yd list) crashed"),
        ("stopped", "■ Process 000042 (yd list) stopped"),
    ],
)
def test_the_ending_text_for_each_outcome(outcome, text):
    run = OutputRun(1, "yd list", pid=42, outcome=outcome)
    assert run.ending_text == text


@pytest.fixture
def window(qapp):
    window = YellowDogApp()
    gui_harness.shown(window)
    yield window
    window.shutdown()
    window.close()


def run_to_the_end(window: YellowDogApp, code: str) -> OutputRun:
    window._run_command_in_subprocess(sys.executable, ["-c", code], yd_command=False)
    process: QProcess = window._processes[-1]
    run = list(window._output._output_runs.values())[-1]
    waited = 0
    while process.state() != QProcess.ProcessState.NotRunning and waited < WAIT_MS:
        QTest.qWait(50)
        waited += 50
    QTest.qWait(50)
    assert run.outcome is not None, "still running"
    return run


def last_line_of(window: YellowDogApp, run: OutputRun) -> str:
    entries = [e for e in window._output._output_entries if run.run_id in e.runs]
    return entries[-1].text


def colour_of(window: YellowDogApp, text: str) -> tuple[int, int, int] | None:
    document = window.log_output.document()
    assert isinstance(document, QTextDocument)
    layout = document.find(text).block().layout()
    assert layout is not None
    ranges = layout.formats()
    if not ranges:
        return None
    colour = ranges[0].format.foreground().color()
    return colour.red(), colour.green(), colour.blue()


def test_a_success_ends_with_a_green_tick(window):
    # The output's last line has no newline: drained first, it still comes
    # before the ending
    run = run_to_the_end(
        window, "import sys; sys.stdout.write('unterminated' + ' last line')"
    )
    entries = [e for e in window._output._output_entries if run.run_id in e.runs]
    assert "unterminated last line" in entries[-2].text
    ending = last_line_of(window, run)
    assert ending.endswith(run.ending_text)
    assert colour_of(window, run.ending_text) == OK_RGB_LIGHT


def test_a_failure_ends_with_a_red_cross_and_its_exit_code(window):
    run = run_to_the_end(window, "import sys; sys.exit(6)")
    assert run.ending_text is not None
    assert run.ending_text.startswith("✗ ")
    assert run.ending_text.endswith(" failed (exit 6)")
    assert last_line_of(window, run).endswith(run.ending_text)
    assert colour_of(window, run.ending_text) == ERROR_RGB_LIGHT


def test_a_stopped_command_ends_amber(window):
    code = "import time; print('waiting' + ' here', flush=True); time.sleep(120)"
    window._run_command_in_subprocess(sys.executable, ["-c", code], yd_command=False)
    process: QProcess = window._processes[-1]
    run = list(window._output._output_runs.values())[-1]
    while "waiting here" not in window.log_output.toPlainText():
        QTest.qWait(50)
    window._output.stop_run(run)
    while process.state() != QProcess.ProcessState.NotRunning:
        QTest.qWait(50)
    QTest.qWait(50)
    assert run.ending_text is not None and run.ending_text.startswith("■")
    assert last_line_of(window, run).endswith(run.ending_text)
    assert colour_of(window, run.ending_text) == WARNING_RGB_LIGHT


def test_the_ending_belongs_to_the_command_and_to_commander(window):
    run = run_to_the_end(window, "pass")
    entry = [e for e in window._output._output_entries if run.run_id in e.runs][-1]
    assert set(entry.runs) == {run.run_id, COMMANDER_RUN}
