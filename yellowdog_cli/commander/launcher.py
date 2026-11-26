"""
Entry point for the yd commander GUI. Kept free of PyQt6 and of the heavy CLI
imports (which parse sys.argv at import time) so that argument parsing and the
optional-extra guard can run and report friendly messages before any Qt import
is attempted.
"""

import argparse
import sys
from os.path import abspath, isfile

from yellowdog_cli.commander.arguments import (
    QuotingError,
    property_is_complete,
    quote_argument,
)
from yellowdog_cli.commander.startup import StartupSettings, variable_is_complete
from yellowdog_cli.utils.check_imports import check_commander_imports
from yellowdog_cli.utils.invocation import selected_prog

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


def _property(value: str) -> str:
    """
    A 'section.key=value' for the Properties box, returned quoted as the box
    needs it (see arguments.py), so that a value containing spaces, such as a
    JSON list, reaches the CLI as the one argument it was given as.
    """
    if any(char in value for char in FIELD_STRIPPED_CHARS):
        raise argparse.ArgumentTypeError(
            f"'{value}' must be a single line with no tabs"
        )
    if not property_is_complete(value):
        raise argparse.ArgumentTypeError(
            f"'{value}' is not of the form section.key=value"
        )
    try:
        return quote_argument(value)
    except QuotingError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


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


# The arguments that name a local file, which shell completion completes as
# files (utils/completion.py reads this parser for the launcher's options)
FILE_ARGUMENTS: tuple[str, ...] = (
    "config_file",
    "config_option",
    "work_requirement",
    "worker_pool",
)


def build_parser() -> argparse.ArgumentParser:
    """
    The launcher's options: parse_args() reads them, and shell completion
    offers them.
    """
    parser = argparse.ArgumentParser(
        prog=selected_prog("yd-commander"),
        description="Launch the YellowDog Commander desktop GUI.",
        epilog=(
            "The namespace, tag, name, path, variable and property options only fill in"
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
        "--reset-appearance",
        action="store_true",
        help=(
            "open with the window's default size and place, Dark Mode following"
            " the system, and the output's default text size"
        ),
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
        "--property",
        action="append",
        default=[],
        metavar="<section.key=value>",
        type=_property,
        help="add a property override to the Properties field; can be repeated",
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
    parser.add_argument(
        "--usage-explorer",
        action="store_true",
        help=(
            "open the Usage Explorer on its own, without the main window; it"
            " takes the configuration file, --property and -n (its starting"
            " namespace) and nothing else"
        ),
    )
    return parser


def parse_args(argv: list[str] | None = None) -> StartupSettings:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.config_file is not None and args.config_option is not None:
        parser.error(
            "give the configuration file once, either as an argument or with -c"
        )
    if args.usage_explorer:
        unused = [
            option
            for option, given in (
                ("-y/--yes", args.yes),
                ("--reset-appearance", args.reset_appearance),
                ("-t/--tag", args.tag is not None),
                ("--name", args.name is not None),
                ("-P/--path", args.path is not None),
                ("-v/--variable", bool(args.variable)),
                ("-r/--work-requirement", args.work_requirement is not None),
                ("-p/--worker-pool", args.worker_pool is not None),
            )
            if given
        ]
        if unused:
            parser.error(
                f"--usage-explorer does not take {', '.join(unused)}: it takes"
                " the configuration file, --property and -n only"
            )

    return StartupSettings(
        config_file=args.config_file or args.config_option,
        disable_confirmations=args.yes,
        namespace=args.namespace,
        tag=args.tag,
        name_glob=args.name,
        object_path=args.path,
        variables=tuple(args.variable),
        properties=tuple(args.property),
        wr_file=args.work_requirement,
        wp_file=args.worker_pool,
        reset_appearance=args.reset_appearance,
        usage_explorer=args.usage_explorer,
    )


def main():
    # Here rather than at the top: the launcher's imports stay light
    from yellowdog_cli.utils.top_level import warn_if_deprecated_script

    warn_if_deprecated_script("yd-commander")
    settings = parse_args()

    try:
        check_commander_imports()
    except ImportError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    # Imported only after the guard passes (these imports pull in PyQt6).
    if settings.usage_explorer:
        from yellowdog_cli.commander.usage_explorer_app import run_usage_explorer

        run_usage_explorer(settings)
    else:
        from yellowdog_cli.commander.commander import run_app

        run_app(settings)


if __name__ == "__main__":
    main()
