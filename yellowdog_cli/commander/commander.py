#!/usr/bin/env python3

"""
YellowDog Commander: GUI application for driving the YellowDog CLI
"""

import os
import re
import subprocess
import sys
from datetime import datetime
from functools import partial as functools_partial
from platform import system as _platform_system
from shlex import quote
from typing import cast

_system = _platform_system()
MACOS = _system == "Darwin"
LINUX = _system == "Linux"
WINDOWS = _system == "Windows"

if not (MACOS or LINUX or WINDOWS):
    print(f"Error: unrecognised platform: {_system}", file=sys.stderr)
    sys.exit(1)

if MACOS or LINUX:
    from os import system as os_system
elif WINDOWS:
    import ctypes
    from os import (
        startfile as os_startfile,  # pyright: ignore[reportAttributeAccessIssue]
    )

from json import loads
from os.path import abspath, basename, dirname, exists, join, relpath

_PKG_DIR = dirname(abspath(__file__))

from PyQt6.QtCore import (
    QEventLoop,
    QFileSystemWatcher,
    QProcess,
    QProcessEnvironment,
    QSize,
    Qt,
    QTimer,
)
from PyQt6.QtGui import (
    QClipboard,
    QColor,
    QFont,
    QIcon,
    QPalette,
    QStyleHints,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QLabel,
    QLayout,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)
from PyQt6.uic import loadUi  # pyright: ignore[reportPrivateImportUsage]

SELECTED_CONFIG_PREFIX = "  "
NO_SELECTED_CONFIG = "No configuration selected"
CWD = os.getcwd()  # default dir for file dialogs when no config selected
RESULTS_DIR = "results"
BRANDING_IMAGE_LIGHT = join(_PKG_DIR, "images", "IconYellowDog.svg")
BRANDING_IMAGE_DARK = join(_PKG_DIR, "images", "IconYellowDogDark.svg")
BRANDING_IMAGE_SIZE = 54
ICON_IMAGE = join(_PKG_DIR, "images", "IconApi.ico")

NAMESPACE = "namespace"
TAG = "tag"
WP_DATA = "workerPoolData"
WR_DATA = "workRequirementData"


class CommandHistory:
    def __init__(self, max_size: int = 250):
        self._max_size = max_size
        self._ptr = 0
        self._commands: list[str] = []
        self._empty_string_returned = False

    def save_command(self, command: str):
        """
        Save a command at the end of the command list.
        Consecutive duplicates are not stored.
        """
        if self._commands and self._commands[-1] == command:
            return
        if len(self._commands) == self._max_size:
            self._commands.pop(0)
        self._commands.append(command)
        self._ptr = len(self._commands) - 1
        self._empty_string_returned = False

    def step_forward(self) -> str | None:
        """
        Return the next (later) command in the list.
        Return an empty string if already at the end of the list.
        """
        if len(self._commands) == 0:
            return None
        if self._ptr < len(self._commands) - 1:
            self._ptr += 1
        else:
            self._empty_string_returned = True
            return ""
        return self._commands[self._ptr]

    def step_back(self) -> str | None:
        """
        Return the previous (earlier) command in the list.
        Keep returning the first command if pointer is at the start.
        """
        if len(self._commands) == 0:
            return None
        if self._ptr > 0:
            if self._empty_string_returned:
                self._empty_string_returned = False
            else:
                self._ptr -= 1
        return self._commands[self._ptr]


class YellowDogApp(QMainWindow):
    # Widgets populated at runtime by loadUi("commander.ui"); declared here so
    # static type checkers can resolve their attribute references.
    branding: QLabel
    select_config_label: QLabel

    log_output: QPlainTextEdit
    user_variables: QPlainTextEdit
    wr_submit_options: QPlainTextEdit
    wp_provision_options: QPlainTextEdit
    any_command: QPlainTextEdit
    namespace_override: QPlainTextEdit
    tag_override: QPlainTextEdit
    object_path_override: QPlainTextEdit
    stdin_input: QPlainTextEdit

    follow_progress: QCheckBox
    dry_run: QCheckBox
    follow_worker_pool: QCheckBox
    dry_run_worker_pool: QCheckBox
    dry_run_objects: QCheckBox
    dark_mode: QCheckBox

    select_config_file: QPushButton
    select_work_requirement: QPushButton
    submit_work_requirement: QPushButton
    download_results: QPushButton
    clear_command_output: QPushButton
    copy_command_output: QPushButton
    delete_objects: QPushButton
    cancel_work_requirements: QPushButton
    cancel_work_requirements_and_abort: QPushButton
    select_worker_pool: QPushButton
    create_worker_pool: QPushButton
    shutdown_all_worker_pools: QPushButton
    terminate_all_compute_requirements: QPushButton
    view_results: QPushButton
    show_configuration: QPushButton
    show_wr: QPushButton
    show_wp: QPushButton
    deselect_files: QPushButton
    view_config_directory: QPushButton
    run_any_command: QPushButton
    next_command: QPushButton
    prev_command: QPushButton

    def __init__(
        self, config_file: str | None = None, disable_confirmations: bool = False
    ):
        super().__init__()
        self._confirmations_disabled = disable_confirmations

        # Dynamically loads the QT UI definition
        loadUi(join(_PKG_DIR, "commander.ui"), self)

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

        # Set up action connections
        self.select_config_file.clicked.connect(self._select_config_file_action)
        self.select_work_requirement.clicked.connect(
            self._select_work_requirement_action
        )
        self.submit_work_requirement.clicked.connect(
            self._submit_work_requirement_action
        )
        self.download_results.clicked.connect(self._download_results_action)
        self.clear_command_output.clicked.connect(self._clear_output_action)
        self.copy_command_output.clicked.connect(self._copy_output_action)
        self.delete_objects.clicked.connect(self._delete_objects_action)
        self.cancel_work_requirements.clicked.connect(
            self._cancel_work_requirements_action
        )
        self.cancel_work_requirements_and_abort.clicked.connect(
            self._cancel_work_requirements_and_abort_action
        )
        self.select_worker_pool.clicked.connect(self._select_worker_pool_action)
        self.create_worker_pool.clicked.connect(self._create_worker_pool_action)
        self.shutdown_all_worker_pools.clicked.connect(
            self._shutdown_all_worker_pools_action
        )
        self.terminate_all_compute_requirements.clicked.connect(
            self._terminate_all_compute_requirements_action
        )
        self.view_results.clicked.connect(self._view_results_action)
        self.show_configuration.clicked.connect(self._show_config_action)
        self.show_wr.clicked.connect(self._show_wr_action)
        self.show_wp.clicked.connect(self._show_wp_action)
        self.deselect_files.clicked.connect(self._deselect_files_action)
        self.view_config_directory.clicked.connect(self._view_config_directory_action)
        self.run_any_command.clicked.connect(self._run_any_command_action)

        self.next_command.clicked.connect(self._next_command_action)
        self.prev_command.clicked.connect(self._prev_command_action)

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

        # Handle specific key presses in text edit boxes
        for ui_object in [
            self.user_variables,
            self.wr_submit_options,
            self.wp_provision_options,
            self.any_command,
            self.namespace_override,
            self.tag_override,
            self.object_path_override,
        ]:
            ui_object.textChanged.connect(
                functools_partial(self._edit_box_keypress_handler, ui_object)
            )

        self._config_file: str | None = None
        self._wr_file: str | None = None
        self._wp_file: str | None = None
        self._skip_confirmations: set[str] = set()

        self._namespace: str | None = None
        self._tag: str | None = None
        self._config_parse_invalid = True

        # Watch the selected config file for on-disk changes
        self._file_watcher = QFileSystemWatcher(self)
        self._file_watcher.fileChanged.connect(self._on_config_file_changed)

        # Invalidate the config parse cache when inputs that affect it change
        for ui_object in [
            self.namespace_override,
            self.tag_override,
            self.user_variables,
        ]:
            ui_object.textChanged.connect(self._invalidate_config_parse)

        # Re-evaluate namespace/tag placeholders after a short delay when
        # user-defined variables change (debounced to avoid running yd-show
        # on every keystroke)
        self._user_vars_reparse_timer = QTimer(self)
        self._user_vars_reparse_timer.setSingleShot(True)
        self._user_vars_reparse_timer.setInterval(600)
        self._user_vars_reparse_timer.timeout.connect(self._reparse_placeholders)
        self.user_variables.textChanged.connect(self._user_vars_reparse_timer.start)

        # Defer config parse until after the window is shown, so the GUI is
        # visible before yd-show runs
        QTimer.singleShot(0, lambda: self._set_config_file(config_file))

        self._any_command_history = CommandHistory()
        self._active_process: QProcess | None = None
        self.stdin_input.textChanged.connect(
            functools_partial(self._edit_box_keypress_handler, self.stdin_input)
        )

    def _update_branding_icon(self, is_dark: bool):
        path = BRANDING_IMAGE_DARK if is_dark else BRANDING_IMAGE_LIGHT
        self.branding.setPixmap(
            QIcon(path).pixmap(QSize(BRANDING_IMAGE_SIZE, BRANDING_IMAGE_SIZE))
        )

    def _invalidate_config_parse(self):
        self._config_parse_invalid = True

    def _reparse_placeholders(self):
        if self._parse_yd_config(quiet=True):
            self._set_placeholders(self._namespace or "", self._tag or "")

    def _set_placeholders(self, namespace: str, tag: str):
        self.namespace_override.setPlaceholderText(namespace)
        cast(QWidget, self.namespace_override.viewport()).repaint()
        self.tag_override.setPlaceholderText(tag)
        cast(QWidget, self.tag_override.viewport()).repaint()
        default_prefix = f"{tag}*" if tag else ""
        self.object_path_override.setPlaceholderText(default_prefix)
        cast(QWidget, self.object_path_override.viewport()).repaint()

    def _parse_yd_config(self, quiet: bool = False) -> bool:
        """
        Parse the configuration file to obtain the CLI-processed values of the
        namespace and tag variables, used to populate placeholder text.
        """
        if not self._config_parse_invalid:
            return True

        yd_process = QProcess()
        event_loop = QEventLoop()

        env = QProcessEnvironment.systemEnvironment()
        yd_process.setProcessEnvironment(env)
        yd_process.setWorkingDirectory(self._working_dir())

        yd_process.finished.connect(event_loop.quit)
        yd_process.errorOccurred.connect(event_loop.quit)

        cmd = "yd-show"
        args = (
            self._config_source_args()
            + [
                "--nf",
                "-q",
                "-r",
                NAMESPACE,
                "-r",
                TAG,
            ]
            + self._namespace_tag_and_user_vars()
        )

        if not quiet:
            self._log(f"Discovering namespace/tag: '{cmd + ' ' + ' '.join(args)}'")
        yd_process.start(cmd, args)
        event_loop.exec()

        if yd_process.error() != QProcess.ProcessError.UnknownError:
            if not quiet:
                self._log(
                    f"Error parsing config with 'yd-show': {yd_process.errorString()}"
                )
            return False

        if yd_process.exitCode() != 0:
            if not quiet:
                error_output = yd_process.readAllStandardError().data().decode().strip()
                self._log(
                    f"Error parsing config with 'yd-show'"
                    f" (Exit {yd_process.exitCode()}): {error_output}"
                )
            return False

        output = yd_process.readAllStandardOutput().data().decode().strip()
        try:
            parsed_data = loads(output)
            self._namespace = parsed_data.get(NAMESPACE)
            self._tag = parsed_data.get(TAG)
        except Exception as e:
            self._log(f"Error reading config variables: {e}")
            return False

        self._config_parse_invalid = False
        return True

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
        self._config_parse_invalid = True
        self._log(f"Config file '{self._config_file}' changed on disk; refreshing...")
        if self._parse_yd_config(quiet=True):
            self._set_placeholders(self._namespace or "", self._tag or "")

    def _set_config_file(self, config_file: str | None):
        """
        Setting config_file to None will deselect the current config file.
        """
        # Stop watching the previously selected config file
        if self._config_file is not None:
            self._file_watcher.removePath(abspath(self._config_file))

        if config_file is None:
            self._config_file = None
            self.select_config_label.setText(
                f"{SELECTED_CONFIG_PREFIX}{NO_SELECTED_CONFIG}"
            )
            self._config_parse_invalid = True
            if self._parse_yd_config(quiet=True):
                self._set_placeholders(self._namespace or "", self._tag or "")
            else:
                self._set_placeholders("", "")
            return

        if not exists(config_file):
            self._log(f"Config file '{config_file}' does not exist")
            return

        self._config_file = relpath(config_file)
        self._config_parse_invalid = True
        self._log(f"Selected configuration file '{self._config_file}'")
        self.select_config_label.setText(f"{SELECTED_CONFIG_PREFIX}{self._config_file}")
        if self._parse_yd_config(quiet=True):
            self._set_placeholders(self._namespace or "", self._tag or "")
        self._file_watcher.addPath(abspath(cast(str, self._config_file)))

    def _select_config_file_action(self):
        file = self._select_file(
            caption="Please select a configuration file",
            directory=(self._config_dir() if self._config_file else CWD),
            file_pattern="*.toml",
        )
        if file is None:
            self._log(NO_SELECTED_CONFIG)
        else:
            self._set_config_file(file)

    def _check_config_file(self, quiet: bool = False) -> bool:
        if self._config_file is None:
            if not quiet:
                self._log(NO_SELECTED_CONFIG)
            return False
        return True

    def _config_dir(self) -> str:
        """
        Absolute path of the directory containing the selected config file.
        Callers must ensure a config file is selected (see _check_config_file).
        """
        return dirname(abspath(cast(str, self._config_file)))

    def _config_basename(self) -> str:
        """
        Base name of the selected config file.
        Callers must ensure a config file is selected (see _check_config_file).
        """
        return basename(cast(str, self._config_file))

    def _working_dir(self) -> str:
        """
        Directory to run commands in: the selected config file's directory if
        one is selected, otherwise the launch directory (cwd).
        """
        return self._config_dir() if self._config_file is not None else os.getcwd()

    def _config_source_args(self) -> list[str]:
        """
        CLI flags selecting the config source: the selected config file, or
        '--nc' (--no-config) to force environment-variable / CLI-argument mode.
        """
        return (
            ["-c", self._config_basename()]
            if self._config_file is not None
            else ["--nc"]
        )

    @staticmethod
    def _color_scheme() -> Qt.ColorScheme:
        return cast(QStyleHints, QApplication.styleHints()).colorScheme()

    def _select_work_requirement_action(self):
        directory = CWD if self._config_file is None else self._config_dir()
        file = self._select_file(
            caption="Please select a Work Requirement definition file",
            directory=directory,
            file_pattern="*.json *.jsonnet",
        )
        if file is None:
            self._log("No Work Requirement definition file selected")
        else:
            self._wr_file = relpath(file)
            self._log(f"Selected Work Requirement definition '{self._wr_file}'")

    def _select_worker_pool_action(self):
        directory = CWD if self._config_file is None else self._config_dir()
        file = self._select_file(
            caption="Please select a Worker Pool definition file",
            directory=directory,
            file_pattern="*.json *.jsonnet",
        )
        if file is None:
            self._log("No Worker Pool definition file selected")
        else:
            self._wp_file = relpath(file)
            self._log(f"Selected Worker Pool definition '{self._wp_file}'")

    def _submit_work_requirement_action(self):
        # Generate and run the command
        if self._wr_file is None:
            args = []
        else:
            args = ["-r", self._wr_file]
        dry_run = self.dry_run.isChecked()
        follow_progress = self.follow_progress.isChecked()
        if dry_run:
            args += ["-D"]
        if follow_progress and not dry_run:
            args += ["-f"]
        args += self.wr_submit_options.toPlainText().split()
        self._run_command_in_subprocess("yd-submit", args)

    def _prefix(self, pid: int | None = None) -> str:
        """
        Create a prefix the same as that used by the CLI.
        """
        if pid is None:
            pid = self._pid
        return f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({pid:06d}) : "

    def _object_path(self) -> str:
        override = self.object_path_override.toPlainText().strip()
        return override if override else f"{self._tag}*"

    def _scope_suffix(self) -> str:
        """
        A human-readable ' in namespace X with tag Y' suffix for confirmation
        messages, using the discovered namespace/tag. Returns a generic phrase
        when neither is known.
        """
        parts = []
        if self._namespace:
            parts.append(f"namespace '{self._namespace}'")
        if self._tag:
            parts.append(f"tag '{self._tag}'")
        if not parts:
            return " in the current namespace and tag"
        return " in " + " with ".join(parts)

    def _confirm_destructive(self, action_key: str, title: str, body: str) -> bool:
        """
        Show a warning confirmation dialog for a destructive action. Returns
        True if the action should proceed. 'Yes (Don't Ask Again)' confirms and
        suppresses future confirmations for this same action (identified by
        action_key) for the rest of the session; the suppression is per-action,
        not global.
        """
        if self._confirmations_disabled or action_key in self._skip_confirmations:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(body)
        no_btn = box.addButton("No", QMessageBox.ButtonRole.NoRole)
        yes_btn = box.addButton("Yes", QMessageBox.ButtonRole.YesRole)
        skip_btn = box.addButton(
            "Yes (Don't Ask Again)", QMessageBox.ButtonRole.YesRole
        )
        box.setDefaultButton(no_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is skip_btn:
            self._skip_confirmations.add(action_key)
            return True
        return clicked is yes_btn

    def _download_results_action(self):
        """
        Download matching objects from remote storage into the results directory.
        """
        dst = join(self._working_dir(), RESULTS_DIR)
        args = ["-d", dst, self._object_path()]
        if self.dry_run_objects.isChecked():
            args += ["-D"]
        self._run_command_in_subprocess("yd-download", args)

    def _delete_objects_action(self):
        """
        Delete matching objects from remote storage.
        """
        dry_run = self.dry_run_objects.isChecked()
        if not dry_run and not self._confirm_destructive(
            "delete",
            "Delete Objects",
            f"Delete objects matching '{self._object_path()}'?"
            "\n\nThis cannot be undone.",
        ):
            return
        args = ["-Ry", self._object_path()]
        if dry_run:
            args += ["-D"]
        self._run_command_in_subprocess("yd-delete", args)

    def _clear_output_action(self):
        self.log_output.setPlainText("")

    def _copy_output_action(self):
        cast(QClipboard, QApplication.clipboard()).setText(
            self.log_output.toPlainText()
        )

    def _cancel_work_requirements_action(self):
        if not self._confirm_destructive(
            "cancel",
            "Cancel Work Requirements",
            f"Cancel ALL work requirements{self._scope_suffix()}?"
            "\n\nThis cannot be undone.",
        ):
            return
        self._run_command_in_subprocess("yd-cancel", ["-y"])

    def _cancel_work_requirements_and_abort_action(self):
        if not self._confirm_destructive(
            "cancel_abort",
            "Cancel and Abort Work Requirements",
            f"Cancel ALL work requirements{self._scope_suffix()} and abort their"
            " running tasks?\n\nThis cannot be undone.",
        ):
            return
        self._run_command_in_subprocess("yd-cancel", ["-ay"])

    def _create_worker_pool_action(self):
        if self._wp_file is None:
            args = []
        else:
            args = ["-p", self._wp_file]
        if self.follow_worker_pool.isChecked():
            args += ["-af"]
        elif self.dry_run_worker_pool.isChecked():
            args += ["-D"]
        args += self.wp_provision_options.toPlainText().split()
        self._run_command_in_subprocess("yd-provision", args)

    def _shutdown_all_worker_pools_action(self):
        if not self._confirm_destructive(
            "shutdown",
            "Shut Down Worker Pools",
            f"Shut down ALL worker pools{self._scope_suffix()}?"
            "\n\nThis cannot be undone.",
        ):
            return
        self._run_command_in_subprocess("yd-shutdown", ["-y"])

    def _terminate_all_compute_requirements_action(self):
        if not self._confirm_destructive(
            "terminate",
            "Terminate Compute Requirements",
            f"Terminate ALL compute requirements{self._scope_suffix()}?"
            "\n\nThis cannot be undone.",
        ):
            return
        self._run_command_in_subprocess("yd-terminate", ["-y"])

    def _namespace_tag_and_user_vars(self) -> list[str]:
        # Split out a list of variables of the form "x=y",
        # and prefix each with "-v" -> ["-v', "x=y"], etc.
        # Apply a namespace override if it exists.
        # Apply a tag override if it exists.
        namespace_tag_user_vars = [
            x for y in self.user_variables.toPlainText().split() for x in ["-v", y]
        ]

        tag_override = self.tag_override.toPlainText().strip()
        if tag_override:
            namespace_tag_user_vars = [
                "-t",
                tag_override,
            ] + namespace_tag_user_vars

        namespace_override = self.namespace_override.toPlainText().strip()
        if namespace_override:
            namespace_tag_user_vars = [
                "-n",
                namespace_override,
            ] + namespace_tag_user_vars

        return namespace_tag_user_vars

    def _build_command_args(
        self, command: str, args: list[str], yd_command: bool
    ) -> list[str]:
        """
        Decorate a command's arguments for execution. For 'yd-' commands this
        injects the config source ('-c <file>' or '--nc'), the namespace / tag /
        user variables, and the '--nf'/'--pp' flags. Non-yd commands are
        returned unchanged.
        """
        if yd_command:
            return (
                self._config_source_args()
                + ["--nf", "--pp"]
                + self._namespace_tag_and_user_vars()
                + args
            )

        if command.startswith("yd-"):
            args = list(args)
            # Use the selected config source unless one is set explicitly
            # (or config use is explicitly disabled) on the command line.
            if not ({"-c", "--config", "--no-config", "--nc"} & set(args)):
                args = self._config_source_args() + args
            # Ensure user-defined variables can be overridden by commands
            # by specifying them first.
            for index, var in enumerate(self._namespace_tag_and_user_vars()):
                args.insert(index, var)
            args += ["--nf", "--pp"]

        return args

    def _run_command_in_subprocess(
        self,
        command: str,
        args: list[str],
        yd_command: bool = True,
        accept_stdin: bool = False,
    ):
        """
        Run a command in a subprocess, with adaptations for 'yd-'
        commands.
        """
        args = self._build_command_args(command, args, yd_command)

        process = QProcess(self)
        process_env: QProcessEnvironment = process.processEnvironment()

        if WINDOWS:
            # Windows non-console channels don't use utf-8 by default
            sys_env: list[str] = process.systemEnvironment()
            for env_var in sys_env:
                try:
                    name, value = env_var.split("=", 1)
                    process_env.insert(name, value)
                except ValueError:
                    pass
            process_env.insert("PYTHONIOENCODING", "utf-8")

        process.setProcessEnvironment(process_env)
        process.readyReadStandardOutput.connect(
            functools_partial(self._on_stdout, process)
        )
        process.readyReadStandardError.connect(
            functools_partial(self._on_stderr, process)
        )

        command_line_text = (command + " " + " ".join(args)).rstrip()
        self._log(
            f"Executing: '{command_line_text}' in directory '{self._working_dir()}'"
        )

        process.setWorkingDirectory(self._working_dir())
        process.start(command, args)
        process.waitForStarted()
        if process.error() != QProcess.ProcessError.UnknownError:
            self._log(f"Error running command: '{process.errorString()}'")
        else:
            if accept_stdin:
                self._active_process = process
                self.stdin_input.setEnabled(True)
                self.stdin_input.setPlaceholderText("Send input to process...")
                process.finished.connect(self._on_active_process_finished)

    def _on_active_process_finished(self):
        self._active_process = None
        self.stdin_input.setEnabled(False)
        self.stdin_input.setPlaceholderText("No command running")
        self.stdin_input.setPlainText("")

    def _send_stdin_action(self, text: str):
        if self._active_process is None:
            return
        pid = self._active_process.processId()
        self._active_process.write((text + "\n").encode())
        self._log(f"{self._prefix(pid)}<-- {text}", prefix=False)
        self.stdin_input.setPlainText("")

    def _view_results_action(self):
        self._open_file_viewer(join(self._working_dir(), RESULTS_DIR))

    def _view_config_directory_action(self):
        self._open_file_viewer(self._working_dir())

    def _open_file_viewer(self, directory: str):
        if not exists(directory):
            self._log(f"Directory '{directory}' does not (yet) exist")
            return
        if MACOS:
            os_system(f"open {quote(directory)}")
        elif LINUX:
            os_system(f"xdg-open {quote(directory)} &")
        elif WINDOWS:
            os_startfile(directory)

    def _show_config_action(self):
        if not self._check_config_file():
            return
        self._log(f"Displaying contents of '{self._config_file}':\n")
        with open(cast(str, self._config_file)) as f:
            self._log(f.read(), prefix=False)

    def _get_config_data_file(self, key: str) -> str | None:
        """
        Extract the value of workRequirementData or workerPoolData directly
        from the config TOML text, resolving template variable defaults and
        checking user_variables overrides.
        """
        if self._config_file is None or not exists(self._config_file):
            return None
        try:
            with open(self._config_file) as f:
                content = f.read()
        except OSError:
            return None

        m = re.search(rf"\b{key}\s*=\s*\"([^\"]*)\"", content)
        if not m:
            return None

        value = m.group(1)

        # Resolve template variables iteratively, innermost first, to support up
        # to three levels of nesting (e.g. {{file_{{xxx}}:={{def_file}}}}).
        # Each pass finds the deepest {{...}} with no further {{ inside it,
        # resolves that single variable via yd-show, and substitutes the result.
        for _ in range(3):
            if "{{" not in value:
                break
            inner = re.search(r"\{\{([^{}]+)}}", value)
            if not inner:
                break
            fragment = inner.group(1)
            var_name, default = (
                fragment.split(":=", 1) if ":=" in fragment else (fragment, "")
            )
            try:
                result = subprocess.run(
                    [
                        "yd-show",
                        "-c",
                        self._config_basename(),
                        "-q",
                        "-r",
                        var_name,
                    ]
                    + self._namespace_tag_and_user_vars(),
                    capture_output=True,
                    text=True,
                    check=True,
                    cwd=self._config_dir(),
                )
                resolved = loads(result.stdout.strip()).get(var_name)
                substitution = resolved if resolved is not None else default
            except Exception:
                substitution = default
            value = value[: inner.start()] + substitution + value[inner.end() :]

        if not value:
            return None

        return str(join(self._config_dir(), value))

    def _show_wr_action(self):
        path = self._wr_file or self._get_config_data_file(WR_DATA)
        if path is None:
            self._log("No Work Requirement definition file selected")
            return
        try:
            with open(path) as f:
                self._log(f"Displaying contents of '{path}':\n")
                self._log(f.read(), prefix=False)
        except OSError as e:
            self._log(f"Cannot open Work Requirement file '{path}': {e}")

    def _show_wp_action(self):
        path = self._wp_file or self._get_config_data_file(WP_DATA)
        if path is None:
            self._log("No Worker Pool definition file selected")
            return
        try:
            with open(path) as f:
                self._log(f"Displaying contents of '{path}':\n")
                self._log(f.read(), prefix=False)
        except OSError as e:
            self._log(f"Cannot open Worker Pool file '{path}': {e}")

    def _deselect_files_action(self):
        deselected_files = False
        if self._config_file is not None:
            self._set_config_file(None)
            self._log("Deselected configuration file")
            deselected_files = True

        if self._wr_file is not None:
            self._wr_file = None
            self._log("Deselected Work Requirement definition file")
            deselected_files = True

        if self._wp_file is not None:
            self._wp_file = None
            self._log("Deselected Worker Pool definition file")
            deselected_files = True

        if not deselected_files:
            self._log("No configuration or definition files to deselect")

    def _on_stdout(self, process: QProcess):
        text = process.readAllStandardOutput().data().decode("utf-8").rstrip()
        self._log(text, prefix=False)

    def _on_stderr(self, process: QProcess):
        text = process.readAllStandardError().data().decode("utf-8").rstrip()
        self._log(text, prefix=False)

    def _log(self, output: str, prefix: bool = True):
        self.log_output.appendPlainText(f"{self._prefix() if prefix else ''}{output}")

    def _follow_progress_set(self, checked_state: Qt.CheckState):
        if self.dry_run.isChecked() and checked_state == Qt.CheckState.Checked:
            # Uncheck the dry run flag and ensure the follow flag is checked
            self.dry_run.setChecked(False)
            self.follow_progress.setChecked(True)

    def _dry_run_set(self, _checked_state: Qt.CheckState):
        if self.follow_progress.isChecked():
            self.follow_progress.setChecked(False)

    def _follow_worker_pool_set(self, checked_state: Qt.CheckState):
        if (
            self.dry_run_worker_pool.isChecked()
            and checked_state == Qt.CheckState.Checked
        ):
            # Uncheck the dry run flag and ensure the follow flag is checked
            self.dry_run_worker_pool.setChecked(False)
            self.follow_worker_pool.setChecked(True)

    def _dry_run_worker_pool_set(self, _checked_state: Qt.CheckState):
        if self.follow_worker_pool.isChecked():
            self.follow_worker_pool.setChecked(False)

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
                "#line_3, #line_4, #line_6 {"
                " background-color: #555555; border: none; max-height: 2px; }"
                " #line_5 { background-color: #555555; border: none; max-width: 2px; }"
            )
        else:
            self.setStyleSheet("")
        self._update_branding_icon(is_dark)

    def _run_any_command_action(self):
        self._run_any_command_core(self.any_command.toPlainText())

    def _run_any_command_core(self, command_text: str):
        command_and_args = command_text.split()
        if len(command_and_args) == 0:
            self._log("No command to run")
            return
        self._any_command_history.save_command(command_text)
        if (
            command_and_args[0].startswith("yd-")
            and command_and_args[0] != "yd-version"
        ):
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
            shell, flag = ("cmd", "/c") if WINDOWS else ("sh", "-c")
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

    def _select_file(
        self,
        caption: str = "",
        directory: str = ".",
        file_pattern: str = "*",
    ) -> str | None:
        options: QFileDialog.Option = QFileDialog.Option.ReadOnly
        options |= QFileDialog.Option.DontUseNativeDialog
        file_name = QFileDialog.getOpenFileName(
            self,
            caption=caption,
            directory=directory,
            filter=file_pattern,
            options=options,
        )
        return None if file_name[0] == "" else file_name[0]


def run_app(config_file: str | None = None, disable_confirmations: bool = False):
    try:
        if WINDOWS:
            # noinspection PyUnresolvedReferences
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
                "yellowdog.commander"
            )
        app = QApplication(sys.argv)
        icon = QIcon(ICON_IMAGE)
        app.setWindowIcon(icon)
        win = YellowDogApp(config_file, disable_confirmations)
        win.setWindowIcon(icon)

        cast(QLayout, win.layout()).activate()
        win.setMinimumHeight(win.minimumSizeHint().height())
        win.setMinimumWidth(win.minimumSizeHint().width())
        win.resize(win.minimumWidth(), win.minimumHeight())

        win.show()
        sys.exit(app.exec())

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run_app()
