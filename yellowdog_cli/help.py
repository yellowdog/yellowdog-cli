#!/usr/bin/env python3

"""
List all available yd-* commands and their purposes.
"""

import json
import re
from argparse import ArgumentParser
from importlib.util import find_spec

from rich.console import Console
from rich.text import Text
from rich.theme import Theme

from yellowdog_cli._version import __version__
from yellowdog_cli.utils.check_imports import EXTRA_PROBES
from yellowdog_cli.utils.command_registry import COMMANDS
from yellowdog_cli.utils.compact_json import CompactJSONEncoder
from yellowdog_cli.utils.output_settings import configure_output
from yellowdog_cli.utils.output_style import DEFAULT_THEME, JSON_INDENT
from yellowdog_cli.utils.printing import print_json_text
from yellowdog_cli.utils.version_info import docs_url

# The CLI's theme, as printing.py uses it: a command name in the style of a
# table's content, and a note -- the extra a command needs -- dimmed so the
# summaries proper stand out.
NAME_STYLE = "pyexamples.table_content"
NOTE_STYLE = "dim"
HEADING_STYLE = "bold"
# The notes dimmed: a trailing '(needs the <extra> extra)' or '(<extra>
# extra installed)' -- never a parenthesis inside the summary's own prose
# ('Hold (pause) ...')
NOTE = re.compile(r" \((needs the \w+ extra|\w+ extra installed)\)$")
# A summary's extra, as the registry and OTHER_COMMANDS write it
EXTRA = re.compile(r" \(needs the (\w+) extra\)$")


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
    return sorted(
        [(name, cmd.summary) for name, cmd in COMMANDS.items()]
        + list(OTHER_COMMANDS.items())
    )


def column_width() -> int:
    return max(len(name) for name, _ in _listing())


def extra_installed(extra: str) -> bool:
    """
    Whether an optional extra is installed: its probe package can be found.
    """
    return find_spec(EXTRA_PROBES[extra]) is not None


def entries() -> list[dict]:
    """
    The listing as '--json' gives it: each command's name and summary, with
    the extra it needs and whether that is installed as fields of their own,
    so that no script has to pick them out of the summary.
    """
    records = []
    for name, summary in _listing():
        record: dict = {"command": name, "summary": summary}
        if (match := EXTRA.search(summary)) is not None:
            record["extra"] = match.group(1)
            record["installed"] = extra_installed(match.group(1))
        records.append(record)
    return records


def shown_summary(summary: str) -> str:
    """
    A summary as the listing shows it: an extra that is installed says so,
    rather than that it is needed.
    """
    match = EXTRA.search(summary)
    if match is None or not extra_installed(match.group(1)):
        return summary
    return f"{summary[: match.start()]} ({match.group(1)} extra installed)"


def _footer() -> str:
    return (
        f"Run 'yd-<command> --help' for a command's options; documentation:"
        f" {docs_url()}"
    )


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
        help="print the listing, or the --json array, without colouring",
    )
    args = parser.parse_args()

    if args.json:
        # Coloured on a terminal, unless --no-format; otherwise the text alone
        configure_output(args)
        print_json_text(
            json.dumps(entries(), indent=JSON_INDENT, cls=CompactJSONEncoder)
        )
        return

    if args.no_format:
        width = column_width()
        print(f"\n{_heading()}\n")
        for name, summary in _listing():
            print(f"  {name:<{width}}  {shown_summary(summary)}")
        print(f"\n{_footer()}\n")
        return

    # Rich drops the styles by itself where stdout is not a terminal, or
    # NO_COLOR is set; soft_wrap keeps a long summary on its one line
    console = Console(theme=Theme(DEFAULT_THEME), highlight=False, emoji=False)
    console.print()
    console.print(Text(_heading(), style=HEADING_STYLE), soft_wrap=True)
    console.print()
    for line in styled_lines():
        console.print(line, soft_wrap=True)
    console.print()
    console.print(Text(_footer(), style=NOTE_STYLE), soft_wrap=True)
    console.print()


def _heading() -> str:
    return f"YellowDog CLI v{__version__} — available commands:"


def styled_lines() -> list[Text]:
    """
    One Text per command: the padded name in NAME_STYLE, then the summary,
    with a trailing extra note in NOTE_STYLE.
    """
    width = column_width()
    lines: list[Text] = []
    for name, summary in _listing():
        summary = shown_summary(summary)
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
