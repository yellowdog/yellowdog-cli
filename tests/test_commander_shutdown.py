"""
Tests for the Commander's shutdown path. A command still running at exit used
to be torn down with the window — Qt warned 'QProcess: Destroyed while process
is still running', the output handlers fired against deleted C++ objects, and
on macOS the resulting failure raised a system error report. Worse, a command
blocked on a network timeout holds a nested event loop that nothing told to
exit.

'sleep' stands in for a yd-* command that is still running; each test stops it
well before it would finish on its own.
"""

import os

import pytest
import qt_guard

qt_guard.require_qt()

from PyQt6.QtCore import QEventLoop, QProcess, QTimer
from PyQt6.QtWidgets import QDialogButtonBox, QPlainTextEdit

from yellowdog_cli.commander.commander import (
    CONFIG_PARSE_TIMEOUT_MS,
    YellowDogApp,
)

SLEEP_SECONDS = "30"  # long enough that finishing on its own would be a bug


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture
def win(qapp):
    window = YellowDogApp()
    window.show()
    qapp.processEvents()
    yield window
    window.shutdown()  # never leave a child behind, even if a test fails
    window.close()


def _start_sleep(win) -> QProcess:
    win._run_command_in_subprocess("sleep", [SLEEP_SECONDS], yd_command=False)
    process = win._processes[-1]
    process.waitForStarted(2000)
    return process


# --- Tracking ---------------------------------------------------------------


def test_launched_command_is_tracked(win):
    assert win._processes == []
    process = _start_sleep(win)
    assert win._processes == [process]


def test_finished_command_is_forgotten(win, qapp):
    win._run_command_in_subprocess("sleep", ["0"], yd_command=False)
    process = win._processes[-1]
    process.waitForFinished(5000)
    qapp.processEvents()  # let the finished signal be delivered

    assert win._processes == []


# --- Stopping ---------------------------------------------------------------


def test_shutdown_stops_a_running_command(win):
    process = _start_sleep(win)
    pid = process.processId()
    assert alive(pid)

    win.shutdown()

    assert process.state() == QProcess.ProcessState.NotRunning
    assert not alive(pid)
    assert win._processes == []


def test_shutdown_reports_what_it_stopped(win):
    _start_sleep(win)
    win.log_output.setPlainText("")

    win.shutdown()

    assert "Stopped 1 running command(s) on exit" in win.log_output.toPlainText()


def test_shutdown_says_nothing_when_no_commands_are_running(win):
    win.log_output.setPlainText("")
    win.shutdown()
    assert "Stopped" not in win.log_output.toPlainText()


def test_shutdown_is_idempotent(win):
    _start_sleep(win)
    win.shutdown()
    win.shutdown()  # must not raise
    assert win._shutting_down is True


def test_stop_process_reports_whether_it_acted(win):
    already_finished = QProcess()
    already_finished.start("sleep", ["0"])
    already_finished.waitForFinished(5000)
    assert win._stop_process(already_finished) is False

    running = _start_sleep(win)
    assert win._stop_process(running) is True


def test_closing_the_window_stops_a_running_command(win, monkeypatch):
    process = _start_sleep(win)
    pid = process.processId()
    monkeypatch.setattr(win, "_confirm_quit", lambda running: True)

    win.close()

    assert process.state() == QProcess.ProcessState.NotRunning
    assert not alive(pid)


# --- Quitting with commands still running -----------------------------------


def test_closing_asks_when_a_command_is_running(win, monkeypatch):
    process = _start_sleep(win)
    asked: list[list[QProcess]] = []
    monkeypatch.setattr(
        win, "_confirm_quit", lambda running: asked.append(running) or True
    )

    win.close()

    assert asked == [[process]]


def test_closing_does_not_ask_when_nothing_is_running(win, monkeypatch):
    def fail(running):
        raise AssertionError("should not ask when no command is running")

    monkeypatch.setattr(win, "_confirm_quit", fail)
    win.close()  # must not raise

    assert win._shutting_down is True


def test_declining_the_quit_keeps_the_window_and_command_alive(win, monkeypatch):
    process = _start_sleep(win)
    pid = process.processId()
    monkeypatch.setattr(win, "_confirm_quit", lambda running: False)

    win.close()

    assert win._shutting_down is False
    assert win.isVisible()
    assert process.state() != QProcess.ProcessState.NotRunning
    assert alive(pid)


def test_internal_helpers_are_not_offered_as_running_commands(win):
    helper = QProcess()
    helper.setProgram("sleep")
    helper.setArguments([SLEEP_SECONDS])
    helper.start()
    helper.waitForStarted(2000)
    win._helper_processes.append(helper)
    try:
        assert win._running_commands() == []
    finally:
        win._stop_process(helper)


def test_confirmations_disabled_quits_without_asking(qapp, monkeypatch):
    window = YellowDogApp(disable_confirmations=True)
    window.show()
    process = _start_sleep(window)
    pid = process.processId()

    def fail(running):
        raise AssertionError("--yes should suppress the quit dialog")

    monkeypatch.setattr(window, "_confirm_quit", fail)
    window.close()

    assert window._shutting_down is True
    assert not alive(pid)


def test_quit_dialog_lists_the_running_commands(win):
    process = _start_sleep(win)
    dialog, quit_btn = win._build_quit_dialog(
        [f"{process.program()} (pid {process.processId()})"]
    )

    assert dialog.windowTitle() == "Commands Still Running"
    listing = dialog.findChild(QPlainTextEdit, "running_listing")
    assert listing.toPlainText() == f"sleep (pid {process.processId()})"

    box = dialog.findChild(QDialogButtonBox)
    assert {button.text() for button in box.buttons()} == {"Cancel", "Quit and Stop"}
    # Cancel is the default: stopping a submission part-way is the worse outcome
    cancel = next(b for b in box.buttons() if b.text() == "Cancel")
    assert cancel.isDefault()
    assert not quit_btn.isDefault()


# --- Nested event loops -----------------------------------------------------


def test_shutdown_releases_a_blocked_nested_loop(win):
    """
    The case that hangs: a synchronous helper waiting on a command that is
    itself blocked on a network timeout. Closing the window must release the
    nested loop instead of leaving it running while the widgets are destroyed.
    """
    process = QProcess()
    process.setProgram("sleep")
    process.setArguments([SLEEP_SECONDS])
    event_loop = QEventLoop()
    process.finished.connect(event_loop.quit)
    process.start()
    process.waitForStarted(2000)
    pid = process.processId()

    QTimer.singleShot(100, win.close)
    win._run_nested(process, event_loop)  # returns only once released

    assert win._shutting_down is True
    assert win._nested_loops == []
    assert win._processes == []
    process.waitForFinished(2000)
    assert not alive(pid)


def test_nested_loop_times_out_and_stops_the_process(win):
    """
    A command that never returns must not hold the nested loop for ever: the
    loop gives up, the child is stopped, and the caller is told it failed.
    """
    process = QProcess()
    process.setProgram("sleep")
    process.setArguments([SLEEP_SECONDS])
    event_loop = QEventLoop()
    process.finished.connect(event_loop.quit)
    process.start()
    process.waitForStarted(2000)
    pid = process.processId()

    finished_normally = win._run_nested(process, event_loop, timeout_ms=300)

    assert finished_normally is False
    assert win._shutting_down is False  # a timeout is not a shutdown
    assert win._nested_loops == []
    assert win._helper_processes == []
    process.waitForFinished(2000)
    assert not alive(pid)


def test_nested_loop_within_the_timeout_reports_success(win):
    process = QProcess()
    process.setProgram("sleep")
    process.setArguments(["0"])
    event_loop = QEventLoop()
    process.finished.connect(event_loop.quit)
    process.start()

    assert win._run_nested(process, event_loop, timeout_ms=10_000) is True


@pytest.mark.real_config_parse
def test_config_parse_timeout_is_bounded(win, monkeypatch):
    """
    _parse_yd_config must pass its timeout through, and report a timeout in the
    log rather than leaving the placeholders silently blank.

    One of the two tests that need the real method rather than the stub the
    '_no_config_discovery' fixture installs.
    """
    seen: dict[str, object] = {}

    def fake_run_nested(process, event_loop, timeout_ms=None):
        seen["timeout_ms"] = timeout_ms
        win._stop_process(process)
        return False  # as if it had timed out

    monkeypatch.setattr(win, "_run_nested", fake_run_nested)
    win._config_parse_invalid = True
    win.log_output.setPlainText("")

    assert win._parse_yd_config(quiet=True) is False
    assert seen["timeout_ms"] == CONFIG_PARSE_TIMEOUT_MS
    # Reported even though quiet=True
    assert "Timed out after 10s parsing configuration" in win.log_output.toPlainText()


@pytest.mark.real_config_parse
def test_config_parse_stays_quiet_when_shutting_down(win, monkeypatch):
    monkeypatch.setattr(
        win, "_run_nested", lambda process, loop, timeout_ms=None: False
    )
    win._config_parse_invalid = True
    win._shutting_down = True
    win.log_output.setPlainText("")

    assert win._parse_yd_config(quiet=True) is False
    assert win.log_output.toPlainText() == ""


def test_run_nested_deregisters_after_normal_completion(win):
    process = QProcess()
    process.setProgram("sleep")
    process.setArguments(["0"])
    event_loop = QEventLoop()
    process.finished.connect(event_loop.quit)
    process.start()

    win._run_nested(process, event_loop)

    assert win._shutting_down is False
    assert win._nested_loops == []
    assert win._processes == []
