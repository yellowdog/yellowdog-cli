#!/usr/bin/env python3

"""
Report version numbers, etc.
"""

import json
from argparse import ArgumentParser
from importlib.metadata import PackageNotFoundError, metadata
from importlib.metadata import version as package_version
from os.path import abspath
from sys import executable, path
from sys import version as py_version

from yellowdog_cli import __author__, __email__
from yellowdog_cli._version import __version__
from yellowdog_cli.utils.compact_json import CompactJSONEncoder
from yellowdog_cli.utils.rclone_version import find_rclone
from yellowdog_cli.utils.rclone_version import rclone_version as _rclone_version
from yellowdog_cli.utils.settings import JSON_INDENT

NOT_INSTALLED = "Not installed"
SDK_DISTRIBUTION = "yellowdog-sdk"
CLI_DISTRIBUTION = "yellowdog-cli"
UNKNOWN_LICENCE = "Unknown"

DOCS_URL = f"https://github.com/yellowdog/yellowdog-cli/blob/v{__version__}/README.md"


def sdk_version() -> str:
    """
    The installed YellowDog SDK's version, from its package metadata: read
    without importing the package, whose __init__ builds the whole Platform
    client (~140ms), so that nothing needs the SDK just to name it.
    """
    try:
        return package_version(SDK_DISTRIBUTION)
    except PackageNotFoundError:
        return NOT_INSTALLED


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
            "print the version numbers as a JSON object, null for one not"
            " installed; with --debug, the Python executable and path too"
        ),
    )
    parser.add_argument(
        "--debug", action="store_true", help="print Python path and executable details"
    )
    args = parser.parse_args()

    if args.json:
        _print_json(debug=args.debug)
        return

    if args.cli:
        print(__version__)
        return
    if args.sdk:
        print(sdk_version())
        return
    if args.python:
        print(py_version.split()[0])
        return
    if args.jsonnet:
        version = _jsonnet_version()
        if version == NOT_INSTALLED:
            exit(1)
        print(version)
        return
    if args.rclone:
        version = _rclone_version()
        if version == NOT_INSTALLED:
            exit(1)
        print(version)
        return
    if args.mcp:
        version = _mcp_version()
        if version == NOT_INSTALLED:
            exit(1)
        print(version)
        return

    print(f"  YellowDog CLI Version:   {__version__} (Docs: {DOCS_URL})")
    print(f"  YellowDog SDK Version:   {sdk_version()}")
    print(f"  Python Version:          {py_version.split()[0]} ")
    print(f"  Jsonnet Version:         {_jsonnet_version()}")
    print(f"  rclone Version:          {_rclone_version()}")
    print(f"  MCP SDK Version:         {_mcp_version()}")
    print(f"  Author:                  {__author__} ({__email__}) ")
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

    def installed(version: str) -> str | None:
        return None if version == NOT_INSTALLED else version

    document: dict = {
        "cli": __version__,
        "sdk": sdk_version(),
        "python": py_version.split()[0],
        "jsonnet": installed(_jsonnet_version()),
        "rclone": installed(_rclone_version()),
        "mcp": installed(_mcp_version()),
    }
    if debug:
        document["executable"] = executable
        document["path"] = list(path)
    print(json.dumps(document, indent=JSON_INDENT, cls=CompactJSONEncoder))


if __name__ == "__main__":
    main()
