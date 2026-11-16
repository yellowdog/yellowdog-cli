"""
The file viewer (FileViewer): a configuration or definition file shown in a
window of its own, which Show Config, Show WR JSON and Show WP JSON open, so
that a file kept open for reference neither interleaves with nor scrolls away
the commands' output. Modeless and read-only, one per file (the window keeps
them and raises one again rather than opening a second), coloured as TOML or
JSON line by line (FileHighlighter, over output_model's tokenizers), reloaded
when the file changes on disk, with Find and Open in Editor.
"""

import os
from collections.abc import Callable
from typing import cast

from PyQt6.QtCore import QFileSystemWatcher, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QKeySequence,
    QResizeEvent,
    QShortcut,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from yellowdog_cli.commander.elision import elide_path_to_fit
from yellowdog_cli.commander.output_model import (
    TOML_COMMENT,
    TOML_TABLE,
    json_tokens,
    toml_tokens,
)
from yellowdog_cli.commander.output_pane import (
    JSON_STYLES,
    PREFIX_RGB_DARK,
    PREFIX_RGB_LIGHT,
)

# How a file is coloured: as TOML (a configuration file, or a definition file
# named '.toml') or, by its lines' shape, as JSON (JSON and Jsonnet alike)
TOML = "toml"
JSON = "json"
TOML_EXTENSION = ".toml"
# A TOML document's colours: JSON's for the kinds the two share, a table
# heading bold, as the heading of the lines below it, and a comment muted, as
# a message's prefix is in the output window
TOML_STYLES: dict[
    str, tuple[tuple[int, int, int] | None, tuple[int, int, int] | None, bool, bool]
] = {
    **JSON_STYLES,
    TOML_TABLE: (None, None, True, False),
    TOML_COMMENT: (PREFIX_RGB_LIGHT, PREFIX_RGB_DARK, False, False),
}
VIEWER_SIZE = (760, 640)  # px: a viewer's opening width and height
OPEN_IN_EDITOR = "Open in Editor"
FIND_PLACEHOLDER = "Find"
NOT_FOUND = "Not found"
# How long after a change on disk the file is read again: an editor saving it
# may write it in more than one step
RELOAD_DELAY_MS = 150


def language_of(path: str, is_config: bool) -> str:
    """
    How a file is coloured: a configuration file, or a file named '.toml', as
    TOML; anything else as JSON, which colours Jsonnet near enough.
    """
    if is_config or path.lower().endswith(TOML_EXTENSION):
        return TOML
    return JSON


class FileHighlighter(QSyntaxHighlighter):
    """
    Colours each line of the viewer's document by toml_tokens() or
    json_tokens(), from TOML_STYLES (whose JSON kinds are JSON_STYLES).
    """

    def __init__(self, document: QTextDocument, language: str):
        super().__init__(document)
        self._tokens = toml_tokens if language == TOML else json_tokens
        self._formats: dict[str, QTextCharFormat] = {}
        for name, (_light, _dark, bold, italic) in TOML_STYLES.items():
            self._formats[name] = QTextCharFormat()
            if bold:
                self._formats[name].setFontWeight(QFont.Weight.Bold)
            self._formats[name].setFontItalic(italic)
        self.set_dark(False)

    def set_dark(self, is_dark: bool) -> None:
        """
        Use the colours for the appearance, and recolour what is shown.
        """
        for name, (light, dark, _bold, _italic) in TOML_STYLES.items():
            colour = dark if is_dark else light
            if colour is not None:
                self._formats[name].setForeground(QColor(*colour))
        self.rehighlight()

    def highlightBlock(self, text: str | None) -> None:
        if not text:
            return
        for start, length, kind in self._tokens(text):
            self.setFormat(start, length, self._formats[kind])


class FileViewer(QDialog):
    """
    One file's window: its path, a Find field, the text, and Open in Editor
    and Close. load() reads the file, keeping what is shown and saying why
    where it cannot; a change on disk reads it again, keeping the place.
    """

    def __init__(
        self,
        parent: QWidget,
        path: str,
        description: str,
        language: str,
        font: QFont,
        is_dark: bool,
        open_file: Callable[[str], None],
    ):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle(f"{os.path.basename(path)} — {description}")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(*VIEWER_SIZE)

        # Elided from the left to fit (_fit_path()), the whole path its
        # tooltip: at its full width a long path would widen the window
        self.path_label = QLabel(path, self)
        self.path_label.setToolTip(path)
        self.path_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.find_field = QLineEdit(self)
        self.find_field.setPlaceholderText(FIND_PLACEHOLDER)
        self.find_field.setClearButtonEnabled(True)
        self.find_field.returnPressed.connect(self.find_next)
        QShortcut(
            QKeySequence("Shift+Return"),
            self.find_field,
            self.find_previous,
            context=Qt.ShortcutContext.WidgetShortcut,
        )
        QShortcut(QKeySequence.StandardKey.Find, self, self._focus_find)
        self.status = QLabel(self)
        self.status.hide()

        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text.setFont(font)
        self.highlighter = FileHighlighter(
            cast(QTextDocument, self.text.document()), language
        )
        self.highlighter.set_dark(is_dark)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self.open_button = QPushButton(OPEN_IN_EDITOR, self)
        # Return in the Find field finds; it must not open the editor
        self.open_button.setAutoDefault(False)
        buttons.addButton(self.open_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.open_button.clicked.connect(lambda: open_file(self.path))
        buttons.rejected.connect(self.close)

        layout = QVBoxLayout(self)
        layout.addWidget(self.path_label)
        layout.addWidget(self.find_field)
        layout.addWidget(self.status)
        layout.addWidget(self.text)
        layout.addWidget(buttons)

        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(RELOAD_DELAY_MS)
        self._reload_timer.timeout.connect(self.load)
        self._watcher = QFileSystemWatcher([path], self)
        self._watcher.fileChanged.connect(self._reload_timer.start)

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        self._fit_path()

    def _fit_path(self) -> None:
        """
        Show as much of the path as the label's width takes, cut at a
        directory so that the file's name is kept whole.
        """
        metrics = QFontMetrics(self.path_label.font())
        available = self.path_label.contentsRect().width()
        self.path_label.setText(
            elide_path_to_fit(
                self.path, lambda text: metrics.horizontalAdvance(text) <= available
            )
        )

    def load(self) -> str | None:
        """
        Read the file into the window, keeping the place scrolled to, and
        watch it again (an editor that saves by replacing the file ends the
        watch). Returns why it could not be read, which the window also says,
        keeping what it showed; or None.
        """
        try:
            with open(self.path, encoding="utf-8") as file:
                content = file.read()
        except (OSError, UnicodeDecodeError) as e:
            self._say(f"Cannot read '{self.path}': {e}")
            return str(e)
        if self.path not in self._watcher.files():
            self._watcher.addPath(self.path)
        self._say(None)
        if content != self.text.toPlainText():
            vertical = self.text.verticalScrollBar()
            horizontal = self.text.horizontalScrollBar()
            places = (
                vertical.value() if vertical else 0,
                horizontal.value() if horizontal else 0,
            )
            self.text.setPlainText(content)
            if vertical:
                vertical.setValue(places[0])
            if horizontal:
                horizontal.setValue(places[1])
        return None

    def set_dark(self, is_dark: bool) -> None:
        self.highlighter.set_dark(is_dark)

    def set_font(self, font: QFont) -> None:
        self.text.setFont(font)

    def find_next(self) -> bool:
        return self._find(QTextDocument.FindFlag(0))

    def find_previous(self) -> bool:
        return self._find(QTextDocument.FindFlag.FindBackward)

    def _find(self, flags: QTextDocument.FindFlag) -> bool:
        """
        Select the next (or previous) occurrence of the Find field's text,
        ignoring case, going round from the end (or start) where there is no
        more; say so where there is none at all.
        """
        wanted = self.find_field.text()
        if not wanted:
            self._say(None)
            return False
        if not self.text.find(wanted, flags):
            cursor = self.text.textCursor()
            cursor.movePosition(
                cursor.MoveOperation.End
                if flags & QTextDocument.FindFlag.FindBackward
                else cursor.MoveOperation.Start
            )
            self.text.setTextCursor(cursor)
            if not self.text.find(wanted, flags):
                self._say(NOT_FOUND)
                return False
        self._say(None)
        return True

    def _focus_find(self) -> None:
        self.find_field.setFocus()
        self.find_field.selectAll()

    def _say(self, message: str | None) -> None:
        """
        Show a line above the text (why the file cannot be read, or that the
        text sought is not there), or hide it.
        """
        self.status.setText(message or "")
        self.status.setVisible(message is not None)
