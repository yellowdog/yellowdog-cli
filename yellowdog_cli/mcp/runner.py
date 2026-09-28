"""
Runs one yd-* command line as a child process with a bound, and parses what
it wrote. Imports nothing from the 'mcp' package, the SDK, wrapper.py,
args.py or printing.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from json import JSONDecodeError, JSONDecoder


@dataclass(frozen=True)
class Run:
    exit_code: int
    stdout: str
    stderr: str
    stopped: bool  # killed at the timeout; stdout and stderr hold what it wrote

    @property
    def document(self) -> object | None:
        """stdout as one JSON document, or None if it is not one."""
        try:
            return json.loads(self.stdout)
        except JSONDecodeError:
            return None


def command_argv(command_name: str) -> list[str]:
    """
    The command line that runs 'yd-<name>' under this interpreter: the
    console script may not be on the client's PATH (a desktop client launches
    the server with a minimal environment), and the module is what the
    script runs; command_from_argv0() resolves the module's file name to the
    command.
    """
    module = command_name.removeprefix("yd-").replace("-", "_")
    return [sys.executable, "-m", f"yellowdog_cli.{module}"]


def run(
    argv: list[str], working_dir: str, environment: dict[str, str], timeout_seconds: int
) -> Run:
    """
    Run 'argv' in 'working_dir' with 'environment', stdin closed, and stop it
    at 'timeout_seconds'. A child that could not be started at all is a Run
    that failed, with the reason in stderr, so the caller reports it as a
    tool error rather than raising.
    """
    try:
        completed = subprocess.run(
            argv,
            cwd=working_dir,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            # A byte the encoding cannot decode is replaced, as the timeout
            # path's _text() replaces it, never raised out of the call
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as stopped:
        # subprocess.run() has killed the child and collected what it wrote
        return Run(
            exit_code=-9,
            stdout=_text(stopped.stdout),
            stderr=_text(stopped.stderr),
            stopped=True,
        )
    except OSError as error:
        return Run(
            exit_code=127, stdout="", stderr=f"{argv[0]}: {error}", stopped=False
        )
    return Run(
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        stopped=False,
    )


def _text(output: str | bytes | None) -> str:
    if output is None:
        return ""
    return output.decode(errors="replace") if isinstance(output, bytes) else output


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
