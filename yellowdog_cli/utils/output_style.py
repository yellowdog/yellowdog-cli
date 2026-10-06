"""
How output looks: widths, the message markers and styles, the Rich theme and
the states it highlights, JSON indentation, the redaction placeholder.
"""

import re

DEFAULT_LOG_WIDTH = 120
MAX_TABLE_DESCRIPTION = 50
# Longer output is printed uncoloured: Rich's highlighting costs ~50us a
# line for a table (a span per cell) and ~11us for JSON, on Apple silicon
MAX_LINES_COLOURED_TABLE = 2000
MAX_LINES_COLOURED_JSON = 5000
JSON_INDENT = 2

ERROR_STYLE = "bold red3"
WARNING_STYLE = "red3"
# Mark the messages printed by print_error() and print_warning()
ERROR_MARKER = "ERROR : "
WARNING_MARKER = "WARNING : "
# Marks and colours the configuration/startup messages shown only under '--debug'
DEBUG_MARKER = "DEBUG : "
DEBUG_STYLE = "dark_orange"
# Marks the messages reporting what a '--dry-run' would have done
DRY_RUN_MARKER = "DRY-RUN : "

# Stands in for a credential that's being withheld ('--show-secrets' reveals it)
REDACTED_VALUE = "<REDACTED>"

# A state as a whole word: '_' is a word character, so a name holding one
# ('MY_NEW_TASKS') is left alone, as are 'ALREADY' and 'UNTERMINATED'. One
# regex per style, not per state: each scans the whole text, and 42 of them
# were half the cost of colouring a table. Longest first, so that 'MAYBE
# MATCHING' is matched whole rather than as 'MATCHING'
_STATES_BY_STYLE: dict[str, tuple[str, ...]] = {
    "active": (
        "ALLOCATED",
        "DOING_TASK",
        "BATCH_ALLOCATION",
        "EXECUTING",
        "EXPECTED",
        "PENDING",
        "READY",
        "RUNNING",
        "TARGET",
        "ALIVE",
        "MATCHING",
        "MAYBE MATCHING",
        "FINISHING",
    ),
    "cancelled": (
        "ABORTED",
        "CANCELLED",
        "CANCELLING",
        "DEREGISTERED",
        "SHUTDOWN",
        "STOPPED",
        "TERMINATED",
    ),
    "completed": ("COMPLETED",),
    "failed": (
        "FAILED",
        "FAILING",
        "LOST",
        "NON-MATCHING",
    ),
    "idle": (
        "EMPTY",
        "FOUND",
        "IDLE",
        "SLEEPING",
        "STARTING",
        "WAITING",
        "HELD",
    ),
    "starved": ("STARVED",),
    "transitioning": (
        "CONFIGURING",
        "DOWNLOADING",
        # "LATE", at the end of a line only, was once highlighted too
        "NEW",
        "PROVISIONING",
        "STOPPING",
        "TERMINATING",
        "UNAVAILABLE",
        "UNKNOWN",
        "UPLOADING",
    ),
}
HIGHLIGHTED_STATES = [
    re.compile(
        rf"\b(?P<{style}>{'|'.join(re.escape(state) for state in sorted(states, key=len, reverse=True))})\b"
    )
    for style, states in _STATES_BY_STYLE.items()
]
# For Rich colour options, see colour list & swatches at:
# https://rich.readthedocs.io/en/stable/appendix/colors.html
DEFAULT_THEME = {
    "pyexamples.date_time": "bold deep_sky_blue1",
    "pyexamples.quoted": "bold green4",
    "pyexamples.url": "bold green4",
    "pyexamples.ydid": "bold dark_orange",
    "pyexamples.table_outline": "bold deep_sky_blue4",
    "pyexamples.table_content": "bold green4",
    "pyexamples.transitioning": "bold dark_orange",
    "pyexamples.executing": "bold deep_sky_blue4",
    "pyexamples.failed": "bold red3",
    "pyexamples.completed": "bold green4",
    "pyexamples.cancelled": "bold grey35",
    "pyexamples.active": "bold deep_sky_blue4",
    "pyexamples.idle": "bold dark_goldenrod",
    "pyexamples.starved": "bold dark_orange",
}
