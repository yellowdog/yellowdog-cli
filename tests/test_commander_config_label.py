"""
The selected configuration file's label at the top of the right-hand column:
the full path where it fits, elided from the left at a directory boundary where
it does not, refitted as the window is resized, and never widening the window.
"""

import os

import pytest
import qt_guard

qt_guard.require_qt()

from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QApplication, QFrame

from yellowdog_cli.commander.commander import NO_SELECTED_CONFIG, YellowDogApp
from yellowdog_cli.commander.elision import PATH_ELLIPSIS


@pytest.fixture
def win(qapp):
    window = YellowDogApp()
    window.show()
    qapp.processEvents()
    yield window
    window.close()


def config_at(tmp_path, *directories: str) -> str:
    directory = tmp_path.joinpath(*directories)
    directory.mkdir(parents=True)
    config = directory / "config.toml"
    config.write_text("")
    return str(config)


def text_width(win) -> int:
    label = win.select_config_label
    return QFontMetrics(label.font()).horizontalAdvance(label.text())


def test_it_says_when_nothing_is_selected(win):
    win._set_config_file(None)
    assert win.select_config_label.text() == NO_SELECTED_CONFIG
    assert win.select_config_label.toolTip() == ""


def test_it_has_no_bounding_box(win):
    # Framed, it looked like a field that could be typed into
    assert win.select_config_label.frameShape() == QFrame.Shape.NoFrame


def test_a_path_that_fits_is_shown_whole(win, tmp_path):
    config = config_at(tmp_path, "short")
    # pytest's temporary directories are long, so make room for one
    win.resize(win.width() + 1000, win.height())
    QApplication.processEvents()
    win._set_config_file(config)
    assert win.select_config_label.text() == os.path.abspath(config)
    assert win.select_config_label.toolTip() == os.path.abspath(config)


def test_a_long_path_is_elided_to_fit_and_keeps_the_filename(win, tmp_path):
    config = config_at(tmp_path, *[f"a-long-directory-name-{n}" for n in range(12)])
    width = win.width()

    win._set_config_file(config)
    QApplication.processEvents()

    text = win.select_config_label.text()
    assert text.startswith(f"{PATH_ELLIPSIS}{os.sep}"), "cut at a directory boundary"
    assert text.endswith(f"{os.sep}config.toml")
    assert text_width(win) <= win.select_config_label.contentsRect().width()
    assert win.select_config_label.toolTip() == os.path.abspath(config)
    assert win.width() == width, "a long path must not widen the window"


def test_the_path_is_refitted_when_the_window_is_resized(win, tmp_path):
    config = config_at(tmp_path, *[f"a-long-directory-name-{n}" for n in range(12)])
    win._set_config_file(config)
    QApplication.processEvents()
    at_opening = win.select_config_label.text()

    win.resize(win.width() + 400, win.height())
    QApplication.processEvents()
    wider = win.select_config_label.text()

    assert len(wider) > len(at_opening), "more room shows more of the path"
    assert text_width(win) <= win.select_config_label.contentsRect().width()
