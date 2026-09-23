"""
Tests for filtering Commander's output window to one command's output.

The commands are real child processes, run through _run_command_in_subprocess, so
their output reaches the window the way a yd-* command's does — by the QProcess
signals, in whatever chunks the pipe delivers — and is attributed to its run on the
way in. That attribution is what the filter depends on: most of a command's output
carries no PID (continuation lines, tables, JSON), and the 'Executing:' line
announcing it carries Commander's.
"""

import sys

import pytest
import qt_guard

qt_guard.require_qt()

import commander_dialogs
import gui_harness
from PyQt6.QtCore import QEventLoop, QPoint, QProcess, Qt, QTimer
from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMenu

from yellowdog_cli.commander.commander import YellowDogApp
from yellowdog_cli.commander.output_model import OutputRun, block_count
from yellowdog_cli.commander.output_pane import (
    SHOW_ALL_OUTPUT,
    SHOW_OUTPUT_FROM_PROCESS,
)

CHILD_TIMEOUT_MS = 10_000


@pytest.fixture
def window(qapp):
    return gui_harness.shown(YellowDogApp())


def run_child(window: YellowDogApp, *lines: str):
    """
    Run a child process printing 'lines' through Commander, and wait for its
    output to have been delivered.
    """
    # Hex-encoded, so that the 'Executing:' line echoing the command line does
    # not contain the text the command prints, which the tests search for
    window._run_command_in_subprocess(
        sys.executable,
        [
            "-c",
            "import sys; print(bytes.fromhex(sys.argv[1]).decode())",
            "\n".join(lines).encode().hex(),
        ],
        yd_command=False,
    )
    process: QProcess = window._processes[-1]
    loop = QEventLoop()
    process.finished.connect(loop.quit)
    QTimer.singleShot(CHILD_TIMEOUT_MS, loop.quit)
    if process.state() != QProcess.ProcessState.NotRunning:
        loop.exec()
    assert process.state() == QProcess.ProcessState.NotRunning, "child hung"


def shown(window: YellowDogApp) -> str:
    return window.log_output.toPlainText()


def position_of(window: YellowDogApp, text: str) -> QPoint:
    """Where, in the output window's viewport, the line containing 'text' is."""
    document = window.log_output.document()
    assert isinstance(document, QTextDocument)
    block = document.find(text).block()
    assert block.isValid(), f"{text!r} is not shown"
    window.log_output.setTextCursor(QTextCursor(block))
    window.log_output.ensureCursorVisible()
    return window.log_output.cursorRect(QTextCursor(block)).center()


def menu_action(menu: QMenu, text: str):
    matching = [action for action in menu.actions() if action.text() == text]
    assert matching, f"no {text!r} in {[a.text() for a in menu.actions()]}"
    return matching[0]


def filter_to_line_containing(window: YellowDogApp, text: str):
    """Filter the way a user does: right-click the line, choose the Show Only item."""
    menu = window._output._build_output_menu(position_of(window, text))
    show_only = [a for a in menu.actions() if a.text().startswith("Show Only")]
    assert len(show_only) == 1, [a.text() for a in menu.actions()]
    show_only[0].trigger()


@pytest.fixture
def two_runs(window):
    window._output.log("Commander says hello")
    run_child(
        window,
        "2026-09-23 10:00:00 (123456) : first command, first message",
        "                              which wraps onto a second line",
        "| a | table |",
    )
    run_child(window, "2026-09-23 10:00:01 (654321) : second command's message")
    return window


@pytest.mark.parametrize(
    "text", ["one", "", "a\nb", "a\n", "a\r\nb", "a\rb", "a\u2029b", "a\u2028b"]
)
def test_block_count_is_qts(qapp, text):
    # The window's blocks are tagged with their entry by counting, so a count
    # that disagreed with Qt's would misattribute every line after it.
    document = QTextDocument()
    document.setPlainText(text)
    assert block_count(text) == document.blockCount()


def test_filtering_keeps_the_whole_of_the_run(two_runs):
    filter_to_line_containing(two_runs, "first message")

    text = shown(two_runs)
    assert "Executing:" in text, "the line saying what the command was"
    assert "first message" in text
    assert "which wraps onto a second line" in text, "a line with no PID"
    assert "| a | table |" in text
    assert "second command" not in text
    assert "Commander says hello" not in text
    assert text.count("Executing:") == 1


def test_any_line_of_a_run_selects_it_not_just_a_prefixed_one(two_runs):
    filter_to_line_containing(two_runs, "| a | table |")

    assert "first message" in shown(two_runs)
    assert "second command" not in shown(two_runs)


def show_only_texts(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions() if a.text().startswith("Show Only")]


def test_the_executing_line_offers_its_command_and_commander(two_runs):
    # It belongs to the command, but it is printed with Commander's PID, so a
    # user reading the PID on it could mean either.
    menu = two_runs._output._build_output_menu(position_of(two_runs, "Executing:"))

    assert show_only_texts(menu) == [
        f"Show Only Output from Process 123456 ({sys.executable})",
        "Show Only Commander's Own Messages",
    ], "the command first: it is what the line is about"


def test_the_executing_line_selects_its_command(two_runs):
    menu = two_runs._output._build_output_menu(position_of(two_runs, "Executing:"))
    menu_action(menu, show_only_texts(menu)[0]).trigger()

    assert "first message" in shown(two_runs)
    assert "Commander says hello" not in shown(two_runs)


def test_the_executing_line_selects_commander(two_runs):
    menu = two_runs._output._build_output_menu(position_of(two_runs, "Executing:"))
    menu_action(menu, "Show Only Commander's Own Messages").trigger()

    text = shown(two_runs)
    assert "Commander says hello" in text
    assert text.count("Executing:") == 2, "every command's, not just the one clicked"
    assert "first message" not in text


def test_filtered_to_commander_an_executing_line_offers_its_command(two_runs):
    filter_to_line_containing(two_runs, "Commander says hello")

    menu = two_runs._output._build_output_menu(position_of(two_runs, "Executing:"))

    assert show_only_texts(menu) == [
        f"Show Only Output from Process 123456 ({sys.executable})"
    ]
    menu_action(menu, show_only_texts(menu)[0]).trigger()
    assert "first message" in shown(two_runs)


def test_an_executing_line_arriving_while_filtered_to_commander_is_shown(two_runs):
    filter_to_line_containing(two_runs, "Commander says hello")

    run_child(two_runs, "a third command's message")

    assert shown(two_runs).count("Executing:") == 3
    assert "a third command's message" not in shown(two_runs)
    assert two_runs.output_filter_label.text().endswith(" · 1 new line hidden")


def test_the_menu_names_the_pid_the_command_printed(two_runs):
    menu = two_runs._output._build_output_menu(position_of(two_runs, "second command"))

    menu_action(menu, "Show Only Output from Process 654321 (" + sys.executable + ")")


def test_commanders_own_messages_can_be_filtered_to(two_runs):
    menu = two_runs._output._build_output_menu(
        position_of(two_runs, "Commander says hello")
    )
    menu_action(menu, "Show Only Commander's Own Messages").trigger()

    assert "Commander says hello" in shown(two_runs)
    assert "first message" not in shown(two_runs)
    assert "second command" not in shown(two_runs)


def test_the_menu_keeps_the_standard_actions(two_runs):
    menu = two_runs._output._build_output_menu(position_of(two_runs, "first message"))

    texts = [action.text() for action in menu.actions()]
    assert any("Copy" in text for text in texts)
    assert any("Select All" in text for text in texts)
    assert SHOW_ALL_OUTPUT not in texts, "nothing to show all of yet"


def test_the_bar_says_what_is_shown_and_show_all_ends_it(two_runs):
    assert not two_runs.output_filter_bar.isVisible()
    everything = shown(two_runs)

    filter_to_line_containing(two_runs, "second command")

    assert two_runs.output_filter_bar.isVisible()
    label = two_runs.output_filter_label.text()
    assert "process 654321" in label
    assert f"2 of {everything.count(chr(10)) + 1} lines" in label
    assert "hidden" not in label, "nothing new has arrived"

    two_runs.output_filter_show_all.click()

    assert not two_runs.output_filter_bar.isVisible()
    assert shown(two_runs) == everything, "in the original order"


def test_the_menu_offers_show_all_while_filtered(two_runs):
    filter_to_line_containing(two_runs, "second command")

    menu = two_runs._output._build_output_menu(position_of(two_runs, "second command"))
    texts = [action.text() for action in menu.actions()]
    assert not any(text.startswith("Show Only") for text in texts), (
        "already showing only that"
    )
    menu_action(menu, SHOW_ALL_OUTPUT).trigger()

    assert "first message" in shown(two_runs)


def test_escape_ends_the_filter(two_runs):
    filter_to_line_containing(two_runs, "second command")
    two_runs.log_output.setFocus()

    QTest.keyClick(two_runs.log_output, Qt.Key.Key_Escape)

    assert "first message" in shown(two_runs)
    assert not two_runs.output_filter_bar.isVisible()


def test_output_arriving_while_filtered(two_runs):
    # Counted on the bar's label, and shown by Show All Output: the bar's only
    # button, because a second one doing the same would say nothing more.
    filter_to_line_containing(two_runs, "second command")
    assert two_runs._output._output_filter is not None
    (second_run,) = two_runs._output._output_filter

    two_runs._output.log("more from Commander")
    two_runs._output.log("more from the second command", prefix=False, run=second_run)

    assert "more from Commander" not in shown(two_runs)
    assert "more from the second command" in shown(two_runs)
    assert two_runs.output_filter_label.text().endswith(" · 1 new line hidden")

    run_child(two_runs, "a third command's message", "and another line")
    assert two_runs.output_filter_label.text().endswith(" · 4 new lines hidden")

    two_runs.output_filter_show_all.click()
    assert "more from Commander" in shown(two_runs)
    assert "a third command's message" in shown(two_runs)


def test_a_line_arriving_while_filtered_can_itself_be_filtered_to(two_runs):
    # Appended to a filtered view, it must be tagged like any other line.
    filter_to_line_containing(two_runs, "second command")
    assert two_runs._output._output_filter is not None
    (second_run,) = two_runs._output._output_filter
    two_runs._output.log("more from the second command", prefix=False, run=second_run)
    two_runs._output._show_all_output()

    filter_to_line_containing(two_runs, "more from the second command")

    assert "second command's message" in shown(two_runs)
    assert "first message" not in shown(two_runs)


def test_clear_clears_everything_and_ends_the_filter(two_runs):
    filter_to_line_containing(two_runs, "second command")

    two_runs.clear_command_output.click()

    assert shown(two_runs) == ""
    assert not two_runs.output_filter_bar.isVisible()
    two_runs._output.log("after the clear")
    assert shown(two_runs).endswith("after the clear")
    assert "first message" not in shown(two_runs)


def test_copy_takes_what_is_shown(two_runs):
    filter_to_line_containing(two_runs, "second command")

    two_runs.copy_command_output.click()

    clipboard = QApplication.clipboard()
    assert clipboard is not None
    assert clipboard.text() == shown(two_runs)
    assert "first message" not in clipboard.text()
    assert "Only the lines shown" in two_runs.copy_command_output.toolTip()


def test_save_takes_what_is_shown(two_runs, tmp_path, monkeypatch):
    target = tmp_path / "saved.txt"
    monkeypatch.setattr(
        two_runs._file_dialogs, "save_file", lambda **kwargs: str(target)
    )
    filter_to_line_containing(two_runs, "second command")
    expected = shown(two_runs)

    two_runs.save_command_output.click()

    assert target.read_text(encoding="utf-8") == f"{expected}\n"


def interleaved(window: YellowDogApp, runs: int = 60):
    """Many short runs, interleaved with Commander's messages, to scroll through."""
    window._output._output_runs[1] = OutputRun(1, "yd-a", pid=111111)
    window._output._output_runs[2] = OutputRun(2, "yd-b", pid=222222)
    for n in range(runs):
        window._output.log(f"a{n:03d}", prefix=False, run=1)
        window._output.log(f"b{n:03d}", prefix=False, run=2)


def row_on_screen(window: YellowDogApp, text: str) -> int:
    document = window.log_output.document()
    assert isinstance(document, QTextDocument)
    block = document.find(text).block()
    return block.blockNumber() - window.log_output.firstVisibleBlock().blockNumber()


def test_the_line_right_clicked_stays_where_it_was(window):
    interleaved(window)
    scrollbar = window.log_output.verticalScrollBar()
    assert scrollbar is not None
    scrollbar.setValue(scrollbar.maximum() // 2)
    # An 'a' line a few rows down from the top, so that its row is not trivially 0
    block = window.log_output.firstVisibleBlock().next().next().next()
    if not block.text().startswith("a"):
        block = block.next()
    target = block.text()
    before = row_on_screen(window, target)
    assert before > 0

    menu = window._output._build_output_menu(
        window.log_output.cursorRect(
            QTextCursor(window.log_output.document().find(target).block())
        ).center()
    )
    menu_action(menu, "Show Only Output from Process 111111 (yd-a)").trigger()

    assert row_on_screen(window, target) == before


def test_ending_the_filter_keeps_the_top_line_in_view(window):
    interleaved(window)
    window._output._filter_output(frozenset({1}))
    scrollbar = window.log_output.verticalScrollBar()
    assert scrollbar is not None
    scrollbar.setValue(scrollbar.maximum() // 2)
    top = window.log_output.firstVisibleBlock().text()

    window._output._show_all_output()

    assert window.log_output.firstVisibleBlock().text() == top


def test_following_the_end_keeps_following(window):
    interleaved(window)
    scrollbar = window.log_output.verticalScrollBar()
    assert scrollbar is not None
    scrollbar.setValue(scrollbar.maximum())

    window._output._filter_output(frozenset({1}))

    assert scrollbar.value() == scrollbar.maximum()
    window._output.log("a-late", prefix=False, run=1)
    assert scrollbar.value() == scrollbar.maximum()


def test_right_clicking_opens_the_menu(window, monkeypatch):
    # The wiring from the widget's context-menu signal to the menu Commander
    # builds; the menu itself is driven inside its real exec().
    interleaved(window, runs=3)
    point = position_of(window, "b001")
    chosen: list[str] = []

    def choose():
        popup = QApplication.activePopupWidget()
        assert isinstance(popup, QMenu), "no menu was shown"
        action = menu_action(popup, "Show Only Output from Process 222222 (yd-b)")
        chosen.append(action.text())
        action.trigger()
        popup.close()

    def watchdog():
        popup = QApplication.activePopupWidget()
        if popup is not None:
            popup.close()

    QTimer.singleShot(0, choose)
    QTimer.singleShot(gui_harness.MODAL_WATCHDOG_MS, watchdog)
    window.log_output.customContextMenuRequested.emit(point)

    assert chosen
    assert "a001" not in shown(window)
    assert "b001" in shown(window)


# The process chooser: 'Show Output from Process…' on the same menu.


def rows_of(dialog) -> list[str]:
    process_list = commander_dialogs.listing(dialog)
    return [process_list.item(n).text() for n in range(process_list.count())]


def chooser_rows(window: YellowDogApp):
    """The chooser's rows, read from inside its real exec() and then cancelled."""
    rows: list[str] = []
    return rows, lambda dialog: rows.extend(rows_of(dialog))


def open_chooser_from(window: YellowDogApp, text: str):
    menu = window._output._build_output_menu(position_of(window, text))
    menu_action(menu, SHOW_OUTPUT_FROM_PROCESS).trigger()


def test_the_chooser_lists_commander_then_the_commands_in_order(two_runs, monkeypatch):
    rows, inspect = chooser_rows(two_runs)
    commander_dialogs.drive_process_chooser(
        two_runs, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )

    open_chooser_from(two_runs, "Commander says hello")

    assert len(rows) == 3
    assert "Commander's own messages" in rows[0]
    assert f"{two_runs._pid:06d}" in rows[0]
    assert rows[1].startswith("123456"), "the PID the command printed"
    assert rows[2].startswith("654321")
    assert all("exit 0" in row for row in rows[1:])
    assert rows[1].rstrip().endswith("4 lines"), "Executing line + three printed"
    assert rows[2].rstrip().endswith("2 lines")
    assert rows[0].rstrip().endswith("3 lines"), "its message and two Executing lines"


def test_the_chooser_shows_the_command_line_as_the_user_gave_it(window, monkeypatch):
    # Not the echoed one, with the config source and '--nf --pp' Commander adds.
    window._build_command_args = lambda command, args, yd_command: (
        ["--nc", "--nf", "--pp", *args]
    )
    run_child(window, "hello")
    rows, inspect = chooser_rows(window)
    commander_dialogs.drive_process_chooser(
        window, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )

    window._output._choose_output_run()

    assert "--nf" in shown(window), "the echo still carries them"
    assert "--nf" not in rows[1]
    assert sys.executable in rows[1]


def test_the_rows_line_up(two_runs, monkeypatch):
    rows, inspect = chooser_rows(two_runs)
    commander_dialogs.drive_process_chooser(
        two_runs, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )

    two_runs._output._choose_output_run()

    assert len({len(row) for row in rows}) == 1, "padded to a common width"


def test_choosing_one_row_filters_to_it(two_runs, monkeypatch):
    # Opened from the second command's line, so that is ticked; swap it for the first.
    commander_dialogs.drive_process_chooser(
        two_runs,
        monkeypatch,
        commander_dialogs.ACCEPT,
        tick_rows=(1,),
        untick_rows=(2,),
    )

    open_chooser_from(two_runs, "second command")

    assert "first message" in shown(two_runs)
    assert "second command" not in shown(two_runs)
    assert two_runs.output_filter_bar.isVisible()


def test_choosing_two_rows_shows_both(two_runs, monkeypatch):
    commander_dialogs.drive_process_chooser(
        two_runs, monkeypatch, commander_dialogs.ACCEPT, tick_rows=(1,)
    )

    open_chooser_from(two_runs, "second command")

    text = shown(two_runs)
    assert "first message" in text
    assert "which wraps onto a second line" in text
    assert "second command's message" in text
    assert "Commander says hello" not in text
    assert text.index("first message") < text.index("second command's message"), (
        "in the order they arrived"
    )


def test_two_commands_and_commander(two_runs, monkeypatch):
    commander_dialogs.drive_process_chooser(
        two_runs, monkeypatch, commander_dialogs.ACCEPT, tick_rows=(0, 1, 2)
    )

    two_runs._output._choose_output_run()

    assert shown(two_runs).count("Executing:") == 2, "once each, not twice"
    assert "Commander says hello" in shown(two_runs)
    label = two_runs.output_filter_label.text()
    assert label.startswith("Showing only output from process 123456"), (
        "the commands first"
    )
    assert "process 654321" in label
    assert " and Commander's own messages · " in label


def test_the_bar_names_every_process_shown(two_runs, monkeypatch):
    commander_dialogs.drive_process_chooser(
        two_runs, monkeypatch, commander_dialogs.ACCEPT, tick_rows=(1, 2)
    )

    two_runs._output._choose_output_run()

    label = two_runs.output_filter_label.text()
    assert label.startswith(
        f"Showing only output from process 123456 ({sys.executable})"
        f" and process 654321 ({sys.executable}) · "
    )
    assert two_runs.output_filter_label.toolTip().count("\n") == 1, (
        "one command line each"
    )


def test_output_arriving_for_either_is_shown(two_runs, monkeypatch):
    commander_dialogs.drive_process_chooser(
        two_runs, monkeypatch, commander_dialogs.ACCEPT, tick_rows=(1, 2)
    )
    two_runs._output._choose_output_run()
    first, second = sorted(two_runs._output._output_filter or ())

    two_runs._output.log("late from the first", prefix=False, run=first)
    two_runs._output.log("late from the second", prefix=False, run=second)
    two_runs._output.log("late from Commander")

    assert "late from the first" in shown(two_runs)
    assert "late from the second" in shown(two_runs)
    assert "late from Commander" not in shown(two_runs)


def test_the_menu_offers_one_of_several_shown(two_runs, monkeypatch):
    # Filtered to two, right-clicking one of them narrows to it.
    commander_dialogs.drive_process_chooser(
        two_runs, monkeypatch, commander_dialogs.ACCEPT, tick_rows=(1, 2)
    )
    two_runs._output._choose_output_run()

    filter_to_line_containing(two_runs, "second command's message")

    assert "first message" not in shown(two_runs)
    assert "second command's message" in shown(two_runs)


def test_show_output_is_greyed_with_nothing_ticked(two_runs, monkeypatch):
    enabled: list[bool] = []

    def inspect(dialog):
        commander_dialogs.untick(dialog, (2,))
        enabled.append(gui_harness.button_labelled(dialog, "Show Output").isEnabled())

    commander_dialogs.drive_process_chooser(
        two_runs, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )

    two_runs._output._choose_output_run()

    assert enabled == [False]


def test_cancel_changes_nothing(two_runs, monkeypatch):
    before = shown(two_runs)
    commander_dialogs.drive_process_chooser(
        two_runs, monkeypatch, commander_dialogs.CANCEL, tick_rows=(1,)
    )

    open_chooser_from(two_runs, "second command")

    assert shown(two_runs) == before
    assert not two_runs.output_filter_bar.isVisible()


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_return_accepts(two_runs, monkeypatch, key):
    def inspect(dialog):
        process_list = commander_dialogs.listing(dialog)
        process_list.setFocus()
        QTest.keyClick(process_list, key)

    commander_dialogs.drive_process_chooser(
        two_runs, monkeypatch, commander_dialogs.NOTHING, inspect=inspect
    )

    two_runs._output._choose_output_run()

    assert "second command" in shown(two_runs)
    assert "first message" not in shown(two_runs)


def ticked_when_opened(window, monkeypatch, open_it) -> list[int]:
    seen: list[list[int]] = []
    commander_dialogs.drive_process_chooser(
        window,
        monkeypatch,
        commander_dialogs.CANCEL,
        inspect=lambda dialog: seen.append(commander_dialogs.ticked(dialog)),
    )
    open_it()
    return seen[0]


def test_the_latest_is_ticked_by_default(two_runs, monkeypatch):
    assert ticked_when_opened(
        two_runs, monkeypatch, two_runs._output._choose_output_run
    ) == [2]


def test_the_line_right_clicked_is_ticked(two_runs, monkeypatch):
    assert ticked_when_opened(
        two_runs, monkeypatch, lambda: open_chooser_from(two_runs, "first message")
    ) == [1]


def test_an_executing_line_ticks_its_command(two_runs, monkeypatch):
    assert ticked_when_opened(
        two_runs, monkeypatch, lambda: open_chooser_from(two_runs, "Executing:")
    ) == [1]


def test_the_runs_shown_are_ticked(two_runs, monkeypatch):
    two_runs._output._filter_output(frozenset({0, 2}))
    assert ticked_when_opened(
        two_runs, monkeypatch, lambda: open_chooser_from(two_runs, "Executing:")
    ) == [0, 2]


def test_show_output_is_the_default_button(two_runs, monkeypatch):
    defaults: list = []
    commander_dialogs.drive_process_chooser(
        two_runs,
        monkeypatch,
        commander_dialogs.CANCEL,
        inspect=lambda dialog: defaults.append(gui_harness.default_button(dialog)),
    )

    two_runs._output._choose_output_run()

    assert defaults[0] is not None and defaults[0].text() == "Show Output"


def listing_widths(window, monkeypatch) -> tuple[int, int, int]:
    """The chooser listing's viewport width and its rows', and the window's."""
    widths: list[tuple[int, int]] = []

    def inspect(dialog):
        process_list = commander_dialogs.listing(dialog)
        widths.append(
            (process_list.viewport().width(), process_list.sizeHintForColumn(0))
        )

    commander_dialogs.drive_process_chooser(
        window, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )
    window._output._choose_output_run()
    return (*widths[0], window.width())


def test_the_listing_is_wide_enough_for_its_rows(window, monkeypatch):
    interleaved(window, runs=2)

    viewport, content, _ = listing_widths(window, monkeypatch)

    assert viewport >= content, "a row elided in a window with room for it"


def test_the_listing_is_no_wider_than_the_window(window, monkeypatch):
    window._output._output_runs[1] = OutputRun(1, "yd-a", pid=111111)
    window._output._output_runs[1].user_command_line = "yd-a " + "x" * 2000
    window._output.log("a line", prefix=False, run=1)

    viewport, content, window_width = listing_widths(window, monkeypatch)

    assert content > window_width, "the row is too long to fit, as intended"
    assert viewport < window_width, "elided rather than stretching the dialog"


def test_a_cleared_finished_run_is_not_listed_but_a_running_one_is(
    two_runs, monkeypatch
):
    two_runs._run_command_in_subprocess(
        sys.executable, ["-c", "import time; time.sleep(30)"], yd_command=False
    )
    try:
        two_runs.clear_command_output.click()
        rows, inspect = chooser_rows(two_runs)
        commander_dialogs.drive_process_chooser(
            two_runs, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
        )

        two_runs._output._choose_output_run()

        assert len(rows) == 1
        assert "time.sleep" in rows[0]
        assert "running" in rows[0]
    finally:
        two_runs.shutdown()


def test_a_command_that_did_not_start(window, monkeypatch):
    window._run_command_in_subprocess("no-such-command-here", [], yd_command=False)
    rows, inspect = chooser_rows(window)
    commander_dialogs.drive_process_chooser(
        window, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )

    window._output._choose_output_run()

    assert "did not start" in rows[1]


def test_the_menu_item_is_greyed_with_nothing_to_choose(window):
    window.clear_command_output.click()

    menu = window._output._build_output_menu(QPoint(5, 5))

    assert not menu_action(menu, SHOW_OUTPUT_FROM_PROCESS).isEnabled()


def test_the_menu_item_is_there_while_filtered(two_runs):
    filter_to_line_containing(two_runs, "second command")

    menu = two_runs._output._build_output_menu(position_of(two_runs, "second command"))

    assert menu_action(menu, SHOW_OUTPUT_FROM_PROCESS).isEnabled()
