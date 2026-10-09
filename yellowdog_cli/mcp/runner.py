"""
Runs one yd-* command line as a child process with a bound, and parses what
it wrote. Imports nothing from the 'mcp' package, the SDK, wrapper.py,
args.py or printing.py.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from json import JSONDecodeError, JSONDecoder

from yellowdog_cli.utils.command_registry import command_module


@dataclass(frozen=True)
class Run:
    exit_code: int
    stdout: str
    stderr: str
    stopped: bool  # killed at the timeout; stdout and stderr hold what it wrote

    @property
    def document(self) -> object | None:
        """
        stdout as one JSON document, or None if it is not one.
        """
        try:
            return json.loads(self.stdout)
        except JSONDecodeError:
            return None


def command_argv(command_name: str) -> list[str]:
    """
    The command line that runs 'yd-<name>' under this interpreter: the
    console script may not be on the client's PATH (a desktop client launches
    the server with a minimal environment), and the module is what the
    script runs (command_registry.command_module(), which Commander shares);
    command_from_argv0() resolves the module's file name to the command.
    """
    module = command_module(command_name)
    if module is None:
        raise ValueError(f"'{command_name}' is not a command of this installation")
    return [sys.executable, "-m", module]


# Set in every child's environment, and how its output is read: a Python
# writing to a pipe otherwise uses the locale's encoding
CHILD_ENVIRONMENT = {"PYTHONIOENCODING": "utf-8"}

# How long a stopped command's output is waited for once its process group
# has been killed: a process that escaped the group may hold the pipes open
DRAIN_SECONDS = 5

# How long a stopped command is given to go once interrupted, before its
# process group is killed: time for its wrapper to flush the --json result
INTERRUPT_SECONDS = 5


def run(
    argv: list[str], working_dir: str, environment: dict[str, str], timeout_seconds: int
) -> Run:
    """
    Run 'argv' in 'working_dir' with 'environment', stdin closed, and stop it
    at 'timeout_seconds'. A child that could not be started at all is a Run
    that failed, with the reason in stderr, so the caller reports it as a
    tool error rather than raising.

    The command runs in a process group of its own, and a stop kills the
    group: killing the command alone left its children running (a data
    client command's rclone, transferring after the call had been reported
    stopped), and on Windows holding the output pipes open, so that the stop
    never returned.
    """
    try:
        process = subprocess.Popen(
            argv,
            cwd=working_dir,
            env={**environment, **CHILD_ENVIRONMENT},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_own_process_group(),
        )
    except OSError as error:
        return Run(
            exit_code=127, stdout="", stderr=f"{argv[0]}: {error}", stopped=False
        )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        stdout, stderr = _interrupted(process)
        if stdout is None:
            _stop_group(process)
            try:
                stdout, stderr = process.communicate(timeout=DRAIN_SECONDS)
            except subprocess.TimeoutExpired as still:
                process.kill()
                stdout, stderr = still.stdout, still.stderr
        else:
            _stop_group(process)  # Whatever it started, still running
        return Run(
            exit_code=-9, stdout=_text(stdout), stderr=_text(stderr), stopped=True
        )
    return Run(
        exit_code=process.returncode,
        stdout=_text(stdout),
        stderr=_text(stderr),
        stopped=False,
    )


def _own_process_group() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _interrupted(
    process: subprocess.Popen,
) -> tuple[str | bytes | None, str | bytes | None]:
    """
    Interrupt the command's process group, as a Ctrl-C at a terminal does,
    and return its output if the command has gone within INTERRUPT_SECONDS,
    or (None, None): the wrappers flush the --json result on an interrupt,
    so the records of what it did before the stop come back, where a kill
    alone lost them all. The whole group, so that what it started (rclone)
    stops too rather than running on through the grace period. Not on
    Windows, whose CTRL_BREAK_EVENT Python does not turn into a
    KeyboardInterrupt.
    """
    if sys.platform == "win32":
        return None, None
    try:
        os.killpg(process.pid, signal.SIGINT)
        return process.communicate(timeout=INTERRUPT_SECONDS)
    except subprocess.TimeoutExpired:
        return None, None
    except OSError:
        return None, None  # Gone already: the kill finds nothing


def _stop_group(process: subprocess.Popen) -> None:
    """
    Kill the command and every process it started.
    """
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=DRAIN_SECONDS,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass  # Gone already, or no taskkill: the command itself still goes
    process.kill()


def _text(output: str | bytes | None) -> str:
    if output is None:
        return ""
    return (
        output.decode("utf-8", errors="replace")
        if isinstance(output, bytes)
        else output
    )


def parse_event_documents(text: str) -> list[object]:
    """
    yd-follow --json's stdout as a list: one JSON document per event, each
    indented over several lines, with a partial last one (the run was
    stopped mid-event) dropped.
    """
    decoder = JSONDecoder()
    documents: list[object] = []
    position = 0
    length = len(text)
    while True:
        while position < length and text[position].isspace():
            position += 1
        if position >= length:
            return documents
        try:
            document, position = decoder.raw_decode(text, position)
        except JSONDecodeError:
            return documents
        documents.append(document)
