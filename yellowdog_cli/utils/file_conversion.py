"""
What the 'yd jsonnet' verbs share: parsed_json(), reading JSON with a
plain reason where it is none, and the '--write' half of the conversions
('tojson', 'fromjson'):
each file given, or each match of a glob pattern, converted and written
beside it under the other extension, replaced whole or not at all. Every
file is converted before any is written, and an existing file that the
conversion would change is replaced only once confirmed (or with --yes),
since it may be a file of its own rather than an earlier conversion.
Errors go to stderr, so that none is ever mistaken for a file's contents.
"""

import json
import os
import sys
from collections.abc import Callable
from glob import glob

from yellowdog_cli.utils.atomic_write import write_text_atomically
from yellowdog_cli.utils.interactive import NoAnswerToPrompt, confirmed
from yellowdog_cli.utils.jsonnet_style import is_jsonnet_path
from yellowdog_cli.utils.output_style import ERROR_MARKER

_GLOB_CHARS = frozenset("*?[")


def print_conversion_error(message: str) -> None:
    print(f"{ERROR_MARKER}{message}", file=sys.stderr)


def parsed_json(text: str, path: str):
    """
    The JSON in 'text', read from 'path': a ValueError saying plainly why
    not where it is none, pointing a file named as Jsonnet to 'tojson'.
    """
    if not text.strip():
        raise ValueError("it is empty")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        if is_jsonnet_path(path):
            raise ValueError(
                "it is a Jsonnet file, not JSON; 'yd jsonnet tojson' converts"
                " Jsonnet to JSON"
            ) from e
        raise ValueError(
            f"it is not JSON ({e.msg.lower()} at line {e.lineno}, column {e.colno})"
        ) from e


def is_glob_pattern(argument: str) -> bool:
    return bool(_GLOB_CHARS.intersection(argument))


def write_conversions(
    arguments: list[str],
    source_extension: str,
    target_extension: str,
    source_kind: str,
    convert: Callable[[str], str],
) -> int:
    """
    Convert each file named in 'arguments' (a pattern expanded, each file
    once in the order first found) whose name ends 'source_extension',
    with 'convert' (a file's path to the text to write), and write it
    beside it with 'target_extension' in its place. A file with another
    extension is skipped, said as a non-'source_kind' file. The number of
    failures is returned, a pattern matching nothing among them.
    """
    errors = 0
    files: list[str] = []
    for argument in arguments:
        if is_glob_pattern(argument):
            expanded = sorted(glob(argument))
            if not expanded:
                print_conversion_error(f"No files match '{argument}'")
                errors += 1
            files.extend(expanded)
        else:
            files.append(argument)

    conversions: list[tuple[str, str, str]] = []
    for filepath in dict.fromkeys(files):
        if not filepath.lower().endswith(source_extension):
            print(f"Skipping non-{source_kind} file: '{filepath}'")
            continue
        out_path = filepath[: -len(source_extension)] + target_extension
        try:
            conversions.append((filepath, out_path, convert(filepath)))
        except Exception as e:
            print_conversion_error(f"Error processing '{filepath}': {e}")
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
            print_conversion_error(str(e))
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
            print_conversion_error(f"Error writing '{out_path}': {e}")
            errors += 1
    return errors


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
