"""
The '--debug' trace: what a command does, written to stderr as it does it,
whatever '--quiet', '--json' and '--no-format' say, so that stdout holds
what it would hold without it.

Every module logs through the standard 'logging' module, to a logger under
'yellowdog_cli' ('LOG = logging.getLogger(__name__)', formatted lazily:
'LOG.debug("resolved %s", name)'), and urllib3's own logger gives a line for
every HTTP request: the SDK's, the event streams' and the CLI's own. The
handler is on those two loggers, never the root one, which rclone_api
configures for itself (dataclient/rclone.py), and neither propagates to it
while the trace is on, so no line is written twice.

set_debug_logging() turns it on or off; output_settings.configure_output()
calls it, so every command that configures its output has the trace it asks
for. Off, nothing is formatted and nothing is written.

A line is '<date> <time> : DEBUG : [+<seconds since start>s] <module>:
<message>', the module named by its path in the package less 'yellowdog_cli'
and 'utils' ('submit', 'load_config', 'dataclient.operations'), plain text, prefixed as an info line is (printing.print_string(),
the process ID too under '--print-pid'), and a traceback logged with it
('exc_info=True') follows it. Never log a
credential: no request headers, no key or secret, no variable's value, a
remote only through shown_remote().

Stdlib only: every command imports it, before any SDK.
"""

import logging
import os
import sys
import time

from yellowdog_cli.utils.output_style import DEBUG_MARKER

CLI_LOGGER = "yellowdog_cli"
HTTP_LOGGER = "urllib3"

_START = time.time()

# The package's directory, and its 'utils', which a module's name leaves out
_PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DROPPED = ("utils",)


class _StderrHandler(logging.StreamHandler):
    """
    A StreamHandler writing to sys.stderr as it is when a line is written,
    rather than when the handler was made, so that a redirection of stderr
    (a test's capture, yd-doctor's) reaches it.
    """

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stderr
        super().emit(record)


class _TraceFormatter(logging.Formatter):
    """
    '2026-10-28 14:48:21 : DEBUG : [+1.234s] submit: message', with the
    process ID after the time when 'print_pid' is set: the CLI's records
    named by their module's path in the package (the caller's, for
    print_debug()'s, so from the record's file rather than its logger), any
    other library's by its logger.
    """

    print_pid = False

    def format(self, record: logging.LogRecord) -> str:
        name = (
            _module_name(record)
            if record.name == CLI_LOGGER or record.name.startswith(f"{CLI_LOGGER}.")
            else record.name.split(".")[0]
        )
        record.message = record.getMessage()
        prefix = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created))
        if self.print_pid:
            prefix += f" ({record.process:06d})"
        line = (
            f"{prefix} : {DEBUG_MARKER}[+{record.created - _START:.3f}s]"
            f" {name}: {record.message}"
        )
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def _module_name(record: logging.LogRecord) -> str:
    """
    The module that logged the record, by its path in the package less the
    package and 'utils' ('dataclient.operations'); a file outside the
    package (a test's) by its module name alone.
    """
    path = os.path.abspath(record.pathname)
    if os.path.commonpath([path, _PACKAGE]) != _PACKAGE:
        return record.module
    parts = os.path.splitext(os.path.relpath(path, _PACKAGE))[0].split(os.sep)
    while len(parts) > 1 and parts[0] in _DROPPED:
        parts = parts[1:]
    return ".".join(parts)


_FORMATTER = _TraceFormatter()
_HANDLER = _StderrHandler()
_HANDLER.setFormatter(_FORMATTER)

# Off, the CLI's own debug lines are not even formatted, whatever level a
# library gives the root logger (rclone_api's is INFO); urllib3 is left as
# it would be without the CLI
_LEVELS_OFF = {CLI_LOGGER: logging.WARNING, HTTP_LOGGER: logging.NOTSET}


def set_debug_logging(enabled: bool, print_pid: bool = False) -> None:
    """
    Turn the trace on or off, its lines carrying the process ID when
    'print_pid' is set; called again, it changes nothing that is already so.
    """
    _FORMATTER.print_pid = print_pid
    for name in _LEVELS_OFF:
        logger = logging.getLogger(name)
        if enabled:
            if _HANDLER not in logger.handlers:
                logger.addHandler(_HANDLER)
            logger.setLevel(logging.DEBUG)
            logger.propagate = False
        else:
            logger.removeHandler(_HANDLER)
            logger.setLevel(_LEVELS_OFF[name])
            logger.propagate = True
