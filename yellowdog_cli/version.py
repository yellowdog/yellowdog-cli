#!/usr/bin/env python3

"""
Report version numbers, etc.
"""

from os.path import abspath
from sys import argv, executable, path
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
    print(f"  YellowDog CLI Version:   {__version__} (Docs: {DOCS_URL})")
    print(f"  YellowDog SDK Version:   {yd_sdk_version}")
    print(f"  Jsonnet Version:         {_jsonnet_version()}")
    print(f"  Python Version:          {py_version.split()[0]} ")
    print(f"  Author:                  {__author__} ({__email__}) ")
    if "--debug" in argv:
        print(f"  Command:                 {abspath(__file__)}")
        print(f"  Python Executable:       {executable}")
        for i, p in enumerate(path, start=1):
            print(f"    Path-{str(i).zfill(2)}:               {p}")


if __name__ == "__main__":
    main()
