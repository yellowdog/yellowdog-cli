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

from yellowdog_cli import __author__, __email__
from yellowdog_cli._version import __version__
from yellowdog_cli.utils.compact_json import CompactJSONEncoder
from yellowdog_cli.utils.output_style import JSON_INDENT
from yellowdog_cli.utils.rclone_version import NOT_INSTALLED, UNKNOWN, find_rclone
from yellowdog_cli.utils.rclone_version import rclone_version as _rclone_version
from yellowdog_cli.utils.version_info import docs_url, sdk_version

CLI_DISTRIBUTION = "yellowdog-cli"
UNKNOWN_LICENCE = "Unknown"


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
    args = parser.parse_args()

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

    print(f"  YellowDog CLI Version:   {__version__} (Docs: {docs_url()})")
    print(f"  YellowDog SDK Version:   {sdk_version()}")
    print(f"  Python Version:          {py_version.split()[0]}")
    print(f"  Jsonnet Version:         {_jsonnet_version()}")
    print(f"  rclone Version:          {_rclone_version()}")
    print(f"  MCP SDK Version:         {_mcp_version()}")
    print(f"  Author:                  {__author__} ({__email__})")
    print(f"  Licence:                 {cli_licence()}")
    if args.debug:
        print(f"  Command:                 {abspath(__file__)}")
        rclone = find_rclone()
        rclone_str = f"{rclone[0]} ({rclone[1]})" if rclone else "Not found"
        print(f"  rclone Binary:           {rclone_str}")
        print(f"  Python Executable:       {executable}")
        for i, p in enumerate(path, start=1):
            print(f"    Path-{str(i).zfill(2)}:               {p}")


def _print_json(debug: bool) -> None:
    """
    Print the versions as one JSON object. Printed directly, like the rest
    of this command: yd-version has no CLI configuration, so printing.py,
    which needs it, is not used.
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
    print(json.dumps(document, indent=JSON_INDENT, cls=CompactJSONEncoder))


if __name__ == "__main__":
    main()
