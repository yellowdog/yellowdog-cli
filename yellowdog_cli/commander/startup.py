"""
What yd-commander was asked to start with. Kept free of PyQt6, like
launcher.py, which builds a StartupSettings before any Qt import is attempted;
commander.py then applies it to the window.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StartupSettings:
    """
    The window's initial state, as given on the command line. Every field only
    fills in the GUI at startup: once the window is up the values are ordinary
    field contents, edited or cleared like any other. Definition file paths are
    absolute, resolved against the launch directory (see YellowDogApp._wr_file).
    """

    config_file: str | None = None
    disable_confirmations: bool = False
    namespace: str | None = None
    tag: str | None = None
    name_glob: str | None = None
    object_path: str | None = None
    variables: tuple[str, ...] = ()
    wr_file: str | None = None
    wp_file: str | None = None


def variable_is_complete(variable: str) -> bool:
    """
    Whether a whitespace-separated token from the user-variables box is a
    'name=value' the CLI will accept. Mirrors the rule in utils/variables.py:
    an '=' with a non-empty name in front of it.
    """
    name, separator, _ = variable.partition("=")
    return bool(separator) and bool(name)
