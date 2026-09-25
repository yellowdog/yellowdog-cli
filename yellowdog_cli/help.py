#!/usr/bin/env python3

"""
List all available yd-* commands and their purposes.
"""

from yellowdog_cli._version import __version__
from yellowdog_cli.utils.command_registry import COMMANDS


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
    width = column_width()
    print(f"\nYellowDog CLI v{__version__} — available commands:\n")
    for name, summary in _listing():
        print(f"  {name:<{width}}  {summary}")
    print()


if __name__ == "__main__":
    main()
