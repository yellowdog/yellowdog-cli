#!/usr/bin/env python3

"""
Simple utility to take Jsonnet file(s) and output their JSON representation.
With a single file, output goes to stdout.
With multiple files or a glob pattern, each file is written to <name>.json.
General purpose, not YellowDog specific.
"""

import json
import sys
from glob import glob

from yellowdog_cli.utils.check_imports import check_jsonnet_import
from yellowdog_cli.utils.compact_json import CompactJSONEncoder

_GLOB_CHARS = frozenset("*?[")


def main():
    check_jsonnet_import()
    from _jsonnet import evaluate_file

    if len(sys.argv) < 2:
        print("Usage: yd-jsonnet2json <file.jsonnet> [<file.jsonnet> ...]")
        exit(1)

    args = sys.argv[1:]
    single_file_mode = len(args) == 1 and not _GLOB_CHARS.intersection(args[0])

    # Expand globs; preserve non-matching paths so errors surface below
    files: list[str] = []
    for pattern in args:
        expanded = glob(pattern)
        files.extend(sorted(expanded) if expanded else [pattern])

    if single_file_mode:
        try:
            json_data = json.loads(evaluate_file(files[0]))
            print(json.dumps(json_data, indent=2, cls=CompactJSONEncoder))
        except Exception as e:
            print(f"Error: {e}")
            exit(1)
        return

    errors = 0
    for filepath in files:
        if not filepath.lower().endswith(".jsonnet"):
            print(f"Skipping non-Jsonnet file: '{filepath}'")
            continue
        out_path = filepath[: -len(".jsonnet")] + ".json"
        try:
            json_data = json.loads(evaluate_file(filepath))
            with open(out_path, "w") as f:
                json.dump(json_data, f, indent=2, cls=CompactJSONEncoder)
                f.write("\n")
            print(f"Converted: '{filepath}' → '{out_path}'")
        except Exception as e:
            print(f"Error processing '{filepath}': {e}")
            errors += 1

    if errors:
        exit(1)


# Entry point
if __name__ == "__main__":
    main()
