"""
The README's Documentation section is the map of the documentation: every
page in docs/, and each optional extension's README, has a row in one of its
tables, linking to the page with a line saying what it covers. A new page
without one fails here, rather than going unnoticed by anyone landing on the
README.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

EXTENSION_READMES = [
    "yellowdog_cli/commander/README.md",
    "yellowdog_cli/mcp/README.md",
    "README_CLOUDWIZARD.md",
]

# A table row: '| **[Title](path)** | what it covers |'
ROW = re.compile(r"^\| \*\*\[[^]]+\]\(([^)#\s]+)\)\*\* \| (.+) \|$")


def _map_rows() -> dict[str, str]:
    """
    The Documentation section's rows, as each linked path and its description.
    """
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    section = text[text.index("\n# Documentation\n") :]
    following = re.search(r"\n# ", section[1:])
    if following is not None:
        section = section[: following.start() + 1]
    rows: dict[str, str] = {}
    for line in section.splitlines():
        match = ROW.match(line)
        if match is not None:
            rows[match.group(1)] = match.group(2)
    return rows


def test_every_docs_page_is_in_the_map():
    pages = {f"docs/{path.name}" for path in (ROOT / "docs").glob("*.md")}
    assert pages, "no pages found in docs/"
    assert sorted(pages - set(_map_rows())) == []


def test_every_extension_readme_is_in_the_map():
    assert sorted(set(EXTENSION_READMES) - set(_map_rows())) == []


def test_every_row_names_a_page_that_exists_and_says_what_it_covers():
    rows = _map_rows()
    assert rows
    for path, description in rows.items():
        assert (ROOT / path).is_file(), path
        assert description.strip(), path
