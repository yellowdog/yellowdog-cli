"""
Commander's online help: its README, shipped in the package and rendered in a
modeless dialog, with the three corrections help_viewer.py makes to Qt's Markdown
importer — heading anchors, shaded code blocks, and the screenshot dropped.
"""

import re
from fnmatch import fnmatch
from pathlib import Path

import qt_guard

qt_guard.require_qt()

import tomli
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QTextDocument, QTextListFormat
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from yellowdog_cli.commander.commander import YellowDogApp
from yellowdog_cli.commander.help_viewer import (
    HELP_FILE,
    HelpDialog,
    build_help_document,
    heading_anchor,
    section_link_item,
)

REPO = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO / "yellowdog_cli" / "commander"
README = (PACKAGE_DIR / HELP_FILE).read_text(encoding="utf-8")


def _anchors(document: QTextDocument) -> list[str]:
    names: list[str] = []
    block = document.begin()
    while block.isValid():
        if block.blockFormat().headingLevel():
            fragments = block.begin()
            while not fragments.atEnd():
                names.extend(fragments.fragment().charFormat().anchorNames())
                fragments += 1
        block = block.next()
    return names


def _headings(markdown: str) -> list[str]:
    """ATX headings outside fenced code blocks."""
    headings, fenced = [], False
    for line in markdown.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and re.match(r"#{1,6} ", line):
            headings.append(line.lstrip("#").strip())
    return headings


def test_the_readme_is_declared_as_package_data():
    # include-package-data is false, so a file the globs miss is simply absent
    # from the wheel — and the help reports itself unavailable to every user.
    with open(REPO / "pyproject.toml", "rb") as file:
        pyproject = tomli.load(file)
    globs = pyproject["tool"]["setuptools"]["package-data"]["yellowdog_cli.commander"]
    assert any(fnmatch(HELP_FILE, pattern) for pattern in globs)


def test_heading_anchors_follow_github():
    assert heading_anchor("A Note on Confirmations") == "a-note-on-confirmations"
    assert (
        heading_anchor("Selecting a Configuration (Panel 1)")
        == "selecting-a-configuration-panel-1"
    )
    assert heading_anchor("Namespace, Tag, and Name Overrides") == (
        "namespace-tag-and-name-overrides"
    )
    used: dict[str, int] = {}
    assert [heading_anchor("Notes", used) for _ in range(3)] == [
        "notes",
        "notes-1",
        "notes-2",
    ]


def test_every_heading_gets_an_anchor(qapp):
    document = build_help_document(README)
    assert _anchors(document) == [heading_anchor(h) for h in _headings(README)]


def test_every_section_link_in_the_readme_lands_on_a_heading(qapp):
    # The links were written for GitHub, and a renamed heading breaks them there
    # and here alike — silently, since a dead anchor is just an inert link.
    links = set(re.findall(r"\]\(#([^)]+)\)", README))
    assert links, "the README has no section links left to check"
    missing = links - set(_anchors(build_help_document(README)))
    assert not missing, f"section links with no heading to land on: {missing}"


def test_code_blocks_are_shaded_and_images_dropped(qapp):
    document = build_help_document(
        "# Title\n\n![shot](screenshots/x.png)\n\n```\nyd-commander\n```\n\nText\n"
    )
    assert "<img" not in document.toHtml()

    block = document.begin()
    code = []
    while block.isValid():
        if block.blockFormat().nonBreakableLines():
            code.append(block)
        block = block.next()
    assert [b.text() for b in code] == ["yd-commander"]
    assert all(
        b.blockFormat().background().style() != Qt.BrushStyle.NoBrush for b in code
    )


def test_the_help_button_opens_one_dialog_showing_the_readme(qapp):
    window = YellowDogApp()
    window.show_help.click()
    dialog = window._help_dialog
    assert isinstance(dialog, HelpDialog)
    assert dialog.isVisible()
    assert "How It Works" in dialog.browser.toPlainText()

    # Opened again, it is the same dialog, keeping the reader's place in it
    dialog.browser.verticalScrollBar().setValue(200)
    window.show_help.click()
    assert window._help_dialog is dialog
    assert dialog.browser.verticalScrollBar().value() == 200
    dialog.close()


def test_f1_opens_the_help(qapp):
    window = YellowDogApp()
    window.show()
    window.activateWindow()
    QApplication.processEvents()
    QTest.keyClick(window, Qt.Key.Key_F1)
    assert window._help_dialog is not None and window._help_dialog.isVisible()
    window._help_dialog.close()


def test_a_section_link_scrolls_to_it_and_back_returns(qapp):
    window = YellowDogApp()
    window.resize(1091, 840)
    window.show_help.click()
    dialog = window._help_dialog
    assert dialog is not None
    QApplication.processEvents()
    scroll = dialog.browser.verticalScrollBar()
    assert not dialog.back_button.isEnabled()

    # Reading part of the way down, the user follows a link near the end...
    scroll.setValue(300)
    dialog.browser.setSource(QUrl("#a-note-on-confirmations"))  # as a click does
    QApplication.processEvents()
    assert scroll.value() > 300
    assert dialog.back_button.isEnabled()

    # ...and Back returns them to where they were, not to the top
    dialog.back_button.click()
    QApplication.processEvents()
    assert scroll.value() == 300
    dialog.close()


def test_a_missing_readme_is_reported_in_the_dialog(qapp, tmp_path):
    dialog = HelpDialog(YellowDogApp(), str(tmp_path))
    text = dialog.browser.toPlainText()
    assert "Help is not available" in text
    assert str(tmp_path / HELP_FILE) in text


def test_a_table_of_contents_is_tight_and_prose_lists_are_not(qapp):
    document = build_help_document(
        "# Title\n\n"
        "* [Alpha](#alpha)\n"
        "   * [Beta](#beta)\n\n"
        "## Alpha\n\n"
        "- **Bold** — an item with [a link](#beta) inside prose\n"
        "- [External](https://example.com)\n\n"
        "## Beta\n"
    )
    items = {}
    block = document.begin()
    while block.isValid():
        if block.textList() is not None:
            items[block.text()] = block
        block = block.next()

    contents = [items["Alpha"], items["Beta"]]
    assert all(section_link_item(b) for b in contents)
    assert all(
        b.blockFormat().topMargin() == 0 and b.blockFormat().bottomMargin() == 0
        for b in contents
    )
    assert all(
        b.textList().format().style() == QTextListFormat.Style.ListDisc
        for b in contents
    )

    # Prose, and a link that leaves the document, keep the paragraph spacing
    prose = [b for text, b in items.items() if text not in ("Alpha", "Beta")]
    assert len(prose) == 2
    assert not any(section_link_item(b) for b in prose)
    assert all(b.blockFormat().bottomMargin() > 0 for b in prose)


def test_the_readme_has_a_table_of_contents(qapp):
    # Generated by 'make toc_commander'; every entry is also checked by the
    # section-link test above, so a stale one fails there
    document = build_help_document(README)
    block = document.begin()
    entries = 0
    while block.isValid():
        entries += section_link_item(block)
        block = block.next()
    assert entries == len(_headings(README)) - 1  # all but the title
