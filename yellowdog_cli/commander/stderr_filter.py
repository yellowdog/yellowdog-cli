"""
Drop known-harmless macOS system messages from Commander's own stderr.

macOS's Text Services Manager (HIToolbox) logs 'TSMSendMessageToUIServer:
CFMessagePortSendRequest FAILED(-1) to send to port com.apple.tsm.uiserver'
straight to file descriptor 2, now and then, as text fields gain focus or the
window is activated. It is not Qt's logging, so QT_LOGGING_RULES cannot reach
it, and no change to how Commander paints has been shown to stop it. So fd 2
is pointed at a pipe, and a thread copies what arrives to the real stderr,
one line at a time, leaving out any line holding one of the markers.

Commander's children are unaffected: QProcess gives each its own pipes, so
only what Commander's own process writes passes through here. faulthandler is
pointed at the real stderr, so a crash's traceback does not depend on the
thread still running, and an atexit hook puts fd 2 back and waits for the
thread to drain the pipe, so a message printed just before exit still appears.
"""

import atexit
import faulthandler
import os
import sys
import threading
from collections.abc import Iterable
from typing import BinaryIO

# A line of stderr holding any of these is dropped
SUPPRESSED_STDERR_MARKERS = (b"TSMSendMessageToUIServer",)

# How long exit waits for the thread to copy what is left in the pipe
_DRAIN_TIMEOUT_S = 1.0

# The real stderr, kept open for faulthandler, which writes to it directly
_fault_file: BinaryIO | None = None


def install_stderr_filter(
    markers: Iterable[bytes] = SUPPRESSED_STDERR_MARKERS,
) -> bool:
    """
    Point fd 2 at a pipe whose lines are copied to the real stderr, less any
    holding one of the markers. Returns False, changing nothing, if stderr
    cannot be duplicated (there is none).
    """
    global _fault_file
    try:
        original_fd = os.dup(2)
    except OSError:
        return False
    read_fd, write_fd = os.pipe()
    os.dup2(write_fd, 2)
    os.close(write_fd)

    _fault_file = os.fdopen(os.dup(original_fd), "wb")
    faulthandler.enable(file=_fault_file)

    thread = threading.Thread(
        target=_copy_lines,
        args=(read_fd, original_fd, tuple(markers)),
        name="stderr-filter",
        daemon=True,
    )
    thread.start()
    atexit.register(_restore, original_fd, thread)
    return True


def _copy_lines(read_fd: int, original_fd: int, markers: tuple[bytes, ...]):
    """
    Copy each line from the pipe to the real stderr unless it holds a marker.
    The pipe is read until it closes whatever happens to the writes: a reader
    that stopped would leave anything writing to stderr blocked once the pipe
    filled, which would hang the window.
    """
    with os.fdopen(read_fd, "rb") as pipe:
        for line in pipe:
            if any(marker in line for marker in markers):
                continue
            try:
                os.write(original_fd, line)
            except OSError:
                pass


def _restore(original_fd: int, thread: threading.Thread):
    """
    At exit, put the real stderr back on fd 2, which closes the pipe's last
    write end, and let the thread copy what was left in it.
    """
    try:
        sys.stderr.flush()
    except (OSError, ValueError):
        pass
    os.dup2(original_fd, 2)
    thread.join(_DRAIN_TIMEOUT_S)
