#!/usr/bin/env python3

"""
Simple utility to take Jsonnet file(s) and output their JSON representation.
One file's output goes to stdout, coloured on a terminal unless --no-format
is given, and errors to stderr, so that a failed conversion piped to a
file never leaves an error message in it; several files or a glob pattern
are refused, since their documents together are no JSON document.
With --write, each file (or a pattern's matches) is written to <name>.json,
replaced whole or not at all: every file is converted before any is
written, and an existing <name>.json that the conversion would change is
replaced only once confirmed (or with --yes), since it may be a file of
its own rather than an earlier conversion (utils/file_conversion.py).
General purpose, not YellowDog specific.
"""

import json
import sys

from yellowdog_cli.utils.check_imports import check_jsonnet_import
from yellowdog_cli.utils.command_registry import COMMANDS, build_parser
from yellowdog_cli.utils.compact_json import CompactJSONEncoder
from yellowdog_cli.utils.file_conversion import (
    is_glob_pattern,
    print_conversion_error,
    write_conversions,
)
from yellowdog_cli.utils.invocation import selected_prog
from yellowdog_cli.utils.output_encoding import use_utf8_output
from yellowdog_cli.utils.output_settings import configure_output
from yellowdog_cli.utils.printing import print_json_text
from yellowdog_cli.utils.top_level import warn_if_deprecated_script


def _as_json(json_text: str) -> str:
    """
    Jsonnet's output in the CLI's compact layout, non-ASCII text kept as it
    is: Jsonnet writes UTF-8, and there is no reason to escape it.
    """
    return json.dumps(
        json.loads(json_text), indent=2, cls=CompactJSONEncoder, ensure_ascii=False
    )


def main():
    use_utf8_output()
    parser = build_parser(
        COMMANDS["yd-jsonnet2json"], prog=selected_prog("yd-jsonnet2json")
    )
    args = parser.parse_args()
    # --no-format, for print_json_text(), and --yes, for confirmed()
    configure_output(args)
    warn_if_deprecated_script("yd-jsonnet2json")
    # Several documents on stdout would be no JSON document
    if not args.write and (len(args.files) > 1 or is_glob_pattern(args.files[0])):
        parser.error(
            "several files or a glob pattern are written beside their sources"
            " with --write; without it, give one file, whose JSON goes to stdout"
        )

    # This command has no @main_wrapper to catch and print an exception, so the
    # guard's message is presented here; otherwise advice about how to install
    # Jsonnet arrives buried in a traceback.
    try:
        check_jsonnet_import()
    except ImportError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    from _jsonnet import evaluate_file

    if not args.write:
        try:
            print_json_text(_as_json(evaluate_file(args.files[0])))
        except Exception as e:
            print_conversion_error(str(e))
            sys.exit(1)
        return

    errors = write_conversions(
        args.files,
        ".jsonnet",
        ".json",
        "Jsonnet",
        lambda filepath: _as_json(evaluate_file(filepath)) + "\n",
    )
    if errors:
        sys.exit(1)


# Entry point
if __name__ == "__main__":
    main()
