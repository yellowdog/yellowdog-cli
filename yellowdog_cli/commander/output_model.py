"""
The output window's model: where each piece of text came from (OutputRun,
OutputEntry), how many blocks it makes in the widget, and the reassembly of
a child process's output into lines. Qt-free; the window in commander.py
is the view of it.
"""

import re
from codecs import getincrementaldecoder
from dataclasses import dataclass, field
from datetime import datetime

from yellowdog_cli.utils.command_registry import DRY_RUN, FOLLOW, PROGRESS
from yellowdog_cli.utils.noun_registry import command_named
from yellowdog_cli.utils.ydid_utils import (
    YDID_HIGHLIGHT_RE,
    YDIDType,
    get_ydid_type,
)

# The run Commander's own messages belong to in the output window; the commands it
# launches are numbered from 1. See OutputRun.
COMMANDER_RUN = 0
# What starts a new block when text is put into a QTextDocument: a line feed, a
# carriage return (alone or before a line feed, which together make one), Unicode's
# paragraph separator, and Qt's two frame markers. The output window's blocks are
# tagged with the entry they came from by counting them, so the count must be Qt's.
BLOCK_SEPARATORS = re.compile(r"\r\n|[\r\n\u2029\ufdd0\ufdd1]")


# The command that does nothing but follow the YDIDs it is given
FOLLOWING_COMMAND = "yd-follow"  # the registry command, by any name


def block_count(text: str) -> int:
    """
    The number of blocks 'text' becomes in a QTextDocument; see BLOCK_SEPARATORS.
    """
    return len(BLOCK_SEPARATORS.split(text))


# The marks starting the line that says how a command ended, after the
# message prefix; OutputHighlighter colours each line by its mark
ENDED_OK_MARK = "✓"
ENDED_FAILED_MARK = "✗"
ENDED_STOPPED_MARK = "■"


@dataclass
class OutputRun:
    """
    One source of text in the output window — a command Commander launched, or
    Commander itself — which the window can be filtered to.

    The output is filtered by run rather than by the PID text in each line,
    because most of a command's output does not carry its PID: a wrapped
    message's continuation lines, a table or a JSON document have no prefix at
    all, and the 'Executing:' line announcing the command is printed by
    Commander, with Commander's PID, before the command has one. Every chunk of
    text arrives from a known QProcess, so it is attributed when it arrives.
    """

    run_id: int
    command: (
        str  # the program run, e.g. 'yd workrequirement submit'; empty for Commander
    )
    command_line: str = ""  # as echoed on the 'Executing:' line
    # As the user would recognise it: without the config source, namespace, tag,
    # variables and '--nf --pp' that Commander adds to every 'yd-*' command
    user_command_line: str = ""
    started_at: datetime | None = None
    pid: int | None = None  # as QProcess reports it, once started
    # 'exit N', 'crashed' or 'stopped' once finished, 'did not start' if it
    # never did; None while running
    outcome: str | None = None
    # Whether Stop has been chosen for it, so that its ending is recorded as
    # 'stopped' rather than as the crash a terminate() or kill() looks like
    stop_requested: bool = False
    # The PID the command printed in its own message prefixes, preferred for
    # display because it is the one the user sees in the output; QProcess's can
    # differ where a console-script launcher stands between the two.
    printed_pid: int | None = None
    # The arguments it was run with, as given to the process
    arguments: tuple[str, ...] = ()
    # The Work Requirement YDIDs it has printed: the one a 'yd workrequirement
    # submit' created
    work_requirements_printed: set[str] = field(default_factory=set)

    def note_output(self, text: str) -> None:
        """
        Note the Work Requirement YDIDs in a piece of the run's output.
        """
        self.work_requirements_printed.update(
            ydid
            for ydid in YDID_HIGHLIGHT_RE.findall(text)
            if get_ydid_type(ydid) == YDIDType.WORK_REQUIREMENT
        )

    @property
    def is_follow_command(self) -> bool:
        """
        Whether the command is 'yd follow' (by any of its names), whose only
        work is following, so that stopping it stops nothing else.
        """
        command = command_named(self.command)
        return command is not None and command.internal_name == FOLLOWING_COMMAND

    @property
    def follows_events(self) -> bool:
        """
        Whether the command follows the event streams of the entities it is
        about: 'yd follow' (a noun's 'follow' verb, or 'yd follow'), or a
        command given '--follow' or '--progress' that is not a dry run. Only
        separate flags count, not a cluster such as '-fD', whose letters could
        be another option's value.
        """
        command = command_named(self.command)
        if command is None:
            return False
        if command.internal_name == FOLLOWING_COMMAND:
            return True
        # A variant() keeps its base's flags, so the base's are the command's
        flags = {
            flag
            for option in (FOLLOW, PROGRESS)
            if command.has(option)
            for flag in option.flags
        }
        dry_run = set(DRY_RUN.flags) if command.has(DRY_RUN) else set()
        given = set(self.arguments)
        return bool(given & flags) and not given & dry_run

    def is_following(self, work_requirement_id: str) -> bool:
        """
        Whether this run, still running, is following the Work Requirement:
        one it follows events for, and named on its command line or printed
        by it (the one a 'yd workrequirement submit' created).
        """
        return (
            self.running
            and self.follows_events
            and (
                work_requirement_id in self.arguments
                or work_requirement_id in self.work_requirements_printed
            )
        )

    def _subject(self, process_word: str) -> str:
        pid = self.shown_pid
        if pid is None:  # it never started
            return self.command
        return f"{process_word} {pid:06d} ({self.command})"

    @property
    def menu_text(self) -> str:
        if self.run_id == COMMANDER_RUN:
            return "Show Only Commander's Own Messages"
        return f"Show Only Output from {self._subject('Process')}"

    @property
    def ending_text(self) -> str | None:
        """
        The line saying how the command ended, marked with how it went, or
        None while it runs or if it never started (which is said already).
        """
        subject = self._subject("Process")
        match self.outcome:
            case None | "did not start":
                return None
            case "exit 0":
                return f"{ENDED_OK_MARK} {subject} finished (exit 0)"
            case "stopped":
                return f"{ENDED_STOPPED_MARK} {subject} stopped"
            case "crashed":
                return f"{ENDED_FAILED_MARK} {subject} crashed"
            case outcome:
                return f"{ENDED_FAILED_MARK} {subject} failed ({outcome})"

    @property
    def stop_text(self) -> str:
        return f"Stop {self._subject('Process')}"

    @property
    def bar_subject(self) -> str:
        if self.run_id == COMMANDER_RUN:
            return "Commander's own messages"
        return self._subject("process")

    @property
    def shown_pid(self) -> int | None:
        return self.printed_pid if self.printed_pid is not None else self.pid

    @property
    def running(self) -> bool:
        return self.run_id != COMMANDER_RUN and self.outcome is None


def line_pattern(text: str) -> re.Pattern[str] | None:
    """
    The output window's text filter as a pattern to search each line for:
    'text' found anywhere in the line, ignoring case, with '*' matching any
    run of characters and '?' any one. Every other character is itself, '['
    included, which fnmatch would read as a character class. None for a
    filter with nothing in it but spaces, which shows every line.
    """
    text = text.strip()
    if not text:
        return None
    wildcards = {"*": ".*", "?": "."}
    return re.compile(
        "".join(wildcards.get(char, re.escape(char)) for char in text),
        re.IGNORECASE,
    )


def filter_description(runs: list[OutputRun], text: str = "") -> str:
    """
    What the filter bar says is shown: 'Showing only' and the runs, commands
    in the order they started and Commander's own messages last, where the
    sentence reads better than at its start, then the text the lines are
    filtered by. Either can be absent, but not both.
    """
    matching = f'lines matching "{text}"' if text else ""
    if not runs:
        return f"Showing only {matching}"
    ordered = sorted(runs, key=lambda run: (run.run_id == COMMANDER_RUN, run.run_id))
    subjects = [run.bar_subject for run in ordered]
    listed = (
        subjects[0]
        if len(subjects) == 1
        else f"{', '.join(subjects[:-1])} and {subjects[-1]}"
    )
    if ordered[0].run_id == COMMANDER_RUN:  # Commander's alone
        description = f"Showing only {listed}"
    else:
        description = f"Showing only output from {listed}"
    return f"{description} · {matching}" if matching else description


@dataclass
class OutputEntry:
    """
    One call's worth of text in the output window, which may be several lines,
    and the run it came from. The entries are the window's contents; what the
    widget holds is the view of them the current filter allows.
    """

    run_id: int
    text: str
    # An 'Executing:' line, which belongs to its command's run and is also one
    # of Commander's own messages: Commander prints it, with Commander's PID, so
    # a user reading the PID on it can mean either.
    announcement: bool = False

    @property
    def lines(self) -> int:
        return block_count(self.text)

    @property
    def runs(self) -> list[int]:
        """
        The runs this entry is shown under, its command's first.
        """
        return [self.run_id, COMMANDER_RUN] if self.announcement else [self.run_id]

    def shown_under(self, run_ids: frozenset[int] | None) -> bool:
        """
        Whether a filter to 'run_ids' shows this entry; None shows everything.
        """
        return run_ids is None or any(run_id in run_ids for run_id in self.runs)

    def lines_shown(
        self, run_ids: frozenset[int] | None, pattern: re.Pattern[str] | None
    ) -> list[tuple[int, str]]:
        """
        The lines of this entry a filter to 'run_ids' and 'pattern' shows, each
        with its number in the entry: none if its run is filtered out, else
        those 'pattern' is found in, or every line with no pattern. A line is
        what Qt makes a block of, so the numbers count blocks.
        """
        if not self.shown_under(run_ids):
            return []
        return [
            (number, line)
            for number, line in enumerate(BLOCK_SEPARATORS.split(self.text))
            if pattern is None or pattern.search(line)
        ]


class LineBuffer:
    """
    Accumulates raw bytes read from a subprocess output channel and yields
    complete lines. Pipe reads don't respect line boundaries (or UTF-8
    character boundaries), so any partial trailing line is held back until the
    rest of it arrives; without this, appending each read to the log pane
    inserts a spurious line break wherever a read boundary happens to fall.
    """

    def __init__(self):
        self._decoder = getincrementaldecoder("utf-8")(errors="replace")
        self._partial_line = ""

    def feed(self, data: bytes) -> list[str]:
        """
        Add the bytes from one read and return the lines completed by them.
        """
        self._partial_line += self._decoder.decode(data)
        *lines, self._partial_line = self._partial_line.split("\n")
        return [line.rstrip("\r") for line in lines]

    def flush(self) -> list[str]:
        """
        Return any unterminated final line. Only safe to call once no more
        data is coming, i.e. when the process has exited.
        """
        self._partial_line += self._decoder.decode(b"", final=True)
        remainder, self._partial_line = self._partial_line.rstrip("\r"), ""
        return [remainder] if remainder else []


def message_prefix(pid: int) -> str:
    """
    The prefix the CLI gives each message it prints: the time, and the PID of
    the process printing it.
    """
    return f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({pid:06d}) : "


# How the line announcing each command Commander runs begins: the output
# window shows its message in bold, so each command's output has a heading
EXECUTING = "Executing: "

# The prefix of a message, with or without the PID ('--pp')
MESSAGE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} (?:\(\d+\) )?: ")

# The pieces of a JSON line the output window colours, by kind
JSON_KEY = "key"
JSON_STRING = "string"
JSON_NUMBER = "number"
JSON_LITERAL = "literal"  # true, false, null
JSON_BRACKET = "bracket"

_JSON_STRING = r'"(?:[^"\\]|\\.)*"'
_JSON_NUMBER = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
_JSON_VALUE_START = rf"(?:{_JSON_STRING}|{_JSON_NUMBER}|true|false|null|[{{\[])"
# A line of indented JSON: a key and the start of its value, an element of a
# list, or brackets alone (with a trailing comma, or '{}'/'[]'); or a whole
# document on one line, from an opening to a closing bracket
_JSON_LINE = re.compile(
    rf"^\s*(?:"
    rf"{_JSON_STRING}\s*:\s*{_JSON_VALUE_START}.*"
    rf"|(?:{_JSON_STRING}|{_JSON_NUMBER}|true|false|null),?"
    rf"|[{{\[\]}}]{{1,2}},?"
    rf"|[{{\[].*[}}\]],?"
    rf")\s*$"
)
_JSON_TOKEN = re.compile(
    rf"(?P<key>{_JSON_STRING})(?=\s*:)"
    rf"|(?P<string>{_JSON_STRING})"
    rf"|(?P<number>(?<![\w.]){_JSON_NUMBER}(?![\w.]))"
    rf"|(?P<literal>\b(?:true|false|null)\b)"
    rf"|(?P<bracket>[{{}}\[\]])"
)


def json_tokens(text: str) -> list[tuple[int, int, str]]:
    """
    The pieces of a line of JSON to colour, as (start, length, kind), or none
    for a line that is not JSON. Judged by the line's shape alone, with no
    memory of the lines before it, so that it holds when the text filter
    shows only some of a document's lines; a line with a message prefix (a
    message, not output) is never JSON.
    """
    if not _JSON_LINE.match(text) or MESSAGE_PREFIX.match(text):
        return []
    return [
        (match.start(), match.end() - match.start(), str(match.lastgroup))
        for match in _JSON_TOKEN.finditer(text)
    ]


# The pieces of a TOML line the file viewer colours beyond JSON's kinds
TOML_TABLE = "table"  # a [table] or [[array of tables]] heading
TOML_COMMENT = "comment"

_TOML_BASIC_STRING = r'"(?:[^"\\]|\\.)*"'
_TOML_LITERAL_STRING = r"'[^']*'"
_TOML_SIMPLE_KEY = rf"(?:[A-Za-z0-9_-]+|{_TOML_BASIC_STRING}|{_TOML_LITERAL_STRING})"
_TOML_KEY = rf"{_TOML_SIMPLE_KEY}(?:\s*\.\s*{_TOML_SIMPLE_KEY})*"
# A heading: a key in single or double brackets, alone on its line but for a
# comment
_TOML_HEADING = re.compile(
    rf"^\s*(?P<table>\[\[?\s*{_TOML_KEY}\s*\]\]?)\s*(?P<comment>#.*)?$"
)
_TOML_DATE = (
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?"
    r"|\d{2}:\d{2}:\d{2}(?:\.\d+)?"
)
_TOML_NUMBER = (
    r"[+-]?(?:0x[0-9A-Fa-f_]+|0o[0-7_]+|0b[01_]+"
    r"|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d[\d_]*)?)"
)
# Scanned left to right, so a '#' or '=' inside a string is the string's; a
# multi-line string's opening or closing quotes are coloured, not its text
_TOML_TOKEN = re.compile(
    rf"(?P<comment>#.*$)"
    rf"|(?P<key>{_TOML_KEY})(?=\s*=(?!=))"
    rf'|(?P<string>"""|\'\'\'|{_TOML_BASIC_STRING}|{_TOML_LITERAL_STRING})'
    rf"|(?P<number>(?<![\w.:-])(?:{_TOML_DATE}|{_TOML_NUMBER})(?![\w.:-]))"
    rf"|(?P<literal>(?<![\w.-])(?:true|false|[+-]?inf|[+-]?nan)(?![\w.-]))"
    rf"|(?P<bracket>[\[\]{{}}])"
)


def toml_tokens(text: str) -> list[tuple[int, int, str]]:
    """
    The pieces of a line of a TOML document to colour, as (start, length,
    kind): a table heading (TOML_TABLE), a key, a string, a number or date, a
    literal (true, false, inf, nan), a bracket, a comment (TOML_COMMENT).
    Judged line by line, as json_tokens() is, so that it holds when the text
    filter shows only some of the document's lines; the text of a multi-line
    string is read as TOML too, so may be coloured where it is not.
    """
    if heading := _TOML_HEADING.match(text):
        return [
            (heading.start(kind), heading.end(kind) - heading.start(kind), kind)
            for kind in (TOML_TABLE, TOML_COMMENT)
            if heading.group(kind) is not None
        ]
    return [
        (match.start(), match.end() - match.start(), str(match.lastgroup))
        for match in _TOML_TOKEN.finditer(text)
    ]
