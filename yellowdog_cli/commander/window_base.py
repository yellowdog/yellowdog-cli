"""
The base of YellowDogApp's class hierarchy (see commander.py).
"""

import os
from os.path import abspath, basename, dirname, exists
from typing import cast

from PyQt6.QtCore import (
    QEventLoop,
    QProcess,
    Qt,
)
from PyQt6.QtGui import (
    QFont,
    QFontMetrics,
    QStyleHints,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
)

from yellowdog_cli._version import __version__
from yellowdog_cli.commander.arguments import QuotingError, split_arguments
from yellowdog_cli.commander.config_discovery import ConfigDiscovery
from yellowdog_cli.commander.elision import elide_middle
from yellowdog_cli.commander.file_dialogs import FileDialogs
from yellowdog_cli.commander.output_pane import OutputPane
from yellowdog_cli.commander.selection import path_would_be_globbed
from yellowdog_cli.utils.command_registry import (
    COMMANDS,
    NAMESPACE,
    PROPERTY,
    TAG,
    VARIABLE,
    CommandKind,
)

# The 'yd-' commands that take none of the configuration options Commander adds
# to the others (the config source, namespace, tag, variables, properties,
# '--pp'), so a typed one is run as it was typed, bar '--nf' (below)
UNDECORATED_YD_COMMANDS = frozenset(
    name for name, command in COMMANDS.items() if command.kind is CommandKind.STANDALONE
)
# Those of them that take '--nf', which Commander adds as it does to the rest,
# since the output window shows no colour. Kept by hand because three of them
# parse their own arguments outside the registry; a test holds it to each
# command's '--help'
NO_FORMAT_UNDECORATED_YD_COMMANDS = frozenset(
    {"yd-help", "yd-jsonnet2json", "yd-schema", "yd-version"}
)
NO_FORMAT_FLAGS = ("--nf", "--no-format")
BUTTON_TEXT_MARGIN = 24  # px of button padding to keep clear of the label
MAX_LOGGED_ENTITY_IDS = 3  # above this, the echoed command line shows a count
WINDOW_TITLE = f"YellowDog CLI Commander (v{__version__})"
CWD = os.getcwd()  # default dir for file dialogs when no config selected
# Shown when an action that lists entities with 'yd-list' has no tag to list
# them by. 'yd-list' defaults its tag to '' (every entity in the namespace), so
# the tag must be passed explicitly, and without one the listing would offer
# entities from outside the scope the dialog names.
NO_LISTING_TAG = (
    "No tag: none has been discovered, so there is no default scope to list."
    " Enter a Tag or a Name pattern, or select a configuration file to discover"
    " one from (reselect it if discovery has already failed)."
)


class WindowBase(QMainWindow):
    """
    The window's foundation: the widgets commander.ui provides and the state
    the window sets up, declared for the layers built on it; the configuration
    file's directory and source arguments; the options every 'yd-*' command is
    given (namespace, tag, variables, properties); the listing scope; and the
    action buttons' enabling.
    """

    # Widgets populated at runtime by loadUi("commander.ui"); declared here so
    # static type checkers can resolve their attribute references.
    branding: QLabel
    select_config_label: QLabel
    wr_options_label: QLabel
    wp_options_label: QLabel
    object_path_label: QLabel
    user_variables_label: QLabel
    properties_label: QLabel

    log_output: QPlainTextEdit
    output_filter_bar: QFrame
    output_filter_label: QLabel
    user_variables: QPlainTextEdit
    properties: QPlainTextEdit
    wr_submit_options: QPlainTextEdit
    wp_provision_options: QPlainTextEdit
    any_command: QPlainTextEdit
    namespace_override: QPlainTextEdit
    tag_override: QPlainTextEdit
    name_glob_override: QPlainTextEdit
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
    add_to_work_requirement: QPushButton
    download_results: QPushButton
    clear_command_output: QPushButton
    copy_command_output: QPushButton
    save_command_output: QPushButton
    output_filter_show_all: QPushButton
    delete_objects: QPushButton
    cancel_work_requirements: QPushButton
    cancel_work_requirements_and_abort: QPushButton
    select_worker_pool: QPushButton
    create_worker_pool: QPushButton
    resize_worker_pool: QPushButton
    shutdown_all_worker_pools: QPushButton
    terminate_all_compute_requirements: QPushButton
    browse_results_directory: QPushButton
    show_config: QPushButton
    show_wr_json: QPushButton
    show_wp_json: QPushButton
    deselect_files: QPushButton
    browse_config_directory: QPushButton
    run_any_command: QPushButton
    next_command: QPushButton
    prev_command: QPushButton
    show_help: QPushButton

    # Set up by the window's __init__ (commander.py)
    _confirmations_disabled: bool
    _font: QFont
    _file_dialogs: FileDialogs
    _output: OutputPane
    _config_file: str | None
    _wr_file: str | None
    _wp_file: str | None
    _skip_confirmations: set[str]
    _select_wr_default_text: str
    _select_wp_default_text: str
    _select_wr_default_tooltip: str
    _select_wp_default_tooltip: str
    _discovery: ConfigDiscovery
    _active_process: QProcess | None
    _active_run: int  # the output run ID of _active_process
    _processes: list[QProcess]
    _helper_processes: list[QProcess]
    _nested_loops: list[QEventLoop]
    _shutting_down: bool
    _nested_depth: int

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

    def _show_selection_on_button(
        self,
        button: QPushButton,
        prefix: str,
        default_text: str,
        default_tooltip: str,
        file: str | None,
    ):
        """
        Indicate the selected definition file on its own 'Select' button, so
        that the selection is visible without adding a widget to the left-hand
        column. The filename is elided to fit the button's current width, so a
        long name never widens the column; the full path becomes the tooltip.
        Passing file=None restores the button's original label and tooltip.
        """
        if file is None:
            button.setText(default_text)
            button.setToolTip(default_tooltip)
            return

        name = basename(file)
        metrics = QFontMetrics(button.font())
        available = (
            button.width() - BUTTON_TEXT_MARGIN - metrics.horizontalAdvance(prefix)
        )
        if available > 0:
            name = metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, available)
        else:  # not yet laid out, so fall back to a character cap
            name = elide_middle(name)
        button.setText(f"{prefix}{name}")
        button.setToolTip(abspath(file))

    def _scope_phrase(self, match_word: str) -> str:
        """
        A human-readable ' in namespace X with <match_word> including Y' phrase
        describing how the CLI selects entities: Work Requirements and Compute
        Requirements are matched by tag ('tags'), Worker Pools by name ('names').
        Uses the discovered namespace/tag, degrading gracefully when unknown.
        """
        if self._discovery.namespace and self._discovery.tag:
            return (
                f" in namespace '{self._discovery.namespace}'"
                f" with {match_word} including '{self._discovery.tag}'"
            )
        if self._discovery.namespace:
            return f" in namespace '{self._discovery.namespace}'"
        if self._discovery.tag:
            return f" with {match_word} including '{self._discovery.tag}'"
        return " in the current namespace and tag"

    def _yd_list_scope_args(self, name_args: list[str]) -> list[str] | None:
        """
        The 'yd-list' arguments that confine a listing to the scope the other
        actions use: the Name pattern as '--name' when one is set, else the tag
        as '-t' — the Tag field's, or the discovered one. None when there is
        neither, since 'yd-list' defaults its tag to '' and would list every
        entity in the namespace; callers must refuse, with NO_LISTING_TAG.

        The tag has to be passed even when the configuration file names one,
        because that default is 'yd-list''s own: the configuration's tag
        reaches every other command and not this one.
        """
        if name_args:
            return ["--name", name_args[0]]
        tag = self.tag_override.toPlainText().strip() or self._discovery.tag
        return ["-t", tag] if tag else None

    def _listing_scope(self, match_word: str, name_args: list[str]) -> str:
        """
        The scope phrase for an action that lists entities: the Name pattern
        when one is set, since entities are then selected by that glob rather
        than by tag or name substring, and otherwise _scope_phrase().
        """
        if not name_args:
            return self._scope_phrase(match_word)
        scope = f" matching name pattern '{name_args[0]}'"
        if self._discovery.namespace:
            scope = f" in namespace '{self._discovery.namespace}'{scope}"
        return scope

    def _action_buttons(self) -> tuple[QPushButton, ...]:
        """
        The buttons whose actions enumerate before acting, and so must not be
        startable while an enumeration is already blocking in a nested event
        loop. Submit and provision are absent deliberately: they launch a command
        and return, without a nested loop or a pre-flight listing to be confused.
        Add to and Resize are here, although neither destroys anything, because
        each lists its targets first.

        All eight grey together, including ones unrelated to the action in flight.
        That is deliberately conservative rather than strictly required — the
        demonstrable failure is one action re-entering itself, where the inner
        dialog's 'Don't Ask Again' makes the outer call return an empty selection.
        Overlapping *different* actions has no such failure, but it interleaves two
        listings in the one output window and stacks two modal confirmations in an
        order unrelated to the clicks, which is a poor property for irreversible
        operations. One rule also stays correct as actions are added. The block
        lasts one subprocess, so the cost is a second or two, visibly greyed.
        """
        return (
            self.add_to_work_requirement,
            self.cancel_work_requirements,
            self.cancel_work_requirements_and_abort,
            self.resize_worker_pool,
            self.shutdown_all_worker_pools,
            self.terminate_all_compute_requirements,
            self.download_results,
            self.delete_objects,
        )

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        """
        Grey the enumerating actions out, or restore them. Safe to restore
        unconditionally because nothing else ever disables these buttons.
        """
        for button in self._action_buttons():
            button.setEnabled(enabled)

    def _operation_in_flight(self, action: str) -> bool:
        """
        Whether a nested event loop is already blocking, in which case 'action'
        must not start. Logs when it refuses, so a click that lands anyway — a
        queued one, or a keyboard activation — does not look as though it was
        simply ignored.

        The check belongs at the top of each action, not inside the enumeration:
        a re-entrant enumeration that returned None would be read as 'enumeration
        failed', which for the destructive actions means falling back to acting
        over the whole scope. Refusing early is the only safe answer.
        """
        if self._nested_depth == 0:
            return False
        self._output.log(f"Another operation is still in progress; ignoring {action}")
        return True

    def _handles_are_safe_to_target(
        self, handles: list[str], verb: str, past_participle: str
    ) -> bool:
        """
        Whether every selected object path can be named literally on a yd-*
        command line. False — with the offending names logged — when any contains
        a glob metacharacter or a '{{' substitution placeholder.

        Both would be expanded before the absolute-path check ever sees them, so
        the command would act on whatever they matched or resolved to rather than
        on the object the user ticked. The whole run is refused rather than the
        offending handles dropped: acting on part of a confirmed selection leaves
        the user believing it all happened. 'verb'/'past_participle' shape the
        message, e.g. 'delete'/'removed' or 'download'/'downloaded'.
        """
        unsafe = [
            handle
            for handle in handles
            if path_would_be_globbed(handle) or "{{" in handle
        ]
        if not unsafe:
            return True

        self._output.log(
            f"Cannot {verb} by path — these names contain wildcard characters"
            " ('*', '?', '[') or a '{{' substitution placeholder:"
            f" {', '.join(unsafe)}."
            f" Deselect them to {verb} the rest; these objects can only be"
            f" {past_participle} with rclone directly."
        )
        return False

    def _name_glob_args(self) -> list[str]:
        """
        The Name-pattern field's value as a positional glob argument for the
        destructive commands, or [] when the field is empty. It applies to
        whichever destructive action is invoked and is NOT a global
        namespace/tag override, so it is appended per-action rather than via
        '_namespace_tag_and_user_vars'.
        """
        value = self.name_glob_override.toPlainText().strip()
        return [value] if value else []

    def _abbreviated_run_args(
        self, run_args: list[str], handles: list[str], plural: str
    ) -> list[str] | None:
        """
        A display form of the run arguments for the output window: above
        MAX_LOGGED_ENTITY_IDS selected items, the handles collapse to a count so
        the echoed command line stays readable. None means 'echo the real
        arguments'. Nothing is lost by abbreviating — the dialog has just listed
        the selected items by name, and the command reports each one as it acts
        on it. 'plural' is the entity noun, e.g. 'Work Requirements'.
        """
        if len(handles) <= MAX_LOGGED_ENTITY_IDS:
            return None
        return [*run_args, f"<{len(handles)} {plural}>"]

    def _namespace_tag_and_user_vars(self, command: str | None = None) -> list[str]:
        """
        The arguments every 'yd-' command is given from the top of the window:
        '-n' and '-t' from the Namespace and Tag fields, '-v' for each user
        variable and '--property' for each property override. Given the
        'command', only those it takes: typed into the command box, a
        command without '-n' (yd-show) failed on it, and one without '-v'
        (yd-cloud-info) read the namespace as its own positional.

        Each property is passed joined to its flag, '--property=section.key=value',
        so a value that begins with '-' is never taken for an option. Raises
        QuotingError when the Properties field cannot be split, which every
        action refuses on beforehand (_properties_are_usable).
        """
        registered = None if command is None else COMMANDS.get(command)

        def takes(option) -> bool:
            # A command the registry does not know is given everything
            return registered is None or registered.has(option)

        # Split out a list of variables of the form "x=y",
        # and prefix each with "-v" -> ["-v', "x=y"], etc.
        # Apply a namespace override if it exists.
        # Apply a tag override if it exists.
        namespace_tag_user_vars = [
            x
            for y in self.user_variables.toPlainText().split()
            for x in ["-v", y]
            if takes(VARIABLE)
        ] + [
            f"--property={override}"
            for override in split_arguments(self.properties.toPlainText())
            if takes(PROPERTY)
        ]

        tag_override = self.tag_override.toPlainText().strip()
        if tag_override and takes(TAG):
            namespace_tag_user_vars = ["-t", tag_override, *namespace_tag_user_vars]

        namespace_override = self.namespace_override.toPlainText().strip()
        if namespace_override and takes(NAMESPACE):
            namespace_tag_user_vars = [
                "-n",
                namespace_override,
                *namespace_tag_user_vars,
            ]

        return namespace_tag_user_vars

    def _split_field(self, field: QPlainTextEdit, name: str) -> list[str] | None:
        """
        A field's contents as arguments, split as a shell would split them (see
        arguments.py), so that a value containing spaces can be quoted. None,
        having said why, when its quotes do not balance.
        """
        return self._split_text(field.toPlainText(), name)

    def _split_text(self, text: str, name: str) -> list[str] | None:
        """
        _split_field() for text already read from the field called 'name'.
        """
        try:
            return split_arguments(text)
        except QuotingError as error:
            self._output.log(f"Cannot use the {name} field: {error}")
            return None

    def _properties_are_usable(self) -> bool:
        """
        Whether the Properties field can be split into arguments. Every action
        that runs a 'yd-' command asks first, and refuses when it cannot: the
        overrides are part of every such command line, so there is nothing to
        run without them, and a listing attempted without them would fail and
        read as 'the listing failed' rather than as the quoting mistake it is.
        """
        return self._split_field(self.properties, "Properties") is not None

    def _build_command_args(
        self, command: str, args: list[str], yd_command: bool
    ) -> list[str]:
        """
        Decorate a command's arguments for execution. For 'yd-' commands this
        injects the config source ('-c <file>' or '--nc'), the namespace / tag /
        user variables, and the '--nf'/'--pp' flags. Non-yd commands are
        returned unchanged, and the standalone ones in UNDECORATED_YD_COMMANDS
        given only '--nf', where they take it and it was not typed.
        """
        if yd_command:
            return [
                *self._config_source_args(),
                "--nf",
                "--pp",
                *self._namespace_tag_and_user_vars(),
                *args,
            ]

        if command.startswith("yd-") and command not in UNDECORATED_YD_COMMANDS:
            args = list(args)
            # Use the selected config source unless one is set explicitly
            # (or config use is explicitly disabled) on the command line.
            if not ({"-c", "--config", "--no-config", "--nc"} & set(args)):
                args = self._config_source_args() + args
            # Ensure user-defined variables can be overridden by commands
            # by specifying them first.
            for index, var in enumerate(self._namespace_tag_and_user_vars(command)):
                args.insert(index, var)
            args += ["--nf", "--pp"]
        elif command in NO_FORMAT_UNDECORATED_YD_COMMANDS and not (
            set(NO_FORMAT_FLAGS) & set(args)
        ):
            args = [*args, "--nf"]

        return args

    def _open_file_viewer(self, directory: str):
        """
        Browse a directory using Qt's own file dialog rather than the platform's
        file viewer, so the listing looks and behaves like the file selectors
        elsewhere in the window. A chosen file is handed to the platform's
        default application for its type; dismissing the dialog does nothing.
        """
        if not exists(directory):
            self._output.log(f"Directory '{directory}' does not (yet) exist")
            return
        file_name = self._file_dialogs.browse(f"Browse '{directory}'", directory)
        if file_name is not None:
            self._file_dialogs.open_with_default_application(file_name)
