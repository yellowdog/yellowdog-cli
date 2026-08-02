"""
Smoke test that the Commander UI actually loads. Constructing YellowDogApp runs
loadUi() against commander.ui and wires every action signal to a named widget,
so a successful construction proves the .ui file is compatible with the
installed PyQt6 and that no code-referenced widget is missing. Guards against
Qt-version incompatibilities and accidental .ui edits.
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QPlainTextEdit, QPushButton

from yellowdog_cli._version import __version__
from yellowdog_cli.commander.commander import YellowDogApp


def test_ui_loads_and_binds_expected_widgets(qapp):
    win = YellowDogApp()

    # loadUi succeeded and the window is the branded Commander window, with the
    # CLI version appended to the title.
    assert win.windowTitle() == f"YellowDog Commander v{__version__}"

    # A representative sample of code-referenced widgets exist with the right
    # types (loadUi would have failed, or __init__'s signal wiring would have
    # raised AttributeError, if any were missing).
    assert isinstance(win.log_output, QPlainTextEdit)
    assert isinstance(win.name_glob_override, QPlainTextEdit)
    assert isinstance(win.submit_work_requirement, QPushButton)
    assert isinstance(win.create_worker_pool, QPushButton)
    assert isinstance(win.download_results, QPushButton)
