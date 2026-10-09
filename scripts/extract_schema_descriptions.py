#!/usr/bin/env python3
"""
Extract the Work Requirement Property Dictionary's descriptions from
docs/property-dictionary.md
as JSON on stdout: {property name: plain-text description}. Run by
`make schema_descriptions`, which writes yellowdog_cli/spec_data/descriptions.json,
the file yd-schema ships; tests/test_spec_properties.py fails when that file
is not a fresh extraction. Markdown is unwrapped: code spans lose their
backticks, links keep their text, bold loses its markers.
"""

import json
import re
import sys
from pathlib import Path

DICTIONARY = Path(__file__).resolve().parent.parent / "docs" / "property-dictionary.md"


def plain(markdown: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", markdown)
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def extract(dictionary: str) -> dict[str, str]:
    lines = dictionary.splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith("| Property Name")
    )
    out: dict[str, str] = {}
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        out[cells[0].strip("`")] = plain(cells[1])
    return dict(sorted(out.items()))


if __name__ == "__main__":
    json.dump(extract(DICTIONARY.read_text(encoding="utf-8")), sys.stdout, indent=2)
    sys.stdout.write("\n")
