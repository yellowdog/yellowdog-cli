"""
The output window's model: where each piece of text came from (OutputRun,
OutputEntry), how many blocks it makes in the widget, and the reassembly of
a child process's output into lines. Qt-free; the window in commander.py
is the view of it.
"""

import re
from codecs import getincrementaldecoder
from dataclasses import dataclass
from datetime import datetime

# The run Commander's own messages belong to in the output window; the commands it
# launches are numbered from 1. See OutputRun.
COMMANDER_RUN = 0
# What starts a new block when text is put into a QTextDocument: a line feed, a
# carriage return (alone or before a line feed, which together make one), Unicode's
# paragraph separator, and Qt's two frame markers. The output window's blocks are
# tagged with the entry they came from by counting them, so the count must be Qt's.
BLOCK_SEPARATORS = re.compile(r"\r\n|[\r\n\u2029\ufdd0\ufdd1]")


def block_count(text: str) -> int:
    """
    The number of blocks 'text' becomes in a QTextDocument; see BLOCK_SEPARATORS.
    """
    return len(BLOCK_SEPARATORS.split(text))


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
    command: str  # the program run, e.g. 'yd-submit'; empty for Commander
    command_line: str = ""  # as echoed on the 'Executing:' line
    # As the user would recognise it: without the config source, namespace, tag,
    # variables and '--nf --pp' that Commander adds to every 'yd-*' command
    user_command_line: str = ""
    started_at: datetime | None = None
    pid: int | None = None  # as QProcess reports it, once started
    # 'exit N' or 'crashed' once finished, 'did not start' if it never did;
    # None while running
    outcome: str | None = None
    # The PID the command printed in its own message prefixes, preferred for
    # display because it is the one the user sees in the output; QProcess's can
    # differ where a console-script launcher stands between the two.
    printed_pid: int | None = None

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


def filter_description(runs: list[OutputRun]) -> str:
    """
    What the filter bar says is shown: 'Showing only' and the runs, commands
    in the order they started and Commander's own messages last, where the
    sentence reads better than at its start.
    """
    ordered = sorted(runs, key=lambda run: (run.run_id == COMMANDER_RUN, run.run_id))
    subjects = [run.bar_subject for run in ordered]
    listed = (
        subjects[0]
        if len(subjects) == 1
        else f"{', '.join(subjects[:-1])} and {subjects[-1]}"
    )
    if ordered[0].run_id == COMMANDER_RUN:  # Commander's alone
        return f"Showing only {listed}"
    return f"Showing only output from {listed}"


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
        """The runs this entry is shown under, its command's first."""
        return [self.run_id, COMMANDER_RUN] if self.announcement else [self.run_id]

    def shown_under(self, run_ids: frozenset[int] | None) -> bool:
        """Whether a filter to 'run_ids' shows this entry; None shows everything."""
        return run_ids is None or any(run_id in run_ids for run_id in self.runs)


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
