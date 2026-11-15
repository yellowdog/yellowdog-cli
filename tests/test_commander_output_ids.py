"""
Tests for acting on the YellowDog IDs in Commander's output window from its
right-click menu: which IDs a line offers, Copy, Show and Follow for each, and
Follow refused for one already followed.
"""

import pytest
import qt_guard

qt_guard.require_qt()

import gui_harness
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtWidgets import QApplication, QMenu

from yellowdog_cli.commander.commander import YellowDogApp
from yellowdog_cli.commander.output_model import OutputRun
from yellowdog_cli.commander.output_pane import (
    FOLLOWABLE_YDID_TYPES,
    MAX_LINE_YDIDS,
    ydid_kind,
    ydids_at,
)

WR = "ydid:workreq:000000:11111111-1111-1111-1111-111111111111"
POOL = "ydid:wrkrpool:000000:22222222-2222-2222-2222-222222222222"
TASK = "ydid:task:000000:11111111-1111-1111-1111-111111111111:1:3"


def test_the_ids_on_a_line_without_repeats_in_order():
    line = f"Created {WR} and {POOL}, then {WR} again"
    assert ydids_at(line, 0) == [WR, POOL]


def test_the_id_under_the_pointer_comes_first():
    line = f"Created {WR} and {POOL}"
    assert ydids_at(line, line.index(POOL) + 3) == [POOL, WR]


def test_at_most_a_few():
    many = " ".join(
        f"ydid:workreq:000000:{n:08d}-1111-1111-1111-111111111111" for n in range(9)
    )
    assert len(ydids_at(many, 0)) == MAX_LINE_YDIDS


def test_a_line_without_ids():
    assert ydids_at("Generated Work Requirement 'render'", 0) == []


def test_the_kinds_are_named():
    assert ydid_kind(WR) == "Work Requirement"
    assert ydid_kind(POOL) == "Worker Pool"
    assert ydid_kind(TASK) == "Task"


def test_follow_is_offered_for_what_yd_follow_follows():
    from yellowdog_cli.utils.follow_utils import _FOLLOWABLE

    assert FOLLOWABLE_YDID_TYPES == _FOLLOWABLE


@pytest.fixture
def window(qapp, monkeypatch):
    window = YellowDogApp()
    gui_harness.shown(window)
    window.ran = []
    monkeypatch.setattr(
        window,
        "_run_command_in_subprocess",
        lambda command, args, **kwargs: window.ran.append((command, args)),
    )
    yield window
    window.shutdown()
    window.close()


def menu_at(window: YellowDogApp, text: str, offset: int = 0) -> QMenu:
    """
    The right-click menu for the line holding 'text', clicked 'offset'
    characters into it.
    """
    document = window.log_output.document()
    assert isinstance(document, QTextDocument)
    block = document.find(text).block()
    assert block.isValid(), f"{text!r} is not shown"
    cursor = QTextCursor(block)
    cursor.movePosition(
        QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, offset
    )
    window.log_output.setTextCursor(cursor)
    window.log_output.ensureCursorVisible()
    position: QPoint = window.log_output.cursorRect(cursor).center()
    return window._output._build_output_menu(position)


def action(menu: QMenu, text: str):
    matching = [a for a in menu.actions() if a.text() == text]
    assert matching, f"no {text!r} in {[a.text() for a in menu.actions()]}"
    return matching[0]


def texts(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions()]


def test_one_id_is_offered_by_its_kind(window):
    window._output.log(f"Created Work Requirement {WR}")
    menu = menu_at(window, "Created Work Requirement")
    for text in (
        "Copy Work Requirement ID",
        "Show Work Requirement",
        "Follow Work Requirement",
    ):
        assert text in texts(menu)


def test_copy_puts_the_id_on_the_clipboard(window):
    window._output.log(f"Created Work Requirement {WR}")
    action(
        menu_at(window, "Created Work Requirement"), "Copy Work Requirement ID"
    ).trigger()
    clipboard = QApplication.clipboard()
    assert clipboard is not None and clipboard.text() == WR


def test_show_runs_yd_show_of_it(window):
    window._output.log(f"Created Work Requirement {WR}")
    action(
        menu_at(window, "Created Work Requirement"), "Show Work Requirement"
    ).trigger()
    assert window.ran == [("yd show", [WR])]


def test_follow_runs_yd_follow_of_it(window):
    window._output.log(f"Created Work Requirement {WR}")
    action(
        menu_at(window, "Created Work Requirement"), "Follow Work Requirement"
    ).trigger()
    assert window.ran == [("yd follow", [WR])]


def test_a_task_is_not_offered_follow(window):
    window._output.log(f"Task {TASK} failed")
    menu = menu_at(window, "failed")
    assert "Show Task" in texts(menu)
    assert not any(text.startswith("Follow") for text in texts(menu))


def test_several_ids_get_a_submenu_each(window):
    window._output.log(f"Pool {POOL} serves {WR}")
    menu = menu_at(window, "serves")
    submenus = [a.menu() for a in menu.actions() if a.menu() is not None]
    titles = [a.text() for a in menu.actions() if a.menu() is not None]
    assert [title.split(" ydid:")[0] for title in titles] == [
        "Worker Pool",
        "Work Requirement",
    ]
    assert texts(submenus[0]) == ["Copy ID", "Show", "Follow"]


def test_a_line_without_ids_offers_none(window):
    window._output.log("Generated Work Requirement 'render'")
    menu = menu_at(window, "Generated")
    assert not any(t.startswith(("Copy ", "Show W", "Follow")) for t in texts(menu))


def test_one_followed_already_is_not_followed_again(window):
    following = OutputRun(5, "yd follow", pid=4242, arguments=(WR,))
    window._output._output_runs[following.run_id] = following
    window._output.log(f"Created Work Requirement {WR}")
    action(
        menu_at(window, "Created Work Requirement"), "Follow Work Requirement"
    ).trigger()
    assert window.ran == []
    assert f"Not following '{WR}' again" in window.log_output.toPlainText()
