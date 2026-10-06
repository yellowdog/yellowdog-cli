"""
Running commands for YellowDogApp (see commander.py).
"""

from functools import partial as functools_partial
from json import loads

from PyQt6.QtCore import (
    QEventLoop,
    QProcess,
    QProcessEnvironment,
    QTimer,
)

from yellowdog_cli.commander.host import (
    CHILD_ENVIRONMENT,
    cli_program,
)
from yellowdog_cli.commander.output_model import (
    OutputRun,
    message_prefix,
)
from yellowdog_cli.commander.selection import (
    EntitySummary,
    ObjectSummary,
    parse_download_summaries,
    parse_entity_summaries,
    parse_object_summaries,
)
from yellowdog_cli.commander.window_base import WindowBase

TERMINATE_TIMEOUT_MS = 2000  # grace period for a child to exit on terminate()
KILL_TIMEOUT_MS = 1000  # further wait after resorting to kill()


def command_line_text(command: str, args: list[str]) -> str:
    """
    A command and its arguments as echoed to the output window.
    """
    return (command + " " + " ".join(args)).rstrip()


class CommandRunning(WindowBase):
    """
    Running commands: a 'yd-*' command or a shell command as a child process
    whose output goes to the output pane, a command run in a nested event
    loop for its '--json' document (the listings and dry runs the dialogs
    offer), and stopping them.
    """

    def _capture_dry_run_json(
        self,
        command: str,
        extra_args: list[str] | None = None,
        failures_recorded: bool = False,
    ) -> list | None:
        """
        Run '<command> -D --json' (quiet, no formatting) with the current config
        source and namespace/tag/user variables, and return the parsed JSON
        array. Return None on any failure (process error, non-zero exit, or
        output that is not a JSON array) so callers can fall back to a
        scope-level confirmation.
        """
        return self._capture_json(
            command, ["-D", "--json"], extra_args, failures_recorded
        )

    def _capture_json(
        self,
        command: str,
        flags: list[str],
        extra_args: list[str] | None = None,
        failures_recorded: bool = False,
    ) -> list | None:
        """
        Run '<command> <flags>' (quiet, no formatting) with the current config
        source and namespace/tag/user variables, then 'extra_args', and return
        the parsed JSON array; 'flags' must ask for JSON. None on any failure: a
        process error, a non-zero exit, or output that is not a JSON array.
        With 'failures_recorded', an exit 1 still returns the array, for a
        command (yd-download) that records what failed -- a path that matched
        nothing -- in it, for the caller to read.
        """
        yd_process = QProcess()
        event_loop = QEventLoop()

        env = QProcessEnvironment.systemEnvironment()
        for name, value in CHILD_ENVIRONMENT.items():
            env.insert(name, value)
        yd_process.setProcessEnvironment(env)
        yd_process.setWorkingDirectory(self._working_dir())

        yd_process.finished.connect(event_loop.quit)
        yd_process.errorOccurred.connect(event_loop.quit)

        args = (
            self._config_source_args()
            + ["--nf", "-q"]
            + flags
            + self._namespace_tag_and_user_vars()
            + (extra_args or [])
        )
        yd_process.start(*cli_program(command, args))
        self._run_nested(yd_process, event_loop)
        if self._shutting_down:
            return None  # the widgets are going away; don't touch them

        if yd_process.error() != QProcess.ProcessError.UnknownError:
            return None
        exit_code = yd_process.exitCode()
        if exit_code != 0 and not (failures_recorded and exit_code == 1):
            return None

        output = (
            yd_process.readAllStandardOutput().data().decode(errors="replace").strip()
        )
        try:
            parsed = loads(output)
        except Exception:
            return None
        return parsed if isinstance(parsed, list) else None

    def _capture_dry_run_summaries(
        self, command: str, extra_args: list[str] | None = None
    ) -> list[EntitySummary] | None:
        """
        The affected entities from a '-D --json' enumeration, with their YDIDs,
        so the user can select a subset and the action can target exactly that
        subset. Returns None when the enumeration failed or did not carry YDIDs,
        which drops the caller to a scope-level confirmation.
        """
        parsed = self._capture_dry_run_json(command, extra_args)
        if parsed is None:
            return None
        summaries = parse_entity_summaries(parsed)
        if summaries is None:
            self._output.log(
                "Entity listing did not include YDIDs; cannot offer a selection"
            )
        return summaries

    def _capture_dry_run_objects(
        self, command: str, extra_args: list[str]
    ) -> list[ObjectSummary] | None:
        """
        The objects and top-level directories 'command' would act on, with the
        resolved path needed to name each one individually. Returns None when the
        enumeration failed or did not carry paths, which drops the caller back to
        acting over the whole pattern.

        'command' is 'yd-delete' or 'yd-download', which offer the same
        selection: yd-delete's '--dry-run --json' records one row per item,
        yd-download's one per file, naming the item each belongs to.
        """
        downloading = command == "yd-download"
        parsed = self._capture_dry_run_json(
            command, extra_args, failures_recorded=downloading
        )
        if parsed is None:
            return None
        if downloading:
            # A path that matched nothing is a recorded failure, which says why
            failed = [
                row
                for row in parsed
                if isinstance(row, dict) and row.get("action") == "failed"
            ]
            for row in failed:
                self._output.log(str(row.get("error")))
            parsed = [row for row in parsed if row not in failed]
        else:
            # A path already gone is recorded 'skipped': nothing to offer
            parsed = [
                row
                for row in parsed
                if not isinstance(row, dict)
                or row.get("action", "would delete") == "would delete"
            ]
        summaries = (
            parse_download_summaries(parsed)
            if command == "yd-download"
            else parse_object_summaries(parsed)
        )
        if summaries is None:
            self._output.log(
                "Object listing did not include paths; cannot offer a selection"
            )
        return summaries

    def _run_command_in_subprocess(
        self,
        command: str,
        args: list[str],
        yd_command: bool = True,
        accept_stdin: bool = False,
        log_args: list[str] | None = None,
    ):
        """
        Run a command in a subprocess, with adaptations for 'yd-'
        commands. 'log_args' replaces 'args' in the echoed command line only —
        used to collapse a long list of YDIDs to a count — and is built the
        same way, so the config-source prefix still appears in the echo.
        """
        raw_args = args
        args = self._build_command_args(command, args, yd_command)
        display_args = (
            args
            if log_args is None
            else self._build_command_args(command, log_args, yd_command)
        )

        process = QProcess(self)
        process_env = QProcessEnvironment.systemEnvironment()
        for name, value in CHILD_ENVIRONMENT.items():
            process_env.insert(name, value)
        process.setProcessEnvironment(process_env)
        run = self._output.start_run(
            command,
            command_line_text(command, display_args),
            command_line_text(command, raw_args if log_args is None else log_args),
            arguments=args,
        )
        self._output.attach(process, run)
        self._processes.append(process)
        process.finished.connect(functools_partial(self._forget_process, process))
        process.finished.connect(functools_partial(self._record_outcome, run))

        # Part of the command's run, although printed by Commander with its own
        # PID, since it is the line saying what the command was
        self._output.log(
            f"Executing: '{run.command_line}' in directory '{self._working_dir()}'",
            run=run.run_id,
            announcement=True,
        )

        process.setWorkingDirectory(self._working_dir())
        process.start(*cli_program(command, args))
        process.waitForStarted()
        if process.error() != QProcess.ProcessError.UnknownError:
            run.outcome = "did not start"
            self._output.log(
                f"Error running command: '{process.errorString()}'", run=run.run_id
            )
        else:
            run.pid = process.processId()
            if accept_stdin:
                self._active_process = process
                self._active_run = run.run_id
                self.stdin_input.setEnabled(True)
                self.stdin_input.setPlaceholderText("Send input to process...")
                process.finished.connect(self._on_active_process_finished)

    @staticmethod
    def _record_outcome(
        run: OutputRun, exit_code: int, exit_status: QProcess.ExitStatus
    ):
        run.outcome = (
            "crashed"
            if exit_status == QProcess.ExitStatus.CrashExit
            else f"exit {exit_code}"
        )

    def _forget_process(self, process: QProcess, *_signal_args):
        for processes in (self._processes, self._helper_processes):
            if process in processes:
                processes.remove(process)

    def _run_nested(
        self, process: QProcess, event_loop: QEventLoop, timeout_ms: int | None = None
    ) -> bool:
        """
        Block in a nested event loop until a synchronous helper's child process
        finishes, registering both so that shutdown() can release them. A
        command blocked on a network timeout can hold this loop for as long as
        that timeout lasts, and the user can close the window while it does.

        With timeout_ms, give up after that long and stop the process. Returns
        True if the process finished on its own, and False if it timed out or
        was stopped by shutdown() — in the latter case the caller must not
        touch any widget, as they are about to be destroyed.
        """
        self._helper_processes.append(process)
        self._nested_loops.append(event_loop)

        timed_out = False
        timer: QTimer | None = None
        if timeout_ms is not None:

            def on_timeout():
                nonlocal timed_out
                timed_out = True
                event_loop.quit()

            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(on_timeout)
            timer.start(timeout_ms)

        # Hold the enumerating actions for as long as this loop blocks. The
        # buttons are greyed for visible feedback; _operation_in_flight is the
        # guard the actions themselves check, because a click already queued
        # before the buttons went grey would still be delivered.
        self._nested_depth += 1
        self._set_action_buttons_enabled(False)
        try:
            event_loop.exec()
        finally:
            self._nested_depth -= 1
            if self._nested_depth == 0 and not self._shutting_down:
                self._set_action_buttons_enabled(True)
            if timer is not None:
                timer.stop()
            self._nested_loops.remove(event_loop)
            self._forget_process(process)

        if timed_out:
            self._stop_process(process)
        return not (timed_out or self._shutting_down)

    def _stop_process(self, process: QProcess) -> bool:
        """
        Stop a running child process, politely first and forcibly if it doesn't
        go. Returns True if it was running and had to be stopped.

        The output handlers are disconnected first: they write to widgets that
        are about to be destroyed, and would otherwise fire during teardown.
        """
        if process.state() == QProcess.ProcessState.NotRunning:
            return False

        for signal in (
            process.readyReadStandardOutput,
            process.readyReadStandardError,
            process.finished,
        ):
            try:
                signal.disconnect()
            except TypeError:
                pass  # nothing was connected to this signal

        process.terminate()
        if not process.waitForFinished(TERMINATE_TIMEOUT_MS):
            process.kill()
            process.waitForFinished(KILL_TIMEOUT_MS)
        return True

    def _running_commands(self) -> list[QProcess]:
        """
        Commands launched from the UI that are still running. Internal helpers
        are excluded: they are short-lived and not the user's business.
        """
        return [
            process
            for process in self._processes
            if process.state() != QProcess.ProcessState.NotRunning
        ]

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
        self._output.log(
            f"{message_prefix(pid)}<-- {text}", prefix=False, run=self._active_run
        )
        self.stdin_input.setPlainText("")
