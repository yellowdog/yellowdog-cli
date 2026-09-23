"""
Namespace and tag discovery (ConfigDiscovery): running 'yd-variables' against the
current configuration source, overrides and user variables to learn what the
CLI will resolve them to, and showing the result as the placeholders of the
Namespace, Tag and Path fields. Every failure is reported, bar the one that
means nothing is configured yet; a timed-out discovery is retried once; and an
edit to the user variables reparses after a pause, once every variable in the
box is complete.
"""

from collections.abc import Callable
from json import loads
from typing import cast

from PyQt6.QtCore import QEventLoop, QObject, QProcess, QProcessEnvironment, QTimer
from PyQt6.QtWidgets import QPlainTextEdit, QWidget

from yellowdog_cli.commander.startup import variable_is_complete
from yellowdog_cli.utils.settings import MISSING_CONFIG_DATA

CONFIG_PARSE_TIMEOUT_MS = 10_000  # 'yd-variables' can block on an unreachable API URL
# The one retry after a timeout gets a longer budget: by then it is known that a
# 'yd-variables' here is slow rather than hung, and on Windows the first 'yd-*' of a
# session can legitimately need this long to start (interpreter start, SDK
# imports, a virus scan of a freshly installed console script).
CONFIG_PARSE_RETRY_TIMEOUT_MS = 30_000
CONFIG_PARSE_RETRY_DELAY_MS = 1_000  # let the event loop breathe before retrying
NAMESPACE = "namespace"
TAG = "tag"


class ConfigDiscovery:
    """
    Owns what discovery found (namespace and tag, None until found), whether it
    is stale, and the one retry a timeout earns. The window reads 'namespace'
    and 'tag', and tells it when the configuration file changes (invalidate,
    reparse_placeholders, clear); an edit to the fields it is given it notices
    itself.

    Given the window's methods as callables rather than the window, so what it
    depends on is the list below: whether a configuration file is selected, the
    arguments naming the config source and the overrides, the directory to run
    in, the nested-loop runner, whether Commander is shutting down, and the
    output window to report to.
    """

    def __init__(
        self,
        *,
        parent: QObject,
        namespace_field: QPlainTextEdit,
        tag_field: QPlainTextEdit,
        object_path_field: QPlainTextEdit,
        user_variables: QPlainTextEdit,
        config_selected: Callable[[], bool],
        config_source_args: Callable[[], list[str]],
        override_args: Callable[[], list[str]],
        working_dir: Callable[[], str],
        run_nested: Callable[..., bool],
        shutting_down: Callable[[], bool],
        log: Callable[[str], None],
    ):
        self._namespace_field = namespace_field
        self._tag_field = tag_field
        self._object_path_field = object_path_field
        self._user_variables = user_variables
        self._config_selected = config_selected
        self._config_source_args = config_source_args
        self._override_args = override_args
        self._working_dir = working_dir
        self._run_nested = run_nested
        self._shutting_down = shutting_down
        self._log = log

        self.namespace: str | None = None
        self.tag: str | None = None
        self._config_parse_invalid = True  # nothing discovered yet
        self._config_parse_timed_out = False
        self._config_parse_retried = False
        self._last_discovery_failure: str | None = None

        # One retry of namespace/tag discovery, a moment after a timeout. Timers
        # here are parented to the window so they die with it; a bare
        # QTimer.singleShot would fire into destroyed widgets.
        self._discovery_retry_timer = QTimer(parent)
        self._discovery_retry_timer.setSingleShot(True)
        self._discovery_retry_timer.timeout.connect(self._retry_discovery)

        # Invalidate the config parse cache when inputs that affect it change
        for ui_object in [namespace_field, tag_field, user_variables]:
            ui_object.textChanged.connect(self.invalidate)

        # Re-evaluate namespace/tag placeholders after a short delay when
        # user-defined variables change (debounced to avoid running yd-variables
        # on every keystroke)
        self._user_vars_reparse_timer = QTimer(parent)
        self._user_vars_reparse_timer.setSingleShot(True)
        self._user_vars_reparse_timer.setInterval(600)
        self._user_vars_reparse_timer.timeout.connect(
            self._reparse_placeholders_after_edit
        )
        user_variables.textChanged.connect(self._user_vars_reparse_timer.start)

    def clear(self):
        """
        Forget what was discovered, for a configuration file deselected: cleared
        first, then filled in again by whatever discovery finds without one
        (environment variables, or nothing at all), so the previous file's
        namespace and tag cannot linger either way. The values are cleared as
        well as the placeholders showing them, because the window builds the
        default download and delete path out of the tag, so a stale one is a
        path acted on.
        """
        self.invalidate()
        self.namespace = None
        self.tag = None
        self._set_placeholders("", "")

    def invalidate(self):
        """
        Mark the discovered namespace/tag stale, and give the next discovery a
        fresh retry. The retry budget is per parse, not per session: a new
        configuration file must not inherit the exhausted budget of the last one.

        The same goes for what _report_discovery_failure will say next. It
        suppresses a repeat of the message it said last, for the user-variables
        box that reparses after every edit — but a configuration file being
        deselected and selected again is not a repeat, and a failure suppressed
        in between (see _nothing_is_configured) would otherwise leave the last
        message said no longer the last failure there was. Only the three
        configuration-file paths reach here; an edit to the user variables does
        not, which is what keeps that suppression doing its job.
        """
        self._config_parse_invalid = True
        self._config_parse_retried = False
        self._last_discovery_failure = None

    def reparse_placeholders(self, timeout_ms: int | None = None):
        """
        Re-run discovery and show what it found, scheduling one retry if it timed
        out. The single place that pairs a parse with the placeholders, so a
        caller cannot get the retry by accident and lose it by accident.
        """
        if self._parse_yd_config(quiet=True, timeout_ms=timeout_ms):
            self._set_placeholders(self.namespace or "", self.tag or "")
            return
        self._schedule_discovery_retry()

    def _reparse_placeholders_after_edit(self):
        """
        The debounced reparse behind an edit to the user-variables box.

        Held back while any variable in the box is not yet 'name=value'. Every
        variable is typed through states that are not — 'instances' on the way
        to 'instances=3' — and 'yd-variables' rejects one and exits 1, so the reparse
        landing on such a keystroke reported "Error in variable substitution
        'instances'" against a mistake the user had not made. Nothing is said
        about it, because at 600ms after a keystroke there is nothing to say: an
        unfinished variable and a wrong one are the same text. The parse stays
        marked invalid, so the edit that completes the variable reparses as
        usual.

        Only this path is held back. A malformed variable still reaches the CLI
        when the user runs a command, which is where it is a real error rather
        than an unfinished one, and where they are there to read it.
        """
        if all(
            variable_is_complete(variable)
            for variable in self._user_variables.toPlainText().split()
        ):
            self.reparse_placeholders()

    def _schedule_discovery_retry(self):
        """
        Queue the one retry allowed after a timed-out discovery.

        Only after a *timeout*: a non-zero exit or a program that cannot be
        started will fail again the same way, so retrying would only be noise. A
        timeout is different — the incident this exists for was a first 'yd-variables'
        on Windows that needed longer than its budget to start, where the second
        one is warm and finishes at once. Before this, the placeholders stayed
        blank until Commander was restarted, which is what the user had to do.
        """
        if (
            self._shutting_down()
            or self._config_parse_retried
            or not self._config_parse_timed_out
        ):
            return
        self._config_parse_retried = True
        self._log(
            f"Retrying namespace/tag discovery with a"
            f" {CONFIG_PARSE_RETRY_TIMEOUT_MS // 1000}s timeout; the first"
            f" 'yd-*' command of a session can be slow to start"
        )
        self._discovery_retry_timer.start(CONFIG_PARSE_RETRY_DELAY_MS)

    def _retry_discovery(self):
        self.reparse_placeholders(timeout_ms=CONFIG_PARSE_RETRY_TIMEOUT_MS)

    def _report_discovery_failure(self, message: str):
        """
        Say why namespace/tag discovery failed. Logged however quiet the parse
        was: blank placeholders with nothing in the output window to explain them
        is what left a Windows incident with no evidence to diagnose.

        Consecutive identical messages are suppressed, because the user-variables
        box reparses 600ms after every edit and a broken configuration would
        otherwise fill the window with one line over and over. A success clears
        the memory, so the same failure recurring is reported again.
        """
        if message == self._last_discovery_failure:
            return
        self._last_discovery_failure = message
        self._log(message)

    def _set_placeholders(self, namespace: str, tag: str):
        """
        Update the placeholder text showing the namespace, tag and object path
        that will be used if those fields are left blank.

        The viewport repaints are scheduled with update() rather than forced
        with repaint(): callers reach this immediately after _parse_yd_config
        has run a nested event loop, and forcing a synchronous paint of a text
        widget from there is what appears to make macOS log bursts of
        'TSMSendMessageToUIServer ... FAILED(-1)'. Control returns to the event
        loop directly afterwards, so the placeholders still appear at once.
        It has to be the viewport, not the widget: QPlainTextEdit is a scroll
        area, and the placeholder text is painted by its viewport.
        """
        self._namespace_field.setPlaceholderText(namespace)
        cast(QWidget, self._namespace_field.viewport()).update()
        self._tag_field.setPlaceholderText(tag)
        cast(QWidget, self._tag_field.viewport()).update()
        default_prefix = f"{tag}*" if tag else ""
        self._object_path_field.setPlaceholderText(default_prefix)
        cast(QWidget, self._object_path_field.viewport()).update()

    def _yd_variables_command(self) -> tuple[str, list[str]]:
        """
        The 'yd-variables' invocation that resolves the namespace and tag for the
        current configuration source, namespace/tag overrides and user variables.
        """
        return "yd-variables", [
            *self._config_source_args(),
            "--nf",
            NAMESPACE,
            TAG,
            *self._override_args(),
        ]

    def _nothing_is_configured(self, error_output: str) -> bool:
        """
        Whether a failed discovery means 'nothing is configured yet' rather than
        'something is wrong', in which case it is not reported.

        Only with no configuration file selected. 'yd-variables' is then given
        '--nc' and has nothing but the environment to work from, and an environment
        with no YellowDog credentials in it makes it exit 1 with "Missing
        configuration data: 'key'" before it can resolve anything. Reported, that
        put an error in the output window at startup, and again on every
        Deselect, in front of a user who had done nothing wrong.

        Deliberately narrow in both directions. With a configuration file
        selected the same message means the selected file cannot be used, which
        is the user's to see. And with none selected every *other* failure is
        still reported, because discovery from the environment alone is a
        supported way to run Commander — credentials and namespace/tag in YD_*
        variables, with the definition files nominated by hand — and its
        failures are as worth seeing as any other.

        Matched on the message, the CLI having one exit code for everything.
        MISSING_CONFIG_DATA is the CLI's own definition of it, imported rather
        than written out again here, so the two cannot drift apart silently.
        """
        return not self._config_selected() and MISSING_CONFIG_DATA in error_output

    def _parse_yd_config(
        self, quiet: bool = False, timeout_ms: int | None = None
    ) -> bool:
        """
        Parse the configuration file to obtain the CLI-processed values of the
        namespace and tag variables, used to populate placeholder text.

        'timeout_ms' defaults to CONFIG_PARSE_TIMEOUT_MS; the retry after a
        timeout passes a longer one. Every failure is reported through
        _report_discovery_failure, whatever 'quiet' says — 'quiet' suppresses the
        announcement of a routine reparse, not the reason one failed. The one
        exception is _nothing_is_configured() above.
        """
        if not self._config_parse_invalid:
            return True
        if timeout_ms is None:
            timeout_ms = CONFIG_PARSE_TIMEOUT_MS
        self._config_parse_timed_out = False

        yd_process = QProcess()
        event_loop = QEventLoop()

        env = QProcessEnvironment.systemEnvironment()
        yd_process.setProcessEnvironment(env)
        yd_process.setWorkingDirectory(self._working_dir())

        yd_process.finished.connect(event_loop.quit)
        yd_process.errorOccurred.connect(event_loop.quit)

        cmd, args = self._yd_variables_command()

        if not quiet:
            self._log(f"Discovering namespace/tag: '{cmd + ' ' + ' '.join(args)}'")
        yd_process.start(cmd, args)
        if not self._run_nested(yd_process, event_loop, timeout_ms):
            if self._shutting_down():
                return False  # the widgets are going away; don't touch them
            self._config_parse_timed_out = True
            self._report_discovery_failure(
                f"Timed out after {timeout_ms // 1000}s parsing"
                f" configuration with 'yd-variables'"
            )
            return False

        if yd_process.error() != QProcess.ProcessError.UnknownError:
            self._report_discovery_failure(
                f"Error parsing config with 'yd-variables': {yd_process.errorString()}"
            )
            return False

        if yd_process.exitCode() != 0:
            error_output = yd_process.readAllStandardError().data().decode().strip()
            if self._nothing_is_configured(error_output):
                return False
            self._report_discovery_failure(
                f"Error parsing config with 'yd-variables'"
                f" (Exit {yd_process.exitCode()}): {error_output}"
            )
            return False

        output = yd_process.readAllStandardOutput().data().decode().strip()
        try:
            parsed_data = loads(output)
            self.namespace = parsed_data.get(NAMESPACE)
            self.tag = parsed_data.get(TAG)
        except Exception as e:
            self._report_discovery_failure(f"Error reading config variables: {e}")
            return False

        self._config_parse_invalid = False
        self._last_discovery_failure = None  # a recurrence is worth reporting again
        return True
