"""
How the CLI prints, prompts and selects, as the command line asks: quiet,
'--debug', '--json', '--no-format', the PID prefix, '--count', the output
file, stripped IDs, events as JSON, '--yes', interactive selection and the
listing's sort and detail. The code that prints and asks -- printing.py,
tables.py, interactive.py, results.py, event_printing.py, rclone's logging,
specs/validation.py -- reads OUTPUT, rather than the parsed command line, so
that it can be used and tested without one.

OUTPUT is one object, configured in place as a command starts
(configure_output(), by the wrappers' prepare_run(), yd-doctor and
yd-schema) and changed only through this module: a command that adjusts its
options for output (yd-list's '--count', its interactive selection;
yd-abort's) configures it again from them. configured() does so for the
length of a 'with' block, which is how a test sets it. Before anything
configures it, its defaults print everything, formatted.

Imports nothing from the CLI.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, fields
from typing import Any


@dataclass
class OutputSettings:
    quiet: bool | None = False
    debug: bool | None = False
    json_output: bool | None = False
    no_format: bool | None = False
    print_pid: bool | None = False
    count_only: bool | None = False
    output_file: str | None = None
    strip_ids: bool | None = False
    events_as_json: bool | None = False
    yes: bool | None = False
    interactive: bool | None = False
    auto_select_all: bool | None = False
    details: bool | None = False
    sort: str | None = None
    reverse: bool | None = None


OUTPUT = OutputSettings()

_DEFAULTS = OutputSettings()


def configure_output(args: Any) -> None:
    """
    Set OUTPUT from a parsed command line (or anything with the same
    attributes), in place; one it lacks takes its default.
    """
    for field in fields(OutputSettings):
        setattr(
            OUTPUT,
            field.name,
            getattr(args, field.name, getattr(_DEFAULTS, field.name)),
        )


def snapshot() -> OutputSettings:
    """
    A copy of OUTPUT as it is now.
    """
    return OutputSettings(
        **{f.name: getattr(OUTPUT, f.name) for f in fields(OutputSettings)}
    )


def restore(settings: OutputSettings) -> None:
    """
    Set OUTPUT back to a snapshot().
    """
    for field in fields(OutputSettings):
        setattr(OUTPUT, field.name, getattr(settings, field.name))


@contextmanager
def configured(args: Any) -> Generator[OutputSettings]:
    """
    OUTPUT configured from 'args' for the length of a 'with' block.
    """
    saved = snapshot()
    configure_output(args)
    try:
        yield OUTPUT
    finally:
        restore(saved)
