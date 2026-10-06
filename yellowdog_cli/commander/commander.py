#!/usr/bin/env python3

"""
YellowDog Commander: Qt-based GUI application for driving the YellowDog CLI.

YellowDogApp is built in layers, each a class in its own module, and each
calling only itself and the layers below it: WindowBase (window_base.py: the
widgets and state, the options every command is given, the listing scope),
CommandRunning (command_running.py), WindowDialogs (window_dialogs.py), then
one class per action panel -- WorkPanel, ComputePanel and ResultsPanel, which
do not call one another. This module is the window itself: construction and
layout, the configuration file (Panel 1), the output and utility actions, the
command box, quitting, and run_app().
"""

import os
import sys
from collections.abc import Callable
from datetime import datetime
from functools import partial as functools_partial
from os.path import abspath, dirname, exists, join
from typing import cast

from PyQt6.QtCore import (
    QEvent,
    QEventLoop,
    QFileSystemWatcher,
    QProcess,
    QSize,
    Qt,
    QTimer,
)
from PyQt6.QtGui import (
    QClipboard,
    QCloseEvent,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QPalette,
    QShortcut,
    QStyleHints,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
)
from PyQt6.uic import loadUi  # pyright: ignore[reportPrivateImportUsage]

from yellowdog_cli.commander.command_history import CommandHistory
from yellowdog_cli.commander.compute_panel import ComputePanel
from yellowdog_cli.commander.config_discovery import ConfigDiscovery
from yellowdog_cli.commander.elision import elide_path, elide_path_to_fit
from yellowdog_cli.commander.file_dialogs import FileDialogs
from yellowdog_cli.commander.help_viewer import HelpDialog
from yellowdog_cli.commander.host import (
    LINUX,
    MACOS,
    WINDOWS,
    shell_command,
)
from yellowdog_cli.commander.output_model import COMMANDER_RUN
from yellowdog_cli.commander.output_pane import OutputPane
from yellowdog_cli.commander.results_panel import ResultsPanel
from yellowdog_cli.commander.startup import StartupSettings
from yellowdog_cli.commander.window_base import (
    CWD,
    UNDECORATED_YD_COMMANDS,
    WINDOW_TITLE,
)
from yellowdog_cli.commander.work_panel import WorkPanel
from yellowdog_cli.utils.output_style import ERROR_MARKER
from yellowdog_cli.utils.paths import relative_if_possible

if WINDOWS:
    import ctypes

_PKG_DIR = dirname(abspath(__file__))

NO_SELECTED_CONFIG = "No configuration selected"
MAX_DIALOG_PATH_LENGTH = 60  # dialogs are wider than the left-hand column
DESELECT_ROW_PREFIX = "Deselect "  # keeps the checkbox polarity unambiguous
# strftime for the pre-filled save-output filename. Colons are not filename-safe
# on Windows, so this cannot reuse the ':'-separated prefix format used in the
# output window itself.
SAVED_OUTPUT_NAME_FORMAT = "commander-output-%Y%m%d-%H%M%S.txt"
SAVED_OUTPUT_FILTER = "Text files (*.txt);;All files (*)"
BRANDING_IMAGE_LIGHT = join(_PKG_DIR, "images", "IconYellowDog.svg")
BRANDING_IMAGE_DARK = join(_PKG_DIR, "images", "IconYellowDogDark.svg")
BRANDING_IMAGE_SIZE = 54
ICON_IMAGE = join(_PKG_DIR, "images", "IconApi.ico")


class YellowDogApp(WorkPanel, ComputePanel, ResultsPanel):
    def __init__(self, settings: StartupSettings | None = None):
        super().__init__()
        if settings is None:
            settings = StartupSettings()
        self._confirmations_disabled = settings.disable_confirmations

        # Dynamically loads the QT UI definition
        loadUi(join(_PKG_DIR, "commander.ui"), self)

        # Include the CLI version in the window title
        self.setWindowTitle(WINDOW_TITLE)

        # The framed label showing the selected configuration file (the frame
        # itself comes from commander.ui, which cannot carry this margin)

        self._align_field_labels()

        self._pid = os.getpid()

        # Override the branding pixmap with the SVG for the current style
        self._update_branding_icon(self._color_scheme() == Qt.ColorScheme.Dark)

        # Actual displayed font sizes differ across platforms;
        # use a smaller point size on Windows and Linux for the output window
        self._font = QFont()
        self._font.setPointSize(12 if MACOS else 8)
        self._font.setFamily("Courier New")
        self._font.setWeight(500)
        self.log_output.setFont(self._font)

        # Every file dialog: selecting, saving and browsing
        self._file_dialogs = FileDialogs(self, self._font)

        # The output window, which everything below logs to. The chooser is
        # reached late-bound, through the window, so that a test replacing
        # _build_chooser_dialog on the window replaces the one the pane uses.
        self._output = OutputPane(
            window=self,
            view=self.log_output,
            bar=self.output_filter_bar,
            bar_label=self.output_filter_label,
            show_all_button=self.output_filter_show_all,
            copy_button=self.copy_command_output,
            save_button=self.save_command_output,
            build_chooser=lambda *args, **kwargs: self._build_chooser_dialog(
                *args, **kwargs
            ),
            pid=self._pid,
        )

        # Set up action connections
        self.select_config_file.clicked.connect(self._select_config_file_action)
        self.select_work_requirement.clicked.connect(
            self._select_work_requirement_action
        )
        self.submit_work_requirement.clicked.connect(
            self._submit_work_requirement_action
        )
        self.add_to_work_requirement.clicked.connect(
            self._add_to_work_requirement_action
        )
        self.download_results.clicked.connect(self._download_results_action)
        self.clear_command_output.clicked.connect(self._clear_output_action)
        self.copy_command_output.clicked.connect(self._copy_output_action)
        self.save_command_output.clicked.connect(self._save_output_action)
        self.delete_objects.clicked.connect(self._delete_objects_action)
        self.cancel_work_requirements.clicked.connect(
            self._cancel_work_requirements_action
        )
        self.cancel_work_requirements_and_abort.clicked.connect(
            self._cancel_work_requirements_and_abort_action
        )
        self.select_worker_pool.clicked.connect(self._select_worker_pool_action)
        self.create_worker_pool.clicked.connect(self._create_worker_pool_action)
        self.resize_worker_pool.clicked.connect(self._resize_worker_pool_action)
        self.shutdown_all_worker_pools.clicked.connect(
            self._shutdown_all_worker_pools_action
        )
        self.terminate_all_compute_requirements.clicked.connect(
            self._terminate_all_compute_requirements_action
        )
        self.browse_results_directory.clicked.connect(
            self._browse_results_directory_action
        )
        self.show_config.clicked.connect(self._show_config_action)
        self.show_wr_json.clicked.connect(self._show_wr_json_action)
        self.show_wp_json.clicked.connect(self._show_wp_json_action)
        self.deselect_files.clicked.connect(self._deselect_files_action)
        self.browse_config_directory.clicked.connect(
            self._browse_config_directory_action
        )
        self.run_any_command.clicked.connect(self._run_any_command_action)

        self.next_command.clicked.connect(self._next_command_action)
        self.prev_command.clicked.connect(self._prev_command_action)

        # Help: the button, the platform's help key (Cmd+? on macOS, F1
        # elsewhere) and F1 everywhere, all opening the one modeless dialog
        self._help_dialog: HelpDialog | None = None
        self.show_help.clicked.connect(self._show_help_action)
        help_keys = QKeySequence.keyBindings(QKeySequence.StandardKey.HelpContents)
        for key in {*help_keys, QKeySequence(Qt.Key.Key_F1)}:
            QShortcut(key, self).activated.connect(self._show_help_action)

        # Handle state toggle exclusivity; the 'exclusive' property on the
        # containing button group doesn't allow a state where no boxes are
        # checked
        self.follow_progress.checkStateChanged.connect(self._follow_progress_set)
        self.dry_run.checkStateChanged.connect(self._dry_run_set)
        self.follow_worker_pool.checkStateChanged.connect(self._follow_worker_pool_set)
        self.dry_run_worker_pool.checkStateChanged.connect(
            self._dry_run_worker_pool_set
        )
        self.dark_mode.checkStateChanged.connect(self._dark_mode_action)
        self.dark_mode.setChecked(self._color_scheme() == Qt.ColorScheme.Dark)

        # Default the 'follow' checkboxes
        self.follow_progress.setChecked(True)
        self.follow_worker_pool.setChecked(True)

        # Fill the fields given on the command line before anything is connected
        # to them, so that the deferred config parse below is the first and only
        # one to see them: filled afterwards, the user-variables box would also
        # start its reparse timer and run a second, pointless parse.
        self._apply_startup_fields(settings)

        # Handle specific key presses in text edit boxes
        for ui_object in [
            self.user_variables,
            self.properties,
            self.wr_submit_options,
            self.wp_provision_options,
            self.any_command,
            self.namespace_override,
            self.tag_override,
            self.name_glob_override,
            self.object_path_override,
        ]:
            ui_object.textChanged.connect(
                functools_partial(self._edit_box_keypress_handler, ui_object)
            )

        self._config_file: str | None = None
        # Re-elide the selected configuration's path whenever its label's width
        # changes (see _show_config_selection)
        self.select_config_label.installEventFilter(self)
        # Absolute, deliberately: these are handed to a child process that runs
        # in the config file's directory (see _working_dir), while Commander's own
        # directory is wherever it was launched from — and Show reads them in this
        # process. A path relative to either base is wrong for the other, so
        # 'yd-submit -r ../demos/bash/x.json' went looking for it under the config
        # directory and failed. The config file needs no such care: its consumers
        # take _config_dir() and _config_basename() from it rather than passing it on.
        self._wr_file: str | None = None
        self._wp_file: str | None = None
        self._skip_confirmations: set[str] = set()

        # Original 'Select' button labels and tooltips, restored when a file is
        # deselected (while one is selected, the tooltip is its full path)
        self._select_wr_default_text = self.select_work_requirement.text()
        self._select_wp_default_text = self.select_worker_pool.text()
        self._select_wr_default_tooltip = self.select_work_requirement.toolTip()
        self._select_wp_default_tooltip = self.select_worker_pool.toolTip()

        # Watch the selected config file for on-disk changes
        self._file_watcher = QFileSystemWatcher(self)
        self._file_watcher.fileChanged.connect(self._on_config_file_changed)

        # Namespace/tag discovery and the placeholders showing what it found,
        # connected to the fields after they are filled (_apply_startup_fields).
        # The window's methods are handed over as lambdas, not bound methods, so
        # that a test replacing one on the window — _run_nested, say — replaces
        # the one discovery calls.
        self._discovery = ConfigDiscovery(
            parent=self,
            namespace_field=self.namespace_override,
            tag_field=self.tag_override,
            object_path_field=self.object_path_override,
            user_variables=self.user_variables,
            properties=self.properties,
            config_selected=lambda: self._config_file is not None,
            config_source_args=lambda: self._config_source_args(),
            override_args=lambda: self._namespace_tag_and_user_vars(),
            working_dir=lambda: self._working_dir(),
            run_nested=lambda *args, **kwargs: self._run_nested(*args, **kwargs),
            shutting_down=lambda: self._shutting_down,
            log=lambda message: self._output.log(message),
        )

        if settings.wr_file is not None:
            self._set_wr_file(settings.wr_file)
        if settings.wp_file is not None:
            self._set_wp_file(settings.wp_file)

        # Defer config parse until after the window is shown, so the GUI is
        # visible before yd-variables runs
        QTimer.singleShot(0, lambda: self._set_config_file(settings.config_file))

        self._any_command_history = CommandHistory()
        self._active_process: QProcess | None = None
        self._active_run = COMMANDER_RUN  # the output run of _active_process

        # Live child processes and nested event loops, so that shutdown() can
        # stop them deterministically instead of leaving them to be torn down
        # with the widgets. Commands launched from the UI are kept separately
        # from internal synchronous helpers, because only the former are worth
        # asking the user about on quit.
        self._processes: list[QProcess] = []
        self._helper_processes: list[QProcess] = []
        self._nested_loops: list[QEventLoop] = []
        self._shutting_down = False
        # How many nested event loops are running. A nested loop keeps the main
        # window interactive, so without this an action could be started while
        # another was mid-enumeration.
        #
        # A depth counter rather than a flag, because nested loops really do
        # nest: the config parse deferred below with singleShot(0) runs in the
        # first event loop to spin, which can be one an enumeration has already
        # entered — observed reaching depth 2 for a single enumeration. A flag
        # cleared by the inner parse finishing would unlock the window while the
        # outer loop was still blocking, which is the bug this avoids.
        self._nested_depth = 0
        self.stdin_input.textChanged.connect(
            functools_partial(self._edit_box_keypress_handler, self.stdin_input)
        )

    def _apply_startup_fields(self, settings: StartupSettings):
        """
        Fill the text fields from the command line. The variables are joined
        with spaces, never newlines: _edit_box_keypress_handler deletes a
        newline, which would fuse 'a=1' and 'b=2' into the one variable
        'a=1b=2'. launcher.py has already refused any value these fields could
        not hold as given.
        """
        for field, value in [
            (self.namespace_override, settings.namespace),
            (self.tag_override, settings.tag),
            (self.name_glob_override, settings.name_glob),
            (self.object_path_override, settings.object_path),
        ]:
            if value:
                field.setPlainText(value)
                self._set_cursor_to_end(field)
        if settings.variables:
            self.user_variables.setPlainText(" ".join(settings.variables))
            self._set_cursor_to_end(self.user_variables)
        if settings.properties:
            self.properties.setPlainText(" ".join(settings.properties))
            self._set_cursor_to_end(self.properties)

    def _update_branding_icon(self, is_dark: bool):
        path = BRANDING_IMAGE_DARK if is_dark else BRANDING_IMAGE_LIGHT
        self.branding.setPixmap(
            QIcon(path).pixmap(QSize(BRANDING_IMAGE_SIZE, BRANDING_IMAGE_SIZE))
        )

    def _on_config_file_changed(self, _path: str):
        """
        Called by QFileSystemWatcher when the config file is modified on disk.
        Some editors save atomically (write-new + rename), which removes the
        original inode and causes the watcher to drop the path; re-add it so
        subsequent saves are still detected.
        """
        if self._config_file is not None:
            abs_path = abspath(self._config_file)
            if exists(abs_path) and abs_path not in self._file_watcher.files():
                self._file_watcher.addPath(abs_path)
        self._discovery.invalidate()
        self._output.log(
            f"Config file '{self._config_file}' changed on disk; refreshing..."
        )
        self._discovery.reparse_placeholders()

    def _set_config_file(self, config_file: str | None):
        """
        Setting config_file to None will deselect the current config file.
        """
        # Stop watching the previously selected config file
        if self._config_file is not None:
            self._file_watcher.removePath(abspath(self._config_file))

        if config_file is None:
            self._config_file = None
            self._show_config_selection()
            self._discovery.clear()
            self._discovery.reparse_placeholders()
            return

        if not exists(config_file):
            self._output.log(f"Config file '{config_file}' does not exist")
            return

        # Absolute where there is no relative path (Windows, another drive)
        selected_config_file = relative_if_possible(config_file)
        self._config_file = selected_config_file
        self._discovery.invalidate()
        self._output.log(f"Selected configuration file '{selected_config_file}'")
        self._show_config_selection()
        self._discovery.reparse_placeholders()
        self._file_watcher.addPath(abspath(selected_config_file))

    def _select_config_file_action(self):
        file = self._file_dialogs.select_file(
            caption="Please select a configuration file",
            directory=(self._config_dir() if self._config_file else CWD),
            file_pattern="*.toml",
        )
        if file is None:
            self._output.log(NO_SELECTED_CONFIG)
        else:
            self._set_config_file(file)

    def _check_config_file(self, quiet: bool = False) -> bool:
        if self._config_file is None:
            if not quiet:
                self._output.log(NO_SELECTED_CONFIG)
            return False
        return True

    def _align_field_labels(self):
        """
        Start the left-hand column's input fields at one edge, by widening each
        of their labels to the widest of them; and likewise the right-hand
        column's User-Defined Variables and Properties fields, one above the
        other in separate grid rows.

        Their rows sit in three separate panel layouts, and Qt aligns nothing
        across layouts, so each field began wherever its own label happened to
        end — at 110, 110 and 56. Measured here rather than set as a width in
        commander.ui, because a width in pixels is a width for one font: these
        labels are the widest under this one, and need not be under the next.
        """
        for labels in (
            (self.wr_options_label, self.wp_options_label, self.object_path_label),
            # The right-hand column's two, so that Properties lines up with the
            # User-Defined Variables field above it
            (self.user_variables_label, self.properties_label),
        ):
            widest = max(label.sizeHint().width() for label in labels)
            for label in labels:
                label.setMinimumWidth(widest)

    def _align_checkbox_indicators(self):
        """
        Indent the left-hand column's checkboxes by however far the current style
        insets a push button's frame inside its widget, so that the indicators line
        up with the buttons above and below them.

        Both are laid out at the same x. The macOS style then paints a button's
        bevel 2px in — room for its focus ring — and a checkbox's indicator flush,
        which leaves the checkboxes looking a couple of pixels further left than
        every button in the column.

        Read from the style rather than written as 2, because Dark Mode switches
        the application style to Fusion and back (see _dark_mode_action), and
        Fusion paints the bevel flush; hence also the recomputation on a style
        change in changeEvent(), and clearing the margins before measuring, so that
        the measurement is of the style and not of the last margin applied.

        Not covered by a test: the inset only exists when painting through the real
        platform, so it cannot be reproduced offscreen — even under the macOS style
        a headless button reports its bevel flush. Verified by measuring the painted
        pixels of a real window, where the buttons start at x=22 and the checkboxes
        did at x=20.
        """
        checkboxes = (
            self.dry_run,
            self.follow_progress,
            self.dry_run_worker_pool,
            self.follow_worker_pool,
            self.dry_run_objects,
        )
        for checkbox in checkboxes:
            checkbox.setStyleSheet("")

        inset = self._button_bevel_inset(
            self.submit_work_requirement
        ) - self._indicator_inset(self.dry_run)
        if inset <= 0:
            return
        for checkbox in checkboxes:
            checkbox.setStyleSheet(f"margin-left: {inset}px")

    @staticmethod
    def _button_bevel_inset(button: QPushButton) -> int:
        """How far inside its widget the current style paints a push button's frame."""
        option = QStyleOptionButton()
        button.initStyleOption(option)
        style = button.style()
        if style is None:
            return 0
        return style.subElementRect(
            QStyle.SubElement.SE_PushButtonBevel, option, button
        ).left()

    @staticmethod
    def _indicator_inset(checkbox: QCheckBox) -> int:
        """The same, for a checkbox's indicator."""
        option = QStyleOptionButton()
        checkbox.initStyleOption(option)
        style = checkbox.style()
        if style is None:
            return 0
        return style.subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, option, checkbox
        ).left()

    def _show_config_selection(self):
        """
        Show the selected configuration file's full path on its label, elided
        from the left to the label's width when it does not fit, so that the
        filename and as much of its directory as there is room for stay in view;
        the tooltip always has the whole path. The label's horizontal size
        policy is Ignored in commander.ui, so a long path never widens the
        window: the label takes the width the layout gives it, and the path is
        fitted to that, again on every resize (eventFilter).
        """
        label = self.select_config_label
        if self._config_file is None:
            label.setText(NO_SELECTED_CONFIG)
            label.setToolTip("")
            return
        path = abspath(self._config_file)
        metrics = QFontMetrics(label.font())
        available = label.contentsRect().width()
        label.setText(
            elide_path_to_fit(
                path, lambda text: metrics.horizontalAdvance(text) <= available
            )
        )
        label.setToolTip(path)

    def eventFilter(self, a0, a1):
        if (
            a0 is self.select_config_label
            and a1 is not None
            and a1.type() == QEvent.Type.Resize
        ):
            self._show_config_selection()
        return super().eventFilter(a0, a1)

    def showEvent(self, a0):
        """
        Align the checkboxes once the window is on screen. The style resolves a
        button's bevel inset against the real platform, so measuring it in
        __init__ reports flush — 0 rather than 2 — and the indent never gets
        applied. Idempotent, so a later show costs nothing.
        """
        super().showEvent(a0)
        self._align_checkbox_indicators()

    def changeEvent(self, a0):
        """
        Re-align the checkboxes when the application style changes, which Dark Mode
        does: the inset they are indented by belongs to the style, not to the theme.
        """
        super().changeEvent(a0)
        if a0 is not None and a0.type() == QEvent.Type.StyleChange:
            self._align_checkbox_indicators()

    def _clear_output_action(self):
        self._output.clear()

    def _copy_output_action(self):
        cast(QClipboard, QApplication.clipboard()).setText(
            self.log_output.toPlainText()
        )

    def _save_output_action(self):
        """
        Save the command output window's contents to a file the user nominates.
        The dialog pre-fills a timestamped name in the working directory, so
        repeated saves in one session land in separate files rather than
        prompting to overwrite.

        With no output, log and stop rather than writing an empty file: the user
        asked to save what they can see, and an empty file is not that.
        """
        text = self.log_output.toPlainText()
        if not text:
            self._output.log("No command output to save")
            return

        default_name = datetime.now().strftime(SAVED_OUTPUT_NAME_FORMAT)
        path = self._file_dialogs.save_file(
            caption="Save Command Output",
            directory=join(self._working_dir(), default_name),
            file_pattern=SAVED_OUTPUT_FILTER,
        )
        if path is None:
            return

        try:
            # Explicit utf-8: the output holds whatever a yd-* command emitted,
            # which can include non-ASCII, and Windows would otherwise write it
            # in a narrower default encoding.
            with open(path, "w", encoding="utf-8") as output_file:
                output_file.write(text if text.endswith("\n") else f"{text}\n")
        except OSError as e:
            self._output.log(f"Could not save command output to '{path}': {e}")
            return

        self._output.log(f"Saved command output to '{path}'")

    def shutdown(self):
        """
        Stop child processes and leave any nested event loop, before Qt starts
        destroying the widgets. Idempotent.

        Without this, a command still running at exit is destroyed along with
        the window: Qt warns 'QProcess: Destroyed while process is still
        running', its output handlers fire against deleted C++ objects, and the
        resulting failure during interpreter teardown is what raises a macOS
        error report. A command blocked on a network timeout — an unreachable
        API URL, say — makes this the normal case rather than a rare one.
        """
        if self._shutting_down:
            return
        self._shutting_down = True

        # Release any nested event loop (config parsing, entity enumeration):
        # the close was delivered from inside it, so it must be told to exit or
        # it will keep running while the widgets are destroyed around it
        for event_loop in list(self._nested_loops):
            event_loop.quit()

        stopped = sum(
            self._stop_process(process)
            for process in list(self._processes) + list(self._helper_processes)
        )
        if stopped:
            self._output.log(f"Stopped {stopped} running command(s) on exit")
        self._processes.clear()
        self._helper_processes.clear()

    def closeEvent(self, a0: QCloseEvent | None):
        if not self._shutting_down:
            running = self._running_commands()
            if running and not self._confirmations_disabled:
                if not self._confirm_quit(running):
                    if a0 is not None:
                        a0.ignore()  # keep the window open
                    return
        self.shutdown()
        super().closeEvent(a0)

    def _confirm_quit(self, running: list[QProcess]) -> bool:
        """
        Ask whether to quit while commands are still running. Returns True if
        the user chose to quit. Suppressed by '--yes', which quits immediately.
        """
        dialog, quit_btn = self._build_quit_dialog(
            [f"{process.program()} (pid {process.processId()})" for process in running]
        )
        clicked: dict[str, object] = {}
        buttons = cast(QDialogButtonBox, dialog.findChild(QDialogButtonBox))
        buttons.clicked.connect(
            lambda button: (clicked.__setitem__("button", button), dialog.accept())
        )
        dialog.exec()
        return clicked.get("button") is quit_btn

    def _build_quit_dialog(self, names: list[str]) -> tuple[QDialog, QPushButton]:
        """
        Build (but do not show) the quit-while-running dialog: a warning, the
        commands that would be stopped, and Cancel / 'Quit and Stop' buttons
        (default Cancel, since stopping a submission part-way is worse than
        waiting for it). Returns the dialog and the quit button.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Commands Still Running")
        layout = QVBoxLayout(dialog)

        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(
            cast(QStyle, self.style())
            .standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
            .pixmap(QSize(48, 48))
        )
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        header.addWidget(icon_label)
        message = QLabel(
            f"{len(names)} command(s) are still running. Quitting will stop "
            "them; work already submitted to the platform will carry on there."
        )
        message.setWordWrap(True)
        header.addWidget(message, stretch=1)
        layout.addLayout(header)

        listing = QPlainTextEdit()
        listing.setObjectName("running_listing")
        listing.setReadOnly(True)
        listing.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        listing.setFont(self._font)
        listing.setPlainText("\n".join(names))
        layout.addWidget(listing)

        button_box = QDialogButtonBox(dialog)
        cancel_btn = cast(
            QPushButton,
            button_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole),
        )
        quit_btn = cast(
            QPushButton,
            button_box.addButton(
                "Quit and Stop", QDialogButtonBox.ButtonRole.AcceptRole
            ),
        )
        cancel_btn.setDefault(True)
        layout.addWidget(button_box)

        return dialog, quit_btn

    def _browse_config_directory_action(self):
        self._open_file_viewer(self._working_dir())

    def _show_config_action(self):
        if not self._check_config_file():
            return
        self._output.log(f"Displaying contents of '{self._config_file}':\n")
        with open(cast(str, self._config_file), encoding="utf-8") as f:
            self._output.log(f.read(), prefix=False)

    def _deselect_files_action(self):
        """
        Deselect the configuration file and/or the Work Requirement and Worker
        Pool definition files. Which of the currently-selected files to
        deselect is chosen in a dialog; all of them start selected, so
        accepting it unchanged deselects everything. The dialog is shown
        regardless of '--yes' (see _choose_files_to_deselect).
        """
        entries: list[tuple[str, str, Callable[[], None]]] = []
        if self._config_file is not None:
            entries.append(
                ("Configuration", self._config_file, self._deselect_config_file)
            )
        if self._wr_file is not None:
            entries.append(("Work Requirement", self._wr_file, self._deselect_wr_file))
        if self._wp_file is not None:
            entries.append(("Worker Pool", self._wp_file, self._deselect_wp_file))

        if not entries:
            self._output.log("No configuration or definition files to deselect")
            return

        # Always ask, even with '--yes': this dialog chooses what to act on
        # rather than confirming a destructive action, so suppressing it would
        # remove the only way to deselect one file and not the others.
        chosen = self._choose_files_to_deselect(
            [(label, path) for label, path, _ in entries]
        )
        if chosen is None:
            self._output.log("Cancelled: no files deselected")
            return
        if not chosen:
            self._output.log("No files chosen: nothing deselected")
            return

        for index in chosen:
            entries[index][2]()

    def _deselect_config_file(self):
        self._set_config_file(None)
        self._output.log("Deselected configuration file")

    def _deselect_wr_file(self):
        self._wr_file = None
        self._show_wr_selection()
        self._output.log("Deselected Work Requirement definition file")

    def _deselect_wp_file(self):
        self._wp_file = None
        self._show_wp_selection()
        self._output.log("Deselected Worker Pool definition file")

    def _choose_files_to_deselect(
        self, entries: list[tuple[str, str]]
    ) -> list[int] | None:
        """
        Ask which of the currently-selected files to deselect, given a list of
        (label, path) entries. Returns the indices of the files chosen, which
        may be empty, or None if the dialog was cancelled.
        """
        dialog, checkboxes = self._build_deselect_dialog(entries)
        if dialog.exec() != QDialog.DialogCode.Accepted.value:
            return None
        return [
            index for index, checkbox in enumerate(checkboxes) if checkbox.isChecked()
        ]

    def _build_deselect_dialog(
        self, entries: list[tuple[str, str]]
    ) -> tuple[QDialog, list[QCheckBox]]:
        """
        Build (but do not show) the deselection dialog: a checkbox per
        currently-selected file, labelled with its type and path and carrying
        the full path as a tooltip, plus Cancel / Deselect buttons (default
        Deselect). Every file starts checked, so accepting the dialog unchanged
        deselects all of them, as the button did before it asked.

        Each row is phrased as an action ('Deselect Worker Pool: ...') rather
        than as state ('Worker Pool: ...'), because a checked row stating only
        the file invites the opposite reading — that the box represents the
        file being selected, and that unchecking it is what deselects it.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Deselect Files")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Check the files to deselect:"))

        checkboxes: list[QCheckBox] = []
        for label, path in entries:
            checkbox = QCheckBox(
                f"{DESELECT_ROW_PREFIX}{label}: "
                f"{elide_path(path, MAX_DIALOG_PATH_LENGTH)}",
                dialog,
            )
            checkbox.setChecked(True)
            checkbox.setToolTip(abspath(path))
            layout.addWidget(checkbox)
            checkboxes.append(checkbox)

        button_box = QDialogButtonBox(dialog)
        button_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        deselect_btn = cast(
            QPushButton,
            button_box.addButton("Deselect", QDialogButtonBox.ButtonRole.AcceptRole),
        )
        deselect_btn.setDefault(True)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        return dialog, checkboxes

    def _dark_mode_action(self, checked_state: Qt.CheckState):
        is_dark = checked_state == Qt.CheckState.Checked
        application = cast(QApplication, QApplication.instance())
        if LINUX:
            if is_dark:
                application.setStyle("Fusion")
                dark = QPalette()
                dark.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
                dark.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
                dark.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
                dark.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
                dark.setColor(QPalette.ColorRole.ToolTipBase, QColor(25, 25, 25))
                dark.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
                dark.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
                dark.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
                dark.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
                dark.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
                dark.setColor(QPalette.ColorRole.Light, QColor(80, 80, 80))
                dark.setColor(QPalette.ColorRole.Midlight, QColor(65, 65, 65))
                dark.setColor(QPalette.ColorRole.Mid, QColor(45, 45, 45))
                dark.setColor(QPalette.ColorRole.Dark, QColor(35, 35, 35))
                dark.setColor(QPalette.ColorRole.Shadow, QColor(20, 20, 20))
                dark.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
                dark.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
                dark.setColor(QPalette.ColorRole.HighlightedText, QColor(35, 35, 35))
                dark.setColor(QPalette.ColorRole.PlaceholderText, QColor(160, 160, 160))
                application.setPalette(dark)
            else:
                application.setStyle("")
                application.setPalette(QPalette())
        else:
            cast(QStyleHints, application.styleHints()).setColorScheme(
                Qt.ColorScheme.Dark if is_dark else Qt.ColorScheme.Light
            )
        if is_dark:
            self.setStyleSheet(
                "#line_3, #line_4, #line_6, #line_7, #line_8, #line_9 {"
                " background-color: #555555; border: none; max-height: 2px; }"
                " #line_5 { background-color: #555555; border: none; max-width: 2px; }"
            )
        else:
            self.setStyleSheet("")
        self._update_branding_icon(is_dark)

    def _show_help_action(self):
        """
        Show the help, creating it the first time and raising it after that, so
        that it keeps the place the user had reached in it.
        """
        if self._help_dialog is None:
            self._help_dialog = HelpDialog(self, _PKG_DIR)
        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    def _run_any_command_action(self):
        self._run_any_command_core(self.any_command.toPlainText())

    def _run_any_command_core(self, command_text: str):
        words = command_text.split()
        if len(words) == 0:
            self._output.log("No command to run")
            return
        self._any_command_history.save_command(command_text)
        if words[0].startswith("yd-"):
            # Split with quoting, as a shell would: the non-yd branch below
            # hands the text to one, so the two agree about what a quote means
            command_and_args = self._split_text(command_text, "command")
            if command_and_args is None:
                return
            # The standalone ones are given nothing (UNDECORATED_YD_COMMANDS),
            # so the Properties field has nothing to do with them
            if (
                command_and_args[0] not in UNDECORATED_YD_COMMANDS
                and not self._properties_are_usable()
            ):
                return
            # yd- commands: inject UI namespace/tag/user vars as normal
            self._run_command_in_subprocess(
                command=command_and_args[0],
                args=command_and_args[1:],
                yd_command=False,
                accept_stdin=True,
            )
        else:
            # Non-yd commands: run via shell to support wildcard expansion,
            # pipes, and other shell features
            shell, flag = shell_command()
            self._run_command_in_subprocess(
                command=shell,
                args=[flag, command_text],
                yd_command=False,
                accept_stdin=True,
            )

    @staticmethod
    def _set_cursor_to_end(edit_box):
        cursor = edit_box.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        edit_box.setTextCursor(cursor)

    def _edit_box_keypress_handler(self, edit_box):
        """
        Suppress the use of the tab and return keys in text edits.
        Issue the command if enter is pressed in the command box.
        """
        edit_box_contents = edit_box.toPlainText()

        if "\t" in edit_box_contents:
            edit_box_contents = edit_box_contents.replace("\t", "")
            edit_box.setPlainText(edit_box_contents)
            self._set_cursor_to_end(edit_box)

        if "\n" in edit_box_contents:
            edit_box_contents = edit_box_contents.replace("\n", "")
            edit_box.setPlainText(edit_box_contents)
            self._set_cursor_to_end(edit_box)

            # Special processing for the command window and stdin input
            if edit_box == self.any_command:
                self._run_any_command_core(edit_box_contents)
            elif edit_box == self.stdin_input:
                self._send_stdin_action(edit_box_contents)

    def _next_command_action(self):
        cmd = self._any_command_history.step_forward()
        if cmd is not None:
            self.any_command.setPlainText(cmd)
            self._set_cursor_to_end(self.any_command)

    def _prev_command_action(self):
        cmd = self._any_command_history.step_back()
        if cmd is not None:
            self.any_command.setPlainText(cmd)
            self._set_cursor_to_end(self.any_command)


def run_app(settings: StartupSettings | None = None):
    try:
        if WINDOWS:
            # noinspection PyUnresolvedReferences
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
                "yellowdog.commander"
            )
        if MACOS:
            # Silence macOS / Qt platform plugin system warnings
            os.environ["QT_LOGGING_RULES"] = "qt.qpa.*=false"
        app = QApplication(sys.argv)
        icon = QIcon(ICON_IMAGE)
        app.setWindowIcon(icon)
        win = YellowDogApp(settings)
        win.setWindowIcon(icon)
        # Covers quits that don't close the window first (macOS Cmd-Q, the Dock)
        app.aboutToQuit.connect(win.shutdown)

        cast(QLayout, win.layout()).activate()
        win.setMinimumHeight(win.minimumSizeHint().height())
        win.setMinimumWidth(win.minimumSizeHint().width())
        win.resize(win.minimumWidth(), win.minimumHeight())

        win.show()
        sys.exit(app.exec())

    except Exception as exc:
        print(f"{ERROR_MARKER}{exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run_app()
