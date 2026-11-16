"""
Tests for jumping to the end and the top of Commander's output window: the
down-arrow button floating in its bottom-right corner while it is scrolled up,
the up-arrow button in its top-right corner while it is scrolled down, and the
right-click menu's Jump to End and Jump to Top.
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
from yellowdog_cli.commander.output_pane import JUMP_TO_END, JUMP_TO_TOP

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


def at_top(window) -> bool:
    return scrollbar(window).value() == scrollbar(window).minimum()


def jump_action(window, text: str = JUMP_TO_END):
    menu: QMenu = window._output._build_output_menu(QPoint(5, 5))
    (action,) = [a for a in menu.actions() if a.text() == text]
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


def test_at_the_end_the_view_stays_there_as_its_range_grows(window):
    # The range grown with nothing else following it, as Windows was seen to
    # leave a view just jumped to its end: Commander keeps it there itself
    assert at_end(window)
    bar = scrollbar(window)
    bar.setRange(bar.minimum(), bar.maximum() + 50)
    QApplication.processEvents()
    assert at_end(window)


def test_scrolled_up_the_view_stays_put_as_its_range_grows(window):
    scroll_up(window)
    bar = scrollbar(window)
    before = bar.value()
    bar.setRange(bar.minimum(), bar.maximum() + 50)
    QApplication.processEvents()
    assert bar.value() == before


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
    Whether the Jump to End button is inside the viewport, in its bottom-right
    quarter, and the Jump to Top button in its top-right quarter.
    """
    viewport = window.log_output.viewport()
    bottom = window._output._jump_button.geometry()
    top = window._output._jump_top_button.geometry()
    return (
        viewport.rect().contains(bottom)
        and bottom.left() > viewport.width() * 3 // 4
        and bottom.top() > viewport.height() * 3 // 4
        and viewport.rect().contains(top)
        and top.left() > viewport.width() * 3 // 4
        and top.bottom() < viewport.height() // 4
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


# --- Jump to Top -------------------------------------------------------------


def test_the_top_button_shows_away_from_the_top(window):
    # The fixture leaves the view at its end, far from its top
    assert window._output._jump_top_button.isVisible()


def test_the_top_button_jumps_to_the_top_and_hides(window):
    window._output._jump_top_button.click()
    QApplication.processEvents()
    assert at_top(window)
    assert not window._output._jump_top_button.isVisible()
    assert window._output._jump_button.isVisible()


def test_at_the_top_new_output_is_not_followed(window):
    window._output._jump_top_button.click()
    window._output.log("a line arriving at the top")
    QApplication.processEvents()
    assert at_top(window)


def test_a_short_output_shows_neither_button(qapp):
    window = YellowDogApp()
    try:
        gui_harness.shown(window)
        window._output.log("one line")
        QApplication.processEvents()
        assert not window._output._jump_button.isVisible()
        assert not window._output._jump_top_button.isVisible()
    finally:
        window.shutdown()
        window.close()


def test_the_top_menu_entry_jumps_to_the_top(window):
    action = jump_action(window, JUMP_TO_TOP)
    assert action.isEnabled()
    action.trigger()
    QApplication.processEvents()
    assert at_top(window)
    assert not jump_action(window, JUMP_TO_TOP).isEnabled()


# --- The arrow buttons' font ------------------------------------------------


def test_the_arrow_font_is_the_window_font_scaled(monkeypatch):
    from PyQt6.QtGui import QFont

    from yellowdog_cli.commander import output_pane

    monkeypatch.setattr(output_pane, "ARROW_FONT_SCALE", 1.6)
    font = output_pane.arrow_font(QFont("Helvetica", 9))
    assert (font.family(), font.pointSize()) == ("Helvetica", 14)


def test_the_arrow_buttons_use_the_arrow_font(qapp, monkeypatch):
    # Larger than the window's font where the scale says so (off macOS, whose
    # default font draws its arrows large enough already)
    from yellowdog_cli.commander import output_pane

    monkeypatch.setattr(output_pane, "ARROW_FONT_SCALE", 1.6)
    window = YellowDogApp()
    try:
        expected = round(window.font().pointSizeF() * 1.6)
        for button in (
            window.prev_command,
            window.next_command,
            window._output._jump_button,
            window._output._jump_top_button,
        ):
            assert button.font().pointSize() == expected, button.objectName()
    finally:
        window.shutdown()
        window.close()


def test_macos_keeps_the_window_font_size():
    from yellowdog_cli.commander import output_pane
    from yellowdog_cli.commander.host import MACOS

    assert (output_pane.ARROW_FONT_SCALE == 1.0) is MACOS
