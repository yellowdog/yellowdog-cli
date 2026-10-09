"""
Every relative link in the documentation resolves: the file it names
exists, and an anchor names a heading in it, as GitHub numbers headings
(a repeat gains '-1', '-2', ...). The README is split across docs/, so a
section moved from one file to another breaks the links that still point
where it was; this is where that shows. A README section left as only a
pointer to its docs page is not a target either: a link to it is one click
short, so it should name the page. Links inside fenced code blocks, in a
table of contents and to external URLs are not checked.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

DOCUMENTS = sorted(
    [
        ROOT / "README.md",
        ROOT / "README_CLOUDWIZARD.md",
        ROOT / "DEVELOPMENT.md",
        ROOT / "yellowdog_cli" / "commander" / "README.md",
        ROOT / "yellowdog_cli" / "mcp" / "README.md",
        *(ROOT / "docs").glob("*.md"),
    ]
)

LINK = re.compile(r"\]\(([^)\s]+)\)")
HEADING = re.compile(r"^(#{1,6}) (.*)$")


def _slug(text: str) -> str:
    """
    GitHub's anchor for a heading's text: a link's text kept, lower case,
    punctuation other than '-' and '_' dropped, spaces as hyphens.
    """
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[^\w\- ]", "", text.strip().lower())
    return text.replace(" ", "-")


def _lines_outside_fences(path: Path) -> list[tuple[int, str]]:
    """
    (line number, line) for each line not in a fenced code block.
    """
    found = []
    fence = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("```"):
            fence = not fence
            continue
        if not fence:
            found.append((number, line))
    return found


def _lines_outside_toc(path: Path) -> list[tuple[int, str]]:
    """
    _lines_outside_fences(), less the <!--ts-->/<!--te--> table of contents.
    """
    found = []
    toc = False
    for number, line in _lines_outside_fences(path):
        if line.strip() == "<!--ts-->":
            toc = True
        elif line.strip() == "<!--te-->":
            toc = False
        elif not toc:
            found.append((number, line))
    return found


def _sections(path: Path) -> list[tuple[str, list[str]]]:
    """
    (anchor, the lines under the heading up to the next) for each heading.
    """
    sections: list[tuple[str, list[str]]] = []
    seen: dict[str, int] = {}
    for _, line in _lines_outside_toc(path):
        if match := HEADING.match(line):
            base = _slug(match.group(2))
            repeat = seen.get(base, 0)
            seen[base] = repeat + 1
            sections.append((base if repeat == 0 else f"{base}-{repeat}", []))
        elif sections:
            sections[-1][1].append(line)
    return sections


def _anchors(path: Path) -> set[str]:
    return {anchor for anchor, _ in _sections(path)}


def _pointers(path: Path) -> set[str]:
    """
    The anchors of the sections that are only a pointer to a docs page: one
    paragraph, linking into docs/.
    """
    return {
        anchor
        for anchor, body in _sections(path)
        if len(text := [line for line in body if line.strip()]) == 1
        and "](docs/" in text[0]
    }


def _broken_links(path: Path) -> list[str]:
    broken = []
    for number, line in _lines_outside_toc(path):
        for link in LINK.findall(line):
            if re.match(r"[a-z]+:", link):
                continue  # https:, mailto:
            target, _, anchor = link.partition("#")
            file = (path.parent / target).resolve() if target else path
            where = f"{path.relative_to(ROOT)}:{number}: {link}"
            if not file.exists():
                broken.append(f"{where} (no such file)")
            elif anchor and file.suffix == ".md" and anchor not in _anchors(file):
                broken.append(f"{where} (no such heading)")
            elif anchor and file.suffix == ".md" and anchor in _pointers(file):
                broken.append(f"{where} (only a pointer: link its docs page)")
    return broken


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_relative_link_resolves(path):
    assert _broken_links(path) == []


def test_the_docs_pages_are_checked():
    # A control: the glob found docs/, so its pages' links are being checked
    assert any(p.parent.name == "docs" for p in DOCUMENTS)


def test_a_broken_link_is_found(tmp_path, monkeypatch):
    # A control: the check reports a missing heading and a missing file
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    page = tmp_path / "page.md"
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "moved.md").write_text("# Moved\n", encoding="utf-8")
    page.write_text(
        "# Title\n\n<!--ts-->\n* [Moved](#moved)\n<!--te-->\n\n"
        "## Part\n\n## Part\n\n## Moved\n\nSee [the page](docs/moved.md).\n\n"
        "## Links\n\n[ok](#part-1) [gone](#nowhere) [file](missing.md)"
        " [short](#moved)\n",
        encoding="utf-8",
    )
    assert _broken_links(page) == [
        "page.md:17: #nowhere (no such heading)",
        "page.md:17: missing.md (no such file)",
        "page.md:17: #moved (only a pointer: link its docs page)",
    ]
