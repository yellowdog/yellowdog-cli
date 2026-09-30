"""
Which platform Commander is running on. Decided once, at import, and refused
outright on anything but the three Commander knows how to open a file on,
rather than guessing. Qt-free.
"""

import os
import sys
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
