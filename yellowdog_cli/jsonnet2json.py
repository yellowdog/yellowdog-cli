#!/usr/bin/env python3

"""
Simple utility to take Jsonnet file(s) and output their JSON representation.
With a single file, output goes to stdout, coloured on a terminal unless
--no-format is given, and errors to stderr, so that a failed conversion
piped to a file never leaves an error message in it.
With multiple files or a glob pattern, each file is written to <name>.json,
replaced whole or not at all: every file is converted before any is
written, and an existing <name>.json that the conversion would change is
replaced only once confirmed (or with --yes), since it may be a file of
its own rather than an earlier conversion. General purpose, not YellowDog
specific.
"""

import json
import os
import sys
from argparse import ArgumentParser
from glob import glob

from yellowdog_cli.utils.atomic_write import write_text_atomically
from yellowdog_cli.utils.check_imports import check_jsonnet_import
from yellowdog_cli.utils.compact_json import CompactJSONEncoder
from yellowdog_cli.utils.interactive import NoAnswerToPrompt, confirmed
from yellowdog_cli.utils.output_settings import configure_output
from yellowdog_cli.utils.output_style import ERROR_MARKER
from yellowdog_cli.utils.printing import print_json_text

_GLOB_CHARS = frozenset("*?[")


def _error(message: str) -> None:
    print(f"{ERROR_MARKER}{message}", file=sys.stderr)


def _as_json(json_text: str) -> str:
    """
    Jsonnet's output in the CLI's compact layout, non-ASCII text kept as it
    is: Jsonnet writes UTF-8, and there is no reason to escape it.
    """
    return json.dumps(
        json.loads(json_text), indent=2, cls=CompactJSONEncoder, ensure_ascii=False
    )


def main():
    parser = ArgumentParser(
        prog="yd-jsonnet2json",
        description=(
            "Convert Jsonnet files to JSON: one file to stdout, or several (or"
            " a glob pattern) each to <name>.json beside it."
        ),
    )
    parser.add_argument(
        "files",
        nargs="+",
        metavar="<file.jsonnet>",
        help="the Jsonnet file(s), or quoted glob pattern(s), to convert",
    )
    parser.add_argument(
        "--no-format",
        "--nf",
        action="store_true",
        help="print a single file's JSON without colouring",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="overwrite existing .json files without asking",
    )
    args = parser.parse_args()
    # --no-format, for print_json_text(), and --yes, for confirmed()
    configure_output(args)

    # This command has no @main_wrapper to catch and print an exception, so the
    # guard's message is presented here; otherwise advice about how to install
    # Jsonnet arrives buried in a traceback.
    try:
        check_jsonnet_import()
    except ImportError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    from _jsonnet import evaluate_file

    single_file_mode = len(args.files) == 1 and not _GLOB_CHARS.intersection(
        args.files[0]
    )

    if single_file_mode:
        try:
            print_json_text(_as_json(evaluate_file(args.files[0])))
        except Exception as e:
            _error(str(e))
            sys.exit(1)
        return

    # Expand globs, each file once in the order first found; a pattern that
    # matches nothing is that argument's failure, said plainly
    errors = 0
    files: list[str] = []
    for pattern in args.files:
        if _GLOB_CHARS.intersection(pattern):
            expanded = sorted(glob(pattern))
            if not expanded:
                _error(f"No files match '{pattern}'")
                errors += 1
            files.extend(expanded)
        else:
            files.append(pattern)

    # Every file converted before any is written, so that the files an
    # overwrite would change can be listed and confirmed once
    conversions: list[tuple[str, str, str]] = []
    for filepath in dict.fromkeys(files):
        if not filepath.lower().endswith(".jsonnet"):
            print(f"Skipping non-Jsonnet file: '{filepath}'")
            continue
        out_path = filepath[: -len(".jsonnet")] + ".json"
        try:
            conversions.append(
                (filepath, out_path, _as_json(evaluate_file(filepath)) + "\n")
            )
        except Exception as e:
            _error(f"Error processing '{filepath}': {e}")
            errors += 1

    changed = [
        out_path
        for _, out_path, text in conversions
        if os.path.isfile(out_path) and _existing_text(out_path) != text
    ]
    overwrite = True
    if changed:
        for out_path in changed:
            print(f"Would overwrite: '{out_path}'")
        plural = "s" if len(changed) > 1 else ""
        try:
            overwrite = confirmed(f"Overwrite {len(changed)} existing file{plural}?")
        except NoAnswerToPrompt as e:
            # Nothing is written yet, and nothing will be
            _error(str(e))
            sys.exit(1)

    for filepath, out_path, text in conversions:
        if out_path in changed and not overwrite:
            print(f"Not overwritten: '{out_path}'")
            continue
        if out_path not in changed and os.path.isfile(out_path):
            print(f"Unchanged: '{out_path}'")
            continue
        try:
            write_text_atomically(out_path, text)
            # '->', not an arrow: print() to a redirected cp1252 stdout on
            # Windows cannot encode one
            print(f"Converted: '{filepath}' -> '{out_path}'")
        except Exception as e:
            _error(f"Error writing '{out_path}': {e}")
            errors += 1

    if errors:
        sys.exit(1)


def _existing_text(path: str) -> str | None:
    """
    An existing file's text, or None if it cannot be read as UTF-8 text:
    then it is not the conversion's, and replacing it needs confirming.
    """
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


# Entry point
if __name__ == "__main__":
    main()
