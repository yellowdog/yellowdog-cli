"""
Which platform Commander is running on, decided once, at import, and refused
outright on anything but the three Commander knows how to open a file on,
rather than guessing; and how a child process is started there: the shell for
a typed command, the program for a 'yd-*' one, and the environment every
child gets. Qt-free.
"""

import os
import sys
from functools import cache
from importlib.metadata import entry_points
from platform import system as _platform_system

from yellowdog_cli.utils.settings import ERROR_MARKER

_system = _platform_system()
MACOS = _system == "Darwin"
LINUX = _system == "Linux"
WINDOWS = _system == "Windows"

if not (MACOS or LINUX or WINDOWS):
    print(f"{ERROR_MARKER}unrecognised platform: {_system}", file=sys.stderr)
    sys.exit(1)


def shell_command() -> tuple[str, str]:
    """
    The shell the command box hands a non-'yd-' command to, as its full path,
    and the flag that makes it run the text that follows.

    By full path, not by name: started as the bare 'cmd', Windows searched for
    it and a Windows machine came back with 'Process failed to start: Access
    is denied.' for every such command. %ComSpec% is what Windows itself uses
    to name the command interpreter, and the System32 copy stands in where it
    is unset; the bare name remains the last resort, as it was before.
    """
    if WINDOWS:
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        for candidate in (
            os.environ.get("ComSpec"),
            os.path.join(system_root, "System32", "cmd.exe"),
        ):
            if candidate and os.path.isfile(candidate):
                return candidate, "/c"
        return "cmd", "/c"
    return ("/bin/sh" if os.path.isfile("/bin/sh") else "sh"), "-c"


# Set in every child's environment: a Python writing to a pipe uses the
# locale's encoding (cp1252 on Windows) unless told otherwise, and the
# messages the CLI prints carry characters such as '→' and '—'
CHILD_ENVIRONMENT = {"PYTHONIOENCODING": "utf-8"}


@cache
def _cli_modules() -> dict[str, str]:
    """
    Each of this package's console scripts and the module it runs: 'yd-rm'
    is 'yellowdog_cli.delete', which no rule on the name would give.
    """
    return {
        point.name: point.value.split(":")[0]
        for point in entry_points(group="console_scripts")
        if point.value.startswith("yellowdog_cli.")
    }


def cli_program(command: str, args: list[str]) -> tuple[str, list[str]]:
    """
    The program and arguments that run 'command': a console script of this
    installation's under this interpreter ('python -m <its module>'), so that
    it is this installation's CLI that runs, whatever the PATH Commander was
    started with holds; anything else as it is.
    """
    module = _cli_modules().get(command)
    if module is None:
        return command, args
    return sys.executable, ["-m", module, *args]
