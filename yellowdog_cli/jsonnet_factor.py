#!/usr/bin/env python3

"""
yd jsonnet factor: a JSON (or Jsonnet) list of specifications, such as
'yd list --details' writes, printed as Jsonnet with what each kind of
specification shares held once in a 'local' base and each specification
written as its differences from it (utils/jsonnet_factor.py). The text is
evaluated before it is printed, and printed only if it gives back the
same JSON. Errors go to stderr, so a failure redirected to a file leaves
nothing in it. With --write, each .json file (or a pattern's matches) is
written to <name>.jsonnet beside it (utils/file_conversion.py); a .jsonnet
file is skipped there, since its own name is where it would be written.
"""

import json
import sys

from yellowdog_cli.utils.check_imports import check_jsonnet_import
from yellowdog_cli.utils.command_registry import COMMANDS, build_parser
from yellowdog_cli.utils.file_conversion import (
    is_glob_pattern,
    parsed_json,
    write_conversions,
)
from yellowdog_cli.utils.invocation import selected_prog
from yellowdog_cli.utils.jsonnet_style import JSONNET_EXTENSION, is_jsonnet_path
from yellowdog_cli.utils.output_encoding import use_utf8_output
from yellowdog_cli.utils.output_settings import configure_output
from yellowdog_cli.utils.output_style import ERROR_MARKER

STDIN_PATH = "-"
JSON_EXTENSION = ".json"


def main():
    use_utf8_output()
    parser = build_parser(
        COMMANDS["yd-jsonnet-factor"], prog=selected_prog("yd jsonnet factor")
    )
    args = parser.parse_args()
    # --yes, for confirmed()
    configure_output(args)
    if args.write and STDIN_PATH in args.files:
        parser.error(
            "standard input ('-') has no file to write beside; leave out --write"
        )
    # Several texts on stdout would be no Jsonnet file
    if not args.write and (len(args.files) > 1 or is_glob_pattern(args.files[0])):
        parser.error(
            "several files or a glob pattern are written beside their sources"
            " with --write; without it, give one file, whose Jsonnet goes to stdout"
        )

    # No wrapper to catch and print an exception: the guard's advice about
    # installing Jsonnet is printed here rather than buried in a traceback
    try:
        check_jsonnet_import()
    except ImportError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    from yellowdog_cli.utils.jsonnet_factor import (
        FactoringError,
        factored_and_checked,
    )

    def factored_file(path: str) -> str:
        specifications = _read(path)
        if not isinstance(specifications, list):
            raise ValueError(
                "it holds a single object, not a list of specifications to factor"
            )
        return factored_and_checked(specifications)

    if args.write:
        errors = write_conversions(
            args.files, JSON_EXTENSION, JSONNET_EXTENSION, "JSON", factored_file
        )
        if errors:
            sys.exit(1)
        return

    path = args.files[0]
    try:
        text = factored_file(path)
    except (OSError, ValueError, RuntimeError, FactoringError) as e:
        # parsed_json() raises a ValueError, and _jsonnet a RuntimeError for
        # a file that does not evaluate
        name = "standard input" if path == STDIN_PATH else f"'{path}'"
        print(f"{ERROR_MARKER}Cannot factor {name}: {e}", file=sys.stderr)
        sys.exit(1)
    sys.stdout.write(text)


def _read(path: str):
    """
    The specifications in 'path': JSON, or Jsonnet evaluated for a
    '.jsonnet' file; '-' is standard input, read as JSON.
    """
    if path == STDIN_PATH:
        return parsed_json(sys.stdin.read(), path)
    if is_jsonnet_path(path):
        from _jsonnet import evaluate_file

        return json.loads(evaluate_file(path))
    with open(path, encoding="utf-8") as f:
        return parsed_json(f.read(), path)


# Entry point
if __name__ == "__main__":
    main()
