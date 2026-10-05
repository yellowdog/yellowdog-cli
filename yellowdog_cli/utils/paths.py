"""
Path helpers with no dependencies beyond the standard library, so that
anything -- the configuration loader at import, Commander -- can use them.
"""

from os.path import abspath, relpath


def relative_if_possible(path: str) -> str:
    """
    The path relative to the current directory, which reads better in the
    messages that name it; or, where there is no relative path to it -- on
    Windows, a file on another drive, where relpath() raises ValueError --
    the absolute path, which still names it correctly from anywhere.
    """
    try:
        return relpath(path)
    except ValueError:
        return abspath(path)
