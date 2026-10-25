"""
Replace a file's contents whole or not at all: write the new text to a
temporary file beside it, then move that into place, so an interruption
(a full disk, Ctrl-C) leaves the original, never a truncated file.
Standard library only, for the standalone commands that use it.
"""

import os
import tempfile


def write_text_atomically(filename: str, text: str, mode: int | None = None) -> None:
    """
    Write 'text' (UTF-8) to 'filename' atomically. The file gets 'mode' if
    given; else an existing file keeps its permissions, and a new one gets
    those an ordinary write would give it (0o666 less the umask), rather
    than the temporary file's 0o600. The mode is set before the file takes
    the name, so a file holding a secret is never readable more widely.
    """
    directory = os.path.dirname(os.path.abspath(filename))
    if mode is None:
        try:
            mode = os.stat(filename).st_mode & 0o7777
        except FileNotFoundError:
            umask = os.umask(0)
            os.umask(umask)
            mode = 0o666 & ~umask
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=directory, prefix=".yd-write-", delete=False
    ) as temporary:
        temporary.write(text)
    try:
        os.chmod(temporary.name, mode)
        os.replace(temporary.name, filename)
    except BaseException:
        os.unlink(temporary.name)
        raise
