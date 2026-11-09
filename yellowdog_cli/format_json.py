#!/usr/bin/env python3

"""
Reformat JSON files in place, using the CLI's compact JSON encoder.

A formatter must never change what a file says, only how it is laid out:
the file is read as utils/file_conversion.py's parsed_json() reads it, so
numbers are written back exactly as they were written and a file with a
repeated key is refused rather than losing one of them; non-ASCII text is
kept as it is; and a file is replaced only once its new text is complete,
so an interruption leaves the original. A quoted glob pattern is expanded
as the 'yd jsonnet' verbs expand one. '--stdout' prints one file
reformatted, and '-' standard input, to stdout instead, coloured only for
a terminal (print_json_text()), so a pipe gets the bytes a file would hold.
"""

import json
import sys

from yellowdog_cli.utils.atomic_write import write_text_atomically
from yellowdog_cli.utils.command_registry import COMMANDS, build_parser
from yellowdog_cli.utils.compact_json import CompactJSONEncoder
from yellowdog_cli.utils.file_conversion import (
    expanded_files,
    is_glob_pattern,
    parsed_json,
    print_conversion_error,
)
from yellowdog_cli.utils.invocation import selected_prog
from yellowdog_cli.utils.output_encoding import use_utf8_output
from yellowdog_cli.utils.output_settings import configure_output
from yellowdog_cli.utils.printing import print_json_text
from yellowdog_cli.utils.top_level import warn_if_deprecated_script

STDIN_PATH = "-"
JSON_EXTENSION = ".json"


def reformatted(text: str, path: str = "") -> str:
    """
    The reformatted text of a JSON document, read from 'path', raising
    ValueError for one that is not valid JSON or repeats a key.
    """
    data = parsed_json(text, path)
    return json.dumps(data, indent=2, cls=CompactJSONEncoder, ensure_ascii=False) + "\n"


def main():
    use_utf8_output()
    warn_if_deprecated_script("yd-format-json")
    parser = build_parser(
        COMMANDS["yd-format-json"], prog=selected_prog("yd-format-json")
    )
    args = parser.parse_args()
    # --no-format, for print_json_text()
    configure_output(args)
    if STDIN_PATH in args.files and len(args.files) > 1:
        parser.error("standard input ('-') is reformatted alone, to stdout")
    if args.stdout:
        if args.check:
            parser.error("--check writes nothing, to stdout or anywhere else")
        # Several documents on stdout would be no JSON document
        if len(args.files) > 1 or is_glob_pattern(args.files[0]):
            parser.error("--stdout prints one file; give one, not several or a pattern")
    if STDIN_PATH in args.files:
        sys.exit(_reformat_standard_input(args.check))
    if args.stdout:
        sys.exit(_print_reformatted(args.files[0]))

    files, failed = expanded_files(args.files)
    would_change = 0
    for filename in files:
        if not filename.lower().endswith(JSON_EXTENSION):
            print(f"Skipping non-JSON file: '{filename}'")
            continue

        try:
            with open(filename, encoding="utf-8") as f:
                text = f.read()
            new_text = reformatted(text, filename)
        except (OSError, UnicodeDecodeError, ValueError) as e:
            print_conversion_error(f"Cannot format '{filename}': {e}")
            failed += 1
            continue

        if new_text == text:
            print(f"Unchanged: '{filename}'")
            continue
        if args.check:
            print(f"Would reformat: '{filename}'")
            would_change += 1
            continue

        try:
            write_text_atomically(filename, new_text)
        except OSError as e:
            print_conversion_error(f"Cannot write '{filename}': {e}")
            failed += 1
            continue
        print(f"Reformatted: '{filename}'")

    if failed or would_change:
        sys.exit(1)


def _reformat_standard_input(check: bool) -> int:
    """
    Standard input reformatted to stdout, or with 'check' only said to be
    unchanged or not; the exit code.
    """
    text = sys.stdin.read()
    try:
        new_text = reformatted(text)
    except ValueError as e:
        print_conversion_error(f"Cannot format standard input: {e}")
        return 1
    if not check:
        print_json_text(new_text)
        return 0
    if new_text == text:
        print("Unchanged: standard input")
        return 0
    print("Would reformat: standard input")
    return 1


def _print_reformatted(filename: str) -> int:
    """
    A file reformatted to stdout, the file left as it is; the exit code.
    Any file is read, whatever its name, since nothing is written.
    """
    try:
        with open(filename, encoding="utf-8") as f:
            new_text = reformatted(f.read(), filename)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        print_conversion_error(f"Cannot format '{filename}': {e}")
        return 1
    print_json_text(new_text)
    return 0


if __name__ == "__main__":
    main()
