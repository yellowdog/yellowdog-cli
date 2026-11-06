#!/usr/bin/env python3

"""
yd jsonnet fromjson: a JSON file, any JSON at all, written as Jsonnet in
the style of a hand-written file (utils/jsonnet_style.py): keys unquoted
where they are identifiers, strings in single quotes, trailing commas.
Nothing is factored ('yd jsonnet factor' does that, for a list of
specifications). The text is evaluated before it is used, and used only if
it gives back the same JSON.

One file's Jsonnet goes to stdout ('-' reads standard input), and errors to
stderr, so that a failed conversion redirected to a file leaves nothing in
it; several files or a glob pattern are refused, since their texts
together are no Jsonnet file. With --write, each file (or a pattern's
matches) is written to <name>.jsonnet beside it (utils/file_conversion.py).
"""

import json
import sys

from yellowdog_cli.utils.check_imports import check_jsonnet_import
from yellowdog_cli.utils.command_registry import COMMANDS, build_parser
from yellowdog_cli.utils.compact_json import CompactJSONEncoder
from yellowdog_cli.utils.file_conversion import (
    is_glob_pattern,
    parsed_json,
    print_conversion_error,
    write_conversions,
)
from yellowdog_cli.utils.invocation import selected_prog
from yellowdog_cli.utils.jsonnet_style import JSONNET_EXTENSION, jsonnet_style
from yellowdog_cli.utils.output_encoding import use_utf8_output
from yellowdog_cli.utils.output_settings import configure_output

STDIN_PATH = "-"
JSON_EXTENSION = ".json"


class ConversionError(Exception):
    """
    The Jsonnet text does not evaluate to the JSON it was made from: a fault
    in the conversion, so nothing is written.
    """


def main():
    use_utf8_output()
    parser = build_parser(
        COMMANDS["yd-jsonnet-fromjson"], prog=selected_prog("yd jsonnet fromjson")
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

    if args.write:
        errors = write_conversions(
            args.files, JSON_EXTENSION, JSONNET_EXTENSION, "JSON", _converted_file
        )
        if errors:
            sys.exit(1)
        return

    path = args.files[0]
    try:
        if path == STDIN_PATH:
            text = _converted(parsed_json(sys.stdin.read(), path))
        else:
            text = _converted_file(path)
    except (OSError, ValueError, ConversionError) as e:
        name = "standard input" if path == STDIN_PATH else f"'{path}'"
        print_conversion_error(f"Cannot convert {name}: {e}")
        sys.exit(1)
    sys.stdout.write(text)


def _converted_file(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return _converted(parsed_json(f.read(), path))


def _converted(value) -> str:
    """
    'value' as Jsonnet text, evaluated to make sure it gives back 'value':
    ConversionError if it does not.
    """
    from _jsonnet import evaluate_snippet

    text = (
        jsonnet_style(
            json.dumps(value, indent=2, cls=CompactJSONEncoder, ensure_ascii=False)
        )
        + "\n"
    )
    if json.loads(evaluate_snippet("converted.jsonnet", text)) != value:
        raise ConversionError(
            "the Jsonnet would not evaluate to the same JSON, so it was not written"
        )
    return text


# Entry point
if __name__ == "__main__":
    main()
