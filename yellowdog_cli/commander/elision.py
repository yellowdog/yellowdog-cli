"""
Shortening file paths and names for display, keeping the parts that
identify them.
"""

import os

MAX_DISPLAYED_PATH_LENGTH = 45  # longer paths are elided in the config label
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
