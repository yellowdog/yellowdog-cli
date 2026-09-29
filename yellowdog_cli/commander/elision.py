"""
Shortening file paths and names for display, keeping the parts that
identify them.
"""

import os
from collections.abc import Callable

MAX_DISPLAYED_PATH_LENGTH = 45  # longer paths are elided by elide_path()
PATH_ELLIPSIS = "…"
MAX_DISPLAYED_NAME_LENGTH = 20  # fallback cap before the button has a width


def elide_path(path: str, max_length: int = MAX_DISPLAYED_PATH_LENGTH) -> str:
    """
    Shorten a file path for display so that it doesn't stretch the layout,
    keeping the end of the path (including the filename) visible. Paths within
    the length limit are returned unchanged.
    """
    if len(path) <= max_length:
        return path

    tail = path[-(max_length - len(PATH_ELLIPSIS)) :]
    separator_index = tail.find(os.sep)
    if separator_index != -1:  # discard any partial leading directory name
        tail = tail[separator_index:]
    return f"{PATH_ELLIPSIS}{tail}"


def elide_middle(text: str, max_length: int = MAX_DISPLAYED_NAME_LENGTH) -> str:
    """
    Shorten text for display by removing characters from the middle, keeping
    both ends visible. Used for filenames, where the start and the extension
    are the informative parts.
    """
    if len(text) <= max_length:
        return text

    keep = max_length - len(PATH_ELLIPSIS)
    head = keep - keep // 2
    return f"{text[:head]}{PATH_ELLIPSIS}{text[len(text) - keep // 2 :]}"


def elide_path_to_fit(path: str, fits: Callable[[str], bool]) -> str:
    """
    The longest form of 'path' that 'fits' accepts: the whole path if it fits,
    else the ellipsis and the longest tail of it that starts at a separator, so
    that no directory name is shown cut off and the filename is kept. Where not
    even the filename fits, the ellipsis and the filename (or, with no separator,
    the path as it is), for the caller to clip. 'fits' is the caller's measure — a width in pixels, typically — which
    keeps this free of Qt.
    """
    if fits(path):
        return path
    tails = [path[index:] for index, char in enumerate(path) if char in (os.sep, "/")]
    for tail in tails:  # longest first
        candidate = f"{PATH_ELLIPSIS}{tail}"
        if fits(candidate):
            return candidate
    return f"{PATH_ELLIPSIS}{tails[-1]}" if tails else path
