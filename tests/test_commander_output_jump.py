"""
Tests for jumping to the end of Commander's output window: the down-arrow
button floating in its bottom-right corner while it is scrolled up, and the
right-click menu's Jump to End.
"""

import pytest
import qt_guard

qt_guard.require_qt()

import gui_harness
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMenu

from yellowdog_cli.commander.commander import YellowDogApp
from yellowdog_cli.commander.output_pane import JUMP_TO_END

LINES = 300  # enough to scroll a window of any font


@pytest.fixture
def window(qapp):
    window = YellowDogApp()
    gui_harness.shown(window)
    for number in range(LINES):
        window._output.log(f"line {number}")
    QApplication.processEvents()
    yield window
    window.shutdown()
    window.close()


def scrollbar(window):
    return window.log_output.verticalScrollBar()


def at_end(window) -> bool:
    return scrollbar(window).value() == scrollbar(window).maximum()


def scroll_up(window) -> None:
    scrollbar(window).setValue(scrollbar(window).maximum() // 2)
    QApplication.processEvents()


def jump_action(window):
    menu: QMenu = window._output._build_output_menu(QPoint(5, 5))
    (action,) = [a for a in menu.actions() if a.text() == JUMP_TO_END]
    return action


def test_the_button_is_hidden_at_the_end(window):
    assert at_end(window)
    assert not window._output._jump_button.isVisible()


def test_scrolling_up_shows_the_button(window):
    scroll_up(window)
    assert window._output._jump_button.isVisible()


def test_the_button_jumps_to_the_end_and_hides(window):
    scroll_up(window)
    window._output._jump_button.click()
    QApplication.processEvents()
    assert at_end(window)
    assert not window._output._jump_button.isVisible()


def test_after_the_jump_new_output_is_followed(window):
    scroll_up(window)
    window._output._jump_button.click()
    window._output.log("a line arriving after the jump")
    QApplication.processEvents()
    assert at_end(window)


def test_scrolled_up_new_output_is_not_followed(window):
    # Which is what the button is for
    scroll_up(window)
    before = scrollbar(window).value()
    window._output.log("a line arriving while scrolled up")
    QApplication.processEvents()
    assert scrollbar(window).value() == before
    assert window._output._jump_button.isVisible()


def wheel(window, dx: int = 0, dy: int = 0, times: int = 10) -> None:
    """
    Scroll as a mouse wheel or trackpad does, by wheel events to the
    viewport, which scroll its contents (and its children) rather than set
    the scrollbar from outside.
    """
    viewport = window.log_output.viewport()
    centre = QPointF(viewport.rect().center())
    for _ in range(times):
        QApplication.sendEvent(
            viewport,
            QWheelEvent(
                centre,
                QPointF(viewport.mapToGlobal(centre.toPoint())),
                QPoint(dx, dy),
                QPoint(dx, dy),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            ),
        )
        QApplication.processEvents()


def in_the_corner(window) -> bool:
    """
    Whether the button is inside the viewport, in its bottom-right quarter.
    """
    viewport = window.log_output.viewport()
    corner = window._output._jump_button.geometry()
    return (
        viewport.rect().contains(corner)
        and corner.left() > viewport.width() * 3 // 4
        and corner.top() > viewport.height() * 3 // 4
    )


def test_wheel_scrolling_up_shows_the_button_in_the_corner(window):
    # Scrolling moves the viewport's children with its text, which carried the
    # button up out of the corner, out of sight, as the output scrolled
    wheel(window, dy=120)
    assert not at_end(window)
    assert window._output._jump_button.isVisible()
    assert in_the_corner(window)


def test_the_button_stays_in_the_corner_scrolling_sideways(window):
    window._output.log("x" * 2000)  # wider than any window, as lines never wrap
    wheel(window, dy=120)
    wheel(window, dx=-120)
    assert window.log_output.horizontalScrollBar().value() > 0
    assert in_the_corner(window)


def test_the_button_stays_in_the_corner_as_the_window_resizes(window):
    # Smaller as well as larger: at its minimum height, as run_app() opens it,
    # the viewport is far shorter than before the window was shown
    wheel(window, dy=120)
    for width, height in (
        (window.minimumWidth(), window.minimumHeight()),
        (1400, 1000),
        (window.minimumWidth(), window.minimumHeight()),
    ):
        window.resize(width, height)
        QApplication.processEvents()
        assert in_the_corner(window), (width, height)


def test_a_click_focuses_the_output_window_not_the_button(window):
    # A real mouse click, not click(), which moves no focus at all: the click
    # lands in the output window, so the focus goes there, as a click anywhere
    # in it would, and not to the button
    window.output_text_filter.setFocus()
    scroll_up(window)
    QTest.mouseClick(window._output._jump_button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert at_end(window)
    assert QApplication.focusWidget() is window.log_output


def test_the_menu_entry_is_greyed_at_the_end(window):
    assert not jump_action(window).isEnabled()


def test_the_menu_entry_jumps_to_the_end(window):
    scroll_up(window)
    action = jump_action(window)
    assert action.isEnabled()
    action.trigger()
    QApplication.processEvents()
    assert at_end(window)
    assert not window._output._jump_button.isVisible()
