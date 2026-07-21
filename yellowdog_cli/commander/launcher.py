"""
Entry point for the yd-commander GUI. Kept free of PyQt6 and of the heavy CLI
imports (which parse sys.argv at import time) so that argument parsing and the
optional-extra guard can run and report friendly messages before any Qt import
is attempted.
"""

import argparse
import sys

from yellowdog_cli.utils.check_imports import check_commander_imports


def main():
    parser = argparse.ArgumentParser(
        prog="yd-commander",
        description="Launch the YellowDog Commander desktop GUI.",
    )
    parser.add_argument(
        "config_file",
        nargs="?",
        metavar="<config_file.toml>",
        help="optional TOML configuration file to pre-select on startup",
    )
    args = parser.parse_args()

    try:
        check_commander_imports()
    except ImportError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    # Imported only after the guard passes (this import pulls in PyQt6).
    from yellowdog_cli.commander.commander import run_app

    run_app(args.config_file)


if __name__ == "__main__":
    main()
