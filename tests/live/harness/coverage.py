"""
Which CLI commands the live suite ran: each command 'yd' ran, as the user
would type it ('yd workrequirement show', a noun's alias resolved; 'yd list'),
recorded when it exited as the test expected, by each process in a file of
its own under the session's coverage directory. The gate (gate()) compares
the record with every noun verb and top-level command, less NOT_EXERCISED,
each entry of which carries its reason.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from yellowdog_cli.utils.noun_registry import NOUNS
from yellowdog_cli.utils.top_level import TOP_LEVEL

_DIRECTORY: Path | None = None
# A noun's name and alias to its name, and its verbs
_NOUN_NAMES = {
    word: noun.name for noun in NOUNS for word in (noun.name, noun.alias) if word
}
_VERBS = {noun.name: {verb.name for verb in noun.verbs} for noun in NOUNS}
_COMMANDS = {word for word, entry in TOP_LEVEL.items() if entry.kind.name != "NOUN"}


def configure(directory: Path | None) -> None:
    global _DIRECTORY
    _DIRECTORY = directory


def command_of(args: Sequence[str]) -> str | None:
    """
    The command the arguments run, as the user would type it, or None.
    """
    if not args:
        return None
    first = args[0]
    noun = _NOUN_NAMES.get(first)
    if noun is not None:
        if len(args) > 1 and args[1] in _VERBS[noun]:
            return f"yd {noun} {args[1]}"
        return None
    if first in _COMMANDS:
        return f"yd {first}"
    return None


def record(args: Sequence[str]) -> None:
    command = command_of(args)
    if _DIRECTORY is None or command is None:
        return
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    with (_DIRECTORY / f"coverage-{worker}.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps({"command": command}) + "\n")


def recorded(directory: Path) -> set[str]:
    found: set[str] = set()
    for path in directory.glob("coverage-*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                found.add(json.loads(line)["command"])
    return found


def expected() -> set[str]:
    """
    Every noun verb, and every top-level command that is not a noun.
    """
    return {f"yd {noun} {verb}" for noun, verbs in _VERBS.items() for verb in verbs} | {
        f"yd {word}" for word in _COMMANDS
    }


_UNIT_TESTED = "offline, covered by the unit tests"

# What the live suite does not run, and why: commands with no live scenario,
# each with its reason
NOT_EXERCISED: dict[str, str] = {
    "yd cloudwizard": "builds its own cloud infrastructure; a separate design",
    "yd commander": "drives these same commands; its own suite",
    "yd mcp": "drives these same commands; its own suite",
    "yd help": _UNIT_TESTED,
    "yd version": _UNIT_TESTED,
    "yd completion": _UNIT_TESTED,
    "yd format-json": _UNIT_TESTED,
    "yd jsonnet2json": _UNIT_TESTED,
    "yd schema": (
        "never reaches the Platform, and takes neither --config nor --quiet;"
        " covered by the unit tests"
    ),
    "yd node stop": (
        "a Worker Pool takes a stopped node's instance away; stopping is"
        " exercised by 'yd instance stop' and 'yd cr stop'"
    ),
    "yd node restart": (
        "a Worker Pool takes a restarted node's instance away (live run"
        " ydst-2610131704-37bo: TERMINATED, no new Worker); restarting is exercised by"
        " 'yd instance restart'"
    ),
    "yd node start": (
        "a Worker Pool takes a stopped node's instance away; starting is"
        " exercised by 'yd instance start' and 'yd cr start'"
    ),
}

DATA_COMMANDS = frozenset(
    f"yd data {verb}" for verb in ("upload", "download", "list", "delete", "copy")
)


def gate(directory: Path, excluded: Mapping[str, str]) -> list[str]:
    """
    One line per command neither recorded, nor in NOT_EXERCISED, nor
    excluded for this session.
    """
    missing = expected() - recorded(directory) - set(NOT_EXERCISED) - set(excluded)
    return [f"not exercised: {command}" for command in sorted(missing)]
