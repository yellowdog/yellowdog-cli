#!/usr/bin/env python3

"""
Reformat JSON files in place, using the CLI's compact JSON encoder.

A formatter must never change what a file says, only how it is laid out:
numbers are written back exactly as they were written, non-ASCII text is
kept as it is, a file with a repeated key is refused rather than losing
one of them, and a file is replaced only once its new text is complete,
so an interruption leaves the original.
"""

import json
import os
import sys
import tempfile
from argparse import ArgumentParser

from yellowdog_cli.utils.compact_json import (
    CompactJSONEncoder,
    FloatAsWritten,
    IntAsWritten,
)
from yellowdog_cli.utils.settings import ERROR_MARKER


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    """
    An object's pairs as a dict, refusing a repeated key, which json.loads()
    would otherwise resolve by silently dropping all but the last.
    """
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key '{key}'")
        result[key] = value
    return result


def reformatted(text: str) -> str:
    """
    The reformatted text of a JSON document, raising ValueError for one
    that is not valid JSON or repeats a key.
    """
    data = json.loads(
        text,
        object_pairs_hook=_no_duplicate_keys,
        parse_float=FloatAsWritten,
        parse_int=IntAsWritten,
    )
    return json.dumps(data, indent=2, cls=CompactJSONEncoder, ensure_ascii=False) + "\n"


def _replace(filename: str, text: str) -> None:
    """
    Write 'text' to a temporary file beside 'filename', with its
    permissions, and move it into place: the file is either the original or
    the complete new text, never something in between.
    """
    directory = os.path.dirname(os.path.abspath(filename))
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=directory, prefix=".yd-format-", delete=False
    ) as temporary:
        temporary.write(text)
    try:
        os.chmod(temporary.name, os.stat(filename).st_mode & 0o7777)
        os.replace(temporary.name, filename)
    except BaseException:
        os.unlink(temporary.name)
        raise


def _error(message: str) -> None:
    print(f"{ERROR_MARKER}{message}", file=sys.stderr)


def main():
    parser = ArgumentParser(
        prog="yd-format-json",
        description=(
            "Reformat JSON files in place with the CLI's compact layout (small"
            " containers on one line), changing nothing but the layout."
        ),
    )
    parser.add_argument(
        "files", nargs="+", metavar="<file.json>", help="the JSON file(s) to reformat"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "report the files that would be reformatted, without writing"
            " anything, and exit 1 if there are any"
        ),
    )
    args = parser.parse_args()

    failed = would_change = 0
    for filename in args.files:
        if not filename.lower().endswith(".json"):
            print(f"Ignoring non-JSON file: '{filename}'")
            continue

        try:
            with open(filename, encoding="utf-8") as f:
                text = f.read()
            new_text = reformatted(text)
        except Exception as e:
            _error(f"Unable to process '{filename}': {e}")
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
            _replace(filename, new_text)
        except Exception as e:
            _error(f"Unable to write '{filename}': {e}")
            failed += 1
            continue
        print(f"Reformatted: '{filename}'")

    if failed or would_change:
        sys.exit(1)


if __name__ == "__main__":
    main()
