"""
Ctrl+C in the terminal running Commander or the Usage Explorer
(commander.quit_on_interrupt(), installed by make_application()): the
application quits as Quit does, exiting 130, rather than aborting when the
next Qt callback raises the KeyboardInterrupt. Run in a child process, since
the handler replaces the test process's own SIGINT handling.
"""

import os
import subprocess
import sys
import textwrap

import qt_guard

qt_guard.require_qt()

import pytest

# The application made as both apps make it, a window shown with a Python
# event filter (as the explorer's is), Ctrl+C sent, and the window closed a
# moment later, as by its close button: the sequence that aborted
CHILD = textwrap.dedent(
    """
    import os, signal, sys
    from PyQt6.QtCore import QObject, QTimer
    from PyQt6.QtWidgets import QWidget
    from yellowdog_cli.commander.commander import make_application

    class Filter(QObject):
        def eventFilter(self, watched, event):
            return False

    app = make_application()
    window = QWidget()
    events = Filter()
    window.installEventFilter(events)
    app.aboutToQuit.connect(lambda: print("about to quit", flush=True))
    window.show()

    def interrupt():
        os.kill(os.getpid(), signal.SIGINT)
        QTimer.singleShot(300, window.close)

    QTimer.singleShot(300, interrupt)
    sys.exit(app.exec())
    """
)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="os.kill() cannot send SIGINT to a process on Windows",
)
def test_ctrl_c_quits_as_quit_does_and_exits_130(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", CHILD],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert "Fatal Python error" not in result.stderr
    assert "KeyboardInterrupt" not in result.stderr
    assert result.stdout == "about to quit\n"
    assert result.returncode == 130
