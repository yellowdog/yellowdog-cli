#!/usr/bin/env python3

"""
Report version numbers, etc.
"""

import json
import sys
from argparse import ArgumentParser
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, metadata
from importlib.metadata import version as package_version
from os.path import abspath
from sys import executable, path
from sys import version as py_version

from rich.markup import escape
from tabulate import tabulate

from yellowdog_cli import __author__, __email__
from yellowdog_cli._version import __version__
from yellowdog_cli.utils.compact_json import CompactJSONEncoder
from yellowdog_cli.utils.dataclient.rclone_version import (
    NOT_INSTALLED,
    UNKNOWN,
    find_rclone,
)
from yellowdog_cli.utils.dataclient.rclone_version import (
    rclone_version as _rclone_version,
)
from yellowdog_cli.utils.output_settings import configure_output
from yellowdog_cli.utils.output_style import JSON_INDENT
from yellowdog_cli.utils.printing import (
    CONSOLE,
    CONSOLE_TABLE,
    indent,
    print_json_text,
)
from yellowdog_cli.utils.version_info import docs_url, sdk_version

CLI_DISTRIBUTION = "yellowdog-cli"
UNKNOWN_LICENCE = "Unknown"
# The report's indentation, as yd-list's tables have
INDENT = 4


def readable(version: str) -> str | None:
    """
    A version as a caller can use it: None when it is not installed, or
    could not be read ('unknown', an rclone that would not run).
    """
    return None if version in (NOT_INSTALLED, UNKNOWN) else version


def cli_licence() -> str:
    """
    The CLI's licence, from its package metadata ('License-Expression', or
    the older 'License' field), so that pyproject.toml is the one place it
    is stated.
    """
    try:
        dist_metadata = metadata(CLI_DISTRIBUTION)
    except PackageNotFoundError:
        return UNKNOWN_LICENCE
    for field in ("License-Expression", "License"):
        values = dist_metadata.get_all(field)
        if values and values[0]:
            return values[0]
    return UNKNOWN_LICENCE


def _jsonnet_version() -> str:
    try:
        from _jsonnet import version

        # Strip the initial 'v' if present
        return version[1:] if version.startswith("v") else version
    except ImportError:
        return NOT_INSTALLED


def _mcp_version() -> str:
    """
    The 'mcp' extra's SDK version, from its package metadata: read without
    importing the package, which keeps yd-version standalone and fast.
    """
    try:
        return package_version("mcp")
    except PackageNotFoundError:
        return NOT_INSTALLED


def main():
    parser = ArgumentParser(
        prog="yd-version",
        description="Report YellowDog CLI and related version numbers.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--cli", action="store_true", help="print CLI version number only"
    )
    group.add_argument(
        "--sdk", action="store_true", help="print SDK version number only"
    )
    group.add_argument(
        "--python", action="store_true", help="print Python version number only"
    )
    group.add_argument(
        "--jsonnet", action="store_true", help="print Jsonnet version number only"
    )
    group.add_argument(
        "--rclone", action="store_true", help="print rclone version number only"
    )
    group.add_argument(
        "--mcp", action="store_true", help="print the MCP SDK version number only"
    )
    group.add_argument(
        "--json",
        action="store_true",
        help=(
            "print the version numbers, author and licence as a JSON object,"
            " null for a version not installed; with --debug, the Python"
            " executable and path too"
        ),
    )
    parser.add_argument(
        "--debug", action="store_true", help="print Python path and executable details"
    )
    parser.add_argument(
        "--no-format",
        "--nf",
        action="store_true",
        help="print the report without colouring",
    )
    args = parser.parse_args()
    # --no-format, for print_json_text()
    configure_output(args)

    single: dict[str, Callable[[], str]] = {
        "cli": lambda: __version__,
        "sdk": sdk_version,
        "python": lambda: py_version.split()[0],
        "jsonnet": _jsonnet_version,
        "rclone": _rclone_version,
        "mcp": _mcp_version,
    }
    chosen = [name for name in single if getattr(args, name)]
    if chosen and args.debug:
        parser.error(f"--debug cannot be used with --{chosen[0]}")

    if args.json:
        _print_json(debug=args.debug)
        return

    if chosen:
        # The version alone, for a script to use: nothing, and exit 1, when
        # it is not installed or could not be read
        version = readable(single[chosen[0]]())
        if version is None:
            sys.exit(1)
        print(version)
        return

    _print_report(debug=args.debug, no_format=args.no_format)


def _print_report(debug: bool, no_format: bool) -> None:
    """
    The versions as a table, then the author, licence and documentation
    link beneath it, where the link's length cannot widen the table, and
    with --debug a second table of where the CLI is running from. Coloured
    as yd-list's tables and messages are; Rich drops the colour by itself
    where stdout is not a terminal, or NO_COLOR is set.
    """
    versions = [
        ["YellowDog CLI", __version__],
        ["YellowDog SDK", sdk_version()],
        ["Python", py_version.split()[0]],
        ["Jsonnet", _jsonnet_version()],
        ["rclone", _rclone_version()],
        ["MCP SDK", _mcp_version()],
    ]
    _print_table(["Component", "Version"], versions, no_format)
    _print_line("", no_format)
    _print_line(f"Author:  {__author__} ({__email__})", no_format)
    _print_line(f"Licence: {cli_licence()}", no_format)
    _print_line(f"Docs:    {docs_url()}", no_format)
    if debug:
        rclone = find_rclone()
        details = [
            ["Command", abspath(__file__)],
            ["rclone Binary", f"{rclone[0]} ({rclone[1]})" if rclone else "Not found"],
            ["Python Executable", executable],
        ] + [[f"Path-{i:02d}", entry] for i, entry in enumerate(path, start=1)]
        _print_line("", no_format)
        _print_table(["Detail", "Value"], details, no_format)


def _print_table(headers: list[str], rows: list[list[str]], no_format: bool) -> None:
    table = indent(tabulate(rows, headers=headers, tablefmt="simple_outline"), INDENT)
    if no_format:
        print(table)
    else:
        CONSOLE_TABLE.print(escape(table), soft_wrap=True)


def _print_line(line: str, no_format: bool) -> None:
    text = indent(line, INDENT) if line else ""
    if no_format:
        print(text)
    else:
        CONSOLE.print(escape(text), soft_wrap=True)


def _print_json(debug: bool) -> None:
    """
    Print the versions as one JSON object: coloured on a terminal, and
    otherwise, for a script, the text alone.
    """

    # null for a version not installed, or one that could not be read
    document: dict = {
        "cli": __version__,
        "sdk": readable(sdk_version()),
        "python": py_version.split()[0],
        "jsonnet": readable(_jsonnet_version()),
        "rclone": readable(_rclone_version()),
        "mcp": readable(_mcp_version()),
        "author": {"name": __author__, "email": __email__},
        "licence": cli_licence(),
    }
    if debug:
        document["executable"] = executable
        document["path"] = list(path)
    print_json_text(json.dumps(document, indent=JSON_INDENT, cls=CompactJSONEncoder))


if __name__ == "__main__":
    main()
