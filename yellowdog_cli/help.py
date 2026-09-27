#!/usr/bin/env python3

"""
List all available yd-* commands and their purposes.
"""

import json
from argparse import ArgumentParser

from yellowdog_cli._version import __version__
from yellowdog_cli.utils.command_registry import COMMANDS
from yellowdog_cli.utils.compact_json import CompactJSONEncoder
from yellowdog_cli.utils.settings import JSON_INDENT


def _listing() -> list[tuple[str, str]]:
    # An alias (e.g. yd-rm, which shares yd-delete's entry) is mentioned in
    # its target's summary rather than listed twice, so only list a command
    # under its own name; yd-commander has no registry entry and, as before,
    # is not listed.
    return sorted(
        (name, cmd.summary) for name, cmd in COMMANDS.items() if cmd.name == name
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

    width = column_width()
    print(f"\nYellowDog CLI v{__version__} — available commands:\n")
    for name, summary in _listing():
        print(f"  {name:<{width}}  {summary}")
    print()


if __name__ == "__main__":
    main()
