#!/usr/bin/env python3

"""
Reformat JSON files using a compact JSON encoder.
Usage: ./reformat_json.py file_1.json file_2.json ...
"""

import json
import sys

from yellowdog_cli.utils.compact_json import CompactJSONEncoder


def main():
    for filename in sys.argv[1:]:
        # Check file extension
        backup_filename = filename + ".backup"

        if not filename.lower().endswith(".json"):
            print(f"Ignoring non-JSON file: '{filename}'")
            continue

        # Load contents
        try:
            with open(filename, encoding="utf-8") as f:
                contents = f.read()
                f.seek(0)
                data = json.load(f)
        except Exception as e:
            print(f"Unable to process: '{filename}': {e}")
            continue

        # Save the backup file
        # try:
        #     with open(backup_filename, "w") as f:
        #         f.write(contents)
        #         print(f"Saved backup file to '{backup_filename}'")
        # except Exception as e:
        #     print(f"Error writing backup '{backup_filename}': {e}")
        #     continue

        # Write the reformatted JSON file
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, cls=CompactJSONEncoder)
                f.write("\n")
            print(f"Reformatted: '{filename}'")
        except Exception as e:
            print(f"Unable to write file: '{filename}': {e}")
            continue


if __name__ == "__main__":
    main()
