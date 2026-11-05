#!/usr/bin/env python3

"""
yd jsonnet factor: a JSON (or Jsonnet) list of specifications, such as
'yd list --details' writes, printed as Jsonnet with what each kind of
specification shares held once in a 'local' base and each specification
written as its differences from it (utils/jsonnet_factor.py). The text is
evaluated before it is printed, and printed only if it gives back the
same JSON. Errors go to stderr, so a failure redirected to a file leaves
nothing in it.
"""

import json
import sys

from yellowdog_cli.utils.check_imports import check_jsonnet_import
from yellowdog_cli.utils.command_registry import COMMANDS, build_parser
from yellowdog_cli.utils.invocation import selected_prog
from yellowdog_cli.utils.jsonnet_style import is_jsonnet_path
from yellowdog_cli.utils.output_encoding import use_utf8_output
from yellowdog_cli.utils.output_style import ERROR_MARKER

STDIN_PATH = "-"


def main():
    use_utf8_output()
    parser = build_parser(
        COMMANDS["yd-jsonnet-factor"], prog=selected_prog("yd jsonnet factor")
    )
    args = parser.parse_args()

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

    try:
        specifications = _read(args.file)
        if not isinstance(specifications, list):
            raise ValueError(
                "it holds a single object, not a list of specifications to factor"
            )
        text = factored_and_checked(specifications)
    except (OSError, ValueError, RuntimeError, FactoringError) as e:
        # json.JSONDecodeError is a ValueError, and _jsonnet raises a
        # RuntimeError for a file that does not evaluate
        name = "standard input" if args.file == STDIN_PATH else f"'{args.file}'"
        print(f"{ERROR_MARKER}Cannot factor {name}: {e}", file=sys.stderr)
        sys.exit(1)
    sys.stdout.write(text)


def _read(path: str):
    """
    The specifications in 'path': JSON, or Jsonnet evaluated for a
    '.jsonnet' file; '-' is standard input, read as JSON.
    """
    if path == STDIN_PATH:
        return json.load(sys.stdin)
    if is_jsonnet_path(path):
        from _jsonnet import evaluate_file

        return json.loads(evaluate_file(path))
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# Entry point
if __name__ == "__main__":
    main()
