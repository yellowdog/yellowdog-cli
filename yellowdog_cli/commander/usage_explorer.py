"""
The Usage Explorer: a modeless window over `yd usage --json` (UsageExplorer),
drilling down a breadcrumb of views, each one a `yd usage` child process, and
its asynchronous runner (UsageRunner; also used for `yd list namespaces`). Not
command_running's _capture_json_document(), which blocks in a nested event
loop and drops stderr: the explorer is modeless and shows the CLI's error.
Commander groups, sorts and adds up nothing: every figure shown is the CLI's.
"""

import csv
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from functools import partial
from math import ceil
from typing import Any, cast

from PyQt6.QtCore import (
    QByteArray,
    QEvent,
    QObject,
    QPoint,
    QProcess,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPalette,
    QShortcut,
    QTextOption,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QProxyStyle,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleFactory,
    QTableView,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from yellowdog_cli.commander import file_dialogs
from yellowdog_cli.commander.branding import BRANDING_IMAGE_SIZE, branding_pixmap
from yellowdog_cli.commander.host import MACOS, cli_program
from yellowdog_cli.commander.output_pane import (
    ERROR_RGB_DARK,
    ERROR_RGB_LIGHT,
    MAX_OUTPUT_FONT_SIZE,
    MIN_OUTPUT_FONT_SIZE,
    TABLE_OUTLINE_RGB_DARK,
    TABLE_OUTLINE_RGB_LIGHT,
    copy_to_clipboard,
)
from yellowdog_cli.commander.processes import child_process
from yellowdog_cli.commander.usage_table import (
    HIDEABLE_COLUMNS,
    STATUS_COLUMNS,
    UsageTableModel,
    figure_heading,
)
from yellowdog_cli.commander.usage_views import (
    DEFAULT_PRESET,
    DRILL_PATH,
    PRESETS,
    USAGE_SORT_VALUE_KEYS,
    Level,
    Scope,
    command_line,
    drill,
    eligible_keys,
    heading,
    preset_window,
    toggled_by,
    view_args,
)
from yellowdog_cli.utils.output_style import ERROR_MARKER, WARNING_MARKER
from yellowdog_cli.utils.usage_text import duration_text

# The exit code and message of a run the user stopped
STOPPED_EXIT_CODE = -1
STOPPED_MESSAGE = "Stopped"


class UnusableArguments(Exception):
    """
    Raised by the base arguments' callable when Commander cannot build them
    (a Properties field that cannot be split); its text is shown as the
    failure, and nothing is run.
    """


@dataclass
class RunResult:
    request: int  # The request number it answers
    document: Any  # The parsed JSON object or array, None on failure
    exit_code: int
    error: str  # stderr, stripped; '' on success
    arguments: list[str]  # The view's arguments, as passed
    warnings: list[str] = field(default_factory=list)  # A success's stderr lines


@dataclass
class _Run:
    process: QProcess
    arguments: list[str]
    started: float
    timer: QTimer
    stopped: bool = False


def _disconnect(process: QProcess) -> None:
    """
    Cut a child's finished and error signals from the runner. Not
    QObject.disconnect() with no argument, which Qt warns of for the proxies
    that partial slots make on the child's destroyed signal.
    """
    for signal in (process.finished, process.errorOccurred):
        try:
            signal.disconnect()
        except TypeError:
            pass


class UsageRunner(QObject):
    """
    One child process per requested view, started at once. Only the latest
    request's result is emitted: an older run is left to finish (it may be
    fetching the report the next view reuses) and its result dropped. Only
    stop() ends a run.
    """

    # A RunResult, for the latest request only
    finished = pyqtSignal(object)
    # The latest run has taken longer than WAIT_DELAY_MS
    started_waiting = pyqtSignal()

    WAIT_DELAY_MS = 300

    def __init__(
        self,
        parent: QObject,
        working_dir: Callable[[], str],
        base_args: Callable[[], list[str]],
        command: str = "yd usage",
    ) -> None:
        super().__init__(parent)
        self._working_dir = working_dir
        self._base_args = base_args
        self._command = command
        self._runs: dict[int, _Run] = {}
        self._latest = 0
        # Children are killed before the parent's destruction takes the
        # runner's own C++ object, whose slots would otherwise emit into it
        parent.destroyed.connect(lambda *_: self.stop_all())

    def run(self, arguments: list[str]) -> int:
        """
        Start a child for a view now and return its request number.
        """
        self._latest += 1
        request = self._latest
        try:
            base = self._base_args()
        except UnusableArguments as error:
            # The failure is this request's result, so an older run's is
            # dropped as it is for any newer request; emitted once the caller
            # has the request number
            result = RunResult(request, None, 3, str(error), list(arguments))
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(partial(self._emit_unusable, request, result))
            timer.timeout.connect(timer.deleteLater)
            timer.start(0)
            return request
        program, args = cli_program(self._command, [*base, *arguments])
        process = child_process(self._working_dir(), self)
        # Parented to the process, so it dies with it and never fires into
        # a destroyed runner (a bare QTimer.singleShot would)
        timer = QTimer(process)
        timer.setSingleShot(True)
        timer.timeout.connect(partial(self._on_wait_delay, request))
        run = _Run(process, list(arguments), time.monotonic(), timer)
        self._runs[request] = run
        process.finished.connect(partial(self._on_finished, request))
        process.errorOccurred.connect(partial(self._on_error, request))
        process.start(program, args)
        timer.start(self.WAIT_DELAY_MS)
        return request

    def _emit_unusable(self, request: int, result: RunResult) -> None:
        if request == self._latest and request not in self._runs:
            self.finished.emit(result)

    def stop(self) -> None:
        """
        Kill the latest run; its result is exit code -1, 'Stopped'.
        """
        run = self._runs.get(self._latest)
        if run is None:
            return
        run.stopped = True
        run.process.kill()

    def stop_all(self) -> None:
        """
        Kill every child, for shutdown, and emit nothing.
        """
        runs = list(self._runs.values())
        self._runs.clear()
        for run in runs:
            run.timer.stop()
            _disconnect(run.process)
            run.process.kill()
            run.process.waitForFinished(2000)
            run.process.deleteLater()

    def running(self) -> bool:
        """
        Whether the latest request's child is still running.
        """
        return self._latest in self._runs

    def elapsed_seconds(self) -> float:
        """
        Seconds the latest run has taken so far; 0 when none is running.
        """
        run = self._runs.get(self._latest)
        return 0.0 if run is None else time.monotonic() - run.started

    def _on_wait_delay(self, request: int) -> None:
        if request == self._latest and request in self._runs:
            self.started_waiting.emit()

    def _on_error(self, request: int, error: QProcess.ProcessError) -> None:
        # A child that never started sends no finished()
        if error == QProcess.ProcessError.FailedToStart:
            self._complete(request, 127, None, "", failed_to_start=True)

    def _on_finished(
        self, request: int, exit_code: int, _status: QProcess.ExitStatus
    ) -> None:
        run = self._runs.get(request)
        if run is None:
            return
        out = bytes(run.process.readAllStandardOutput().data()).decode(
            "utf-8", errors="replace"
        )
        err = bytes(run.process.readAllStandardError().data()).decode(
            "utf-8", errors="replace"
        )
        self._complete(request, exit_code, out, err.strip())

    def _complete(
        self,
        request: int,
        exit_code: int,
        out: str | None,
        error: str,
        failed_to_start: bool = False,
    ) -> None:
        run = self._runs.pop(request, None)
        if run is None:
            return
        run.timer.stop()
        process = run.process
        _disconnect(process)
        process.deleteLater()
        if request != self._latest:
            return
        document: Any = None
        warnings: list[str] = []
        if run.stopped:
            exit_code, error = STOPPED_EXIT_CODE, STOPPED_MESSAGE
        elif failed_to_start:
            error = f"{self._command} could not be started: {process.errorString()}"
        elif exit_code == 0:
            document = self._parse(out or "")
            if document is not None:
                warnings = error_lines(error)
                error = ""
            else:
                exit_code = 1
                error = self._command + " did not print a JSON document"
        elif not error:
            error = f"{self._command} exited with code {exit_code}"
        self.finished.emit(
            RunResult(request, document, exit_code, error, run.arguments, warnings)
        )

    @staticmethod
    def _parse(text: str) -> Any:
        try:
            document = json.loads(text)
        except ValueError:
            return None
        return document if isinstance(document, (dict, list)) else None


# Commander's own settings (file_dialogs.dialog_settings()) for the explorer
SETTING_EXPLORER_GEOMETRY = "usageExplorer/geometry"
SETTING_EXPLORER_PRESET = "usageExplorer/preset"
SETTING_EXPLORER_COST = "usageExplorer/cost"
SETTING_EXPLORER_HIDDEN_COLUMNS = "usageExplorer/hiddenColumns"
SETTING_EXPLORER_FONT_SIZE = "usageExplorer/fontSize"
SETTING_EXPLORER_EXPORT_TOTAL = "usageExplorer/exportTotal"
# The CSV export's suggested name (hyphenated, no colons, which Windows refuses
# in a file name) and the save dialog's filter
EXPORT_NAME_FORMAT = "usage-%Y%m%d-%H%M%S.csv"
EXPORT_FILTER = "CSV files (*.csv);;All files (*)"
EXPORTED_LOG = "Saved the Usage Explorer's table to '{path}'"
EXPORT_FAILED = "Could not save the table to '{path}': {error}"

EXPLORER_SIZE = (1000, 640)
# A new scope's first level: every namespace, totalled by namespace
TOP_LEVEL = Level((DRILL_PATH[0],))
CUSTOM_PRESET = "Custom"
# A single left-pointing angle quotation mark, then Back
BACK_TEXT = "\u2039 Back"
ALL_NAMESPACES = "All namespaces"
# A single right-pointing angle quotation mark, spaced
CRUMB_SEPARATOR = " \u203a "
OVERLAY_TICK_MS = 1000
OVERLAY_ALPHA = 190
# The table's inset from its frame's left and top edges, in pixels
TABLE_INDENT = 6
# The scope rows set close together, and the window's margins narrowed: the
# style's own spacing (20px between rows on macOS) spreads the controls over
# twice the height they need
CONTROL_ROW_SPACING = 4
WINDOW_MARGINS = (16, 12, 16, 12)
# The main window's separator style in Dark Mode (commander.py)
DARK_SEPARATOR_STYLE = "background-color: #555555; border: none; max-height: 2px;"
# How much of the text colour tints the headings
HEADING_TINT = 0.15
RUNNING_TEXT = "Running yd usage… {elapsed}"
FETCH_BUTTON = "Fetch Report"
KEPT_SEPARATOR = " \u00b7 "
KEPT_TOOLTIP = (
    "The reports kept from earlier runs (yd usage --reports): choose one to"
    " see it again, without fetching it"
)
NO_KEPT_TOOLTIP = "No reports are kept for this configuration yet"
FETCH_TEXT = "Fetch the usage report for this window and namespace"
FETCHED_LOG = "Fetched the usage report: {command}"
FAILED_LOG = "{command} failed (exit {code}): {message}"
NO_INSTANCES = "No Instances in this window"
NO_MATCHING_INSTANCES = "No Instances in this window match the filters"
PRICES_REFUSED = "This Application may not read cloud prices; no cost is estimated"

# What an exit code means, said beneath the CLI's message (exit codes 2, 3
# and 4, a usage, configuration or authentication error, need nothing more)
EXIT_CODE_MEANINGS = {
    5: "This Application may not read usage there",
    6: "The namespace does not exist",
    8: "The report took too long; a larger requestTimeout in [common] gives it longer",
}


@dataclass(frozen=True)
class _View:
    """
    What one `yd usage` run shows: the window and namespace, and the
    breadcrumb down to it.
    """

    scope: Scope
    levels: tuple[Level, ...]


def _minutes_and_seconds(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60}:{whole % 60:02}"


def _shown_time(iso: str) -> str:
    """
    A time from the document ('2026-11-25T15:02:30.1234Z') as the report
    line gives it, in UTC to the minute, or as it is if it cannot be read.
    """
    try:
        moment = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return str(iso)
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%d %H:%M")


def error_lines(error: str) -> list[str]:
    """
    The CLI's error message, line by line, less the markers '--nf' leaves
    (and anything before them on a line).
    """
    lines = []
    for line in error.splitlines():
        for marker in (ERROR_MARKER, WARNING_MARKER):
            _, found, rest = line.partition(marker)
            if found:
                line = rest
                break
        if line.strip():
            lines.append(line.strip())
    return lines


def _plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}" + ("" if count == 1 else "s")


def _row_of(row: QHBoxLayout, parent: QWidget) -> QWidget:
    """
    A row of controls as a widget of its own, without margins.
    """
    widget = QWidget(parent)
    widget.setLayout(row)
    row.setContentsMargins(0, 0, 0, 0)
    return widget


class _Notes(QTextEdit):
    """
    The notes beneath the table: read-only plain text with no frame or
    background, wrapped to the window's width (at spaces, else anywhere, so
    that a long URL in an error breaks rather than widening the window) and
    exactly as tall as its text, whatever its width.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("QTextEdit { background: transparent; }")
        document = self.document()
        if document is not None:
            document.setDocumentMargin(0)
        self.textChanged.connect(self._fit)

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:
        self.setPlainText(text)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._fit()

    def _fit(self) -> None:
        document = self.document()
        viewport = self.viewport()
        if document is None or viewport is None:
            return
        document.setTextWidth(viewport.width())
        height = ceil(document.size().height())
        margins = self.contentsMargins()
        self.setFixedHeight(height + margins.top() + margins.bottom())


class _TableOverlay(QWidget):
    """
    The table dimmed, with a line of text and a button at its centre: while
    a view takes a while (how long, and Stop), or until a new report is
    asked for (Fetch Report). It covers the table and follows its size.
    """

    def __init__(self, table: QWidget, button: str, tooltip: str) -> None:
        super().__init__(table)
        self.label = QLabel(self)
        self.button = QPushButton(button, self)
        self.button.setAutoDefault(False)
        self.button.setToolTip(tooltip)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(self.label, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        table.installEventFilter(self)
        self.hide()

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a0 is self.parent() and a1 is not None and a1.type() == QEvent.Type.Resize:
            self.setGeometry(cast(QWidget, a0).rect())
        return super().eventFilter(a0, a1)

    def show_over_table(self) -> None:
        self.setGeometry(cast(QWidget, self.parent()).rect())
        self.show()
        self.raise_()

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        colour = QColor(self.palette().color(QPalette.ColorRole.Window))
        colour.setAlpha(OVERLAY_ALPHA)
        QPainter(self).fillRect(self.rect(), colour)


class _GridStyle(QProxyStyle):
    """
    The application's style with the table's grid in the command output's
    table-outline blue (TABLE_OUTLINE_RGB_*), one per appearance. Built over
    a fresh copy of the application's style, since the proxy owns its base
    and the application's own must not be handed over; rebuilt as the
    appearance changes, which on Linux changes the application's style too.
    """

    def __init__(self, dark: bool) -> None:
        application = cast(QApplication, QApplication.instance())
        base = QStyleFactory.create(cast(QStyle, application.style()).name())
        super().__init__(base)
        rgb = TABLE_OUTLINE_RGB_DARK if dark else TABLE_OUTLINE_RGB_LIGHT
        # styleHint() returns a signed int, so the colour's ARGB as one
        argb = QColor(*rgb).rgba()
        self._grid = argb - (1 << 32) if argb >= 1 << 31 else argb

    def styleHint(self, hint, option=None, widget=None, returnData=None) -> int:
        if hint == QStyle.StyleHint.SH_Table_GridLineColor:
            return self._grid
        return super().styleHint(hint, option, widget, returnData)


def grid_colour(table: QTableView) -> QColor:
    """
    The colour the table's style draws its grid in.
    """
    style = table.style()
    grid = (
        style.styleHint(QStyle.StyleHint.SH_Table_GridLineColor, None, table)
        if style is not None
        else -1
    )
    if grid == -1:
        return table.palette().color(QPalette.ColorRole.Mid)
    return QColor.fromRgb(grid & 0xFFFFFFFF)


class _UsageHeader(QHeaderView):
    """
    The table's headings, set apart from the rows: bold, each section tinted
    with HEADING_TINT of the text colour (the palette has no role for it: on
    macOS the window, base and alternate colours can all be white), with
    lines in the grid's colour beneath it and after it.
    """

    def __init__(self, table: QTableView) -> None:
        super().__init__(Qt.Orientation.Horizontal, table)
        self._table = table
        font = self.font()
        font.setBold(True)
        self.setFont(font)

    def paintSection(self, painter: QPainter | None, rect, logicalIndex: int) -> None:
        if painter is None:
            return
        super().paintSection(painter, rect, logicalIndex)
        painter.save()
        # Over the section, since the macOS style paints it opaque; the text
        # beneath is the tint's own colour, so it is barely changed
        tint = QColor(self.palette().color(QPalette.ColorRole.Text))
        tint.setAlphaF(HEADING_TINT)
        painter.fillRect(rect, tint)
        painter.setPen(grid_colour(self._table))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        # The divider after each heading, full height like the grid's lines,
        # over the style's own shorter one
        painter.drawLine(rect.right(), rect.top(), rect.right(), rect.bottom())
        painter.restore()


class _TableFrame(QFrame):
    """
    The table's frame, the style's own: the table inset TABLE_INDENT inside
    it, at the left and above, and lines in the grid's colour along the top
    of the headings and down the first column's left edge to the foot of
    the last row (the grid draws each cell's right and bottom edges, so none
    there).
    """

    def __init__(self, table: QTableView, parent: QWidget) -> None:
        super().__init__(parent)
        self._table = table
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setBackgroundRole(QPalette.ColorRole.Base)
        self.setAutoFillBackground(True)
        table.setFrameShape(QFrame.Shape.NoFrame)
        layout = QVBoxLayout(self)
        # Within the contents, which the frame's own width is already outside
        layout.setContentsMargins(TABLE_INDENT, TABLE_INDENT, 0, 0)
        layout.addWidget(table)
        model = table.model()
        if model is not None:
            model.modelReset.connect(self.update)
        for bar in (table.verticalScrollBar(), table.horizontalScrollBar()):
            if bar is not None:
                bar.valueChanged.connect(self.update)
        header = table.horizontalHeader()
        if header is not None:
            header.sectionResized.connect(self.update)

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        super().paintEvent(a0)
        table = self._table
        model = table.model()
        bar = table.horizontalScrollBar()
        viewport = table.viewport()
        if (
            model is None
            or viewport is None
            or not model.rowCount()
            or (bar is not None and bar.value())
        ):
            # Nothing shown, or the first column scrolled out of sight
            return
        rows = model.rowCount()
        bottom = (
            table.rowViewportPosition(rows - 1) + table.rowHeight(rows - 1)
            if rows
            else 0
        )
        foot = viewport.mapTo(self, QPoint(0, min(bottom, viewport.height())))
        painter = QPainter(self)
        painter.setPen(grid_colour(table))
        x = table.x() - 1
        painter.drawLine(x, table.y() - 1, x, foot.y() - 1)
        header = table.horizontalHeader()
        if header is not None and header.count():
            columns = min(header.length() - header.offset(), viewport.width())
            right = viewport.mapTo(self, QPoint(columns, 0)).x() - 1
            painter.drawLine(x, table.y() - 1, right, table.y() - 1)


class UsageExplorer(QDialog):
    """
    The Usage Explorer window: the window, namespace and cost controls, a
    breadcrumb with Back and Total by, the table, the notes strip, the report
    line and the view's command line. Every view is a `yd usage` run; the
    window is pinned to the report's own once a run of it has succeeded, so
    every later view regroups that one kept report. Modeless and parentless,
    as the file viewers are, deleted on close.
    """

    # A line for Commander's output window
    logged = pyqtSignal(str)
    # Select... beside the configuration, shown only when the explorer runs on
    # its own (show_configuration())
    select_configuration = pyqtSignal()
    # Dark Mode ticked or unticked, shown only when the explorer runs on its
    # own (offer_dark_mode()): in Commander the main window's checkbox sets it
    dark_mode_chosen = pyqtSignal(bool)

    def __init__(
        self,
        title: str,
        working_dir: Callable[[], str],
        base_args: Callable[[], list[str]],
        font: QFont,
        dark: bool,
    ) -> None:
        super().__init__(None)
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setModal(False)
        # A dialog on Windows has a close button alone: a window of this
        # size wants maximising and minimising as any other does
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint)
        self._base_args = base_args
        self._working_dir = working_dir
        # The export's save dialog, Commander's own
        self._file_dialogs = file_dialogs.FileDialogs(self, font)
        self._dark = dark
        self._shown: _View | None = None
        self._requested: _View | None = None
        self._requested_line = ""
        self._typed: tuple[str, str, str | None] | None = None
        # Whether the latest request is a new scope's first run, still
        # running (the view actions wait for it), and with '--refresh'
        self._resolving = False
        self._resolving_refresh = False
        # Whether the controls name a report not yet asked for, awaiting
        # Fetch Report (_await_fetch())
        self._pending = False
        # The Window, From, Until and Namespace controls' text of the scope
        # requested last, and of the one shown, which a new scope's failed
        # first run puts back
        self._requested_inputs: tuple[str, str, str, str] | None = None
        self._shown_inputs: tuple[str, str, str, str] | None = None
        self._error_showing = False

        settings = file_dialogs.dialog_settings()
        preset = str(settings.value(SETTING_EXPLORER_PRESET, DEFAULT_PRESET))
        if preset not in PRESETS:
            preset = DEFAULT_PRESET
        hidden = settings.value(SETTING_EXPLORER_HIDDEN_COLUMNS)
        self._hidden: set[str] = (
            set(STATUS_COLUMNS)
            if hidden is None
            else {key for key in str(hidden).split(",") if key in HIDEABLE_COLUMNS}
        )

        self._build_controls(
            preset, bool(settings.value(SETTING_EXPLORER_COST, True, type=bool))
        )
        # Commander's text at its default size, at the size last left here
        self._default_font_size = font.pointSize()
        table_font = QFont(font)
        size = settings.value(SETTING_EXPLORER_FONT_SIZE, font.pointSize(), type=int)
        table_font.setPointSize(
            max(MIN_OUTPUT_FONT_SIZE, min(MAX_OUTPUT_FONT_SIZE, int(size)))
        )
        self._build_table(table_font)
        self._build_footer()
        self._build_configuration_row()
        self._lay_out()
        self._add_shortcuts()

        geometry = settings.value(SETTING_EXPLORER_GEOMETRY)
        if not (isinstance(geometry, QByteArray) and self.restoreGeometry(geometry)):
            self.resize(*EXPLORER_SIZE)

        self._runner = UsageRunner(self, working_dir, base_args)
        self._runner.finished.connect(self._on_result)
        self._runner.started_waiting.connect(self._on_waiting)
        self._namespace_runner = UsageRunner(
            self, working_dir, base_args, command="yd list"
        )
        self._namespace_runner.finished.connect(self._on_namespaces)
        # The reports kept for this configuration (yd usage --reports), for
        # Kept Reports
        self._reports_runner = UsageRunner(self, working_dir, base_args)
        self._reports_runner.finished.connect(self._on_reports)
        self._tick = QTimer(self)
        self._tick.setInterval(OVERLAY_TICK_MS)
        self._tick.timeout.connect(self._show_elapsed)

        self._list_namespaces()
        self._list_reports()
        self._await_fetch()

    # Construction -----------------------------------------------------------

    def _build_controls(self, preset: str, cost: bool) -> None:
        self._preset = QComboBox(self)
        self._preset.addItems([*PRESETS, CUSTOM_PRESET])
        self._preset.setCurrentText(preset)
        self._preset.setToolTip("The time window the usage report covers")
        self._from = QLineEdit(self)
        self._until = QLineEdit(self)
        self._from.setToolTip("When the window starts, as yd usage --from reads it")
        self._until.setToolTip("When the window ends, as yd usage --until reads it")
        self._fill_window(preset)
        self._preset.currentIndexChanged.connect(self._preset_chosen)
        self._kept = QPushButton("Kept Reports", self)
        self._kept.setAutoDefault(False)
        self._kept.setMenu(QMenu(self._kept))
        self._kept.setEnabled(False)
        self._kept.setToolTip(NO_KEPT_TOOLTIP)
        for field in (self._from, self._until):
            field.textEdited.connect(self._typed_window)
            field.editingFinished.connect(self._await_fetch)

        self._namespace = QComboBox(self)
        self._namespace.setEditable(True)
        self._namespace.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._namespace.addItem(ALL_NAMESPACES)
        self._namespace.setToolTip("The namespace to report on, or all of them")
        self._namespace.setMinimumContentsLength(16)
        self._namespace.activated.connect(lambda *_: self._await_fetch())
        line_edit = self._namespace.lineEdit()
        if line_edit is not None:
            line_edit.editingFinished.connect(self._await_fetch)

        self._cost = QCheckBox("Estimated cost", self)
        self._cost.setChecked(cost)
        self._cost.setToolTip("Estimate each row's cost from list prices (--cost)")
        self._cost.clicked.connect(self._cost_toggled)
        self._refresh = QPushButton("Refresh", self)
        self._refresh.setToolTip("Fetch the usage report again (--refresh)")
        self._refresh.setAutoDefault(False)
        self._refresh.clicked.connect(lambda: self._resolve(refresh=True))

        self._back = QToolButton(self)
        self._back.setText(BACK_TEXT)
        self._back.setAutoRaise(True)
        self._back.setToolTip("Back to the level above")
        self._back.clicked.connect(self._step_back)
        self._back.setEnabled(False)
        self._crumbs = QHBoxLayout()
        self._crumbs.setSpacing(6)
        self._crumb_buttons: list[QToolButton] = []
        # A menu of the keys this level may total by, each ticked or not;
        # _show_total_by() fills it for the view shown
        self._total_by = QPushButton(self)
        self._total_by.setAutoDefault(False)
        self._total_by.setMenu(QMenu(self._total_by))
        self._total_by.setToolTip(
            "What this level's rows total by (--by): tick keys to add columns,"
            " each row one combination"
        )

    def _build_table(self, font: QFont) -> None:
        self._model = UsageTableModel(self)
        self._table = QTableView(self)
        self._table.setHorizontalHeader(_UsageHeader(self._table))
        self._grid_style = _GridStyle(self._dark)
        self._table.setStyle(self._grid_style)
        self._table.setModel(self._model)
        self._table.setFont(font)
        vertical = self._table.verticalHeader()
        # The style's padding around a row's text at the default size (its
        # row height is the same for any font), kept as the size changes
        default = QFont(font)
        default.setPointSize(self._default_font_size)
        self._row_padding = (
            vertical.defaultSectionSize() - QFontMetrics(default).height()
            if vertical is not None
            else 0
        )
        self._fit_rows()
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems
        )
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setWordWrap(False)
        if vertical is not None:
            vertical.hide()
        header = cast(QHeaderView, self._table.horizontalHeader())
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setHighlightSections(False)
        header.sectionClicked.connect(self._heading_clicked)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_column_menu)
        header.setToolTip(
            "Click a heading to sort by it; right-click to show or hide columns"
        )
        self._table.doubleClicked.connect(lambda index: self._drill(index.row()))
        # Return drills and Cmd/Ctrl+C copies: taken here, before the view's
        # own handling (which copies one cell) or the dialog's
        self._table.installEventFilter(self)
        self._overlay = _TableOverlay(
            self._table, "Stop", "Stop this yd usage run; the previous view stays"
        )
        self._overlay_text = self._overlay.label
        self._stop = self._overlay.button
        self._stop.clicked.connect(self._runner_stop)
        # Over the waiting overlay when both are up: a new report is asked
        # for only by its button (or Cmd/Ctrl+R), never by a control changed
        self._fetch_overlay = _TableOverlay(
            self._table,
            FETCH_BUTTON,
            "Run yd usage for this window and namespace",
        )
        self._fetch_overlay.label.setText(FETCH_TEXT)
        self._fetch = self._fetch_overlay.button
        self._fetch.clicked.connect(lambda: self._resolve(refresh=False))

    def _build_footer(self) -> None:
        self._notes = _Notes(self)
        self._details_button = QPushButton("Details", self)
        self._details_button.setAutoDefault(False)
        self._details_button.setToolTip("List the instance types with no list price")
        self._details_button.clicked.connect(self._toggle_details)
        self._details_button.hide()
        self._details = QLabel(self)
        self._details.setTextFormat(Qt.TextFormat.PlainText)
        self._details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._details.hide()
        self._report = QLabel(self)
        self._report.setTextFormat(Qt.TextFormat.PlainText)
        self._command_line = QLineEdit(self)
        self._command_line.setReadOnly(True)
        self._command_line.setToolTip("The yd usage command of this view")
        self._copy_command = QPushButton("Copy", self)
        self._copy_command.setAutoDefault(False)
        self._copy_command.setToolTip("Copy the command line")
        self._copy_command.clicked.connect(
            lambda: copy_to_clipboard(self._command_line.text())
        )
        # Export CSV: a menu of the two forms, raw figures first
        self._export = QPushButton("Export CSV", self)
        self._export.setAutoDefault(False)
        self._export.setToolTip(
            "Save the table's visible columns and rows, the Total row too,"
            " as a CSV file"
        )
        self._export.setEnabled(False)
        export_menu = QMenu(self._export)
        self._export_raw = QAction("Raw Numbers…", export_menu)
        export_menu.addAction(self._export_raw)
        self._export_raw.setToolTip(
            "Instances, hours as decimals and the cost as a number,"
            " with the running hours no price covered"
        )
        self._export_raw.triggered.connect(partial(self._export_csv, True))
        self._export_shown = QAction("As Shown…", export_menu)
        export_menu.addAction(self._export_shown)
        self._export_shown.setToolTip("Every cell as the table shows it")
        self._export_shown.triggered.connect(partial(self._export_csv, False))
        export_menu.addSeparator()
        self._export_total = QAction("Include Total Row", export_menu)
        self._export_total.setCheckable(True)
        self._export_total.setChecked(
            bool(
                file_dialogs.dialog_settings().value(
                    SETTING_EXPLORER_EXPORT_TOTAL, True, type=bool
                )
            )
        )
        self._export_total.setToolTip("End the file with the table's Total row")
        self._export_total.toggled.connect(
            lambda checked: file_dialogs.dialog_settings().setValue(
                SETTING_EXPLORER_EXPORT_TOTAL, checked
            )
        )
        export_menu.addAction(self._export_total)
        export_menu.setToolTipsVisible(True)
        self._export.setMenu(export_menu)

    def _build_configuration_row(self) -> None:
        """
        The configuration, Dark Mode and Select..., hidden until
        show_configuration(): in Commander the main window has them.
        """
        self._config_label = QLabel("Configuration:", self)
        self._config_path = QLabel(self)
        self._config_path.setTextFormat(Qt.TextFormat.PlainText)
        self._config_path.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        # Ignored, so that a long path cannot widen the window; its tooltip
        # holds the whole of it
        self._config_path.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._select_config = QPushButton("Select…", self)
        self._select_config.setAutoDefault(False)
        self._select_config.setToolTip("Choose another configuration file")
        self._select_config.clicked.connect(self.select_configuration.emit)
        self._dark_mode = QCheckBox("Dark Mode", self)
        self._dark_mode.setToolTip("Show the explorer in dark colours")
        self._dark_mode.hide()
        self._dark_mode.clicked.connect(self.dark_mode_chosen.emit)

    def _lay_out(self) -> None:
        window_row = QHBoxLayout()
        window_row.addWidget(QLabel("Window:", self))
        window_row.addWidget(self._preset)
        window_row.addWidget(QLabel("From", self))
        window_row.addWidget(self._from, 1)
        window_row.addWidget(QLabel("Until", self))
        window_row.addWidget(self._until, 1)
        window_row.addWidget(self._kept)
        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Namespace:", self))
        scope_row.addWidget(self._namespace, 1)
        scope_row.addWidget(self._cost)
        scope_row.addWidget(self._refresh)
        crumb_row = QHBoxLayout()
        crumb_row.addWidget(self._back)
        crumb_row.addLayout(self._crumbs)
        crumb_row.addStretch(1)
        crumb_row.addWidget(QLabel("Total by:", self))
        crumb_row.addWidget(self._total_by)
        crumb_row.addWidget(self._export)
        notes_row = QHBoxLayout()
        notes_row.addWidget(self._notes, 1)
        notes_row.addWidget(self._details_button, 0, Qt.AlignmentFlag.AlignTop)
        command_row = QHBoxLayout()
        command_row.addWidget(self._command_line, 1)
        command_row.addWidget(self._copy_command)
        # The two rows of scope controls, with the dog beside them at the top
        # right, as in the main window
        config_row = QHBoxLayout()
        config_row.addWidget(self._config_label)
        config_row.addWidget(self._select_config)
        config_row.addWidget(self._config_path, 1)
        config_row.addWidget(self._dark_mode)
        # Each row in a widget of its own, so that the rows can be set close
        # together while each keeps the style's spacing between its controls
        # (a row's layout would otherwise take the column's spacing)
        self._config_row = _row_of(config_row, self)
        self._config_row.hide()
        controls = QVBoxLayout()
        controls.setSpacing(CONTROL_ROW_SPACING)
        controls.addWidget(self._config_row)
        controls.addWidget(_row_of(window_row, self))
        controls.addWidget(_row_of(scope_row, self))
        self._branding = QLabel(self)
        self._branding.setPixmap(branding_pixmap())
        self._branding.setFixedSize(BRANDING_IMAGE_SIZE, BRANDING_IMAGE_SIZE)
        top = QHBoxLayout()
        top.addLayout(controls, 1)
        top.addWidget(self._branding, 0, Qt.AlignmentFlag.AlignVCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*WINDOW_MARGINS)
        layout.addLayout(top)
        # A rule under the scope controls, as under the main window's
        # configuration row, setting them apart from the view below
        self._separator = QFrame(self)
        self._separator.setFrameShape(QFrame.Shape.HLine)
        self._separator.setFrameShadow(QFrame.Shadow.Sunken)
        self._style_separator()
        layout.addWidget(self._separator)
        layout.addLayout(crumb_row)
        layout.addWidget(_TableFrame(self._table, self), 1)
        layout.addLayout(notes_row)
        layout.addWidget(self._details)
        layout.addWidget(self._report)
        layout.addLayout(command_row)
        self._show_breadcrumb((TOP_LEVEL,))

    def _add_shortcuts(self) -> None:
        back_keys: list[QKeySequence] = [
            *QKeySequence.keyBindings(QKeySequence.StandardKey.Back),
            QKeySequence("Alt+Left"),
        ]
        if MACOS:
            back_keys.append(QKeySequence("Ctrl+["))
        unique = {key.toString(): key for key in back_keys if not key.isEmpty()}
        back = QShortcut(self)
        # One shortcut holding every key: two matching one press would be
        # ambiguous to Qt, and neither would fire
        back.setKeys(list(unique.values()))
        back.activated.connect(self._step_back)
        QShortcut(QKeySequence("Ctrl+R"), self, self._rerun)
        for keys, step in (
            (QKeySequence(QKeySequence.StandardKey.ZoomIn), 1),
            # Cmd/Ctrl+=, the unshifted key, which ZoomIn does not include
            (QKeySequence("Ctrl+="), 1),
            (QKeySequence(QKeySequence.StandardKey.ZoomOut), -1),
            (QKeySequence("Ctrl+0"), 0),
        ):
            QShortcut(keys, self).activated.connect(partial(self._zoom, step))

    # The window's interface -------------------------------------------------

    def reset(self, title: str) -> None:
        """
        A new configuration: retitled, its namespaces listed, and its
        report awaiting Fetch Report.
        """
        self.setWindowTitle(title)
        self._namespace.clear()
        self._namespace.addItem(ALL_NAMESPACES)
        self._shown = None
        self._shown_inputs = None
        self._model.clear()
        self._export.setEnabled(False)
        self._show_breadcrumb((TOP_LEVEL,))
        self._say([])
        self._report.clear()
        self._command_line.clear()
        self._list_namespaces()
        self._list_reports()
        self._await_fetch()

    def show_configuration(self, path: str) -> None:
        """
        Show the configuration row, naming 'path', with Select...: for the
        explorer run on its own, which chooses its configuration itself.
        """
        self._config_path.setText(path)
        self._config_path.setToolTip(path)
        self._config_row.show()

    def offer_dark_mode(self, dark: bool) -> None:
        """
        Show Dark Mode in the configuration row, ticked if 'dark': for the
        explorer run on its own, which has no main window to set it from.
        """
        self._dark_mode.setChecked(dark)
        self._dark_mode.show()

    def set_namespace(self, namespace: str) -> None:
        """
        Start on a namespace, as `yd commander -n` gives it: in the Namespace
        control, awaiting Fetch Report.
        """
        self._namespace.setCurrentText(namespace)
        self._await_fetch()

    def _zoom(self, step: int) -> None:
        """
        Make the table's text a point larger (1) or smaller (-1), within
        MIN_OUTPUT_FONT_SIZE and MAX_OUTPUT_FONT_SIZE, or put it back to the
        default size (0), and remember it for the next session.
        """
        size = (
            self._default_font_size
            if step == 0
            else self._table.font().pointSize() + step
        )
        size = max(MIN_OUTPUT_FONT_SIZE, min(MAX_OUTPUT_FONT_SIZE, size))
        font = QFont(self._table.font())
        font.setPointSize(size)
        self._table.setFont(font)
        self._fit_rows()
        self._table.resizeColumnsToContents()
        file_dialogs.dialog_settings().setValue(SETTING_EXPLORER_FONT_SIZE, size)

    def _fit_rows(self) -> None:
        """
        The rows' height for the table's font, keeping the style's padding.
        """
        vertical = self._table.verticalHeader()
        if vertical is not None:
            height = QFontMetrics(self._table.font()).height()
            vertical.setDefaultSectionSize(height + self._row_padding)

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self._colour_notes()
        self._style_separator()
        self._grid_style = _GridStyle(dark)
        self._table.setStyle(self._grid_style)
        header = self._table.horizontalHeader()
        if header is not None:
            header.update()
        frame = self._table.parentWidget()
        if frame is not None:
            frame.update()

    def _style_separator(self) -> None:
        """
        The rule under the scope controls painted by hand in Dark Mode, where
        the native sunken line all but disappears, as the main window's are.
        """
        self._separator.setStyleSheet(DARK_SEPARATOR_STYLE if self._dark else "")

    def shut_down(self) -> None:
        """
        Stop every child and close the window.
        """
        self._runner.stop_all()
        self._namespace_runner.stop_all()
        self._reports_runner.stop_all()
        self._tick.stop()
        self.close()

    def breadcrumb_text(self) -> str:
        """
        The breadcrumb as shown: each level's label, joined by
        CRUMB_SEPARATOR ('All', then the value drilled into at each level).
        """
        levels = self._shown.levels if self._shown else (TOP_LEVEL,)
        return CRUMB_SEPARATOR.join(level.label for level in levels)

    # Events -----------------------------------------------------------------

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:
        # Esc does nothing: the window is a workspace, closed by its close
        # button, not a dialog to dismiss
        if a0 is not None and a0.key() == Qt.Key.Key_Escape:
            a0.accept()
            return
        super().keyPressEvent(a0)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if (
            a0 is self._table
            and isinstance(a1, QKeyEvent)
            and (a1.type() == QEvent.Type.KeyPress)
        ):
            if a1.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._drill(self._table.currentIndex().row())
                return True
            if a1.matches(QKeySequence.StandardKey.Copy):
                self._copy_cells()
                return True
        return super().eventFilter(a0, a1)

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        file_dialogs.dialog_settings().setValue(
            SETTING_EXPLORER_GEOMETRY, self.saveGeometry()
        )
        super().closeEvent(a0)

    # Requests ---------------------------------------------------------------

    def _list_reports(self) -> None:
        """
        Start listing the kept reports (yd usage --reports); with base
        arguments Commander cannot build, nothing.
        """
        try:
            self._base_args()
        except UnusableArguments:
            return
        self._reports_runner.run(["--reports"])

    def _on_reports(self, result: RunResult) -> None:
        """
        Kept Reports filled with the reports listed, the last fetched first;
        disabled with none, or when they could not be listed.
        """
        document = result.document
        reports = (
            [item for item in document if isinstance(item, dict)]
            if result.exit_code == 0 and isinstance(document, list)
            else []
        )
        menu = cast(QMenu, self._kept.menu())
        menu.clear()
        for item in reports:
            namespace = item.get("namespace")
            action = cast(
                QAction,
                menu.addAction(
                    f"{_shown_time(item.get('from', ''))} \u2192"
                    f" {_shown_time(item.get('until', ''))} UTC"
                    f"{KEPT_SEPARATOR}{namespace or ALL_NAMESPACES}"
                ),
            )
            action.setToolTip(
                f"Fetched {_shown_time(item.get('fetched', ''))} UTC, last used"
                f" {_shown_time(item.get('lastUsed', ''))} UTC"
            )
            action.triggered.connect(partial(self._use_kept_report, item))
        self._kept.setEnabled(bool(reports))
        self._kept.setToolTip(KEPT_TOOLTIP if reports else NO_KEPT_TOOLTIP)

    def _use_kept_report(self, item: dict) -> None:
        """
        A kept report chosen: the controls set to its window and namespace
        (the window as Custom), and the report shown at once, at the top
        level: it is used again, not fetched, so it waits for no Fetch Report.
        """
        self._preset.blockSignals(True)
        self._preset.setCurrentText(CUSTOM_PRESET)
        self._preset.blockSignals(False)
        self._from.setText(str(item.get("from", "")))
        self._until.setText(str(item.get("until", "")))
        self._namespace.setCurrentText(str(item.get("namespace") or ALL_NAMESPACES))
        self._resolve(refresh=False)

    def _list_namespaces(self) -> None:
        """
        Start the namespace listing; with base arguments Commander cannot
        build, nothing (the view's own request says why).
        """
        try:
            self._base_args()
        except UnusableArguments:
            return
        self._namespace_runner.run(["namespaces"])

    def _request(self, view: _View, refresh: bool = False) -> None:
        arguments = view_args(view.scope, list(view.levels), refresh)
        self._requested = view
        self._resolving = not view.scope.pinned
        self._resolving_refresh = refresh
        try:
            self._requested_line = command_line([*self._base_args(), *arguments])
        except UnusableArguments:
            # The runner reports it as that request's failure
            self._requested_line = ""
        self._runner.run(arguments)
        viewport = self._table.viewport()
        if viewport is not None:
            viewport.setCursor(Qt.CursorShape.BusyCursor)

    def _request_levels(self, levels: list[Level] | tuple[Level, ...]) -> None:
        if self._shown is not None:
            self._request(_View(self._shown.scope, tuple(levels)))

    def _control_inputs(self) -> tuple[str, str, str, str]:
        return (
            self._from.text(),
            self._until.text(),
            self._namespace.currentText(),
            self._preset.currentText(),
        )

    def _put_back_controls(self) -> None:
        """
        The Window, From, Until and Namespace controls as they were for the
        scope shown, without running anything.
        """
        if self._shown_inputs is None:
            return
        from_text, until_text, namespace, preset = self._shown_inputs
        for widget in (self._preset, self._from, self._until, self._namespace):
            widget.blockSignals(True)
        self._preset.setCurrentText(preset)
        self._from.setText(from_text)
        self._until.setText(until_text)
        self._namespace.setCurrentText(namespace)
        for widget in (self._preset, self._from, self._until, self._namespace):
            widget.blockSignals(False)
        self._typed = self._typed_inputs()

    def _typed_inputs(self) -> tuple[str, str, str | None]:
        namespace = self._namespace.currentText().strip()
        return (
            self._from.text().strip(),
            self._until.text().strip(),
            None if namespace in ("", ALL_NAMESPACES) else namespace,
        )

    def _resolve(self, refresh: bool) -> None:
        """
        A new first run: the window as typed, at the top level.
        """
        self._pending = False
        self._fetch_overlay.hide()
        self._typed = self._typed_inputs()
        self._requested_inputs = self._control_inputs()
        from_text, until_text, namespace = self._typed
        scope = Scope(from_text, until_text, namespace, self._cost.isChecked())
        self._request(_View(scope, (TOP_LEVEL,)), refresh=refresh)

    @property
    def _busy(self) -> bool:
        """
        Whether the view actions (drilling, sorting, Back, the crumbs, Total
        by) wait: a new report is being fetched, or awaits Fetch Report.
        """
        return self._resolving or self._pending

    def _await_fetch(self) -> None:
        """
        After the window or namespace controls change (or with nothing asked
        for yet): the table dimmed under Fetch Report while they name a report
        other than the one shown, and clear again once they name it.
        """
        self._pending = self._shown is None or self._typed_inputs() != self._typed
        if self._pending:
            self._fetch_overlay.show_over_table()
        else:
            self._fetch_overlay.hide()

    def _rerun(self) -> None:
        """
        Fetch the report the controls name, while one awaits Fetch Report;
        else run the latest view again (the one shown, or one that failed).
        """
        if self._pending:
            self._resolve(refresh=False)
        elif self._requested is not None:
            self._request(self._requested)

    def _runner_stop(self) -> None:
        self._runner.stop()

    # Controls ---------------------------------------------------------------

    def _fill_window(self, preset: str) -> None:
        from_text, until_text = preset_window(preset, datetime.now(timezone.utc))
        self._from.setText(from_text)
        self._until.setText(until_text)

    def _preset_chosen(self, _index: int) -> None:
        preset = self._preset.currentText()
        if preset == CUSTOM_PRESET:
            return
        self._fill_window(preset)
        file_dialogs.dialog_settings().setValue(SETTING_EXPLORER_PRESET, preset)
        self._await_fetch()

    def _typed_window(self, *_args) -> None:
        self._preset.blockSignals(True)
        self._preset.setCurrentText(CUSTOM_PRESET)
        self._preset.blockSignals(False)

    def _cost_toggled(self, checked: bool) -> None:
        file_dialogs.dialog_settings().setValue(SETTING_EXPLORER_COST, checked)
        shown = self._shown
        if self._pending:
            # Taken by the fetch to come
            return
        if shown is None or self._resolving:
            # A new scope's first run, again with the new cost
            self._resolve(refresh=self._resolving and self._resolving_refresh)
            return
        self._request(_View(replace(shown.scope, cost=checked), shown.levels))

    def _total_by_toggled(self, key: str) -> None:
        """
        A key ticked or unticked in Total by: the level regrouped by the keys
        then ticked (toggled_by()); the last key unticked stays.
        """
        current = self._shown
        level = current.levels[-1] if current is not None else None
        by = toggled_by(level.by, key) if level is not None else None
        if current is None or level is None or by is None or self._busy:
            self._show_total_by()
            return
        # A sort by a key this level no longer shows is dropped
        sort = (
            level.sort
            if level.sort in USAGE_SORT_VALUE_KEYS or level.sort in by
            else None
        )
        changed = replace(
            level, by=by, sort=sort, reverse=level.reverse if sort else False
        )
        self._request_levels((*current.levels[:-1], changed))

    def _heading_clicked(self, column: int) -> None:
        key = self._model.sort_key(column)
        current = self._shown
        if key is None or current is None or self._busy:
            self._show_sort_indicator()
            return
        level = current.levels[-1]
        reverse = not level.reverse if (level.sort or "total") == key else False
        self._request_levels(
            (*current.levels[:-1], replace(level, sort=key, reverse=reverse))
        )

    def _drill(self, row: int) -> None:
        group = self._model.group(row)
        if group is None or self._shown is None or self._busy:
            return
        levels = drill(list(self._shown.levels), group)
        if levels is not None:
            self._request_levels(levels)

    def _step_back(self) -> None:
        shown = self._shown
        if shown is not None and not self._busy and len(shown.levels) > 1:
            self._request_levels(shown.levels[:-1])

    def _crumb_clicked(self, depth: int) -> None:
        shown = self._shown
        if shown is not None and not self._busy:
            self._request_levels(shown.levels[: depth + 1])

    def _show_column_menu(self, position: QPoint) -> None:
        header = self._table.horizontalHeader()
        if header is not None:
            self._column_menu().exec(header.mapToGlobal(position))

    def _column_menu(self) -> QMenu:
        """
        The heading's right-click menu: a tick for each figure column but
        the cost (which Estimated cost adds), the status columns after a
        separator.
        """
        menu = QMenu(self)
        for key in HIDEABLE_COLUMNS:
            if key == STATUS_COLUMNS[0]:
                menu.addSeparator()
            action = cast(QAction, menu.addAction(figure_heading(key)))
            action.setCheckable(True)
            action.setChecked(key not in self._hidden)
            action.toggled.connect(partial(self._show_column, key))
        return menu

    def _show_column(self, key: str, shown: bool) -> None:
        if shown:
            self._hidden.discard(key)
        else:
            self._hidden.add(key)
        file_dialogs.dialog_settings().setValue(
            SETTING_EXPLORER_HIDDEN_COLUMNS,
            ",".join(k for k in HIDEABLE_COLUMNS if k in self._hidden),
        )
        self._apply_hidden_columns()

    def _apply_hidden_columns(self) -> None:
        """
        Every column shown bar the figure columns hidden: the view keeps a
        column hidden by its place, which the cost column moves.
        """
        hidden = {self._model.figure_column(key) for key in self._hidden}
        for column in range(self._model.columnCount()):
            self._table.setColumnHidden(column, column in hidden)

    def _toggle_details(self) -> None:
        self._details.setVisible(not self._details.isVisible())

    def _export_csv(self, raw: bool) -> None:
        """
        The table's visible columns, saved to a CSV file the user names, in
        UTF-8: raw figures (UsageTableModel.raw_rows()) or the cells as shown,
        the Total row left out unless Include Total Row is ticked; the outcome
        logged, and a failure shown too.
        """
        columns = [
            column
            for column in range(self._model.columnCount())
            if not self._table.isColumnHidden(column)
        ]
        if not columns:
            return
        rows = self._model.raw_rows(columns) if raw else self._model.text_rows(columns)
        if self._model.has_total and not self._export_total.isChecked():
            rows = rows[:-1]
        name = datetime.now().strftime(EXPORT_NAME_FORMAT)
        path = self._file_dialogs.save_file(
            caption="Export CSV",
            directory=os.path.join(self._working_dir(), name),
            file_pattern=EXPORT_FILTER,
        )
        if path is None:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as file:
                csv.writer(file).writerows(rows)
        except OSError as error:
            message = EXPORT_FAILED.format(path=path, error=error)
            self.logged.emit(message)
            self._say([message], error=True)
            return
        self.logged.emit(EXPORTED_LOG.format(path=path))

    def _copy_cells(self) -> None:
        """
        The selected cells as tab-separated text, their headings first.
        """
        selection = self._table.selectionModel()
        indexes = selection.selectedIndexes() if selection is not None else []
        if not indexes:
            return
        rows = sorted({index.row() for index in indexes})
        columns = sorted(
            {i.column() for i in indexes if not self._table.isColumnHidden(i.column())}
        )
        chosen = {(index.row(), index.column()) for index in indexes}
        lines = [
            "\t".join(
                str(self._model.headerData(c, Qt.Orientation.Horizontal))
                for c in columns
            )
        ]
        for row in rows:
            lines.append(
                "\t".join(
                    str(self._model.data(self._model.index(row, c)))
                    if (row, c) in chosen
                    else ""
                    for c in columns
                )
            )
        copy_to_clipboard("\n".join(lines))

    # Results ----------------------------------------------------------------

    def _on_waiting(self) -> None:
        self._show_elapsed()
        self._overlay.show_over_table()
        self._tick.start()

    def _show_elapsed(self) -> None:
        self._overlay_text.setText(
            RUNNING_TEXT.format(
                elapsed=_minutes_and_seconds(self._runner.elapsed_seconds())
            )
        )

    def _idle(self) -> None:
        self._tick.stop()
        self._overlay.hide()
        viewport = self._table.viewport()
        if viewport is not None:
            viewport.unsetCursor()

    def _on_result(self, result: RunResult) -> None:
        self._idle()
        view = self._requested
        if view is None:
            return
        if result.exit_code == STOPPED_EXIT_CODE:
            self._first_run_failed()
            self._say([STOPPED_MESSAGE])
            self._sync_controls_to_shown()
            return
        document = result.document
        if result.exit_code == 0 and isinstance(document, dict):
            try:
                self._show_document(view, document, result.warnings)
                return
            except (KeyError, TypeError, ValueError, AttributeError):
                result = replace(
                    result,
                    exit_code=1,
                    error="yd usage printed a document Commander cannot read",
                )
        self._show_failure(result)

    def _show_document(
        self, view: _View, document: dict, warnings: list[str] | None = None
    ) -> None:
        """
        A successful view: shown, its scope pinned to the report's window.
        Raises KeyError, TypeError or ValueError, before anything shown has
        changed, for a document not shaped as `yd usage --json` writes it.
        """
        notes, details = self._notes_of(document)
        notes.extend(warnings or [])
        self._model.set_document(document, bool(view.scope.cost))
        self._export.setEnabled(True)
        scope = (
            view.scope
            if view.scope.pinned
            else view.scope.pinned_to(
                str(document.get("from", view.scope.from_text)),
                str(document.get("until", view.scope.until_text)),
            )
        )
        if self._resolving:
            self._shown_inputs = self._requested_inputs
            self._resolving = False
        self._shown = self._requested = _View(scope, view.levels)
        self._apply_hidden_columns()
        self._table.resizeColumnsToContents()
        self._show_breadcrumb(view.levels)
        self._sync_controls_to_shown()
        self._command_line.setText(self._requested_line)
        self._command_line.setCursorPosition(0)
        self._say(notes)
        self._details.setText("\n".join(details))
        self._details_button.setVisible(bool(details))
        if not details:
            self._details.hide()
        reused = bool(document.get("reused", True))
        self._report.setText(
            f"Report: {_shown_time(document.get('from', ''))} →"
            f" {_shown_time(document.get('until', ''))} UTC,"
            f" fetched {_shown_time(document.get('fetched', ''))} UTC"
            + (" (kept report reused)" if reused else " (fetched for this view)")
        )
        if not reused:
            self.logged.emit(FETCHED_LOG.format(command=self._requested_line))
            # A report fetched is kept: Kept Reports lists it
            self._list_reports()

    @staticmethod
    def _notes_of(document: dict) -> tuple[list[str], list[str]]:
        """
        The notes strip's lines for a document, and the Details lines: each
        instance type with no list price.
        """
        lines: list[str] = []
        covered = document.get("namespaces")
        if document.get("namespace") is None and isinstance(covered, list):
            # An Application allowed to read usage in some namespaces only
            lines.append(
                f"Reporting on the {_plural(len(covered), 'namespace')} this"
                f" Application can read usage in: {', '.join(map(str, covered))}"
            )
        if not document["groups"]:
            lines.append(
                NO_MATCHING_INSTANCES if document.get("where") else NO_INSTANCES
            )
        if document.get("pricesRefused"):
            lines.append(PRICES_REFUSED)
        for place in document.get("unreadablePrices") or []:
            lines.append(
                f"Could not read the list prices in {place['provider']}"
                f" {place['region']}; its Instances are not costed"
            )
        unpriced = document.get("unpriced") or []
        details = [
            f"No list price for {item['provider']} {item['region']}"
            f" {item['instanceType']} ({item['pricing']}):"
            f" {duration_text(float(item['runningHours']) * 3600)} running not costed"
            for item in unpriced
        ]
        if unpriced:
            hours = sum(float(item["runningHours"]) for item in unpriced)
            lines.append(
                f"⚠ {_plural(len(unpriced), 'instance type')} had no list price"
                f" ({duration_text(hours * 3600)} running)"
            )
        return lines, details

    def _first_run_failed(self) -> None:
        """
        After a new scope's first run fails or is stopped: the controls put
        back to the scope shown, which later views start from again (with
        nothing shown, the controls keep what was typed, to run again).
        """
        if not self._resolving:
            return
        self._resolving = False
        if self._shown is not None:
            self._put_back_controls()
            self._requested = self._shown
        # With nothing shown, Fetch Report again, for the controls corrected
        # or as they are
        self._await_fetch()

    def _show_failure(self, result: RunResult) -> None:
        self._first_run_failed()
        lines = error_lines(result.error) or [result.error]
        self.logged.emit(
            FAILED_LOG.format(
                command="yd usage", code=result.exit_code, message=lines[0]
            )
        )
        meaning = EXIT_CODE_MEANINGS.get(result.exit_code)
        self._say([*lines, *([meaning] if meaning else [])], error=True)
        self._details_button.hide()
        self._details.hide()
        self._sync_controls_to_shown()

    def _sync_controls_to_shown(self) -> None:
        """
        Total by, Estimated cost (and the cost remembered) and the sort
        indicator as the view shown has them (Total by as the top level's,
        and the other two as they are, with none shown): after a view is
        shown, or a run is stopped or fails.
        """
        self._show_total_by()
        shown = self._shown
        if shown is not None:
            cost = bool(shown.scope.cost)
            self._cost.blockSignals(True)
            self._cost.setChecked(cost)
            self._cost.blockSignals(False)
            file_dialogs.dialog_settings().setValue(SETTING_EXPLORER_COST, cost)
        self._show_sort_indicator()

    def _show_total_by(self, levels: tuple[Level, ...] | None = None) -> None:
        """
        Total by as the levels given total (by default the view shown's, the
        top level's with none shown): its keys named on the button, and a
        tick for each in a menu of the keys the breadcrumb leaves open.
        """
        if levels is None:
            levels = self._shown.levels if self._shown else (TOP_LEVEL,)
        by = levels[-1].by
        self._total_by.setText(", ".join(heading(key) for key in by))
        menu = cast(QMenu, self._total_by.menu())
        menu.clear()
        for key in eligible_keys(levels):
            action = cast(QAction, menu.addAction(heading(key)))
            action.setCheckable(True)
            action.setChecked(key in by)
            action.triggered.connect(partial(self._total_by_toggled, key))

    def _on_namespaces(self, result: RunResult) -> None:
        document = result.document
        if result.exit_code != 0 or not isinstance(document, list):
            if result.exit_code != STOPPED_EXIT_CODE:
                lines = error_lines(result.error) or [result.error]
                self.logged.emit(
                    FAILED_LOG.format(
                        command="yd list namespaces",
                        code=result.exit_code,
                        message=lines[0],
                    )
                )
            return
        names = sorted(
            {
                str(item["namespace"])
                for item in document
                if isinstance(item, dict) and item.get("namespace")
            }
        )
        text = self._namespace.currentText()
        self._namespace.blockSignals(True)
        self._namespace.clear()
        self._namespace.addItems([ALL_NAMESPACES, *names])
        self._namespace.setCurrentText(text)
        self._namespace.blockSignals(False)

    # Showing ----------------------------------------------------------------

    def _say(self, lines: list[str], error: bool = False) -> None:
        self._error_showing = error
        self._notes.setText("\n".join(lines))
        self._notes.setVisible(bool(lines))
        self._colour_notes()

    def _colour_notes(self) -> None:
        if self._error_showing:
            red, green, blue = ERROR_RGB_DARK if self._dark else ERROR_RGB_LIGHT
            self._notes.setStyleSheet(
                f"QTextEdit {{ color: rgb({red}, {green}, {blue});"
                " background: transparent; }"
            )
        else:
            self._notes.setStyleSheet("QTextEdit { background: transparent; }")

    def _show_breadcrumb(self, levels: tuple[Level, ...]) -> None:
        while self._crumbs.count():
            item = self._crumbs.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self._crumb_buttons = []
        for depth, level in enumerate(levels):
            if depth:
                self._crumbs.addWidget(QLabel(CRUMB_SEPARATOR.strip(), self))
            if depth == len(levels) - 1:
                self._crumbs.addWidget(QLabel(level.label, self))
                continue
            button = QToolButton(self)
            button.setText(level.label)
            button.setAutoRaise(True)
            button.setToolTip("Back to this level")
            button.clicked.connect(partial(self._crumb_clicked, depth))
            self._crumbs.addWidget(button)
            self._crumb_buttons.append(button)
        self._back.setEnabled(len(levels) > 1)
        self._show_total_by(levels)

    def _show_sort_indicator(self) -> None:
        header = self._table.horizontalHeader()
        if header is None:
            return
        level = self._shown.levels[-1] if self._shown else None
        key = (level.sort if level else None) or "total"
        column = self._model.column_of_sort_key(key)
        # The CLI's order: a key's value A to Z, a figure the most first
        most_first = key in USAGE_SORT_VALUE_KEYS
        if level is not None and level.reverse:
            most_first = not most_first
        header.setSortIndicator(
            -1 if column is None else column,
            Qt.SortOrder.DescendingOrder if most_first else Qt.SortOrder.AscendingOrder,
        )
