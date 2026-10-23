"""
UTF-8 for the CLI's own output on Windows. Written to a console, Python's
output is Unicode already; written to a pipe or a file, it takes the
system's ANSI code page (cp1252 in English), in which a character outside
it ends the command with a UnicodeEncodeError and the ones in it reach a
reader expecting UTF-8 garbled. --json output, which RFC 8259 requires to
be UTF-8 between programs, would be wrong either way. Every command calls
use_utf8_output() before it prints anything; Python 3.15 makes UTF-8 the
default (PEP 686). Stdlib only.
"""

import sys
from typing import TextIO


def use_utf8_output() -> None:
    """
    On Windows, write standard output and standard error as UTF-8 where
    they are not already (a pipe or a file; a console is), keeping each
    stream's error handling.
    """
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        _as_utf8(stream)


def _as_utf8(stream: TextIO | None) -> None:
    """
    Reconfigure one stream to UTF-8, if it is a text stream in another
    encoding; anything else (None under pythonw, a replacement without
    reconfigure()) is left as it is.
    """
    if stream is None or not hasattr(stream, "reconfigure"):
        return
    encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
    if encoding == "utf8":
        return
    stream.reconfigure(encoding="utf-8", errors=stream.errors)  # type: ignore[attr-defined]
