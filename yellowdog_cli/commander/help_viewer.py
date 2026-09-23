"""
Commander's online help (HelpDialog): its own README, shipped in the package and
rendered by Qt's Markdown importer, so that the guide on GitHub and the guide in
the application are one file and the latter always matches the installed version.

Qt's importer needs three corrections, which build_help_document() makes:

- It gives headings no anchor names, so the README's '[...](#section)' links
  went nowhere. Each heading is given the anchor GitHub derives from its text
  (heading_anchor()), which is what those links are written against.
- It renders a fenced code block as plain paragraphs, unshaded and with no space
  around them, so a command ran straight into the heading below it.
- The README's screenshot shows at its natural size, cut off at the pane's right
  edge, and a fixed width scales it jaggedly. It is dropped rather than fixed: a
  reader of this help is looking at the real window anyway.
"""

import re
from os.path import join

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextDocument
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

HELP_FILE = "README.md"  # in the package directory, beside commander.ui
HELP_TITLE = "YellowDog Commander Help"
HELP_DOCUMENT_MARGIN = 16  # px: between the text and the pane's edges
HELP_HEADING_TOP_MARGIN = 18  # px: above each heading, which Qt leaves at 0
HELP_CODE_MARGIN = 8  # px: code block indent, and the space below one
# Translucent, so the one shade reads against a light or a dark background
HELP_CODE_BACKGROUND = QColor(128, 128, 128, 40)
HELP_SIZE = (860, 760)  # px: the dialog's opening width and height
HELP_UNAVAILABLE = "Help is not available: {file} was not found."

# A Markdown image on a line of its own, which is how the README writes one
_IMAGE_LINE = re.compile(r"^!\[[^\]]*\]\([^)]*\)[ \t]*$", re.MULTILINE)


def heading_anchor(text: str, used: dict[str, int] | None = None) -> str:
    """
    The anchor GitHub gives a heading: lower-cased, punctuation dropped (other
    than '-' and '_'), and spaces made hyphens. A heading repeating an earlier
    one's anchor gets '-1', '-2' and so on, which 'used' keeps count of.
    """
    anchor = re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")
    if used is None:
        return anchor
    count = used.get(anchor, 0)
    used[anchor] = count + 1
    return anchor if count == 0 else f"{anchor}-{count}"


def build_help_document(markdown: str, parent: QWidget | None = None) -> QTextDocument:
    """
    The README as a document, with the corrections described above.
    """
    document = QTextDocument(parent)
    document.setMarkdown(_IMAGE_LINE.sub("", markdown))
    document.setDocumentMargin(HELP_DOCUMENT_MARGIN)

    used: dict[str, int] = {}
    block = document.begin()
    while block.isValid():
        cursor = QTextCursor(block)
        block_format = block.blockFormat()
        if block_format.headingLevel():
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
            )
            anchor = QTextCharFormat()
            anchor.setAnchor(True)
            anchor.setAnchorNames([heading_anchor(block.text(), used)])
            cursor.mergeCharFormat(anchor)
            block_format.setTopMargin(HELP_HEADING_TOP_MARGIN)
            cursor.setBlockFormat(block_format)
        elif block_format.nonBreakableLines():  # a fenced code block's line
            block_format.setBackground(HELP_CODE_BACKGROUND)
            block_format.setLeftMargin(HELP_CODE_MARGIN)
            block_format.setBottomMargin(HELP_CODE_MARGIN)
            cursor.setBlockFormat(block_format)
        block = block.next()
    return document


class HelpDialog(QDialog):
    """
    The help window. Modeless, so it can stay open beside the main window while
    the user follows it; the window keeps one and raises it again rather than
    opening a second.
    """

    def __init__(self, parent: QWidget, package_dir: str):
        super().__init__(parent)
        self.setWindowTitle(HELP_TITLE)
        self.resize(*HELP_SIZE)

        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(True)
        help_file = join(package_dir, HELP_FILE)
        try:
            with open(help_file, encoding="utf-8") as file:
                markdown = file.read()
        except OSError:
            # A packaging fault, not the user's: say so where they are looking
            markdown = HELP_UNAVAILABLE.format(file=help_file)
        self.browser.setDocument(build_help_document(markdown, self.browser))
        # A source for history to go back to. The document is set rather than
        # loaded, so there is none, and the first link followed would leave Back
        # disabled. A bare fragment names this same document, so nothing reloads.
        self.browser.setSource(QUrl("#"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self.back_button = QPushButton("Back", self)
        buttons.addButton(self.back_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.back_button.setEnabled(False)
        self.back_button.clicked.connect(self.browser.backward)
        self.browser.backwardAvailable.connect(self.back_button.setEnabled)
        buttons.rejected.connect(self.close)

        layout = QVBoxLayout(self)
        layout.addWidget(self.browser)
        layout.addWidget(buttons)
