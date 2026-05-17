#!/usr/bin/env python3

"""
Report version numbers, etc.
"""

from argparse import ArgumentParser
from os.path import abspath
from sys import executable, path
from sys import version as py_version

from yellowdog_client._version import __version__ as yd_sdk_version

from yellowdog_cli import __author__, __email__
from yellowdog_cli._version import __version__

DOCS_URL = f"https://github.com/yellowdog/yellowdog-cli/blob/v{__version__}/README.md"


def _jsonnet_version() -> str:
    try:
        from _jsonnet import version

        # Strip the initial 'v' if present
        return version[1:] if version.startswith("v") else version
    except ImportError:
        return "Not installed"


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
    parser.add_argument(
        "--debug", action="store_true", help="print Python path and executable details"
    )
    args = parser.parse_args()

    if args.cli:
        print(__version__)
        return
    if args.sdk:
        print(yd_sdk_version)
        return
    if args.python:
        print(py_version.split()[0])
        return
    if args.jsonnet:
        version = _jsonnet_version()
        if version == "Not installed":
            exit(1)
        print(version)
        return

    print(f"  YellowDog CLI Version:   {__version__} (Docs: {DOCS_URL})")
    print(f"  YellowDog SDK Version:   {yd_sdk_version}")
    print(f"  Jsonnet Version:         {_jsonnet_version()}")
    print(f"  Python Version:          {py_version.split()[0]} ")
    print(f"  Author:                  {__author__} ({__email__}) ")
    if args.debug:
        print(f"  Command:                 {abspath(__file__)}")
        print(f"  Python Executable:       {executable}")
        for i, p in enumerate(path, start=1):
            print(f"    Path-{str(i).zfill(2)}:               {p}")


if __name__ == "__main__":
    main()
