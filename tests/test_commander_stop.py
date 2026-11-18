"""
Tests for stopping one command from the output window's right-click menu.
The commands are real child processes, run through _run_command_in_subprocess,
so the stop reaches a real process and its ending is recorded as it would be.
"""

import sys

import pytest
import qt_guard

qt_guard.require_qt()

import gui_harness
from PyQt6.QtCore import QPoint, QProcess
from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QMenu

from yellowdog_cli.commander import output_pane
from yellowdog_cli.commander.commander import YellowDogApp
from yellowdog_cli.commander.output_model import OutputRun

WAIT_MS = 10_000
# Prints a line, then waits far longer than any test. Each marker is joined
# as the child runs, so that the 'Executing:' line echoing the code does not
# hold it, and a test waiting for it waits for the child itself
SLEEPER = "import time; print('sleeper' + ' started', flush=True); time.sleep(120)"
# The same, ignoring the polite request to exit, so only kill() ends it
STUBBORN = (
    "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN);"
    " print('stubborn' + ' started', flush=True); time.sleep(120)"
)


@pytest.fixture
def window(qapp):
    window = YellowDogApp()
    gui_harness.shown(window)
    yield window
    window.shutdown()
    window.close()


def start(window: YellowDogApp, code: str, marker: str) -> tuple[QProcess, OutputRun]:
    """
    Start a child running 'code', and wait for it to print 'marker'.
    """
    window._run_command_in_subprocess(sys.executable, ["-c", code], yd_command=False)
    process: QProcess = window._processes[-1]
    run = list(window._output._output_runs.values())[-1]
    waited = 0
    while marker not in window.log_output.toPlainText() and waited < WAIT_MS:
        QTest.qWait(50)
        waited += 50
    assert marker in window.log_output.toPlainText(), "the child printed nothing"
    return process, run


def wait_until_finished(process: QProcess) -> None:
    waited = 0
    while process.state() != QProcess.ProcessState.NotRunning and waited < WAIT_MS:
        QTest.qWait(50)
        waited += 50
    assert process.state() == QProcess.ProcessState.NotRunning, "still running"


def menu_at(window: YellowDogApp, text: str) -> QMenu:
    """
    The right-click menu for the line holding 'text'.
    """
    document = window.log_output.document()
    assert isinstance(document, QTextDocument)
    block = document.find(text).block()
    assert block.isValid(), f"{text!r} is not shown"
    window.log_output.setTextCursor(QTextCursor(block))
    window.log_output.ensureCursorVisible()
    position: QPoint = window.log_output.cursorRect(QTextCursor(block)).center()
    return window._output._build_output_menu(position)


def stop_actions(menu: QMenu) -> list:
    return [a for a in menu.actions() if a.text().startswith("Stop ")]


def test_a_running_command_can_be_stopped_from_its_output(window):
    process, run = start(window, SLEEPER, "sleeper started")
    (stop,) = stop_actions(menu_at(window, "sleeper started"))
    assert stop.text() == run.stop_text
    stop.trigger()
    wait_until_finished(process)
    assert run.outcome == "stopped"
    assert f"Stopping {run.bar_subject}" in window.log_output.toPlainText()


def test_stop_is_the_last_item_set_apart(window):
    process, run = start(window, SLEEPER, "sleeper started")
    actions = menu_at(window, "sleeper started").actions()
    assert actions[-1].text() == run.stop_text
    assert actions[-2].isSeparator()
    window._output.stop_run(run)
    wait_until_finished(process)


def test_a_command_that_ignores_the_request_is_forced_to_stop(window, monkeypatch):
    monkeypatch.setattr(output_pane, "TERMINATE_TIMEOUT_MS", 300)
    process, run = start(window, STUBBORN, "stubborn started")
    window._output.stop_run(run)
    QTest.qWait(150)  # within the grace period it is still running
    if sys.platform != "win32":  # where terminate() is not a signal at all
        assert process.state() != QProcess.ProcessState.NotRunning
    wait_until_finished(process)
    assert run.outcome == "stopped"


def test_stop_is_offered_once_while_running(window):
    process, run = start(window, SLEEPER, "sleeper started")
    window._output.stop_run(run)
    assert stop_actions(menu_at(window, "sleeper started")) == []
    wait_until_finished(process)


def test_a_finished_command_offers_no_stop(window):
    process, _run = start(window, "print('quick' + ' one', flush=True)", "quick one")
    wait_until_finished(process)
    QTest.qWait(100)
    assert stop_actions(menu_at(window, "quick one")) == []


def test_commanders_own_messages_offer_no_stop(window):
    window._output.log("a message from Commander itself")
    assert stop_actions(menu_at(window, "a message from Commander itself")) == []


def test_the_stopping_line_belongs_to_the_command_and_to_commander(window):
    process, run = start(window, SLEEPER, "sleeper started")
    window._output.stop_run(run)
    wait_until_finished(process)
    entry = next(
        e for e in window._output._output_entries if "Stopping process" in e.text
    )
    assert set(entry.runs) == {run.run_id, output_pane.COMMANDER_RUN}
