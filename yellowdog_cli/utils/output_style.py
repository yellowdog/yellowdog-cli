"""
How output looks: widths, the message markers and styles, the Rich theme and
the states it highlights, JSON indentation, the redaction placeholder.
"""

import re

DEFAULT_LOG_WIDTH = 120
MAX_TABLE_DESCRIPTION = 50
MAX_LINES_COLOURED_FORMATTING = 1024
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
# ('MY_NEW_TASKS') is left alone, as are 'ALREADY' and 'UNTERMINATED'
HIGHLIGHTED_STATES = [
    re.compile(r"\b(?P<active>ALLOCATED)\b"),
    re.compile(r"\b(?P<active>DOING_TASK)\b"),
    re.compile(r"\b(?P<active>BATCH_ALLOCATION)\b"),
    re.compile(r"\b(?P<active>EXECUTING)\b"),
    re.compile(r"\b(?P<active>EXPECTED)\b"),
    re.compile(r"\b(?P<active>PENDING)\b"),
    re.compile(r"\b(?P<active>READY)\b"),
    re.compile(r"\b(?P<active>RUNNING)\b"),
    re.compile(r"\b(?P<active>TARGET)\b"),
    re.compile(r"\b(?P<active>ALIVE)\b"),
    re.compile(r"\b(?P<active>MATCHING)\b"),
    re.compile(r"\b(?P<active>MAYBE MATCHING)\b"),
    re.compile(r"\b(?P<active>FINISHING)\b"),
    re.compile(r"\b(?P<cancelled>ABORTED)\b"),
    re.compile(r"\b(?P<cancelled>CANCELLED)\b"),
    re.compile(r"\b(?P<cancelled>CANCELLING)\b"),
    re.compile(r"\b(?P<cancelled>DEREGISTERED)\b"),
    re.compile(r"\b(?P<cancelled>SHUTDOWN)\b"),
    re.compile(r"\b(?P<cancelled>STOPPED)\b"),
    re.compile(r"\b(?P<cancelled>TERMINATED)\b"),
    re.compile(r"\b(?P<completed>COMPLETED)\b"),
    re.compile(r"\b(?P<failed>FAILED)\b"),
    re.compile(r"\b(?P<failed>FAILING)\b"),
    re.compile(r"\b(?P<failed>LOST)\b"),
    re.compile(r"\b(?P<failed>NON-MATCHING)\b"),
    re.compile(r"\b(?P<idle>EMPTY)\b"),
    re.compile(r"\b(?P<idle>FOUND)\b"),
    re.compile(r"\b(?P<idle>IDLE)\b"),
    re.compile(r"\b(?P<idle>SLEEPING)\b"),
    re.compile(r"\b(?P<idle>STARTING)\b"),
    re.compile(r"\b(?P<idle>WAITING)\b"),
    re.compile(r"\b(?P<idle>HELD)\b"),
    re.compile(r"\b(?P<starved>STARVED)\b"),
    re.compile(r"\b(?P<transitioning>CONFIGURING)\b"),
    re.compile(r"\b(?P<transitioning>DOWNLOADING)\b"),
    # re.compile(r"(?P<transitioning>LATE$)"),
    re.compile(r"\b(?P<transitioning>NEW)\b"),
    re.compile(r"\b(?P<transitioning>PROVISIONING)\b"),
    re.compile(r"\b(?P<transitioning>STOPPING)\b"),
    re.compile(r"\b(?P<transitioning>TERMINATING)\b"),
    re.compile(r"\b(?P<transitioning>UNAVAILABLE)\b"),
    re.compile(r"\b(?P<transitioning>UNKNOWN)\b"),
    re.compile(r"\b(?P<transitioning>UPLOADING)\b"),
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
