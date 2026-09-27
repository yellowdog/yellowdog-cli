#!/usr/bin/env python3

"""
List all available yd-* commands and their purposes.
"""

import json
import re
from argparse import ArgumentParser

from rich.console import Console
from rich.text import Text
from rich.theme import Theme

from yellowdog_cli._version import __version__
from yellowdog_cli.utils.command_registry import COMMANDS
from yellowdog_cli.utils.compact_json import CompactJSONEncoder
from yellowdog_cli.utils.settings import DEFAULT_THEME, JSON_INDENT

# The CLI's theme, as printing.py uses it: a command name in the style of a
# table's content, and a note -- the extra a command needs, or what it is a
# synonym for -- dimmed so the summaries proper stand out. printing.py itself
# is not imported: it parses the command line for a registered command at
# import, and yd-help is not one.
NAME_STYLE = "pyexamples.table_content"
NOTE_STYLE = "dim"
HEADING_STYLE = "bold"
# The notes dimmed: a trailing '(needs the <extra> extra)' or '(synonym: yd-x)'
# -- never a parenthesis inside the summary's own prose ('Hold (pause) ...')
NOTE = re.compile(r" \((needs the \w+ extra|synonym: yd-[\w-]+)\)$")

# The entry points that are not registry commands: they take none of the
# CLI's options, so the registry has nothing to say about them, but a user
# has them all the same (each prints the install hint for its extra when
# that is missing). tests/test_command_registry.py holds this table to
# pyproject.toml's entry points less the registry, so a new entry point is
# listed by one or the other.
OTHER_COMMANDS: dict[str, str] = {
    "yd-commander": "Launch the Commander desktop GUI (needs the commander extra)",
    "yd-mcp": "Run the MCP server over the yd-* commands (needs the mcp extra)",
}


def _listing() -> list[tuple[str, str]]:
    # An alias (yd-rm, which shares yd-delete's entry) gets a line of its own
    # saying what it is a synonym for, rather than its target's summary twice
    return sorted(
        [
            (name, cmd.summary if cmd.name == name else f"A synonym for {cmd.name}")
            for name, cmd in COMMANDS.items()
        ]
        + list(OTHER_COMMANDS.items())
    )


def column_width() -> int:
    return max(len(name) for name, _ in _listing())


def main():
    parser = ArgumentParser(
        prog="yd-help",
        description="List the available yd-* commands and their purposes.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the commands as a JSON array of their names and summaries",
    )
    parser.add_argument(
        "--no-format",
        "--nf",
        action="store_true",
        help="print the listing without colouring",
    )
    args = parser.parse_args()

    if args.json:
        print(
            json.dumps(
                [{"command": name, "summary": summary} for name, summary in _listing()],
                indent=JSON_INDENT,
                cls=CompactJSONEncoder,
            )
        )
        return

    if args.no_format:
        width = column_width()
        print(f"\n{_heading()}\n")
        for name, summary in _listing():
            print(f"  {name:<{width}}  {summary}")
        print()
        return

    # Rich drops the styles by itself where stdout is not a terminal, or
    # NO_COLOR is set; soft_wrap keeps a long summary on its one line
    console = Console(theme=Theme(DEFAULT_THEME), highlight=False)
    console.print()
    console.print(Text(_heading(), style=HEADING_STYLE), soft_wrap=True)
    console.print()
    for line in styled_lines():
        console.print(line, soft_wrap=True)
    console.print()


def _heading() -> str:
    return f"YellowDog CLI v{__version__} — available commands:"


def styled_lines() -> list[Text]:
    """
    One Text per command: the padded name in NAME_STYLE, then the summary,
    with a trailing extra or synonym note in NOTE_STYLE.
    """
    width = column_width()
    lines: list[Text] = []
    for name, summary in _listing():
        line = Text("  ")
        line.append(f"{name:<{width}}", style=NAME_STYLE)
        line.append("  ")
        match = NOTE.search(summary)
        if match:
            line.append(summary[: match.start()])
            line.append(match.group(0), style=NOTE_STYLE)
        else:
            line.append(summary)
        lines.append(line)
    return lines


if __name__ == "__main__":
    main()
