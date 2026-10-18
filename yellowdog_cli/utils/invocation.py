"""
How the running command was invoked: the command the 'yd' dispatcher (or a
noun's) selected and the prog it is shown as, and the name argv[0] gives.
Stdlib only: the standalone commands and the launchers read it as they
start.
"""

import os

# The command selected to run and the prog it is shown as ('yd-submit',
# 'yd wr submit'); None when the command runs as its own script
_SELECTED: tuple[str, str] | None = None


def select_command(command: str, prog: str) -> None:
    """
    Make 'command', invoked as 'prog', the one ARGS_PARSER parses for.
    """
    global _SELECTED
    _SELECTED = (command, prog)


def selected() -> tuple[str, str] | None:
    """
    The command selected and its prog, or None.
    """
    return _SELECTED


def selected_prog(default: str) -> str:
    """
    The prog a standalone parser shows: the selection's, else 'default'.
    """
    return default if _SELECTED is None else _SELECTED[1]


def invoked_name(argv0: str) -> str:
    """
    The name a command was invoked by, as typed: argv[0]'s basename, less a
    Windows '.exe' or '-script.py'. 'python -m' gives the module's file
    ('submit.py'), which is no 'yd-*' name.
    """
    return (
        os.path.basename(argv0.replace("\\", "/"))
        .removesuffix(".exe")
        .removesuffix("-script.py")
    )
