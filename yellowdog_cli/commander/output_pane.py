"""
The output window (OutputPane): the widget, its filter bar and right-click menu,
the process chooser and the text filter, over the entries and runs in
output_model. The window logs to it and hands it each process it starts;
everything the filters do is here.
"""

import re
from collections.abc import Callable
from datetime import datetime
from functools import partial as functools_partial
from typing import cast

from PyQt6.QtCore import QPoint, QProcess, Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QShortcut, QTextBlock, QTextDocument
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollBar,
    QWidget,
)

from yellowdog_cli.commander.output_model import (
    COMMANDER_RUN,
    LineBuffer,
    OutputEntry,
    OutputRun,
    filter_description,
    line_pattern,
    message_prefix,
)
from yellowdog_cli.commander.selection import (
    MAX_DIALOG_LIST_ROWS,
    SelectableRow,
    checked_handles,
)

# The prefix a 'yd-*' command run with '--pp' gives each message, carrying the PID
# of the process that printed it; see OutputRun.printed_pid.
PREFIXED_PID = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \((\d+)\) : ")
SHOW_ALL_OUTPUT = "Show All Output"
SHOW_OUTPUT_FROM_PROCESS = "Show Output from Process…"
PROCESS_DIALOG_TITLE = "Show Output from Process"
PROCESS_ROW_GAP = "  "  # between the process chooser's columns
# How long after the last keystroke the text filter is applied, so that a long
# output is not rebuilt for every character typed
TEXT_FILTER_DELAY_MS = 250


class OutputPane:
    """
    The output window: a view of the entries logged to it, filterable by run
    and by the text in each line. Owns the entries, the runs and the filters;
    see OutputEntry and OutputRun.

    Given its widgets rather than the window, so what it can reach is what it
    is handed: the main window only for its layout and width, and the chooser
    dialog the process chooser is built from.
    """

    def __init__(
        self,
        *,
        window: QMainWindow,
        view: QPlainTextEdit,
        bar: QFrame,
        bar_label: QLabel,
        show_all_button: QPushButton,
        text_filter: QLineEdit,
        copy_button: QPushButton,
        save_button: QPushButton,
        build_chooser: Callable[..., tuple[QDialog, QPushButton]],
        pid: int,
    ):
        self._window = window  # its layout is activated before scrolling
        self._view = view
        self._bar = bar
        self._bar_label = bar_label
        self._text_filter = text_filter
        # Copy and Save take what is shown, and their tooltips say so
        self._copy_button = copy_button
        self._save_button = save_button
        # Their own tooltips, the window's, put back when the output is no
        # longer filtered
        self._button_tooltips = {
            button: button.toolTip() for button in (copy_button, save_button)
        }
        self._build_chooser = build_chooser
        self._pid = pid  # Commander's, on its own messages

        # The output window's contents and where they came from, so that it can
        # be filtered to one command's output; see OutputRun
        self._output_runs: dict[int, OutputRun] = {
            COMMANDER_RUN: OutputRun(COMMANDER_RUN, "", pid=pid)
        }
        self._output_entries: list[OutputEntry] = []
        self._output_line_total = 0
        # The runs shown, or None for all of them
        self._output_filter: frozenset[int] | None = None
        # The text each line shown must contain, as typed and as searched for;
        # set from the field when the filter is applied, not as it is typed
        self._filter_text = ""
        self._line_pattern: re.Pattern[str] | None = None
        self._hidden_line_count = 0  # arrived while filtered, and not shown

        bar.hide()
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        view.customContextMenuRequested.connect(self._show_output_menu)
        show_all_button.clicked.connect(self._show_all_output)
        QShortcut(
            QKeySequence(Qt.Key.Key_Escape),
            view,
            self._show_all_output,
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
        )

        self._text_filter_timer = QTimer(view)
        self._text_filter_timer.setSingleShot(True)
        self._text_filter_timer.setInterval(TEXT_FILTER_DELAY_MS)
        self._text_filter_timer.timeout.connect(self._apply_text_filter)
        text_filter.setClearButtonEnabled(True)
        text_filter.textChanged.connect(self._text_filter_edited)
        # Return applies it at once, and Esc empties it at once
        text_filter.returnPressed.connect(self._apply_text_filter)
        QShortcut(
            QKeySequence(Qt.Key.Key_Escape),
            text_filter,
            self._clear_text_filter,
            context=Qt.ShortcutContext.WidgetShortcut,
        )
        # Cmd+F on macOS, Ctrl+F elsewhere, from anywhere in the window
        QShortcut(QKeySequence.StandardKey.Find, window, self._focus_text_filter)

    def start_run(
        self,
        command: str,
        command_line: str,
        user_command_line: str,
        arguments: list[str] | None = None,
    ) -> OutputRun:
        """
        Register a command about to be started as a run its output can be
        attributed to and filtered by, numbered from 1 in the order started.
        'arguments' are those it is run with, which say what it follows.
        """
        run = OutputRun(
            len(self._output_runs),
            command,
            command_line,
            user_command_line=user_command_line,
            started_at=datetime.now(),
            arguments=tuple(arguments or ()),
        )
        self._output_runs[run.run_id] = run
        return run

    def run_following(self, work_requirement_id: str) -> OutputRun | None:
        """
        A command still running that is following the Work Requirement, if
        there is one; see OutputRun.is_following().
        """
        return next(
            (
                run
                for run in self._output_runs.values()
                if run.is_following(work_requirement_id)
            ),
            None,
        )

    def attach(self, process: QProcess, run: OutputRun):
        """
        Show a process's output as it arrives, attributed to its run, and drain
        both channels when it finishes. Called before the window connects its own
        handlers to 'finished', so the last of the output is in the window before
        anything reports the process as done.
        """
        stdout_buffer = LineBuffer()
        stderr_buffer = LineBuffer()
        process.readyReadStandardOutput.connect(
            functools_partial(self._on_stdout, process, run, stdout_buffer)
        )
        process.readyReadStandardError.connect(
            functools_partial(self._on_stderr, process, run, stderr_buffer)
        )
        process.finished.connect(
            functools_partial(
                self._on_process_output_finished,
                process,
                run,
                stdout_buffer,
                stderr_buffer,
            )
        )

    def clear(self):
        """
        Clear everything, filtered out or not, and so end the filter by run:
        clearing only what is shown, or only what is hidden, would leave the
        window's contents a surprise when the filter is lifted. The text filter
        stays, since the field still shows it.
        """
        self._output_entries.clear()
        self._output_line_total = 0
        self._output_filter = None
        self._hidden_line_count = 0
        self._view.setPlainText("")
        self._update_output_filter_bar()

    def log(
        self,
        output: str,
        prefix: bool = True,
        run: int = COMMANDER_RUN,
        announcement: bool = False,
    ):
        """
        Add text to the output window, attributed to the run it came from:
        Commander's own messages unless a command's run is named. While the
        window is filtered to another run it is kept but not shown, and counted
        in the filter bar. An announcement is a command's 'Executing:' line; see
        OutputEntry.
        """
        entry = OutputEntry(
            run, f"{message_prefix(self._pid) if prefix else ''}{output}", announcement
        )
        self._output_entries.append(entry)
        self._output_line_total += entry.lines
        lines = entry.lines_shown(self._output_filter, self._line_pattern)
        if lines:
            self._view.appendPlainText("\n".join(line for _, line in lines))
            # Tag the blocks just added with their entry, which is how a
            # right-click finds the run of the line under it
            block = cast(QTextDocument, self._view.document()).lastBlock()
            for _ in lines:
                block.setUserState(len(self._output_entries) - 1)
                block = block.previous()
        self._hidden_line_count += entry.lines - len(lines)
        self._update_output_filter_bar()

    def _log_lines(self, lines: list[str], run: OutputRun):
        if not lines:
            return
        if run.printed_pid is None:
            for line in lines:
                if match := PREFIXED_PID.match(line):
                    run.printed_pid = int(match.group(1))
                    break
        text = "\n".join(lines)
        run.note_output(text)
        self.log(text, prefix=False, run=run.run_id)

    def _on_stdout(self, process: QProcess, run: OutputRun, line_buffer: LineBuffer):
        self._log_lines(line_buffer.feed(process.readAllStandardOutput().data()), run)

    def _on_stderr(self, process: QProcess, run: OutputRun, line_buffer: LineBuffer):
        self._log_lines(line_buffer.feed(process.readAllStandardError().data()), run)

    def _on_process_output_finished(
        self,
        process: QProcess,
        run: OutputRun,
        stdout_buffer: LineBuffer,
        stderr_buffer: LineBuffer,
        *_signal_args,
    ):
        """
        Drain both output channels when the process exits, and display any
        final line that wasn't terminated by a newline.
        """
        self._log_lines(
            stdout_buffer.feed(process.readAllStandardOutput().data())
            + stdout_buffer.flush(),
            run,
        )
        self._log_lines(
            stderr_buffer.feed(process.readAllStandardError().data())
            + stderr_buffer.flush(),
            run,
        )

    def _show_output_menu(self, position: QPoint):
        menu = self._build_output_menu(position)
        try:
            menu.exec(cast(QWidget, self._view.viewport()).mapToGlobal(position))
        finally:
            menu.deleteLater()

    def _build_output_menu(self, position: QPoint) -> QMenu:
        """
        Build (but do not show) the output window's context menu: the standard
        Copy and Select All, then the filter actions. The runs offered are those
        of the line under the pointer, so nothing has to be selected first — two
        of them for an 'Executing:' line, its command's and Commander's.
        """
        menu = cast(QMenu, self._view.createStandardContextMenu(position))
        block = self._view.cursorForPosition(position).block()
        entry = self._entry_of(block)
        actions: list[tuple[str, Callable[[], None]]] = [
            (
                self._output_runs[run_id].menu_text,
                functools_partial(
                    self._filter_output, frozenset({run_id}), block.blockNumber()
                ),
            )
            for run_id in (entry.runs if entry is not None else [])
            if frozenset({run_id}) != self._output_filter
        ]
        if self._filtered:
            actions.append((SHOW_ALL_OUTPUT, self._show_all_output))
        menu.addSeparator()
        for text, slot in actions:
            cast(QAction, menu.addAction(text)).triggered.connect(slot)
        choose = cast(QAction, menu.addAction(SHOW_OUTPUT_FROM_PROCESS))
        choose.setEnabled(bool(self._choosable_runs()))
        choose.triggered.connect(
            functools_partial(
                self._choose_output_run,
                entry.run_id if entry is not None else None,
                block.blockNumber() if entry is not None else None,
            )
        )
        return menu

    def command_line_of(self, pid: int) -> str | None:
        """
        The command line, as the user would type it, of the run whose
        process has 'pid', or None if no run has.
        """
        for run in self._output_runs.values():
            if run.pid == pid:
                return run.user_command_line or run.command_line or None
        return None

    def _choosable_runs(self) -> list[OutputRun]:
        """
        The runs the process chooser lists: those with something in the output
        window, and those still running, whose output is worth filtering to even
        when Clear has emptied the window. Commander first, then the commands in
        the order they started, which is the order of their output.
        """
        with_output = {
            run_id for entry in self._output_entries for run_id in entry.runs
        }
        return [
            run
            for run in self._output_runs.values()
            if run.run_id in with_output or run.running
        ]

    def _choose_output_run(
        self, clicked_run: int | None = None, anchor_block: int | None = None
    ):
        """
        Offer the process chooser, and filter the output to the runs ticked.
        Ticked at the start: the runs being shown, otherwise that of the line
        right-clicked (its command's, for an 'Executing:' line), otherwise the
        latest. The line right-clicked is kept in place, as the menu's own
        Show Only items keep it, when it is among the runs chosen.
        """
        runs = self._choosable_runs()
        if not runs:
            return
        run_ids = {run.run_id for run in runs}
        preferred = [
            self._output_filter & run_ids if self._output_filter else frozenset(),
            frozenset({clicked_run}) & run_ids,
            frozenset({runs[-1].run_id}),
        ]
        ticked = next(choice for choice in preferred if choice)
        dialog, listing = self._build_process_dialog(runs, ticked)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted.value:
                return
            chosen = frozenset(int(handle) for handle in checked_handles(listing))
        finally:
            dialog.deleteLater()
        if chosen and chosen != self._output_filter:
            self._filter_output(chosen, anchor_block)

    def _process_rows(self, runs: list[OutputRun]) -> list[str]:
        """
        One line per run for the process chooser: PID, command line, start time,
        outcome and line count, in columns padded to line up (the listing is in
        the monospaced output font).
        """
        lines = {
            run.run_id: sum(
                entry.lines
                for entry in self._output_entries
                if run.run_id in entry.runs
            )
            for run in runs
        }
        cells = [
            (
                "" if run.shown_pid is None else f"{run.shown_pid:06d}",
                "Commander's own messages"
                if run.run_id == COMMANDER_RUN
                else run.user_command_line,
                "" if run.started_at is None else run.started_at.strftime("%H:%M:%S"),
                ""
                if run.run_id == COMMANDER_RUN
                else "running"
                if run.outcome is None
                else run.outcome,
                f"{lines[run.run_id]:,} line{'' if lines[run.run_id] == 1 else 's'}",
            )
            for run in runs
        ]
        widths = [max(len(row[column]) for row in cells) for column in range(4)]
        return [
            PROCESS_ROW_GAP.join(
                [cell.ljust(width) for cell, width in zip(row[:4], widths)]
                + [row[4].rjust(max(len(r[4]) for r in cells))]
            )
            for row in cells
        ]

    def _build_process_dialog(
        self, runs: list[OutputRun], ticked: frozenset[int]
    ) -> tuple[QDialog, QListWidget]:
        """
        Build (but do not show) the process chooser: the non-destructive
        chooser over the runs, those in 'ticked' ticked, with Show Output as its
        accept button. Returns the dialog and its listing, whose ticked rows'
        handles are the chosen runs' IDs.

        The listing opens wide enough for its longest row, up to the main
        window's width, since a row is mostly a command line and the other
        choosers' rows are short; beyond that a row is elided, and its tooltip
        has the whole command line.
        """
        rows = [
            SelectableRow(
                display=text, handle=str(run.run_id), tooltip=run.command_line or text
            )
            for run, text in zip(runs, self._process_rows(runs))
        ]
        dialog, _show_btn = self._build_chooser(
            PROCESS_DIALOG_TITLE,
            "Choose the processes whose output to show:",
            "Show Output",
            rows,
            checked={str(run_id) for run_id in ticked},
        )
        listing = cast(QListWidget, dialog.findChild(QListWidget, "selection_list"))
        scrollbar = cast(QScrollBar, listing.verticalScrollBar())
        listing.setMinimumWidth(
            min(
                listing.sizeHintForColumn(0)
                + 2 * listing.frameWidth()
                + (
                    scrollbar.sizeHint().width()
                    if listing.count() > MAX_DIALOG_LIST_ROWS
                    else 0
                ),
                self._window.width(),
            )
        )
        return dialog, listing

    def _entry_of(self, block: QTextBlock) -> OutputEntry | None:
        """
        The entry a block of the output window was added from, or None for a
        block with no entry: one put there other than by log().
        """
        index = block.userState()
        if 0 <= index < len(self._output_entries):
            return self._output_entries[index]
        return None

    @property
    def _filtered(self) -> bool:
        """
        Whether either filter is on: by run, or by text.
        """
        return self._output_filter is not None or self._line_pattern is not None

    def _show_all_output(self):
        """
        Lift both filters: the field is emptied with its signals blocked, so
        that emptying it does not start a second rebuild.
        """
        self._text_filter_timer.stop()
        if self._text_filter.text():
            self._text_filter.blockSignals(True)
            self._text_filter.clear()
            self._text_filter.blockSignals(False)
        if self._filtered:
            self._filter_output(None, text="")

    def _text_filter_edited(self):
        self._text_filter_timer.start()

    def _apply_text_filter(self):
        """
        Filter the lines shown by the text in the field, keeping the filter by
        run; nothing is rebuilt if what the field means has not changed.
        """
        self._text_filter_timer.stop()
        text = self._text_filter.text().strip()
        if text != self._filter_text:
            self._filter_output(self._output_filter, text=text)

    def _clear_text_filter(self):
        self._text_filter.clear()
        self._apply_text_filter()

    def _focus_text_filter(self):
        self._text_filter.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._text_filter.selectAll()

    def _filter_output(
        self,
        run_ids: frozenset[int] | None,
        anchor_block: int | None = None,
        *,
        # Keyword-only: a QAction's 'triggered' passes its checked state on
        # to the partials the menu connects to this, as a third argument
        text: str | None = None,
    ):
        """
        Show only the output of 'run_ids', or (with None) all of it, and of that
        only the lines containing the filter's text, which 'text' replaces when
        given ("" for every line). The line being read stays
        where it was on screen — the line right-clicked, when there was one,
        otherwise the top line — or, if it is no longer shown, the first shown
        line after it does, unless the window was following the output at its
        end, in which case it still is.
        """
        scrollbar = cast(QScrollBar, self._view.verticalScrollBar())
        following = scrollbar.value() == scrollbar.maximum()
        top = self._view.firstVisibleBlock().blockNumber()
        document = cast(QTextDocument, self._view.document())
        anchor = document.findBlockByNumber(
            top if anchor_block is None else anchor_block
        )
        anchor_row = anchor.blockNumber() - top
        # Read under the filters it was shown by, so before they change
        anchor_key = self._line_of(anchor)

        self._output_filter = run_ids
        if text is not None:
            self._filter_text, self._line_pattern = text, line_pattern(text)
        self._hidden_line_count = 0
        # Show or hide the bar before scrolling, and lay it out now rather than
        # at the next event: it takes its height from the output window, and a
        # window that loses rows after being scrolled to its end no longer is.
        self._bar.setVisible(self._filtered)
        cast(QLayout, cast(QWidget, self._window.centralWidget()).layout()).activate()
        shown = [
            (index, number, line)
            for index, entry in enumerate(self._output_entries)
            for number, line in entry.lines_shown(run_ids, self._line_pattern)
        ]
        self._view.setPlainText("\n".join(line for _, _, line in shown))
        block = document.firstBlock()
        anchor_line: int | None = None
        for index, number, _ in shown:
            if anchor_line is None and anchor_key is not None:
                if (index, number) >= anchor_key:
                    anchor_line = block.blockNumber()
            block.setUserState(index)
            block = block.next()

        if following or anchor_line is None:
            scrollbar.setValue(scrollbar.maximum())
        else:
            scrollbar.setValue(max(0, anchor_line - anchor_row))
        self._update_output_filter_bar()

    def _line_of(self, block: QTextBlock) -> tuple[int, int] | None:
        """
        Which line of which entry a block of the output window shows, as
        (entry index, line number in the entry), or None for a block with no
        entry. A block's tag gives its entry; its place among the entry's blocks
        shown, under the filters in force, gives its line.
        """
        entry = self._entry_of(block)
        if entry is None:
            return None
        index = block.userState()
        position = 0
        previous = block.previous()
        while previous.isValid() and previous.userState() == index:
            position += 1
            previous = previous.previous()
        lines = entry.lines_shown(self._output_filter, self._line_pattern)
        if position >= len(lines):  # the view is not what the filters show
            return (index, 0)
        return (index, lines[position][0])

    def _update_output_filter_bar(self):
        """
        Show the filter bar while the output window is filtered, saying what it
        is filtered to and how much is not being shown, and hide it otherwise.
        Copy and Save take what is shown, so their tooltips say so while it is.
        """
        self._bar.setVisible(self._filtered)
        if not self._filtered:
            for button, tooltip in self._button_tooltips.items():
                button.setToolTip(tooltip)
            return

        runs = [self._output_runs[run_id] for run_id in self._output_filter or ()]
        description = filter_description(runs, self._filter_text)
        document = cast(QTextDocument, self._view.document())
        shown = 0 if document.isEmpty() else document.blockCount()
        # The count of hidden new lines is text rather than a button: clicking
        # it could only do what Show All Output beside it does, and a button
        # labelled with a status does not say that
        hidden = self._hidden_line_count
        self._bar_label.setText(
            f"{description} · {shown:,} of {self._output_line_total:,} lines"
            + (
                f" · {hidden:,} new line{'' if hidden == 1 else 's'} hidden"
                if hidden
                else ""
            )
        )
        self._bar_label.setToolTip(
            "\n".join(run.command_line for run in runs if run.command_line)
        )
        for button in (self._copy_button, self._save_button):
            button.setToolTip(
                f"Only the lines shown: {description[0].lower()}{description[1:]}"
            )
