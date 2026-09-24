"""
Entry point for the yd-commander GUI. Kept free of PyQt6 and of the heavy CLI
imports (which parse sys.argv at import time) so that argument parsing and the
optional-extra guard can run and report friendly messages before any Qt import
is attempted.
"""

import argparse
import sys
from os.path import abspath, isfile

from yellowdog_cli.commander.startup import StartupSettings, variable_is_complete
from yellowdog_cli.utils.check_imports import check_commander_imports

# Deleted from a field by Commander's edit-box handler, so a value containing
# one could not be held as given
FIELD_STRIPPED_CHARS = "\t\n\r"


def _field_value(value: str) -> str:
    """
    A value for one of the single-line text fields: non-empty, and holding
    nothing the field would delete.
    """
    if not value:
        raise argparse.ArgumentTypeError("must not be empty")
    if any(char in value for char in FIELD_STRIPPED_CHARS):
        raise argparse.ArgumentTypeError(
            f"'{value}' must be a single line with no tabs"
        )
    return value


def _variable(value: str) -> str:
    """
    A 'name=value' for the user-variables box. Whitespace is refused because
    the box is split on it when a command is built: 'title=my run' would reach
    the CLI as the two tokens 'title=my' and 'run'.
    """
    if any(char.isspace() for char in value):
        raise argparse.ArgumentTypeError(
            f"'{value}' contains whitespace, which the User Variables field cannot hold"
        )
    if not variable_is_complete(value):
        raise argparse.ArgumentTypeError(f"'{value}' is not of the form name=value")
    return value


def _existing_file(value: str) -> str:
    """
    A file that must exist now: one named on the command line is a file the
    user meant, so a missing one fails the launch rather than starting without
    it. Made absolute against the launch directory, which is what a relative
    path typed in a shell means.
    """
    if not isfile(value):
        raise argparse.ArgumentTypeError(f"file '{value}' does not exist")
    return abspath(value)


def parse_args(argv: list[str] | None = None) -> StartupSettings:
    parser = argparse.ArgumentParser(
        prog="yd-commander",
        description="Launch the YellowDog Commander desktop GUI.",
        epilog=(
            "The namespace, tag, name, path and variable options only fill in"
            " Commander's fields at startup; they can be edited or cleared in"
            " the window afterwards."
        ),
    )
    parser.add_argument(
        "config_file",
        nargs="?",
        metavar="<config_file.toml>",
        type=_existing_file,
        help="optional TOML configuration file to pre-select on startup",
    )
    parser.add_argument(
        "--config",
        "-c",
        dest="config_option",
        metavar="<config_file.toml>",
        type=_existing_file,
        help="the configuration file, as an option rather than an argument",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="disable destructive-action confirmation dialogs",
    )
    parser.add_argument(
        "--namespace",
        "-n",
        metavar="<namespace>",
        type=_field_value,
        help="fill the Namespace field",
    )
    parser.add_argument(
        "--tag",
        "-t",
        metavar="<tag>",
        type=_field_value,
        help="fill the Tag field",
    )
    parser.add_argument(
        "--name",
        metavar="<glob>",
        type=_field_value,
        help="fill the Name field (the name pattern for the destructive actions)",
    )
    parser.add_argument(
        "--path",
        "-P",
        metavar="<object-path>",
        type=_field_value,
        help="fill the Path field (the object path to download or delete)",
    )
    parser.add_argument(
        "--variable",
        "-v",
        action="append",
        default=[],
        metavar="<name=value>",
        type=_variable,
        help="add a variable to the User Variables field; can be repeated",
    )
    parser.add_argument(
        "--work-requirement",
        "-r",
        metavar="<file.json|file.jsonnet>",
        type=_existing_file,
        help="select a Work Requirement definition file",
    )
    parser.add_argument(
        "--worker-pool",
        "-p",
        metavar="<file.json|file.jsonnet>",
        type=_existing_file,
        help="select a Worker Pool definition file",
    )
    args = parser.parse_args(argv)

    if args.config_file is not None and args.config_option is not None:
        parser.error(
            "give the configuration file once, either as an argument or with -c"
        )

    return StartupSettings(
        config_file=args.config_file or args.config_option,
        disable_confirmations=args.yes,
        namespace=args.namespace,
        tag=args.tag,
        name_glob=args.name,
        object_path=args.path,
        variables=tuple(args.variable),
        wr_file=args.work_requirement,
        wp_file=args.worker_pool,
    )


def main():
    settings = parse_args()

    try:
        check_commander_imports()
    except ImportError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    # Imported only after the guard passes (this import pulls in PyQt6).
    from yellowdog_cli.commander.commander import run_app

    run_app(settings)


if __name__ == "__main__":
    main()
