#!/usr/bin/env python3

"""
YellowDog Commander: GUI application for driving the YellowDog CLI
"""

import os
import re
import subprocess
import sys
from datetime import datetime
from functools import partial as functools_partial
from platform import system as _platform_system
from shlex import quote
from typing import cast

_system = _platform_system()
MACOS = _system == "Darwin"
LINUX = _system == "Linux"
WINDOWS = _system == "Windows"

if not (MACOS or LINUX or WINDOWS):
    print(f"Error: unrecognised platform: {_system}", file=sys.stderr)
    sys.exit(1)

if MACOS or LINUX:
    from os import system as os_system
elif WINDOWS:
    import ctypes
    from os import (
        startfile as os_startfile,  # pyright: ignore[reportAttributeAccessIssue]
    )

from codecs import getincrementaldecoder
from collections.abc import Callable
from dataclasses import dataclass
from json import loads
from os.path import abspath, basename, dirname, exists, getsize, isdir, join, relpath

_PKG_DIR = dirname(abspath(__file__))

from PyQt6.QtCore import (
    QEvent,
    QEventLoop,
    QFileSystemWatcher,
    QProcess,
    QProcessEnvironment,
    QSettings,
    QSize,
    Qt,
    QTimer,
)
from PyQt6.QtGui import (
    QClipboard,
    QCloseEvent,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QImageReader,
    QPalette,
    QPixmap,
    QStyleHints,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QSplitter,
    QStyle,
    QStyleOptionButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)
from PyQt6.uic import loadUi  # pyright: ignore[reportPrivateImportUsage]

from yellowdog_cli._version import __version__
from yellowdog_cli.utils.glob_utils import contains_glob_chars

WINDOW_TITLE = f"YellowDog CLI Commander (v{__version__})"
# px: inset between the selected-configuration label's frame and its text.
# Set here rather than in commander.ui because PyQt6's loadUi() silently
# drops a QLabel's 'margin' property, leaving the text against the frame.
SELECTED_CONFIG_MARGIN = 5
NO_SELECTED_CONFIG = "No configuration selected"
MAX_DISPLAYED_PATH_LENGTH = 45  # longer paths are elided in the config label
PATH_ELLIPSIS = "…"
SELECTED_WR_PREFIX = "Work Requirement: "
SELECTED_WP_PREFIX = "Worker Pool: "
BUTTON_TEXT_MARGIN = 24  # px of button padding to keep clear of the label
MAX_DISPLAYED_NAME_LENGTH = 20  # fallback cap before the button has a width
MAX_DIALOG_PATH_LENGTH = 60  # dialogs are wider than the left-hand column
DESELECT_ROW_PREFIX = "Deselect "  # keeps the checkbox polarity unambiguous
SKIP_CONFIRMATION_BUTTON_TEXT = "Yes to All (Don't Ask Again)"
MAX_DIALOG_LIST_ROWS = 12  # visible entity rows before the list scrolls
ENTITY_ROW_GAP = 2  # spaces between the name and status columns
ENTITY_LIST_PADDING = 6  # px of breathing room inside the entity list's frame
MAX_LOGGED_ENTITY_IDS = 3  # above this, the echoed command line shows a count
# strftime for the pre-filled save-output filename. Colons are not filename-safe
# on Windows, so this cannot reuse the ':'-separated prefix format used in the
# output window itself.
SAVED_OUTPUT_NAME_FORMAT = "commander-output-%Y%m%d-%H%M%S.txt"
SAVED_OUTPUT_FILTER = "Text files (*.txt);;All files (*)"
TERMINATE_TIMEOUT_MS = 2000  # grace period for a child to exit on terminate()
KILL_TIMEOUT_MS = 1000  # further wait after resorting to kill()
CONFIG_PARSE_TIMEOUT_MS = 10_000  # 'yd-show' can block on an unreachable API URL
# The one retry after a timeout gets a longer budget: by then it is known that a
# 'yd-show' here is slow rather than hung, and on Windows the first 'yd-*' of a
# session can legitimately need this long to start (interpreter start, SDK
# imports, a virus scan of a freshly installed console script).
CONFIG_PARSE_RETRY_TIMEOUT_MS = 30_000
CONFIG_PARSE_RETRY_DELAY_MS = 1_000  # let the event loop breathe before retrying
CWD = os.getcwd()  # default dir for file dialogs when no config selected
RESULTS_DIR = "results"
PREVIEW_PANE_WIDTH = 300  # px: the width a file dialog's preview pane opens at
PREVIEW_MIN_WIDTH = 120  # px: how narrow the user may drag that pane
PREVIEW_IMAGE_HEIGHT = 220  # px: fallback thumbnail height, before layout
PREVIEW_READ_BYTES = 262_144  # bytes read from the head of a file to preview it
PREVIEW_MAX_LINES = 500  # lines of that head shown before the preview is elided
# Characters of any one of those lines shown before it is cut. A performance cap
# rather than a cosmetic one: QPlainTextEdit lays a single line out at superlinear
# cost, so the 256kB head of a minified JSON file — one line, no newlines — took
# 110ms to show, on a preview that is refilled at every arrow-key press. Cut to
# this it is 1.4ms even with every line at the cap, and 2,000 characters is some
# fifty screenfuls of a pane this wide.
PREVIEW_MAX_LINE_CHARS = 2000
# The last line of an elided preview, saying which cap stopped it. Only what is
# knowable without reading the whole file: a total line count would mean reading
# all of it, which is what the byte cap exists to avoid.
PREVIEW_ELIDED_LINES = "… first {lines} lines shown"
PREVIEW_ELIDED_BYTES = "… first {size} shown"
PREVIEW_NO_SELECTION = "No file selected"
SIDEBAR_PANE_WIDTH = 180  # px: the width a file dialog's places sidebar opens at
# The tree, because that is the view a hierarchy can be shown in — Qt's other one
# is a QListView, which has no disclosure. Its size/kind/date columns are hidden
# and its header with them; see _make_listing_a_names_only_tree().
DIALOG_VIEW_MODE = QFileDialog.ViewMode.Detail
# Where Commander keeps the file-dialog choices that outlive a dialog; see
# dialog_settings().
COMMANDER_SETTINGS_ORGANISATION = "YellowDog"
COMMANDER_SETTINGS_APPLICATION = "Commander"
SETTING_DIALOG_SIDEBAR_WIDTH = "fileDialog/sidebarWidth"
SETTING_DIALOG_VIEW_MODE = "fileDialog/viewMode"
# What the browse dialog's button for handing over to the platform's own file
# viewer says. Qt's dialog is read-only, so this is the route to deleting or
# renaming anything in the directory being browsed.
NATIVE_VIEWER_BUTTON_TEXT = (
    "Use Finder" if MACOS else "Use Explorer" if WINDOWS else "Use File Manager"
)
# Shown when the Path field is empty and the tag is unknown, so there is nothing
# to derive a default object path from. Better than acting on a guess: the tag is
# interpolated into the default path, and a missing one used to produce 'None*'.
NO_OBJECT_PATH = (
    "No object path: the namespace/tag discovery has not succeeded, so there is"
    " no default path to match. Enter a Path, or reselect the configuration file."
)
BRANDING_IMAGE_LIGHT = join(_PKG_DIR, "images", "IconYellowDog.svg")
BRANDING_IMAGE_DARK = join(_PKG_DIR, "images", "IconYellowDogDark.svg")
BRANDING_IMAGE_SIZE = 54
ICON_IMAGE = join(_PKG_DIR, "images", "IconApi.ico")

NAMESPACE = "namespace"
TAG = "tag"
WP_DATA = "workerPoolData"
WR_DATA = "workRequirementData"


@dataclass(frozen=True)
class EntitySummary:
    """
    The identity of one entity in a '-D --json' enumeration: the YDID used to
    target it on the command line, plus the name and status shown to the user.
    """

    id: str
    name: str
    status: str | None


def parse_entity_summaries(parsed: list) -> list[EntitySummary] | None:
    """
    Convert a parsed '-D --json' array into EntitySummary objects. Returns None
    if any row is not a dict or lacks an 'id' or a 'name': without a YDID the
    entity cannot be targeted individually, and a selection must never fall back
    to name-based targeting, because names are not guaranteed unique and the
    action is destructive.
    """
    summaries: list[EntitySummary] = []
    for obj in parsed:
        if not isinstance(obj, dict):
            return None
        entity_id, name = obj.get("id"), obj.get("name")
        if not entity_id or not name:
            return None
        status = obj.get("status")
        summaries.append(
            EntitySummary(
                id=str(entity_id),
                name=str(name),
                status=None if status is None else str(status),
            )
        )
    return summaries


@dataclass(frozen=True)
class SelectableRow:
    """
    One row of a checkable listing: the text the user reads, the handle passed
    back to the command if the row stays ticked, and the tooltip. The handle is
    deliberately opaque — that is what lets one widget serve both entity YDIDs
    and object storage paths.
    """

    display: str
    handle: str
    tooltip: str


@dataclass(frozen=True)
class Confirmation:
    """
    The outcome of a destructive-action confirmation. 'proceed' is False when the
    user declined or dismissed the dialog. 'handles' is None when there was
    nothing individually selectable — a suppressed confirmation, or an
    enumeration that failed — in which case the caller acts over its whole scope.
    Otherwise 'handles' is exactly what the user left ticked, and an empty list
    means the user deselected everything, which must act on nothing at all.

    The three states are separate fields rather than a nullable list because the
    difference between 'whole scope' and 'nothing' is the difference between
    destroying everything and destroying nothing.
    """

    proceed: bool
    handles: list[str] | None

    def __bool__(self) -> bool:
        """
        Refuse truthiness. Both 'act over the whole scope' and 'act on nothing'
        are legitimate outcomes, so a bare 'if confirmation:' cannot mean
        anything safe — and unlike the list sentinel this replaced, an always-
        truthy object would proceed even when the user declined. Callers must
        read .proceed explicitly.
        """
        raise TypeError("check Confirmation.proceed explicitly, not truthiness")


def entity_rows(entities: list[EntitySummary]) -> list[SelectableRow]:
    """
    Rows for an entity listing: the name padded to a common width so the status
    column lines up, with the YDID as the handle and kept out of the row text
    (full YDIDs are long enough to push the readable columns off-screen). The
    tooltip carries both, so a row elided by a narrow dialog still has a
    recovery path.
    """
    name_width = max((len(entity.name) for entity in entities), default=0)
    gap = " " * ENTITY_ROW_GAP
    return [
        SelectableRow(
            display=(
                f"{entity.name.ljust(name_width)}{gap}{entity.status or ''}".rstrip()
            ),
            handle=entity.id,
            tooltip=f"{entity.name}\n{entity.id}",
        )
        for entity in entities
    ]


@dataclass(frozen=True)
class ObjectSummary:
    """
    One item in a 'yd-delete -D --json' enumeration: the resolved remote path
    used to delete it, its display name (directories carry a trailing '/'), and
    whether it is a directory — which decides whether the confirmation warns
    that a tick takes the directory's whole contents.
    """

    path: str
    name: str
    is_dir: bool


def parse_object_summaries(parsed: list) -> list[ObjectSummary] | None:
    """
    Convert a parsed 'yd-delete -D --json' array into ObjectSummary objects.
    Returns None if any row is not a dict or lacks a 'path' or a 'name': without
    a path the object cannot be targeted, and guessing one would delete
    something other than what the user ticked. A missing 'isDir' defaults to
    False rather than rejecting the row, because it affects only the display and
    the recursion caveat, never which paths are deleted.
    """
    summaries: list[ObjectSummary] = []
    for obj in parsed:
        if not isinstance(obj, dict):
            return None
        path, name = obj.get("path"), obj.get("name")
        if not path or not name:
            return None
        summaries.append(
            ObjectSummary(path=str(path), name=str(name), is_dir=bool(obj.get("isDir")))
        )
    return summaries


def object_rows(objects: list[ObjectSummary]) -> list[SelectableRow]:
    """
    Rows for an object listing: a single column of display names (a directory
    keeps its trailing '/'), with the resolved remote path as the handle. No
    column padding, unlike entity rows — there is no second column to align.
    """
    return [
        SelectableRow(
            display=obj.name,
            handle=obj.path,
            tooltip=f"{obj.name}\n{obj.path}",
        )
        for obj in objects
    ]


def path_would_be_globbed(remote_path: str) -> bool:
    """
    Whether 'yd-delete' would treat this remote path as a wildcard pattern
    rather than a literal object. Mirrors dataclient_utils.is_glob (which
    Commander cannot import, since that module pulls in rclone_api): strip a
    leading 'remote:' prefix, then look for glob metacharacters.

    This matters because an object whose own name contains '*', '?' or '['
    cannot be targeted by path at all — 'yd-delete' would expand it and act on
    whatever it matched instead, which for 'a[1].txt' is the sibling 'a1.txt'.
    """
    path_part = remote_path.split(":", 1)[-1] if ":" in remote_path else remote_path
    return contains_glob_chars(path_part)


def format_file_size(size: int) -> str:
    """
    A file size in the units the platform's own file viewers use — powers of
    1000, as both Finder and Windows Explorer report — with one decimal place
    above a kilobyte. Small files keep their exact byte count, where '87 bytes'
    says more than '0.1 kB'.
    """
    if size < 1000:
        return f"{size} byte{'' if size == 1 else 's'}"
    scaled = float(size)
    for unit in ("kB", "MB", "GB"):
        scaled /= 1000
        if scaled < 1000:
            return f"{scaled:,.1f} {unit}"
    return f"{scaled / 1000:,.1f} TB"


def dialog_settings() -> QSettings:
    """
    Where Commander keeps the file-dialog choices that outlive a dialog: the width
    of the places sidebar and which of Qt's two views to list files in.

    Commander's own, rather than the ones Qt keeps under FileDialog/*. Qt writes
    those whenever one of these dialogs closes, so every machine that has ever
    opened one carries a value and there is no telling a width the user chose from
    a default written back — which made a default conditional on 'nothing
    remembered' a no-op everywhere but a brand-new profile. Keeping our own
    removes the guess: the stored value is one a user set, and its absence means
    they have set nothing.

    A function, not a constant, so that the tests can point it at a file of their
    own instead of the developer's real settings.
    """
    return QSettings(
        QSettings.Scope.UserScope,
        COMMANDER_SETTINGS_ORGANISATION,
        COMMANDER_SETTINGS_APPLICATION,
    )


class FilePreview(QWidget):
    """
    The preview column added to the directory-browsing file dialog: the name of
    whatever is highlighted, a size-and-kind line, and then either a scaled
    thumbnail (anything Qt can decode as an image) or the head of the file as
    text (anything that decodes as UTF-8). Anything else — a binary, an
    unreadable file — gets the size-and-kind line alone, which is still more
    than the bare listing says.

    This exists because Qt's own file dialog has no preview, and Commander's
    directory buttons no longer hand the directory to the platform's file
    viewer, so Finder's Quick Look is not there to fall back on. It is a plain
    widget driven by the dialog's currentChanged signal rather than a
    QFileDialog subclass, so the dialog itself stays the stock one.

    Its width is the user's to set (it goes into the dialog's own splitter), so
    the pane keeps the decoded image rather than only the scaled thumbnail: a
    widened pane rescales from the original, where rescaling the thumbnail would
    show a magnified version of the smaller one.
    """

    def __init__(self, font: QFont, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumWidth(PREVIEW_MIN_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.name_label = QLabel()
        self.name_label.setWordWrap(True)
        name_font = self.name_label.font()
        name_font.setBold(True)
        self.name_label.setFont(name_font)
        layout.addWidget(self.name_label)

        self.meta_label = QLabel()
        self.meta_label.setWordWrap(True)
        layout.addWidget(self.meta_label)

        # Pinned to the top, and to the height their own text needs. A label
        # defaults to taking a share of any spare height and centring its text in
        # it, and a directory — named and kinded, with no body to show — leaves
        # the pane nothing but spare height: the two headings ended up a third
        # and two thirds of the way down, reading as two unrelated captions.
        for label in (self.name_label, self.meta_label):
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self.image_view = QLabel()
        self.image_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Ignored in both directions: a QLabel's size hint grows with the pixmap
        # it holds, so a label that drives the layout would widen the pane to fit
        # the thumbnail, which rescales the thumbnail, which widens the pane.
        self.image_view.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
        )
        self.image_view.setMinimumSize(1, 1)
        layout.addWidget(self.image_view, 1)

        self.text_view = QPlainTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text_view.setFont(font)
        layout.addWidget(self.text_view, 1)

        # Where the spare height goes once the headings will not take it, and
        # once both bodies are hidden. Deliberately stretch 0, unlike the two
        # bodies: a stretch of 1 would make it an equal claimant with whichever
        # body is on show, halving the thumbnail or the text for nothing.
        layout.addItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )

        self._image: QImage | None = None  # the decoded original, for rescaling
        self.clear()

    def clear(self):
        """Show the placeholder, as before anything has been highlighted."""
        self._describe(PREVIEW_NO_SELECTION, "")

    def show_path(self, path: str):
        """
        Preview whatever 'path' names. Connected to the dialog's currentChanged,
        so it is called for directories and for paths that have since gone away
        as well as for files, and must show something for all of them.
        """
        if not path or not exists(path):
            self.clear()
            return

        if isdir(path):
            self._describe(basename(path.rstrip("/\\")) or path, "Directory")
            return

        name = basename(path)
        try:
            size = getsize(path)
        except OSError as error:
            self._describe(name, f"Unreadable: {error.strerror or error}")
            return

        image, image_format = self._read_image(path)
        if image is not None:
            self._describe(
                name,
                f"{format_file_size(size)}  ·  {image_format} image"
                f"  ·  {image.width()} x {image.height()}",
            )
            self._image = image
            # Shown before it is filled: _thumbnail measures the label, and a
            # layout leaves a hidden widget's geometry alone.
            self.image_view.setVisible(True)
            self.image_view.setPixmap(self._thumbnail(image))
            return

        head = self._decoded_head(path)
        if head is None:
            self._describe(name, f"{format_file_size(size)}  ·  no preview available")
            return
        self._describe(name, f"{format_file_size(size)}  ·  text")
        self.text_view.setPlainText(head)
        self.text_view.setVisible(True)

    def _describe(self, name: str, meta: str):
        """
        Set the two heading lines and hide both preview bodies, which is the
        state every branch of show_path starts from — one of them then reveals
        the body it has filled in.
        """
        self.name_label.setText(name)
        self.meta_label.setText(meta)
        self._image = None
        self.image_view.clear()
        self.image_view.setVisible(False)
        self.text_view.clear()
        self.text_view.setVisible(False)

    @staticmethod
    def _read_image(path: str) -> tuple[QImage | None, str]:
        """
        The decoded image and the name of its format, or (None, "") if Qt cannot
        read the file as an image. canRead() alone is not enough: it is happy
        with a truncated or corrupt file that read() then fails on, and a
        half-downloaded result file is exactly the case in hand.
        """
        reader = QImageReader(path)
        reader.setAutoTransform(True)  # honour a JPEG's EXIF orientation
        if not reader.canRead():
            return None, ""
        # Read the format first: it is the detected format of a file not yet
        # consumed, and comes back empty once read() has been called.
        image_format = reader.format().data().decode(errors="replace").upper()
        image = reader.read()
        if image.isNull():
            return None, ""
        return image, image_format or "unrecognised"

    def resizeEvent(self, a0):
        """
        Rescale the thumbnail to the pane's new width. Dragging the pane wider
        should show more of the image, not the same thumbnail with more grey
        around it — and there is no other moment at which the new width is known.
        """
        super().resizeEvent(a0)
        if self._image is not None:
            self.image_view.setPixmap(self._thumbnail(self._image))

    def _thumbnail(self, image: QImage) -> QPixmap:
        """
        The image scaled to fit the space the pane currently gives it,
        downscaling only — blowing a 16x16 icon up to the width of the pane
        makes it less recognisable, not more. Falls back to the pane's opening
        size for a preview filled in before the pane has been laid out.
        """
        layout = self.layout()
        if layout is not None:
            # Give the label its real geometry before measuring it. A layout is
            # otherwise activated by an event, which has not been delivered yet
            # when the pane has only just been shown or resized — leaving the
            # label at its default size, and the thumbnail scaled to that.
            layout.activate()
        available = QSize(
            self.image_view.width() or PREVIEW_PANE_WIDTH,
            self.image_view.height() or PREVIEW_IMAGE_HEIGHT,
        )
        pixmap = QPixmap.fromImage(image)
        if (
            pixmap.width() <= available.width()
            and pixmap.height() <= available.height()
        ):
            return pixmap
        return pixmap.scaled(
            available,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    @staticmethod
    def _cut(line: str) -> str:
        """
        One line of a preview, cut to PREVIEW_MAX_LINE_CHARS and marked if it was
        longer. See that constant: this is what keeps a file with no newlines in it
        from taking a tenth of a second to show.
        """
        if len(line) <= PREVIEW_MAX_LINE_CHARS:
            return line
        return f"{line[:PREVIEW_MAX_LINE_CHARS]}…"

    @classmethod
    def _decoded_head(cls, path: str) -> str | None:
        """
        The first lines of a text file — ending in a line saying which cap stopped
        it, if either did — or None if the file is not text.

        That last line states only what reading the head can know: how many lines
        were shown, or how much of the file was read. A total line count would mean
        reading all of it, which is what the byte cap is here to avoid.

        Read as bytes and decoded strictly, rather than trusted by extension:
        task output, logs and JSON arrive with every extension and none. The
        incremental decoder is what makes the byte cap safe — it holds back a
        multi-byte character straddling the cap instead of declaring the file
        binary. A NUL byte is treated as proof of binary before that, since a
        UTF-16 file decodes as UTF-8 without complaint and would otherwise be
        previewed as gibberish interleaved with NULs.
        """
        try:
            with open(path, "rb") as file:
                head = file.read(PREVIEW_READ_BYTES + 1)
        except OSError:
            return None

        truncated = len(head) > PREVIEW_READ_BYTES
        head = head[:PREVIEW_READ_BYTES]
        if b"\0" in head:
            return None
        try:
            text = getincrementaldecoder("utf-8")(errors="strict").decode(
                head, final=not truncated
            )
        except UnicodeDecodeError:
            return None

        lines = text.splitlines()
        body = "\n".join(cls._cut(line) for line in lines[:PREVIEW_MAX_LINES])
        if len(lines) > PREVIEW_MAX_LINES:
            # The binding cap when both bite: the reader has been given 500 lines,
            # and the byte cap behind them is not what stopped the preview.
            return (
                f"{body}\n{PREVIEW_ELIDED_LINES.format(lines=f'{PREVIEW_MAX_LINES:,}')}"
            )
        if truncated:
            return (
                f"{body}\n"
                f"{PREVIEW_ELIDED_BYTES.format(size=format_file_size(PREVIEW_READ_BYTES))}"
            )
        return body


class LineBuffer:
    """
    Accumulates raw bytes read from a subprocess output channel and yields
    complete lines. Pipe reads don't respect line boundaries (or UTF-8
    character boundaries), so any partial trailing line is held back until the
    rest of it arrives; without this, appending each read to the log pane
    inserts a spurious line break wherever a read boundary happens to fall.
    """

    def __init__(self):
        self._decoder = getincrementaldecoder("utf-8")(errors="replace")
        self._partial_line = ""

    def feed(self, data: bytes) -> list[str]:
        """
        Add the bytes from one read and return the lines completed by them.
        """
        self._partial_line += self._decoder.decode(data)
        *lines, self._partial_line = self._partial_line.split("\n")
        return [line.rstrip("\r") for line in lines]

    def flush(self) -> list[str]:
        """
        Return any unterminated final line. Only safe to call once no more
        data is coming, i.e. when the process has exited.
        """
        self._partial_line += self._decoder.decode(b"", final=True)
        remainder, self._partial_line = self._partial_line.rstrip("\r"), ""
        return [remainder] if remainder else []


def elide_path(path: str, max_length: int = MAX_DISPLAYED_PATH_LENGTH) -> str:
    """
    Shorten a file path for display so that it doesn't stretch the layout,
    keeping the end of the path (including the filename) visible. Paths within
    the length limit are returned unchanged.
    """
    if len(path) <= max_length:
        return path

    tail = path[-(max_length - len(PATH_ELLIPSIS)) :]
    separator_index = tail.find(os.sep)
    if separator_index != -1:  # discard any partial leading directory name
        tail = tail[separator_index:]
    return f"{PATH_ELLIPSIS}{tail}"


def elide_middle(text: str, max_length: int = MAX_DISPLAYED_NAME_LENGTH) -> str:
    """
    Shorten text for display by removing characters from the middle, keeping
    both ends visible. Used for filenames, where the start and the extension
    are the informative parts.
    """
    if len(text) <= max_length:
        return text

    keep = max_length - len(PATH_ELLIPSIS)
    head = keep - keep // 2
    return f"{text[:head]}{PATH_ELLIPSIS}{text[len(text) - keep // 2 :]}"


def checked_handles(listing: QListWidget) -> list[str]:
    """
    The handles of the ticked rows of a selection list, in list order.
    """
    handles: list[str] = []
    for index in range(listing.count()):
        item = listing.item(index)
        if item is not None and item.checkState() == Qt.CheckState.Checked:
            handles.append(item.data(Qt.ItemDataRole.UserRole))
    return handles


def set_all_check_states(
    listing: QListWidget, state: Qt.CheckState, *_signal_args
) -> None:
    """
    Set every row of a selection list to the same check state, for the All / None
    buttons. Takes and ignores the trailing signal arguments so it can be
    connected to 'clicked' directly.
    """
    for index in range(listing.count()):
        item = listing.item(index)
        if item is not None:
            item.setCheckState(state)


def update_selection_state(
    listing: QListWidget,
    count_label: QLabel,
    yes_btn: QPushButton,
    *_signal_args,
) -> None:
    """
    Refresh the 'N of M selected' label and gate the Yes button on something
    being selected, so the dialog cannot confirm a run that would do nothing.
    """
    selected = len(checked_handles(listing))
    count_label.setText(f"{selected} of {listing.count()} selected")
    yes_btn.setEnabled(selected > 0)


def command_line_text(command: str, args: list[str]) -> str:
    """
    A command and its arguments as echoed to the output window.
    """
    return (command + " " + " ".join(args)).rstrip()


class CommandHistory:
    def __init__(self, max_size: int = 250):
        self._max_size = max_size
        self._ptr = 0
        self._commands: list[str] = []
        self._empty_string_returned = False

    def save_command(self, command: str):
        """
        Save a command at the end of the command list.
        Consecutive duplicates are not stored.
        """
        if self._commands and self._commands[-1] == command:
            return
        if len(self._commands) == self._max_size:
            self._commands.pop(0)
        self._commands.append(command)
        self._ptr = len(self._commands) - 1
        self._empty_string_returned = False

    def step_forward(self) -> str | None:
        """
        Return the next (later) command in the list.
        Return an empty string if already at the end of the list.
        """
        if len(self._commands) == 0:
            return None
        if self._ptr < len(self._commands) - 1:
            self._ptr += 1
        else:
            self._empty_string_returned = True
            return ""
        return self._commands[self._ptr]

    def step_back(self) -> str | None:
        """
        Return the previous (earlier) command in the list.
        Keep returning the first command if pointer is at the start.
        """
        if len(self._commands) == 0:
            return None
        if self._ptr > 0:
            if self._empty_string_returned:
                self._empty_string_returned = False
            else:
                self._ptr -= 1
        return self._commands[self._ptr]


class YellowDogApp(QMainWindow):
    # Widgets populated at runtime by loadUi("commander.ui"); declared here so
    # static type checkers can resolve their attribute references.
    branding: QLabel
    select_config_label: QLabel
    wr_options_label: QLabel
    wp_options_label: QLabel
    object_path_label: QLabel

    log_output: QPlainTextEdit
    user_variables: QPlainTextEdit
    wr_submit_options: QPlainTextEdit
    wp_provision_options: QPlainTextEdit
    any_command: QPlainTextEdit
    namespace_override: QPlainTextEdit
    tag_override: QPlainTextEdit
    name_glob_override: QPlainTextEdit
    object_path_override: QPlainTextEdit
    stdin_input: QPlainTextEdit

    follow_progress: QCheckBox
    dry_run: QCheckBox
    follow_worker_pool: QCheckBox
    dry_run_worker_pool: QCheckBox
    dry_run_objects: QCheckBox
    dark_mode: QCheckBox

    select_config_file: QPushButton
    select_work_requirement: QPushButton
    submit_work_requirement: QPushButton
    download_results: QPushButton
    clear_command_output: QPushButton
    copy_command_output: QPushButton
    save_command_output: QPushButton
    delete_objects: QPushButton
    cancel_work_requirements: QPushButton
    cancel_work_requirements_and_abort: QPushButton
    select_worker_pool: QPushButton
    create_worker_pool: QPushButton
    shutdown_all_worker_pools: QPushButton
    terminate_all_compute_requirements: QPushButton
    view_results: QPushButton
    show_configuration: QPushButton
    show_wr: QPushButton
    show_wp: QPushButton
    deselect_files: QPushButton
    view_config_directory: QPushButton
    run_any_command: QPushButton
    next_command: QPushButton
    prev_command: QPushButton

    def __init__(
        self, config_file: str | None = None, disable_confirmations: bool = False
    ):
        super().__init__()
        self._confirmations_disabled = disable_confirmations

        # Dynamically loads the QT UI definition
        loadUi(join(_PKG_DIR, "commander.ui"), self)

        # Include the CLI version in the window title
        self.setWindowTitle(WINDOW_TITLE)

        # The framed label showing the selected configuration file (the frame
        # itself comes from commander.ui, which cannot carry this margin)
        self.select_config_label.setMargin(SELECTED_CONFIG_MARGIN)

        self._align_field_labels()

        self._pid = os.getpid()

        # The width of the file dialogs' preview pane, for the session: set it
        # once by dragging, and every later dialog opens at that width.
        self._preview_width = PREVIEW_PANE_WIDTH

        # Override the branding pixmap with the SVG for the current style
        self._update_branding_icon(self._color_scheme() == Qt.ColorScheme.Dark)

        # Actual displayed font sizes differ across platforms;
        # use a smaller point size on Windows and Linux for the output window
        self._font = QFont()
        self._font.setPointSize(12 if MACOS else 8)
        self._font.setFamily("Courier New")
        self._font.setWeight(500)
        self.log_output.setFont(self._font)

        # Set up action connections
        self.select_config_file.clicked.connect(self._select_config_file_action)
        self.select_work_requirement.clicked.connect(
            self._select_work_requirement_action
        )
        self.submit_work_requirement.clicked.connect(
            self._submit_work_requirement_action
        )
        self.download_results.clicked.connect(self._download_results_action)
        self.clear_command_output.clicked.connect(self._clear_output_action)
        self.copy_command_output.clicked.connect(self._copy_output_action)
        self.save_command_output.clicked.connect(self._save_output_action)
        self.delete_objects.clicked.connect(self._delete_objects_action)
        self.cancel_work_requirements.clicked.connect(
            self._cancel_work_requirements_action
        )
        self.cancel_work_requirements_and_abort.clicked.connect(
            self._cancel_work_requirements_and_abort_action
        )
        self.select_worker_pool.clicked.connect(self._select_worker_pool_action)
        self.create_worker_pool.clicked.connect(self._create_worker_pool_action)
        self.shutdown_all_worker_pools.clicked.connect(
            self._shutdown_all_worker_pools_action
        )
        self.terminate_all_compute_requirements.clicked.connect(
            self._terminate_all_compute_requirements_action
        )
        self.view_results.clicked.connect(self._view_results_action)
        self.show_configuration.clicked.connect(self._show_config_action)
        self.show_wr.clicked.connect(self._show_wr_action)
        self.show_wp.clicked.connect(self._show_wp_action)
        self.deselect_files.clicked.connect(self._deselect_files_action)
        self.view_config_directory.clicked.connect(self._view_config_directory_action)
        self.run_any_command.clicked.connect(self._run_any_command_action)

        self.next_command.clicked.connect(self._next_command_action)
        self.prev_command.clicked.connect(self._prev_command_action)

        # Handle state toggle exclusivity; the 'exclusive' property on the
        # containing button group doesn't allow a state where no boxes are
        # checked
        self.follow_progress.checkStateChanged.connect(self._follow_progress_set)
        self.dry_run.checkStateChanged.connect(self._dry_run_set)
        self.follow_worker_pool.checkStateChanged.connect(self._follow_worker_pool_set)
        self.dry_run_worker_pool.checkStateChanged.connect(
            self._dry_run_worker_pool_set
        )
        self.dark_mode.checkStateChanged.connect(self._dark_mode_action)
        self.dark_mode.setChecked(self._color_scheme() == Qt.ColorScheme.Dark)

        # Default the 'follow' checkboxes
        self.follow_progress.setChecked(True)
        self.follow_worker_pool.setChecked(True)

        # Handle specific key presses in text edit boxes
        for ui_object in [
            self.user_variables,
            self.wr_submit_options,
            self.wp_provision_options,
            self.any_command,
            self.namespace_override,
            self.tag_override,
            self.name_glob_override,
            self.object_path_override,
        ]:
            ui_object.textChanged.connect(
                functools_partial(self._edit_box_keypress_handler, ui_object)
            )

        self._config_file: str | None = None
        # Absolute, deliberately: these are handed to a child process that runs
        # in the config file's directory (see _working_dir), while Commander's own
        # directory is wherever it was launched from — and Show reads them in this
        # process. A path relative to either base is wrong for the other, so
        # 'yd-submit -r ../demos/bash/x.json' went looking for it under the config
        # directory and failed. The config file needs no such care: its consumers
        # take _config_dir() and _config_basename() from it rather than passing it on.
        self._wr_file: str | None = None
        self._wp_file: str | None = None
        self._skip_confirmations: set[str] = set()

        # Original 'Select' button labels, restored when a file is deselected
        self._select_wr_default_text = self.select_work_requirement.text()
        self._select_wp_default_text = self.select_worker_pool.text()

        self._namespace: str | None = None
        self._tag: str | None = None
        self._config_parse_invalid = True  # nothing discovered yet
        self._config_parse_timed_out = False
        self._config_parse_retried = False
        self._last_discovery_failure: str | None = None

        # One retry of namespace/tag discovery, a moment after a timeout. Timers
        # here are parented to the window so they die with it; a bare
        # QTimer.singleShot would fire into destroyed widgets.
        self._discovery_retry_timer = QTimer(self)
        self._discovery_retry_timer.setSingleShot(True)
        self._discovery_retry_timer.timeout.connect(self._retry_discovery)

        # Watch the selected config file for on-disk changes
        self._file_watcher = QFileSystemWatcher(self)
        self._file_watcher.fileChanged.connect(self._on_config_file_changed)

        # Invalidate the config parse cache when inputs that affect it change
        for ui_object in [
            self.namespace_override,
            self.tag_override,
            self.user_variables,
        ]:
            ui_object.textChanged.connect(self._invalidate_config_parse)

        # Re-evaluate namespace/tag placeholders after a short delay when
        # user-defined variables change (debounced to avoid running yd-show
        # on every keystroke)
        self._user_vars_reparse_timer = QTimer(self)
        self._user_vars_reparse_timer.setSingleShot(True)
        self._user_vars_reparse_timer.setInterval(600)
        self._user_vars_reparse_timer.timeout.connect(self._reparse_placeholders)
        self.user_variables.textChanged.connect(self._user_vars_reparse_timer.start)

        # Defer config parse until after the window is shown, so the GUI is
        # visible before yd-show runs
        QTimer.singleShot(0, lambda: self._set_config_file(config_file))

        self._any_command_history = CommandHistory()
        self._active_process: QProcess | None = None

        # Live child processes and nested event loops, so that shutdown() can
        # stop them deterministically instead of leaving them to be torn down
        # with the widgets. Commands launched from the UI are kept separately
        # from internal synchronous helpers, because only the former are worth
        # asking the user about on quit.
        self._processes: list[QProcess] = []
        self._helper_processes: list[QProcess] = []
        self._nested_loops: list[QEventLoop] = []
        self._shutting_down = False
        # How many nested event loops are running. A nested loop keeps the main
        # window interactive, so without this an action could be started while
        # another was mid-enumeration.
        #
        # A depth counter rather than a flag, because nested loops really do
        # nest: the config parse deferred below with singleShot(0) runs in the
        # first event loop to spin, which can be one an enumeration has already
        # entered — observed reaching depth 2 for a single enumeration. A flag
        # cleared by the inner parse finishing would unlock the window while the
        # outer loop was still blocking, which is the bug this avoids.
        self._nested_depth = 0
        self.stdin_input.textChanged.connect(
            functools_partial(self._edit_box_keypress_handler, self.stdin_input)
        )

    def _update_branding_icon(self, is_dark: bool):
        path = BRANDING_IMAGE_DARK if is_dark else BRANDING_IMAGE_LIGHT
        self.branding.setPixmap(
            QIcon(path).pixmap(QSize(BRANDING_IMAGE_SIZE, BRANDING_IMAGE_SIZE))
        )

    def _invalidate_config_parse(self):
        """
        Mark the discovered namespace/tag stale, and give the next discovery a
        fresh retry. The retry budget is per parse, not per session: a new
        configuration file must not inherit the exhausted budget of the last one.
        """
        self._config_parse_invalid = True
        self._config_parse_retried = False

    def _reparse_placeholders(self, timeout_ms: int | None = None):
        """
        Re-run discovery and show what it found, scheduling one retry if it timed
        out. The single place that pairs a parse with the placeholders, so a
        caller cannot get the retry by accident and lose it by accident.
        """
        if self._parse_yd_config(quiet=True, timeout_ms=timeout_ms):
            self._set_placeholders(self._namespace or "", self._tag or "")
            return
        self._schedule_discovery_retry()

    def _schedule_discovery_retry(self):
        """
        Queue the one retry allowed after a timed-out discovery.

        Only after a *timeout*: a non-zero exit or a program that cannot be
        started will fail again the same way, so retrying would only be noise. A
        timeout is different — the incident this exists for was a first 'yd-show'
        on Windows that needed longer than its budget to start, where the second
        one is warm and finishes at once. Before this, the placeholders stayed
        blank until Commander was restarted, which is what the user had to do.
        """
        if (
            self._shutting_down
            or self._config_parse_retried
            or not self._config_parse_timed_out
        ):
            return
        self._config_parse_retried = True
        self._log(
            f"Retrying namespace/tag discovery with a"
            f" {CONFIG_PARSE_RETRY_TIMEOUT_MS // 1000}s timeout; the first"
            f" 'yd-*' command of a session can be slow to start"
        )
        self._discovery_retry_timer.start(CONFIG_PARSE_RETRY_DELAY_MS)

    def _retry_discovery(self):
        self._reparse_placeholders(timeout_ms=CONFIG_PARSE_RETRY_TIMEOUT_MS)

    def _report_discovery_failure(self, message: str):
        """
        Say why namespace/tag discovery failed. Logged however quiet the parse
        was: blank placeholders with nothing in the output window to explain them
        is what left a Windows incident with no evidence to diagnose.

        Consecutive identical messages are suppressed, because the user-variables
        box reparses 600ms after every edit and a broken configuration would
        otherwise fill the window with one line over and over. A success clears
        the memory, so the same failure recurring is reported again.
        """
        if message == self._last_discovery_failure:
            return
        self._last_discovery_failure = message
        self._log(message)

    def _set_placeholders(self, namespace: str, tag: str):
        """
        Update the placeholder text showing the namespace, tag and object path
        that will be used if those fields are left blank.

        The viewport repaints are scheduled with update() rather than forced
        with repaint(): callers reach this immediately after _parse_yd_config
        has run a nested event loop, and forcing a synchronous paint of a text
        widget from there is what appears to make macOS log bursts of
        'TSMSendMessageToUIServer ... FAILED(-1)'. Control returns to the event
        loop directly afterwards, so the placeholders still appear at once.
        It has to be the viewport, not the widget: QPlainTextEdit is a scroll
        area, and the placeholder text is painted by its viewport.
        """
        self.namespace_override.setPlaceholderText(namespace)
        cast(QWidget, self.namespace_override.viewport()).update()
        self.tag_override.setPlaceholderText(tag)
        cast(QWidget, self.tag_override.viewport()).update()
        default_prefix = f"{tag}*" if tag else ""
        self.object_path_override.setPlaceholderText(default_prefix)
        cast(QWidget, self.object_path_override.viewport()).update()

    def _yd_show_command(self) -> tuple[str, list[str]]:
        """
        The 'yd-show' invocation that resolves the namespace and tag for the
        current configuration source, namespace/tag overrides and user variables.
        """
        return "yd-show", (
            self._config_source_args()
            + [
                "--nf",
                "-q",
                "-r",
                NAMESPACE,
                "-r",
                TAG,
            ]
            + self._namespace_tag_and_user_vars()
        )

    def _parse_yd_config(
        self, quiet: bool = False, timeout_ms: int | None = None
    ) -> bool:
        """
        Parse the configuration file to obtain the CLI-processed values of the
        namespace and tag variables, used to populate placeholder text.

        'timeout_ms' defaults to CONFIG_PARSE_TIMEOUT_MS; the retry after a
        timeout passes a longer one. Every failure is reported through
        _report_discovery_failure, whatever 'quiet' says — 'quiet' suppresses the
        announcement of a routine reparse, not the reason one failed.
        """
        if not self._config_parse_invalid:
            return True
        if timeout_ms is None:
            timeout_ms = CONFIG_PARSE_TIMEOUT_MS
        self._config_parse_timed_out = False

        yd_process = QProcess()
        event_loop = QEventLoop()

        env = QProcessEnvironment.systemEnvironment()
        yd_process.setProcessEnvironment(env)
        yd_process.setWorkingDirectory(self._working_dir())

        yd_process.finished.connect(event_loop.quit)
        yd_process.errorOccurred.connect(event_loop.quit)

        cmd, args = self._yd_show_command()

        if not quiet:
            self._log(f"Discovering namespace/tag: '{cmd + ' ' + ' '.join(args)}'")
        yd_process.start(cmd, args)
        if not self._run_nested(yd_process, event_loop, timeout_ms):
            if self._shutting_down:
                return False  # the widgets are going away; don't touch them
            self._config_parse_timed_out = True
            self._report_discovery_failure(
                f"Timed out after {timeout_ms // 1000}s parsing"
                f" configuration with 'yd-show'"
            )
            return False

        if yd_process.error() != QProcess.ProcessError.UnknownError:
            self._report_discovery_failure(
                f"Error parsing config with 'yd-show': {yd_process.errorString()}"
            )
            return False

        if yd_process.exitCode() != 0:
            error_output = yd_process.readAllStandardError().data().decode().strip()
            self._report_discovery_failure(
                f"Error parsing config with 'yd-show'"
                f" (Exit {yd_process.exitCode()}): {error_output}"
            )
            return False

        output = yd_process.readAllStandardOutput().data().decode().strip()
        try:
            parsed_data = loads(output)
            self._namespace = parsed_data.get(NAMESPACE)
            self._tag = parsed_data.get(TAG)
        except Exception as e:
            self._report_discovery_failure(f"Error reading config variables: {e}")
            return False

        self._config_parse_invalid = False
        self._last_discovery_failure = None  # a recurrence is worth reporting again
        return True

    def _on_config_file_changed(self, _path: str):
        """
        Called by QFileSystemWatcher when the config file is modified on disk.
        Some editors save atomically (write-new + rename), which removes the
        original inode and causes the watcher to drop the path; re-add it so
        subsequent saves are still detected.
        """
        if self._config_file is not None:
            abs_path = abspath(self._config_file)
            if exists(abs_path) and abs_path not in self._file_watcher.files():
                self._file_watcher.addPath(abs_path)
        self._invalidate_config_parse()
        self._log(f"Config file '{self._config_file}' changed on disk; refreshing...")
        self._reparse_placeholders()

    def _set_config_file(self, config_file: str | None):
        """
        Setting config_file to None will deselect the current config file.
        """
        # Stop watching the previously selected config file
        if self._config_file is not None:
            self._file_watcher.removePath(abspath(self._config_file))

        if config_file is None:
            self._config_file = None
            self.select_config_label.setText(NO_SELECTED_CONFIG)
            self.select_config_label.setToolTip("")
            self._invalidate_config_parse()
            # Cleared first, then filled in again by whatever discovery finds
            # without a config file (environment variables, or nothing at all):
            # the previous file's namespace and tag must not linger either way.
            self._set_placeholders("", "")
            self._reparse_placeholders()
            return

        if not exists(config_file):
            self._log(f"Config file '{config_file}' does not exist")
            return

        selected_config_file = relpath(config_file)
        self._config_file = selected_config_file
        self._invalidate_config_parse()
        self._log(f"Selected configuration file '{selected_config_file}'")
        self.select_config_label.setText(elide_path(selected_config_file))
        self.select_config_label.setToolTip(abspath(selected_config_file))
        self._reparse_placeholders()
        self._file_watcher.addPath(abspath(selected_config_file))

    def _select_config_file_action(self):
        file = self._select_file(
            caption="Please select a configuration file",
            directory=(self._config_dir() if self._config_file else CWD),
            file_pattern="*.toml",
        )
        if file is None:
            self._log(NO_SELECTED_CONFIG)
        else:
            self._set_config_file(file)

    def _check_config_file(self, quiet: bool = False) -> bool:
        if self._config_file is None:
            if not quiet:
                self._log(NO_SELECTED_CONFIG)
            return False
        return True

    def _align_field_labels(self):
        """
        Start the left-hand column's input fields at one edge, by widening each
        of their labels to the widest of them.

        Their rows sit in three separate panel layouts, and Qt aligns nothing
        across layouts, so each field began wherever its own label happened to
        end — at 110, 110 and 56. Measured here rather than set as a width in
        commander.ui, because a width in pixels is a width for one font: these
        labels are the widest under this one, and need not be under the next.
        """
        labels = (self.wr_options_label, self.wp_options_label, self.object_path_label)
        widest = max(label.sizeHint().width() for label in labels)
        for label in labels:
            label.setMinimumWidth(widest)

    def _align_checkbox_indicators(self):
        """
        Indent the left-hand column's checkboxes by however far the current style
        insets a push button's frame inside its widget, so that the indicators line
        up with the buttons above and below them.

        Both are laid out at the same x. The macOS style then paints a button's
        bevel 2px in — room for its focus ring — and a checkbox's indicator flush,
        which leaves the checkboxes looking a couple of pixels further left than
        every button in the column.

        Read from the style rather than written as 2, because Dark Mode switches
        the application style to Fusion and back (see _dark_mode_action), and
        Fusion paints the bevel flush; hence also the recomputation on a style
        change in changeEvent(), and clearing the margins before measuring, so that
        the measurement is of the style and not of the last margin applied.

        Not covered by a test: the inset only exists when painting through the real
        platform, so it cannot be reproduced offscreen — even under the macOS style
        a headless button reports its bevel flush. Verified by measuring the painted
        pixels of a real window, where the buttons start at x=22 and the checkboxes
        did at x=20.
        """
        checkboxes = (
            self.dry_run,
            self.follow_progress,
            self.dry_run_worker_pool,
            self.follow_worker_pool,
            self.dry_run_objects,
        )
        for checkbox in checkboxes:
            checkbox.setStyleSheet("")

        inset = self._button_bevel_inset(
            self.submit_work_requirement
        ) - self._indicator_inset(self.dry_run)
        if inset <= 0:
            return
        for checkbox in checkboxes:
            checkbox.setStyleSheet(f"margin-left: {inset}px")

    @staticmethod
    def _button_bevel_inset(button: QPushButton) -> int:
        """How far inside its widget the current style paints a push button's frame."""
        option = QStyleOptionButton()
        button.initStyleOption(option)
        style = button.style()
        if style is None:
            return 0
        return style.subElementRect(
            QStyle.SubElement.SE_PushButtonBevel, option, button
        ).left()

    @staticmethod
    def _indicator_inset(checkbox: QCheckBox) -> int:
        """The same, for a checkbox's indicator."""
        option = QStyleOptionButton()
        checkbox.initStyleOption(option)
        style = checkbox.style()
        if style is None:
            return 0
        return style.subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, option, checkbox
        ).left()

    def showEvent(self, a0):
        """
        Align the checkboxes once the window is on screen. The style resolves a
        button's bevel inset against the real platform, so measuring it in
        __init__ reports flush — 0 rather than 2 — and the indent never gets
        applied. Idempotent, so a later show costs nothing.
        """
        super().showEvent(a0)
        self._align_checkbox_indicators()

    def changeEvent(self, a0):
        """
        Re-align the checkboxes when the application style changes, which Dark Mode
        does: the inset they are indented by belongs to the style, not to the theme.
        """
        super().changeEvent(a0)
        if a0 is not None and a0.type() == QEvent.Type.StyleChange:
            self._align_checkbox_indicators()

    def _config_dir(self) -> str:
        """
        Absolute path of the directory containing the selected config file.
        Callers must ensure a config file is selected (see _check_config_file).
        """
        return dirname(abspath(cast(str, self._config_file)))

    def _config_basename(self) -> str:
        """
        Base name of the selected config file.
        Callers must ensure a config file is selected (see _check_config_file).
        """
        return basename(cast(str, self._config_file))

    def _working_dir(self) -> str:
        """
        Directory to run commands in: the selected config file's directory if
        one is selected, otherwise the launch directory (cwd).
        """
        return self._config_dir() if self._config_file is not None else os.getcwd()

    def _config_source_args(self) -> list[str]:
        """
        CLI flags selecting the config source: the selected config file, or
        '--nc' (--no-config) to force environment-variable / CLI-argument mode.
        """
        return (
            ["-c", self._config_basename()]
            if self._config_file is not None
            else ["--nc"]
        )

    @staticmethod
    def _color_scheme() -> Qt.ColorScheme:
        return cast(QStyleHints, QApplication.styleHints()).colorScheme()

    def _show_selection_on_button(
        self, button: QPushButton, prefix: str, default_text: str, file: str | None
    ):
        """
        Indicate the selected definition file on its own 'Select' button, so
        that the selection is visible without adding a widget to the left-hand
        column. The filename is elided to fit the button's current width, so a
        long name never widens the column; the full path becomes the tooltip.
        Passing file=None restores the button's original label.
        """
        if file is None:
            button.setText(default_text)
            button.setToolTip("")
            return

        name = basename(file)
        metrics = QFontMetrics(button.font())
        available = (
            button.width() - BUTTON_TEXT_MARGIN - metrics.horizontalAdvance(prefix)
        )
        if available > 0:
            name = metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, available)
        else:  # not yet laid out, so fall back to a character cap
            name = elide_middle(name)
        button.setText(f"{prefix}{name}")
        button.setToolTip(abspath(file))

    def _show_wr_selection(self):
        self._show_selection_on_button(
            self.select_work_requirement,
            SELECTED_WR_PREFIX,
            self._select_wr_default_text,
            self._wr_file,
        )

    def _show_wp_selection(self):
        self._show_selection_on_button(
            self.select_worker_pool,
            SELECTED_WP_PREFIX,
            self._select_wp_default_text,
            self._wp_file,
        )

    def _select_work_requirement_action(self):
        directory = CWD if self._config_file is None else self._config_dir()
        file = self._select_file(
            caption="Please select a Work Requirement definition file",
            directory=directory,
            file_pattern="*.json *.jsonnet",
        )
        if file is None:
            self._log("No Work Requirement definition file selected")
        else:
            self._wr_file = abspath(file)
            self._log(f"Selected Work Requirement definition '{self._wr_file}'")
            self._show_wr_selection()

    def _select_worker_pool_action(self):
        directory = CWD if self._config_file is None else self._config_dir()
        file = self._select_file(
            caption="Please select a Worker Pool definition file",
            directory=directory,
            file_pattern="*.json *.jsonnet",
        )
        if file is None:
            self._log("No Worker Pool definition file selected")
        else:
            self._wp_file = abspath(file)
            self._log(f"Selected Worker Pool definition '{self._wp_file}'")
            self._show_wp_selection()

    def _submit_work_requirement_action(self):
        # Generate and run the command
        if self._wr_file is None:
            args = []
        else:
            args = ["-r", self._wr_file]
        dry_run = self.dry_run.isChecked()
        follow_progress = self.follow_progress.isChecked()
        if dry_run:
            args += ["-D"]
        if follow_progress and not dry_run:
            args += ["-f"]
        args += self.wr_submit_options.toPlainText().split()
        self._run_command_in_subprocess("yd-submit", args)

    def _prefix(self, pid: int | None = None) -> str:
        """
        Create a prefix the same as that used by the CLI.
        """
        if pid is None:
            pid = self._pid
        return f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({pid:06d}) : "

    def _object_path(self) -> str | None:
        """
        The object path the download and delete actions work on: the Path field
        if it has one, otherwise every object whose name starts with the
        discovered tag.

        None when neither is available — the Path field is empty and no tag has
        been discovered. Callers must refuse rather than carry on: this used to
        interpolate the missing tag and return the literal 'None*', which was
        then handed to 'yd-download' and 'yd-delete' as the scope to act on.
        """
        override = self.object_path_override.toPlainText().strip()
        if override:
            return override
        return f"{self._tag}*" if self._tag else None

    def _scope_phrase(self, match_word: str) -> str:
        """
        A human-readable ' in namespace X with <match_word> including Y' phrase
        describing how the CLI selects entities: Work Requirements and Compute
        Requirements are matched by tag ('tags'), Worker Pools by name ('names').
        Uses the discovered namespace/tag, degrading gracefully when unknown.
        """
        if self._namespace and self._tag:
            return (
                f" in namespace '{self._namespace}'"
                f" with {match_word} including '{self._tag}'"
            )
        if self._namespace:
            return f" in namespace '{self._namespace}'"
        if self._tag:
            return f" with {match_word} including '{self._tag}'"
        return " in the current namespace and tag"

    def _confirm_destructive(
        self,
        action_key: str,
        title: str,
        body: str,
        *,
        rows: list[SelectableRow] | None = None,
    ) -> Confirmation:
        """
        Show a warning confirmation dialog for a destructive action. Returns a
        Confirmation with 'proceed' False if the action must not proceed;
        otherwise 'handles' is None when there was nothing individually
        selectable (no listing, or a suppressed confirmation) — the caller
        acts over its whole scope — or the ticked subset when 'rows' was
        supplied, where an empty list means the user deselected everything and
        the caller must act on nothing at all.

        'rows' is keyword-only because 'names' — a second, positionally
        adjacent listing parameter — used to sit here too; a positional call
        would have silently landed the wrong argument in this slot. Now there
        is only one listing parameter, but the call stays keyword-only so a
        future one can't reintroduce the hazard.

        'Yes to All (Don't Ask Again)' confirms and suppresses future
        confirmations for this same action (identified by action_key) for the
        rest of the session; the suppression is per-action, not global. It acts
        on every listed row regardless of the tick states, as its label says.
        """
        if self._confirmations_disabled or action_key in self._skip_confirmations:
            return Confirmation(proceed=True, handles=None)
        dialog, yes_btn, skip_btn = self._build_destructive_dialog(
            title, body, rows=rows
        )
        buttons = cast(QDialogButtonBox, dialog.findChild(QDialogButtonBox))
        clicked: dict[str, object] = {}
        buttons.clicked.connect(
            lambda button: (clicked.__setitem__("button", button), dialog.accept())
        )
        dialog.exec()

        try:
            if clicked.get("button") is skip_btn:
                self._skip_confirmations.add(action_key)
                return Confirmation(
                    proceed=True,
                    handles=[row.handle for row in rows] if rows else None,
                )
            if clicked.get("button") is not yes_btn:
                return Confirmation(proceed=False, handles=None)
            if not rows:
                return Confirmation(proceed=True, handles=None)
            listing = cast(QListWidget, dialog.findChild(QListWidget, "selection_list"))
            return Confirmation(proceed=True, handles=checked_handles(listing))
        finally:
            # Parented to the main window, so without this every confirmation
            # dialog — and the hundreds of list items it may own — would live
            # for the rest of the session.
            dialog.deleteLater()

    def _build_selection_list_widget(self, rows: list[SelectableRow]) -> QListWidget:
        """
        A checkable list, every row ticked. Each row shows its display text in
        the monospaced output font and holds its handle in UserRole, which is
        where the run arguments are read from; the tooltip carries the fuller
        text so a row elided by a narrow dialog (QListWidget's default
        ElideRight) is still recoverable. The widget's height is fixed to its
        content, capped at MAX_DIALOG_LIST_ROWS rows so a long listing scrolls
        instead of growing the dialog past the screen.

        The horizontal scrollbar is turned off explicitly, and the height is
        fixed rather than merely capped, because of one bug in each direction. A
        scrollbar appears when a name overflows a narrow dialog and then eats the
        height budgeted for the rows — on Windows that left a 1px viewport, so the
        list showed nothing but the scrollbar. And a bare maximum lets the layout
        squeeze the list towards nothing when the dialog is short of space, which
        is platform- and font-dependent. Eliding plus the tooltip is the intended
        way to cope with a long name, not scrolling sideways.

        ENTITY_LIST_PADDING keeps the rows off the frame, which otherwise reads
        as cramped once there are more than a handful. Qt folds stylesheet
        padding into frameWidth(), so the height below picks it up on its own —
        do not add it a second time.

        A QListWidget is used rather than a column of QCheckBox widgets (as
        _build_deselect_dialog uses for its three fixed rows) because a busy
        namespace or bucket prefix can enumerate hundreds of items, which
        QListWidget scrolls, keyboard-navigates and repaints natively. 'rows'
        must be non-empty.
        """
        listing = QListWidget()
        listing.setObjectName("selection_list")
        listing.setFont(self._font)
        listing.setStyleSheet(f"QListWidget {{ padding: {ENTITY_LIST_PADDING}px; }}")
        listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for row in rows:
            item = QListWidgetItem(row.display)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setToolTip(row.tooltip)
            item.setData(Qt.ItemDataRole.UserRole, row.handle)
            listing.addItem(item)

        row_height = listing.sizeHintForRow(0)
        if row_height > 0:
            visible_rows = min(len(rows), MAX_DIALOG_LIST_ROWS)
            height = row_height * visible_rows + 2 * listing.frameWidth()
            listing.setFixedHeight(height)
        return listing

    def _build_destructive_dialog(
        self,
        title: str,
        message: str,
        *,
        rows: list[SelectableRow] | None = None,
    ) -> tuple[QDialog, QPushButton, QPushButton]:
        """
        Build (but do not show) the destructive-action confirmation dialog: a
        warning icon and message, an optional listing of the affected items, and
        No / Yes / 'Yes to All' buttons (default No). Returns the dialog and the
        Yes / skip buttons so the caller can identify which was clicked.

        With 'rows', the listing is a checkable QListWidget with All / None
        buttons and an 'N of M selected' label, so the user can act on a subset;
        Yes is disabled while nothing is ticked. Without 'rows' — nothing was
        individually selectable — there is no listing at all, and the caller
        acts over its whole scope.

        A plain QDialog is used rather than QMessageBox so the listing has full
        formatting control (no ugly wrapping) and no native-alert 'detailed
        text' limitations.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)

        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(
            cast(QStyle, self.style())
            .standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
            .pixmap(QSize(48, 48))
        )
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        header.addWidget(icon_label)
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        header.addWidget(message_label, stretch=1)
        layout.addLayout(header)

        selection_listing, count_label = self._add_selection_listing(layout, rows)

        button_box = QDialogButtonBox()
        no_btn = cast(
            QPushButton,
            button_box.addButton("No", QDialogButtonBox.ButtonRole.RejectRole),
        )
        yes_btn = cast(
            QPushButton,
            button_box.addButton("Yes", QDialogButtonBox.ButtonRole.AcceptRole),
        )
        skip_btn = cast(
            QPushButton,
            button_box.addButton(
                SKIP_CONFIRMATION_BUTTON_TEXT,
                QDialogButtonBox.ButtonRole.AcceptRole,
            ),
        )
        no_btn.setDefault(True)
        layout.addWidget(button_box)

        self._wire_selection_gating(selection_listing, count_label, yes_btn)

        return dialog, yes_btn, skip_btn

    def _action_buttons(self) -> tuple[QPushButton, ...]:
        """
        The buttons whose actions enumerate before acting, and so must not be
        startable while an enumeration is already blocking in a nested event
        loop. Submit and provision are absent deliberately: they launch a command
        and return, without a nested loop or a pre-flight listing to be confused.

        All six grey together, including ones unrelated to the action in flight.
        That is deliberately conservative rather than strictly required — the
        demonstrable failure is one action re-entering itself, where the inner
        dialog's 'Don't Ask Again' makes the outer call return an empty selection.
        Overlapping *different* actions has no such failure, but it interleaves two
        listings in the one output window and stacks two modal confirmations in an
        order unrelated to the clicks, which is a poor property for irreversible
        operations. One rule also stays correct as actions are added. The block
        lasts one subprocess, so the cost is a second or two, visibly greyed.
        """
        return (
            self.cancel_work_requirements,
            self.cancel_work_requirements_and_abort,
            self.shutdown_all_worker_pools,
            self.terminate_all_compute_requirements,
            self.download_results,
            self.delete_objects,
        )

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        """
        Grey the enumerating actions out, or restore them. Safe to restore
        unconditionally because nothing else ever disables these buttons.
        """
        for button in self._action_buttons():
            button.setEnabled(enabled)

    def _operation_in_flight(self, action: str) -> bool:
        """
        Whether a nested event loop is already blocking, in which case 'action'
        must not start. Logs when it refuses, so a click that lands anyway — a
        queued one, or a keyboard activation — does not look as though it was
        simply ignored.

        The check belongs at the top of each action, not inside the enumeration:
        a re-entrant enumeration that returned None would be read as 'enumeration
        failed', which for the destructive actions means falling back to acting
        over the whole scope. Refusing early is the only safe answer.
        """
        if self._nested_depth == 0:
            return False
        self._log(f"Another operation is still in progress; ignoring {action}")
        return True

    def _handles_are_safe_to_target(
        self, handles: list[str], verb: str, past_participle: str
    ) -> bool:
        """
        Whether every selected object path can be named literally on a yd-*
        command line. False — with the offending names logged — when any contains
        a glob metacharacter or a '{{' substitution placeholder.

        Both would be expanded before the absolute-path check ever sees them, so
        the command would act on whatever they matched or resolved to rather than
        on the object the user ticked. The whole run is refused rather than the
        offending handles dropped: acting on part of a confirmed selection leaves
        the user believing it all happened. 'verb'/'past_participle' shape the
        message, e.g. 'delete'/'removed' or 'download'/'downloaded'.
        """
        unsafe = [
            handle
            for handle in handles
            if path_would_be_globbed(handle) or "{{" in handle
        ]
        if not unsafe:
            return True

        self._log(
            f"Cannot {verb} by path — these names contain wildcard characters"
            " ('*', '?', '[') or a '{{' substitution placeholder:"
            f" {', '.join(unsafe)}."
            f" Deselect them to {verb} the rest; these objects can only be"
            f" {past_participle} with rclone directly."
        )
        return False

    def _add_selection_listing(
        self, layout: QVBoxLayout, rows: list[SelectableRow] | None
    ) -> tuple[QListWidget | None, QLabel | None]:
        """
        Add the checkable listing and its All / None buttons and count label to a
        dialog's layout, returning both so the caller can gate its accept button
        on them. Returns (None, None) when there are no rows — nothing was
        individually selectable — in which case the dialog shows no listing.

        Shared by the destructive-confirmation dialog and the download chooser,
        which differ only in their surrounding chrome (warning icon, wording and
        buttons), not in how a selection is presented or read back.
        """
        if not rows:
            return None, None

        listing = self._build_selection_list_widget(rows)
        count_label = QLabel()
        count_label.setObjectName("selection_count")
        all_btn = QPushButton("All")
        all_btn.setObjectName("select_all")
        all_btn.clicked.connect(
            functools_partial(set_all_check_states, listing, Qt.CheckState.Checked)
        )
        none_btn = QPushButton("None")
        none_btn.setObjectName("select_none")
        none_btn.clicked.connect(
            functools_partial(set_all_check_states, listing, Qt.CheckState.Unchecked)
        )
        # These are the first focusable widgets in the dialog, and an autoDefault
        # QPushButton that has focus takes over as the dialog's default button —
        # which would leave 'All' highlighted instead of the intended default
        # ('No' on a confirmation, 'Download' on a chooser) and make Return do the
        # wrong thing. Opt them out so the explicit default stands.
        all_btn.setAutoDefault(False)
        none_btn.setAutoDefault(False)
        controls = QHBoxLayout()
        controls.addWidget(all_btn)
        controls.addWidget(none_btn)
        controls.addStretch(1)
        controls.addWidget(count_label)
        layout.addLayout(controls)
        layout.addWidget(listing)
        return listing, count_label

    def _wire_selection_gating(
        self,
        listing: QListWidget | None,
        count_label: QLabel | None,
        accept_btn: QPushButton,
    ) -> None:
        """
        Keep the 'N of M selected' label and the accept button in step with the
        listing's check states, so neither dialog can accept a selection of
        nothing. A no-op when there is no listing, since then the caller acts
        over its whole scope rather than a selection.
        """
        if listing is None or count_label is None:
            return
        refresh = functools_partial(
            update_selection_state, listing, count_label, accept_btn
        )
        listing.itemChanged.connect(refresh)
        refresh()

    def _build_chooser_dialog(
        self,
        title: str,
        message: str,
        accept_text: str,
        rows: list[SelectableRow],
    ) -> tuple[QDialog, QPushButton]:
        """
        Build (but do not show) a non-destructive chooser: a message, the same
        checkable listing the confirmation dialog uses, and Cancel / <accept_text>
        buttons with the accept button as the default. Returns the dialog and that
        button so the caller can tell acceptance from dismissal.

        Deliberately unlike _build_destructive_dialog: no warning icon, no 'this
        cannot be undone', and no 'Don't Ask Again'. Following the precedent set
        by Deselect Files, a chooser is not a confirmation — nothing it does is
        irreversible, and suppressing it would remove the only way to pick a
        subset. 'rows' must be non-empty; with nothing to choose there is no
        reason to ask.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)

        message_label = QLabel(message)
        message_label.setWordWrap(True)
        layout.addWidget(message_label)

        listing, count_label = self._add_selection_listing(layout, rows)

        button_box = QDialogButtonBox(dialog)
        button_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        accept_btn = cast(
            QPushButton,
            button_box.addButton(accept_text, QDialogButtonBox.ButtonRole.AcceptRole),
        )
        accept_btn.setDefault(True)
        # Unlike the confirmation dialog, whose caller inspects which button was
        # clicked, this one only needs accept-or-dismiss — so wire the box straight
        # to the dialog. Without these the buttons do nothing at all and exec()
        # never returns.
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        self._wire_selection_gating(listing, count_label, accept_btn)

        return dialog, accept_btn

    def _capture_dry_run_json(
        self, command: str, extra_args: list[str] | None = None
    ) -> list | None:
        """
        Run '<command> -D --json' (quiet, no formatting) with the current config
        source and namespace/tag/user variables, and return the parsed JSON
        array. Return None on any failure (process error, non-zero exit, or
        output that is not a JSON array) so callers can fall back to a
        scope-level confirmation.
        """
        yd_process = QProcess()
        event_loop = QEventLoop()

        env = QProcessEnvironment.systemEnvironment()
        yd_process.setProcessEnvironment(env)
        yd_process.setWorkingDirectory(self._working_dir())

        yd_process.finished.connect(event_loop.quit)
        yd_process.errorOccurred.connect(event_loop.quit)

        args = (
            self._config_source_args()
            + ["--nf", "-q", "-D", "--json"]
            + self._namespace_tag_and_user_vars()
            + (extra_args or [])
        )
        yd_process.start(command, args)
        self._run_nested(yd_process, event_loop)
        if self._shutting_down:
            return None  # the widgets are going away; don't touch them

        if yd_process.error() != QProcess.ProcessError.UnknownError:
            return None
        if yd_process.exitCode() != 0:
            return None

        output = yd_process.readAllStandardOutput().data().decode().strip()
        try:
            parsed = loads(output)
        except Exception:
            return None
        return parsed if isinstance(parsed, list) else None

    def _capture_dry_run_summaries(
        self, command: str, extra_args: list[str] | None = None
    ) -> list[EntitySummary] | None:
        """
        The affected entities from a '-D --json' enumeration, with their YDIDs,
        so the user can select a subset and the action can target exactly that
        subset. Returns None when the enumeration failed or did not carry YDIDs,
        which drops the caller to a scope-level confirmation.
        """
        parsed = self._capture_dry_run_json(command, extra_args)
        if parsed is None:
            return None
        summaries = parse_entity_summaries(parsed)
        if summaries is None:
            self._log("Entity listing did not include YDIDs; cannot offer a selection")
        return summaries

    def _capture_dry_run_objects(
        self, command: str, extra_args: list[str]
    ) -> list[ObjectSummary] | None:
        """
        The objects and top-level directories 'command' would act on, with the
        resolved path needed to name each one individually. Returns None when the
        enumeration failed or did not carry paths, which drops the caller back to
        acting over the whole pattern.

        'command' is 'yd-delete' or 'yd-download': both emit the same row shape
        from their '--dry-run --json' mode, and both offer the same selection
        over it.
        """
        parsed = self._capture_dry_run_json(command, extra_args)
        if parsed is None:
            return None
        summaries = parse_object_summaries(parsed)
        if summaries is None:
            self._log("Object listing did not include paths; cannot offer a selection")
        return summaries

    def _choose_objects(
        self, title: str, body: str, accept_text: str, rows: list[SelectableRow]
    ) -> list[str] | None:
        """
        Offer a non-destructive chooser over 'rows' and return the handles left
        ticked, or None if the user dismissed it. The accept button is disabled
        while nothing is ticked, so the returned list is never empty.

        Unlike _confirm_destructive this has no action_key and no 'Don't Ask
        Again': you would never want to stop being offered a choice permanently.
        Callers are responsible for honouring '--yes', which is a launch-time
        request for unattended operation rather than a mid-session one.
        """
        dialog, _accept_btn = self._build_chooser_dialog(title, body, accept_text, rows)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted.value:
                return None
            listing = cast(QListWidget, dialog.findChild(QListWidget, "selection_list"))
            return checked_handles(listing)
        finally:
            # Parented to the main window, so without this every chooser — and
            # the rows it owns — would live for the rest of the session.
            dialog.deleteLater()

    def _download_results_action(self):
        """
        Download matching objects from remote storage into the results directory,
        letting the user choose which of the matched items to fetch.

        Enumerates via 'yd-download -D --json' first: with nothing matching, log
        and do nothing; when the enumeration fails there are no paths to choose
        between, so fall back to downloading the whole pattern as before.

        The dry-run-checkbox preview fetches nothing, so it runs directly with no
        enumeration or chooser.

        '--yes' skips the chooser and fetches everything matched, as it does for
        the destructive confirmations. The chooser is not a confirmation, but
        '--yes' asks for unattended operation, and an unattended session cannot
        answer a chooser either; a user who wants a subset without being asked can
        narrow the Path field instead.
        """
        if self._operation_in_flight("Download Matching Objects"):
            return

        dst = join(self._working_dir(), RESULTS_DIR)
        path = self._object_path()
        if path is None:
            self._log(NO_OBJECT_PATH)
            return

        if self.dry_run_objects.isChecked():
            self._run_command_in_subprocess("yd-download", ["--into", dst, path, "-D"])
            return

        if self._confirmations_disabled:
            self._log(
                "Selection suppressed by '--yes';"
                f" downloading all objects matching '{path}'"
            )
            self._run_command_in_subprocess("yd-download", ["--into", dst, path])
            return

        self._log(f"Checking which objects match '{path}'...")
        self.log_output.repaint()
        objects = self._capture_dry_run_objects("yd-download", [path])

        if objects is not None and not objects:
            self._log(f"No objects match '{path}'")
            return

        if objects is None:
            self._log("Could not list matching objects; downloading them all instead")
            self._run_command_in_subprocess("yd-download", ["--into", dst, path])
            return

        body = f"Downloading objects matching '{path}' into '{RESULTS_DIR}'."
        if any(obj.is_dir for obj in objects):
            body += " A ticked directory is downloaded with everything inside it."
        handles = self._choose_objects(
            "Download Objects", body, "Download", object_rows(objects)
        )
        if handles is None:
            return

        if not self._handles_are_safe_to_target(handles, "download", "downloaded"):
            return

        self._run_command_in_subprocess(
            "yd-download",
            ["--into", dst] + handles,
            log_args=self._abbreviated_run_args(["--into", dst], handles, "objects"),
        )

    def _delete_objects_action(self):
        """
        Delete matching objects from remote storage, letting the user select
        which of the matched items to remove. Enumerates via
        'yd-delete -D --json -R <path>' first: with nothing matching, log a
        message and do nothing; when the enumeration fails there are no paths to
        target, so confirm at the scope level (without a list) and delete the
        whole pattern.

        The dry-run-checkbox preview changes nothing, so it runs directly with no
        enumeration or confirmation. The '-y'/per-action-skip bypasses delete the
        whole pattern, logging that they have done so.
        """
        if self._operation_in_flight("Delete Matching Objects"):
            return

        path = self._object_path()
        if path is None:
            self._log(NO_OBJECT_PATH)
            return

        if self.dry_run_objects.isChecked():
            # Harmless preview: run directly, no enumeration or confirmation.
            self._run_command_in_subprocess("yd-delete", ["-Ry", path, "-D"])
            return

        if self._confirmations_disabled or "delete" in self._skip_confirmations:
            self._log(
                f"Confirmations suppressed for 'delete';"
                f" deleting all objects matching '{path}'"
            )
            self._run_command_in_subprocess("yd-delete", ["-Ry", path])
            return

        self._log(f"Checking which objects match '{path}'...")
        self.log_output.repaint()
        objects = self._capture_dry_run_objects("yd-delete", ["-R", path])

        if objects is not None and not objects:
            self._log(f"No objects match '{path}'")
            return

        body = f"Deleting objects matching '{path}'."
        if objects and any(obj.is_dir for obj in objects):
            body += " A ticked directory is deleted with everything inside it."
        body += "\n\nThis cannot be undone."
        if objects is None:
            self._log("Could not list affected objects; confirming by scope instead")

        rows = object_rows(objects) if objects else None
        result = self._confirm_destructive("delete", "Delete Objects", body, rows=rows)
        if not result.proceed:
            return

        if result.handles is None:
            # The enumeration failed, so there are no paths to target: delete the
            # whole pattern the user has just confirmed.
            self._run_command_in_subprocess("yd-delete", ["-Ry", path])
            return

        if not result.handles:
            # 'yd-delete -Ry' with no paths would delete the entire configured
            # prefix, so an empty selection must never reach the command.
            self._log("Nothing selected to delete; no objects removed")
            return

        if not self._handles_are_safe_to_target(result.handles, "delete", "removed"):
            return

        self._run_command_in_subprocess(
            "yd-delete",
            ["-Ry"] + result.handles,
            log_args=self._abbreviated_run_args(["-Ry"], result.handles, "objects"),
        )

    def _clear_output_action(self):
        self.log_output.setPlainText("")

    def _copy_output_action(self):
        cast(QClipboard, QApplication.clipboard()).setText(
            self.log_output.toPlainText()
        )

    def _save_output_action(self):
        """
        Save the command output window's contents to a file the user nominates.
        The dialog pre-fills a timestamped name in the working directory, so
        repeated saves in one session land in separate files rather than
        prompting to overwrite.

        With no output, log and stop rather than writing an empty file: the user
        asked to save what they can see, and an empty file is not that.
        """
        text = self.log_output.toPlainText()
        if not text:
            self._log("No command output to save")
            return

        default_name = datetime.now().strftime(SAVED_OUTPUT_NAME_FORMAT)
        path = self._save_file(
            caption="Save Command Output",
            directory=join(self._working_dir(), default_name),
            file_pattern=SAVED_OUTPUT_FILTER,
        )
        if path is None:
            return

        try:
            # Explicit utf-8: the output holds whatever a yd-* command emitted,
            # which can include non-ASCII, and Windows would otherwise write it
            # in a narrower default encoding.
            with open(path, "w", encoding="utf-8") as output_file:
                output_file.write(text if text.endswith("\n") else f"{text}\n")
        except OSError as e:
            self._log(f"Could not save command output to '{path}': {e}")
            return

        self._log(f"Saved command output to '{path}'")

    def _name_glob_args(self) -> list[str]:
        """
        The Name-pattern field's value as a positional glob argument for the
        destructive commands, or [] when the field is empty. It applies to
        whichever destructive action is invoked and is NOT a global
        namespace/tag override, so it is appended per-action rather than via
        '_namespace_tag_and_user_vars'.
        """
        value = self.name_glob_override.toPlainText().strip()
        return [value] if value else []

    def _abbreviated_run_args(
        self, run_args: list[str], handles: list[str], plural: str
    ) -> list[str] | None:
        """
        A display form of the run arguments for the output window: above
        MAX_LOGGED_ENTITY_IDS selected items, the handles collapse to a count so
        the echoed command line stays readable. None means 'echo the real
        arguments'. Nothing is lost by abbreviating — the dialog has just listed
        the selected items by name, and the command reports each one as it acts
        on it. 'plural' is the entity noun, e.g. 'Work Requirements'.
        """
        if len(handles) <= MAX_LOGGED_ENTITY_IDS:
            return None
        return run_args + [f"<{len(handles)} {plural}>"]

    def _run_destructive_with_listing(
        self,
        action_key: str,
        command: str,
        run_args: list[str],
        title: str,
        gerund: str,
        plural: str,
        match_word: str,
        and_abort: bool = False,
    ) -> None:
        """
        Confirm and run a destructive action, listing the affected entities for
        the user to select from and then targeting exactly that selection by
        YDID. Enumerates via '<command> -D --json' first: with no affected
        entities, log a message and do nothing; when the enumeration fails there
        are no YDIDs to target, so confirm at the scope level (without a list)
        and run over the whole scope.

        The Name pattern narrows the *enumeration* only. It must not reach a run
        that passes YDIDs, because the CLI rejects mixing glob patterns with
        literal names/IDs ('cannot mix name glob patterns with explicit
        names/IDs'); by then the pattern's job is done, the selection having
        been resolved from the entities it enumerated.

        The '-y' / per-action-skip bypasses run the command over the whole scope
        without enumerating, logging that they have done so. 'gerund'/'plural'
        describe the action (e.g. 'Cancelling'/'Work Requirements') and
        'match_word' is how the CLI selects entities ('tags' or 'names').
        """
        if self._operation_in_flight(title):
            return

        name_args = self._name_glob_args()

        # When a Name pattern is set, entities are selected by that glob rather
        # than by tag/name-substring, so describe the scope accordingly.
        if name_args:
            scope = f" matching name pattern '{name_args[0]}'"
            if self._namespace:
                scope = f" in namespace '{self._namespace}'{scope}"
        else:
            scope = self._scope_phrase(match_word)

        if self._confirmations_disabled or action_key in self._skip_confirmations:
            self._log(
                f"Confirmations suppressed for '{action_key}';"
                f" acting on all {plural}{scope}"
            )
            self._run_command_in_subprocess(command, run_args + name_args)
            return

        self._log(f"Checking which {plural} would be affected...")
        self.log_output.repaint()
        entities = self._capture_dry_run_summaries(command, extra_args=name_args)

        if entities is not None and not entities:
            self._log(f"No matching {plural}{scope}")
            return

        abort_clause = ", and aborting their running tasks" if and_abort else ""
        body = f"{gerund} {plural}{scope}{abort_clause}.\n\nThis cannot be undone."
        if entities is None:
            self._log("Could not list affected entities; confirming by scope instead")

        rows = entity_rows(entities) if entities else None
        result = self._confirm_destructive(action_key, title, body, rows=rows)
        if not result.proceed:
            return

        if result.handles is None:
            # Nothing was individually selectable — the enumeration failed — so
            # run over the scope the user has just confirmed.
            self._run_command_in_subprocess(command, run_args + name_args)
            return

        if not result.handles:
            # 'run_args + []' IS the whole-scope command, so an empty selection
            # must never fall through to the run below.
            self._log(f"Nothing selected to act on; no {plural} affected")
            return

        self._run_command_in_subprocess(
            command,
            run_args + result.handles,
            log_args=self._abbreviated_run_args(run_args, result.handles, plural),
        )

    def _cancel_work_requirements_action(self):
        self._run_destructive_with_listing(
            action_key="cancel",
            command="yd-cancel",
            run_args=["-y"],
            title="Cancel Work Requirements",
            gerund="Cancelling",
            plural="Work Requirements",
            match_word="tags",
        )

    def _cancel_work_requirements_and_abort_action(self):
        self._run_destructive_with_listing(
            action_key="cancel_abort",
            command="yd-cancel",
            run_args=["-ay"],
            title="Cancel and Abort Work Requirements",
            gerund="Cancelling",
            plural="Work Requirements",
            match_word="tags",
            and_abort=True,
        )

    def _create_worker_pool_action(self):
        if self._wp_file is None:
            args = []
        else:
            args = ["-p", self._wp_file]
        if self.follow_worker_pool.isChecked():
            args += ["-af"]
        elif self.dry_run_worker_pool.isChecked():
            args += ["-D"]
        args += self.wp_provision_options.toPlainText().split()
        self._run_command_in_subprocess("yd-provision", args)

    def _shutdown_all_worker_pools_action(self):
        self._run_destructive_with_listing(
            action_key="shutdown",
            command="yd-shutdown",
            run_args=["-y"],
            title="Shut Down Worker Pools",
            gerund="Shutting down",
            plural="Worker Pools",
            match_word="names",
        )

    def _terminate_all_compute_requirements_action(self):
        self._run_destructive_with_listing(
            action_key="terminate",
            command="yd-terminate",
            run_args=["-y"],
            title="Terminate Compute Requirements",
            gerund="Terminating",
            plural="Compute Requirements",
            match_word="tags",
        )

    def _namespace_tag_and_user_vars(self) -> list[str]:
        # Split out a list of variables of the form "x=y",
        # and prefix each with "-v" -> ["-v', "x=y"], etc.
        # Apply a namespace override if it exists.
        # Apply a tag override if it exists.
        namespace_tag_user_vars = [
            x for y in self.user_variables.toPlainText().split() for x in ["-v", y]
        ]

        tag_override = self.tag_override.toPlainText().strip()
        if tag_override:
            namespace_tag_user_vars = [
                "-t",
                tag_override,
            ] + namespace_tag_user_vars

        namespace_override = self.namespace_override.toPlainText().strip()
        if namespace_override:
            namespace_tag_user_vars = [
                "-n",
                namespace_override,
            ] + namespace_tag_user_vars

        return namespace_tag_user_vars

    def _build_command_args(
        self, command: str, args: list[str], yd_command: bool
    ) -> list[str]:
        """
        Decorate a command's arguments for execution. For 'yd-' commands this
        injects the config source ('-c <file>' or '--nc'), the namespace / tag /
        user variables, and the '--nf'/'--pp' flags. Non-yd commands are
        returned unchanged.
        """
        if yd_command:
            return (
                self._config_source_args()
                + ["--nf", "--pp"]
                + self._namespace_tag_and_user_vars()
                + args
            )

        if command.startswith("yd-"):
            args = list(args)
            # Use the selected config source unless one is set explicitly
            # (or config use is explicitly disabled) on the command line.
            if not ({"-c", "--config", "--no-config", "--nc"} & set(args)):
                args = self._config_source_args() + args
            # Ensure user-defined variables can be overridden by commands
            # by specifying them first.
            for index, var in enumerate(self._namespace_tag_and_user_vars()):
                args.insert(index, var)
            args += ["--nf", "--pp"]

        return args

    def _run_command_in_subprocess(
        self,
        command: str,
        args: list[str],
        yd_command: bool = True,
        accept_stdin: bool = False,
        log_args: list[str] | None = None,
    ):
        """
        Run a command in a subprocess, with adaptations for 'yd-'
        commands. 'log_args' replaces 'args' in the echoed command line only —
        used to collapse a long list of YDIDs to a count — and is built the
        same way, so the config-source prefix still appears in the echo.
        """
        args = self._build_command_args(command, args, yd_command)
        display_args = (
            args
            if log_args is None
            else self._build_command_args(command, log_args, yd_command)
        )

        process = QProcess(self)
        process_env: QProcessEnvironment = process.processEnvironment()

        if WINDOWS:
            # Windows non-console channels don't use utf-8 by default
            sys_env: list[str] = process.systemEnvironment()
            for env_var in sys_env:
                try:
                    name, value = env_var.split("=", 1)
                    process_env.insert(name, value)
                except ValueError:
                    pass
            process_env.insert("PYTHONIOENCODING", "utf-8")

        process.setProcessEnvironment(process_env)
        stdout_buffer = LineBuffer()
        stderr_buffer = LineBuffer()
        process.readyReadStandardOutput.connect(
            functools_partial(self._on_stdout, process, stdout_buffer)
        )
        process.readyReadStandardError.connect(
            functools_partial(self._on_stderr, process, stderr_buffer)
        )
        process.finished.connect(
            functools_partial(
                self._on_process_output_finished, process, stdout_buffer, stderr_buffer
            )
        )
        self._processes.append(process)
        process.finished.connect(functools_partial(self._forget_process, process))

        self._log(
            f"Executing: '{command_line_text(command, display_args)}'"
            f" in directory '{self._working_dir()}'"
        )

        process.setWorkingDirectory(self._working_dir())
        process.start(command, args)
        process.waitForStarted()
        if process.error() != QProcess.ProcessError.UnknownError:
            self._log(f"Error running command: '{process.errorString()}'")
        else:
            if accept_stdin:
                self._active_process = process
                self.stdin_input.setEnabled(True)
                self.stdin_input.setPlaceholderText("Send input to process...")
                process.finished.connect(self._on_active_process_finished)

    def _forget_process(self, process: QProcess, *_signal_args):
        for processes in (self._processes, self._helper_processes):
            if process in processes:
                processes.remove(process)

    def _run_nested(
        self, process: QProcess, event_loop: QEventLoop, timeout_ms: int | None = None
    ) -> bool:
        """
        Block in a nested event loop until a synchronous helper's child process
        finishes, registering both so that shutdown() can release them. A
        command blocked on a network timeout can hold this loop for as long as
        that timeout lasts, and the user can close the window while it does.

        With timeout_ms, give up after that long and stop the process. Returns
        True if the process finished on its own, and False if it timed out or
        was stopped by shutdown() — in the latter case the caller must not
        touch any widget, as they are about to be destroyed.
        """
        self._helper_processes.append(process)
        self._nested_loops.append(event_loop)

        timed_out = False
        timer: QTimer | None = None
        if timeout_ms is not None:

            def on_timeout():
                nonlocal timed_out
                timed_out = True
                event_loop.quit()

            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(on_timeout)
            timer.start(timeout_ms)

        # Hold the enumerating actions for as long as this loop blocks. The
        # buttons are greyed for visible feedback; _operation_in_flight is the
        # guard the actions themselves check, because a click already queued
        # before the buttons went grey would still be delivered.
        self._nested_depth += 1
        self._set_action_buttons_enabled(False)
        try:
            event_loop.exec()
        finally:
            self._nested_depth -= 1
            if self._nested_depth == 0 and not self._shutting_down:
                self._set_action_buttons_enabled(True)
            if timer is not None:
                timer.stop()
            self._nested_loops.remove(event_loop)
            self._forget_process(process)

        if timed_out:
            self._stop_process(process)
        return not (timed_out or self._shutting_down)

    def _stop_process(self, process: QProcess) -> bool:
        """
        Stop a running child process, politely first and forcibly if it doesn't
        go. Returns True if it was running and had to be stopped.

        The output handlers are disconnected first: they write to widgets that
        are about to be destroyed, and would otherwise fire during teardown.
        """
        if process.state() == QProcess.ProcessState.NotRunning:
            return False

        for signal in (
            process.readyReadStandardOutput,
            process.readyReadStandardError,
            process.finished,
        ):
            try:
                signal.disconnect()
            except TypeError:
                pass  # nothing was connected to this signal

        process.terminate()
        if not process.waitForFinished(TERMINATE_TIMEOUT_MS):
            process.kill()
            process.waitForFinished(KILL_TIMEOUT_MS)
        return True

    def shutdown(self):
        """
        Stop child processes and leave any nested event loop, before Qt starts
        destroying the widgets. Idempotent.

        Without this, a command still running at exit is destroyed along with
        the window: Qt warns 'QProcess: Destroyed while process is still
        running', its output handlers fire against deleted C++ objects, and the
        resulting failure during interpreter teardown is what raises a macOS
        error report. A command blocked on a network timeout — an unreachable
        API URL, say — makes this the normal case rather than a rare one.
        """
        if self._shutting_down:
            return
        self._shutting_down = True

        # Release any nested event loop (config parsing, entity enumeration):
        # the close was delivered from inside it, so it must be told to exit or
        # it will keep running while the widgets are destroyed around it
        for event_loop in list(self._nested_loops):
            event_loop.quit()

        stopped = sum(
            self._stop_process(process)
            for process in list(self._processes) + list(self._helper_processes)
        )
        if stopped:
            self._log(f"Stopped {stopped} running command(s) on exit")
        self._processes.clear()
        self._helper_processes.clear()

    def _running_commands(self) -> list[QProcess]:
        """
        Commands launched from the UI that are still running. Internal helpers
        are excluded: they are short-lived and not the user's business.
        """
        return [
            process
            for process in self._processes
            if process.state() != QProcess.ProcessState.NotRunning
        ]

    def closeEvent(self, a0: QCloseEvent | None):
        if not self._shutting_down:
            running = self._running_commands()
            if running and not self._confirmations_disabled:
                if not self._confirm_quit(running):
                    if a0 is not None:
                        a0.ignore()  # keep the window open
                    return
        self.shutdown()
        super().closeEvent(a0)

    def _confirm_quit(self, running: list[QProcess]) -> bool:
        """
        Ask whether to quit while commands are still running. Returns True if
        the user chose to quit. Suppressed by '--yes', which quits immediately.
        """
        dialog, quit_btn = self._build_quit_dialog(
            [f"{process.program()} (pid {process.processId()})" for process in running]
        )
        clicked: dict[str, object] = {}
        buttons = cast(QDialogButtonBox, dialog.findChild(QDialogButtonBox))
        buttons.clicked.connect(
            lambda button: (clicked.__setitem__("button", button), dialog.accept())
        )
        dialog.exec()
        return clicked.get("button") is quit_btn

    def _notify(self, message: str):
        """
        Log a message and show it in a modal notice, for a click that did nothing
        and would otherwise say so only in the output window.

        Logged first and always, so the output window keeps the whole narrative
        with its timestamps whether or not a dialog is shown — and so the notice
        survives the two cases that get no dialog: an unattended session, where
        '--yes' says nobody is there to press OK and a modal would hang, and
        shutdown, where the widgets are going away.
        """
        self._log(message)
        if self._confirmations_disabled or self._shutting_down:
            return
        dialog = self._build_notice_dialog(message)
        try:
            dialog.exec()
        finally:
            # Parented to the main window, so without this every notice would
            # live for the rest of the session.
            dialog.deleteLater()

    def _build_notice_dialog(self, message: str) -> QMessageBox:
        """
        Build (but do not show) the notice: one message, one OK button.

        Plain text deliberately: a notice carries filesystem paths and entity
        names, and as rich text a Windows path loses its backslashes while
        anything between angle brackets disappears as an unknown tag.

        Split from _notify so that a test can arm the real dialog rather than
        stub exec() — the convention the other dialogs here follow.
        """
        dialog = QMessageBox(self)
        dialog.setWindowTitle(WINDOW_TITLE)
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(message)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        return dialog

    def _build_quit_dialog(self, names: list[str]) -> tuple[QDialog, QPushButton]:
        """
        Build (but do not show) the quit-while-running dialog: a warning, the
        commands that would be stopped, and Cancel / 'Quit and Stop' buttons
        (default Cancel, since stopping a submission part-way is worse than
        waiting for it). Returns the dialog and the quit button.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Commands Still Running")
        layout = QVBoxLayout(dialog)

        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(
            cast(QStyle, self.style())
            .standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
            .pixmap(QSize(48, 48))
        )
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        header.addWidget(icon_label)
        message = QLabel(
            f"{len(names)} command(s) are still running. Quitting will stop "
            "them; work already submitted to the platform will carry on there."
        )
        message.setWordWrap(True)
        header.addWidget(message, stretch=1)
        layout.addLayout(header)

        listing = QPlainTextEdit()
        listing.setObjectName("running_listing")
        listing.setReadOnly(True)
        listing.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        listing.setFont(self._font)
        listing.setPlainText("\n".join(names))
        layout.addWidget(listing)

        button_box = QDialogButtonBox(dialog)
        cancel_btn = cast(
            QPushButton,
            button_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole),
        )
        quit_btn = cast(
            QPushButton,
            button_box.addButton(
                "Quit and Stop", QDialogButtonBox.ButtonRole.AcceptRole
            ),
        )
        cancel_btn.setDefault(True)
        layout.addWidget(button_box)

        return dialog, quit_btn

    def _on_active_process_finished(self):
        self._active_process = None
        self.stdin_input.setEnabled(False)
        self.stdin_input.setPlaceholderText("No command running")
        self.stdin_input.setPlainText("")

    def _send_stdin_action(self, text: str):
        if self._active_process is None:
            return
        pid = self._active_process.processId()
        self._active_process.write((text + "\n").encode())
        self._log(f"{self._prefix(pid)}<-- {text}", prefix=False)
        self.stdin_input.setPlainText("")

    def _view_results_action(self):
        """
        Browse the results directory, saying so in a dialog when there is not one
        yet — the commonest reason this button appears to do nothing, and a log
        line alone was missed. The check is repeated in _open_file_viewer, which
        keeps its log-only report for the config-directory button and for the
        directory disappearing between here and there.
        """
        results_dir = join(self._working_dir(), RESULTS_DIR)
        if not exists(results_dir):
            self._notify(f"Directory '{results_dir}' does not (yet) exist")
            return
        self._open_file_viewer(results_dir)

    def _view_config_directory_action(self):
        self._open_file_viewer(self._working_dir())

    def _open_file_viewer(self, directory: str):
        """
        Browse a directory using Qt's own file dialog rather than the platform's
        file viewer, so the listing looks and behaves like the file selectors
        elsewhere in the window. A chosen file is handed to the platform's
        default application for its type; dismissing the dialog does nothing.
        """
        if not exists(directory):
            self._log(f"Directory '{directory}' does not (yet) exist")
            return
        file_name = self._browse_with_preview(f"Browse '{directory}'", directory)
        if file_name is not None:
            self._open_with_default_application(file_name)

    def _build_browse_dialog(self, caption: str, directory: str) -> QFileDialog:
        """
        Build (but do not show) the read-only browse dialog: Qt's own file
        dialog rooted at 'directory', previewing whatever is highlighted.

        Read-only because this is a viewer, not a file manager: Qt's dialog
        otherwise offers renaming, deleting and creating folders inside the
        results directory, none of which is what the button promises.
        """
        dialog = QFileDialog(self, caption, directory)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.Option.ReadOnly, True)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        dialog.setLabelText(QFileDialog.DialogLabel.Accept, "Open")
        self._add_preview_pane(dialog)
        self._apply_dialog_preferences(dialog)
        self._add_platform_viewer_button(dialog)
        return dialog

    def _add_platform_viewer_button(self, dialog: QFileDialog):
        """
        Add a button handing the directory being browsed to the platform's own
        file viewer (Finder, Explorer, the desktop's file manager) and closing
        this dialog.

        Qt's dialog is deliberately read-only, so this is the route to deleting or
        renaming something in the results directory — which is what the platform
        viewer was worth keeping a way back to for. Closing rather than staying
        open: the viewer is where the contents get changed, and a listing left
        behind it would be showing a directory that no longer looks like that.

        ActionRole so Qt does not read the click as accepting or rejecting, and
        autoDefault off so Return still means Open — an autoDefault button that
        gains focus takes the default role from the accept button. The handler
        rejects explicitly, which is what makes _run_file_dialog report no chosen
        file: switching to the viewer is not picking something to open.
        """
        button_box = dialog.findChild(QDialogButtonBox)
        if button_box is None:
            return  # no button box to attach to: leave the dialog as Qt built it
        button = cast(
            QPushButton,
            button_box.addButton(
                NATIVE_VIEWER_BUTTON_TEXT, QDialogButtonBox.ButtonRole.ActionRole
            ),
        )
        button.setAutoDefault(False)
        button.clicked.connect(lambda: self._switch_to_platform_viewer(dialog))

        # Placed explicitly at the head of the box rather than left where the
        # style put it: each style appends an ActionRole button somewhere of its
        # own choosing — macOS after Cancel, Fusion before Open — so the button
        # moved about between platforms. First means above Open in the vertical
        # column macOS lays out, and leftmost in the row Windows and Linux do,
        # which in both cases keeps it clear of the accept and reject buttons
        # rather than trailing after them. The button stays a member of the box
        # with its role and wiring intact; only its position in the layout moves.
        box_layout = button_box.layout()
        if box_layout is not None:
            box_layout.removeWidget(button)
            cast(QBoxLayout, box_layout).insertWidget(0, button)

    def _switch_to_platform_viewer(self, dialog: QFileDialog):
        """
        Hand the directory currently on screen to the platform's file viewer and
        close the dialog. The current directory, not the one the dialog opened
        at, so navigating into a subdirectory first hands over what is displayed.
        """
        self._open_with_default_application(dialog.directory().absolutePath())
        dialog.reject()

    def _add_preview_pane(self, dialog: QFileDialog) -> FilePreview | None:
        """
        Add a FilePreview to a non-native file dialog and wire it to the
        dialog's currentChanged signal, returning it — or None if there was
        nowhere to put it.

        It goes into the splitter that already holds the dialog's sidebar and
        listing, which is what makes the width draggable, and what puts the
        handle where a user looks for one. That splitter is Qt's own, so it is
        reached defensively: a preview parented to the dialog but never placed
        would be drawn on top of the listing rather than beside it, so with no
        splitter to hold it the dialog is left exactly as Qt built it.

        How wide it opens is _apply_dialog_preferences's business, called once the
        pane is in place; what is set here is that it is deliberately not
        collapsible, a pane dragged shut leaving a handle flush against the
        dialog's edge, which is a poor thing to have to find again. The width the
        user drags it to is remembered for the session, on the dialog's own
        finished signal.
        """
        splitter = dialog.findChild(QSplitter, "splitter")
        if splitter is None:
            return None

        preview = FilePreview(self._font, dialog)
        preview.setObjectName("file_preview")
        splitter.addWidget(preview)
        index = splitter.indexOf(preview)
        splitter.setCollapsible(index, False)
        splitter.setStretchFactor(index, 0)

        dialog.currentChanged.connect(preview.show_path)
        dialog.finished.connect(
            lambda _result: self._remember_preview_width(splitter, index)
        )
        return preview

    def _remember_preview_width(self, splitter: QSplitter, index: int):
        """
        Keep the width the preview pane ended up at, for the next dialog. Read
        on the dialog's own finished signal, which is emitted while the splitter
        is still alive — a width read after deleteLater() would not be.
        """
        sizes = splitter.sizes()
        if 0 <= index < len(sizes) and sizes[index] > 0:
            self._preview_width = sizes[index]

    @staticmethod
    def _make_listing_a_names_only_tree(dialog: QFileDialog):
        """
        Turn Qt's Detail listing into the names-only hierarchy Commander shows: a
        directory expands in place rather than having to be navigated into and back
        out of, and the name gets the width the other columns were using.

        Qt ships the tree flat — `rootIsDecorated` and `itemsExpandable` both off —
        though the model under it (`QFileSystemModel`) has always been hierarchical.
        Turning them on is all the hierarchy needs, and it costs nothing that was
        there before: double-clicking a directory still navigates into it, so the
        triangle and the double-click each keep their own job. A file picked inside
        an expanded directory comes back with its full path, since the selection is
        the model's, not the listed directory's.

        That double-click behaviour is worth being sure of rather than assuming,
        since a QTreeView with expandable items can consume a double-click to
        expand instead of activating the row. Measured on macOS with a collapsed
        directory: it navigated and did not expand, with `expandsOnDoubleClick`
        either way, QFileDialog's own activation winning. It is not covered by a
        test because the offscreen platform delivers neither a double-click nor a
        Return to an item view — a stock dialog does not navigate there either.

        Size, kind and date go because between them they take most of the width and
        leave the name — the one column that says which file this is — elided. The
        header goes with them, having one column left to sort. Stretching that
        column is not cosmetic either: left at its own width the name still elides,
        now with empty space beside it, which is the worst of both.

        Applied when the dialog is built rather than when the tree is shown, so a
        user who switches views mid-dialog finds it set up either way.
        """
        tree = dialog.findChild(QTreeView, "treeView")
        if tree is None:
            return

        tree.setRootIsDecorated(True)
        tree.setItemsExpandable(True)

        header = tree.header()
        if header is None:
            return
        for column in range(1, header.count()):
            tree.setColumnHidden(column, True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(True)
        header.hide()

    def _apply_dialog_preferences(self, dialog: QFileDialog):
        """
        Set up a non-native file dialog the way the user last left one: listing
        files in their chosen view, with the places sidebar at their width and the
        preview pane — if this dialog has one — at the width the session left it
        at. Called by all three dialogs, once the pane is in place.

        The widths go in one setSizes, and every pane's is stated except the
        listing's. Both matter, because this runs on a dialog that has not been
        shown: the splitter reports placeholder sizes rather than the widths it
        has been given, so a second call throws the first call's away, and a pane
        left out of the list is squashed to its minimum. The listing is the pane
        left to the splitter, being the one that should take what is over.

        The dialog grows by whatever the panes gain, rather than the panes taking
        it out of the listing — the listing is the part the user came for.
        """
        self._make_listing_a_names_only_tree(dialog)
        dialog.setViewMode(self._preferred_view_mode())

        splitter = dialog.findChild(QSplitter, "splitter")
        if splitter is None:
            return

        # Placeholders, and no use for measuring how much wider the dialog should
        # be, so each pane says that for itself: the preview counts its whole
        # width, being a pane nothing has given any width up for yet, and the
        # sidebar only what it gains on the width Qt would have opened it at.
        sizes = splitter.sizes()
        widened = 0
        stated = False

        widening = self._sidebar_widening(dialog)
        if widening is not None:
            sizes[0], extra = widening
            widened += extra
            stated = True

        preview = dialog.findChild(FilePreview, "file_preview")
        if preview is not None:
            sizes[splitter.indexOf(preview)] = self._preview_width
            widened += self._preview_width
            stated = True

        dialog.finished.connect(
            lambda _result: self._remember_dialog_preferences(dialog, splitter)
        )

        if not stated:
            # Nothing to say about any pane, and the sizes read above are
            # placeholders — setting them would be setting nonsense.
            return
        dialog.resize(dialog.width() + widened, dialog.height())
        splitter.setSizes(sizes)

    @staticmethod
    def _remember_dialog_preferences(dialog: QFileDialog, splitter: QSplitter):
        """
        Keep the view mode and sidebar width a dialog is closing with, so the next
        one opens the way the user left this one. Read on the dialog's own finished
        signal, which is emitted while the splitter is still alive.

        Written even when they are the defaults, and that is the point: what is
        stored is a width and a mode a user has been shown and not changed, so
        Commander need never guess whether a stored value was chosen.
        """
        settings = dialog_settings()
        settings.setValue(SETTING_DIALOG_VIEW_MODE, dialog.viewMode().name)
        sizes = splitter.sizes()
        if sizes and sizes[0] > 0:
            settings.setValue(SETTING_DIALOG_SIDEBAR_WIDTH, sizes[0])

    @staticmethod
    def _preferred_view_mode() -> QFileDialog.ViewMode:
        """
        Which of Qt's two views to list files in: whichever the user last left a
        dialog in, or DIALOG_VIEW_MODE — names only — if they have not switched.

        Anything unreadable in the setting reads as 'not switched', which is the
        harmless way round: a dialog opens in Commander's own view rather than
        refusing to open.
        """
        stored = dialog_settings().value(SETTING_DIALOG_VIEW_MODE)
        try:
            return QFileDialog.ViewMode[str(stored)]
        except KeyError:
            return DIALOG_VIEW_MODE

    @classmethod
    def _sidebar_widening(cls, dialog: QFileDialog) -> tuple[int, int] | None:
        """
        How wide to open the dialog's places sidebar — 'Computer', the home
        directory, whatever the user has dropped there — and how much wider the
        dialog must be for the listing not to pay for it. None if the dialog has
        no sidebar to size.

        Qt opens the sidebar at its own size hint, which elides even 'Computer' to
        'Co...', so SIDEBAR_PANE_WIDTH is the width to start from; from then on it
        is whatever the user last dragged one to.

        The dialog pays for the width Commander chose and no more: a sidebar
        dragged wider than SIDEBAR_PANE_WIDTH is a listing the user has chosen to
        shrink, and re-widening the dialog would be undoing that.
        """
        sidebar = dialog.findChild(QListView, "sidebar")
        if sidebar is None:
            return None
        stored = dialog_settings().value(SETTING_DIALOG_SIDEBAR_WIDTH)
        try:
            width = int(stored)
        except (TypeError, ValueError):
            width = SIDEBAR_PANE_WIDTH
        natural = sidebar.sizeHint().width()
        return width, max(0, min(width, SIDEBAR_PANE_WIDTH) - natural)

    def _browse_with_preview(self, caption: str, directory: str) -> str | None:
        """
        Browse 'directory' and return the file the user opened, or None if the
        dialog was dismissed.
        """
        return self._run_file_dialog(self._build_browse_dialog(caption, directory))

    @staticmethod
    def _run_file_dialog(dialog: QFileDialog) -> str | None:
        """
        Run a file dialog and return the single path chosen, or None if it was
        dismissed. Shared by browsing, selecting and saving, which differ in how
        the dialog is set up and not at all in how it is run.
        """
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted.value:
                return None
            selected = dialog.selectedFiles()
            return selected[0] if selected else None
        finally:
            # Parented to the main window, so without this every dialog — and
            # the file-system model behind it — would live for the session.
            dialog.deleteLater()

    @staticmethod
    def _open_with_default_application(path: str):
        if MACOS:
            os_system(f"open {quote(path)}")
        elif LINUX:
            os_system(f"xdg-open {quote(path)} &")
        elif WINDOWS:
            os_startfile(path)

    def _show_config_action(self):
        if not self._check_config_file():
            return
        self._log(f"Displaying contents of '{self._config_file}':\n")
        with open(cast(str, self._config_file)) as f:
            self._log(f.read(), prefix=False)

    def _get_config_data_file(self, key: str) -> str | None:
        """
        Extract the value of workRequirementData or workerPoolData directly
        from the config TOML text, resolving template variable defaults and
        checking user_variables overrides.
        """
        if self._config_file is None or not exists(self._config_file):
            return None
        try:
            with open(self._config_file) as f:
                content = f.read()
        except OSError:
            return None

        m = re.search(rf"\b{key}\s*=\s*\"([^\"]*)\"", content)
        if not m:
            return None

        value = m.group(1)

        # Resolve template variables iteratively, innermost first, to support up
        # to three levels of nesting (e.g. {{file_{{xxx}}:={{def_file}}}}).
        # Each pass finds the deepest {{...}} with no further {{ inside it,
        # resolves that single variable via yd-show, and substitutes the result.
        for _ in range(3):
            if "{{" not in value:
                break
            inner = re.search(r"\{\{([^{}]+)}}", value)
            if not inner:
                break
            fragment = inner.group(1)
            var_name, default = (
                fragment.split(":=", 1) if ":=" in fragment else (fragment, "")
            )
            try:
                result = subprocess.run(
                    [
                        "yd-show",
                        "-c",
                        self._config_basename(),
                        "-q",
                        "-r",
                        var_name,
                    ]
                    + self._namespace_tag_and_user_vars(),
                    capture_output=True,
                    text=True,
                    check=True,
                    cwd=self._config_dir(),
                )
                resolved = loads(result.stdout.strip()).get(var_name)
                substitution = resolved if resolved is not None else default
            except Exception:
                substitution = default
            value = value[: inner.start()] + substitution + value[inner.end() :]

        if not value:
            return None

        return str(join(self._config_dir(), value))

    def _show_wr_action(self):
        path = self._wr_file or self._get_config_data_file(WR_DATA)
        if path is None:
            self._log("No Work Requirement definition file selected")
            return
        try:
            with open(path) as f:
                self._log(f"Displaying contents of '{path}':\n")
                self._log(f.read(), prefix=False)
        except OSError as e:
            self._log(f"Cannot open Work Requirement file '{path}': {e}")

    def _show_wp_action(self):
        path = self._wp_file or self._get_config_data_file(WP_DATA)
        if path is None:
            self._log("No Worker Pool definition file selected")
            return
        try:
            with open(path) as f:
                self._log(f"Displaying contents of '{path}':\n")
                self._log(f.read(), prefix=False)
        except OSError as e:
            self._log(f"Cannot open Worker Pool file '{path}': {e}")

    def _deselect_files_action(self):
        """
        Deselect the configuration file and/or the Work Requirement and Worker
        Pool definition files. Which of the currently-selected files to
        deselect is chosen in a dialog; all of them start selected, so
        accepting it unchanged deselects everything. The dialog is shown
        regardless of '--yes' (see _choose_files_to_deselect).
        """
        entries: list[tuple[str, str, Callable[[], None]]] = []
        if self._config_file is not None:
            entries.append(
                ("Configuration", self._config_file, self._deselect_config_file)
            )
        if self._wr_file is not None:
            entries.append(("Work Requirement", self._wr_file, self._deselect_wr_file))
        if self._wp_file is not None:
            entries.append(("Worker Pool", self._wp_file, self._deselect_wp_file))

        if not entries:
            self._log("No configuration or definition files to deselect")
            return

        # Always ask, even with '--yes': this dialog chooses what to act on
        # rather than confirming a destructive action, so suppressing it would
        # remove the only way to deselect one file and not the others.
        chosen = self._choose_files_to_deselect(
            [(label, path) for label, path, _ in entries]
        )
        if chosen is None:
            self._log("Cancelled: no files deselected")
            return
        if not chosen:
            self._log("No files chosen: nothing deselected")
            return

        for index in chosen:
            entries[index][2]()

    def _deselect_config_file(self):
        self._set_config_file(None)
        self._log("Deselected configuration file")

    def _deselect_wr_file(self):
        self._wr_file = None
        self._show_wr_selection()
        self._log("Deselected Work Requirement definition file")

    def _deselect_wp_file(self):
        self._wp_file = None
        self._show_wp_selection()
        self._log("Deselected Worker Pool definition file")

    def _choose_files_to_deselect(
        self, entries: list[tuple[str, str]]
    ) -> list[int] | None:
        """
        Ask which of the currently-selected files to deselect, given a list of
        (label, path) entries. Returns the indices of the files chosen, which
        may be empty, or None if the dialog was cancelled.
        """
        dialog, checkboxes = self._build_deselect_dialog(entries)
        if dialog.exec() != QDialog.DialogCode.Accepted.value:
            return None
        return [
            index for index, checkbox in enumerate(checkboxes) if checkbox.isChecked()
        ]

    def _build_deselect_dialog(
        self, entries: list[tuple[str, str]]
    ) -> tuple[QDialog, list[QCheckBox]]:
        """
        Build (but do not show) the deselection dialog: a checkbox per
        currently-selected file, labelled with its type and path and carrying
        the full path as a tooltip, plus Cancel / Deselect buttons (default
        Deselect). Every file starts checked, so accepting the dialog unchanged
        deselects all of them, as the button did before it asked.

        Each row is phrased as an action ('Deselect Worker Pool: ...') rather
        than as state ('Worker Pool: ...'), because a checked row stating only
        the file invites the opposite reading — that the box represents the
        file being selected, and that unchecking it is what deselects it.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Deselect Files")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Check the files to deselect:"))

        checkboxes: list[QCheckBox] = []
        for label, path in entries:
            checkbox = QCheckBox(
                f"{DESELECT_ROW_PREFIX}{label}: "
                f"{elide_path(path, MAX_DIALOG_PATH_LENGTH)}",
                dialog,
            )
            checkbox.setChecked(True)
            checkbox.setToolTip(abspath(path))
            layout.addWidget(checkbox)
            checkboxes.append(checkbox)

        button_box = QDialogButtonBox(dialog)
        button_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        deselect_btn = cast(
            QPushButton,
            button_box.addButton("Deselect", QDialogButtonBox.ButtonRole.AcceptRole),
        )
        deselect_btn.setDefault(True)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        return dialog, checkboxes

    def _on_stdout(self, process: QProcess, line_buffer: LineBuffer):
        self._log_lines(line_buffer.feed(process.readAllStandardOutput().data()))

    def _on_stderr(self, process: QProcess, line_buffer: LineBuffer):
        self._log_lines(line_buffer.feed(process.readAllStandardError().data()))

    def _on_process_output_finished(
        self,
        process: QProcess,
        stdout_buffer: LineBuffer,
        stderr_buffer: LineBuffer,
        *_signal_args,
    ):
        """
        Drain both output channels when the process exits, and display any
        final line that wasn't terminated by a newline.
        """
        self._log_lines(
            stdout_buffer.feed(process.readAllStandardOutput().data())
            + stdout_buffer.flush()
        )
        self._log_lines(
            stderr_buffer.feed(process.readAllStandardError().data())
            + stderr_buffer.flush()
        )

    def _log_lines(self, lines: list[str]):
        if lines:
            self._log("\n".join(lines), prefix=False)

    def _log(self, output: str, prefix: bool = True):
        self.log_output.appendPlainText(f"{self._prefix() if prefix else ''}{output}")

    def _follow_progress_set(self, checked_state: Qt.CheckState):
        if self.dry_run.isChecked() and checked_state == Qt.CheckState.Checked:
            # Uncheck the dry run flag and ensure the follow flag is checked
            self.dry_run.setChecked(False)
            self.follow_progress.setChecked(True)

    def _dry_run_set(self, _checked_state: Qt.CheckState):
        if self.follow_progress.isChecked():
            self.follow_progress.setChecked(False)

    def _follow_worker_pool_set(self, checked_state: Qt.CheckState):
        if (
            self.dry_run_worker_pool.isChecked()
            and checked_state == Qt.CheckState.Checked
        ):
            # Uncheck the dry run flag and ensure the follow flag is checked
            self.dry_run_worker_pool.setChecked(False)
            self.follow_worker_pool.setChecked(True)

    def _dry_run_worker_pool_set(self, _checked_state: Qt.CheckState):
        if self.follow_worker_pool.isChecked():
            self.follow_worker_pool.setChecked(False)

    def _dark_mode_action(self, checked_state: Qt.CheckState):
        is_dark = checked_state == Qt.CheckState.Checked
        application = cast(QApplication, QApplication.instance())
        if LINUX:
            if is_dark:
                application.setStyle("Fusion")
                dark = QPalette()
                dark.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
                dark.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
                dark.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
                dark.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
                dark.setColor(QPalette.ColorRole.ToolTipBase, QColor(25, 25, 25))
                dark.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
                dark.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
                dark.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
                dark.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
                dark.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
                dark.setColor(QPalette.ColorRole.Light, QColor(80, 80, 80))
                dark.setColor(QPalette.ColorRole.Midlight, QColor(65, 65, 65))
                dark.setColor(QPalette.ColorRole.Mid, QColor(45, 45, 45))
                dark.setColor(QPalette.ColorRole.Dark, QColor(35, 35, 35))
                dark.setColor(QPalette.ColorRole.Shadow, QColor(20, 20, 20))
                dark.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
                dark.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
                dark.setColor(QPalette.ColorRole.HighlightedText, QColor(35, 35, 35))
                dark.setColor(QPalette.ColorRole.PlaceholderText, QColor(160, 160, 160))
                application.setPalette(dark)
            else:
                application.setStyle("")
                application.setPalette(QPalette())
        else:
            cast(QStyleHints, application.styleHints()).setColorScheme(
                Qt.ColorScheme.Dark if is_dark else Qt.ColorScheme.Light
            )
        if is_dark:
            self.setStyleSheet(
                "#line_3, #line_4, #line_6 {"
                " background-color: #555555; border: none; max-height: 2px; }"
                " #line_5 { background-color: #555555; border: none; max-width: 2px; }"
            )
        else:
            self.setStyleSheet("")
        self._update_branding_icon(is_dark)

    def _run_any_command_action(self):
        self._run_any_command_core(self.any_command.toPlainText())

    def _run_any_command_core(self, command_text: str):
        command_and_args = command_text.split()
        if len(command_and_args) == 0:
            self._log("No command to run")
            return
        self._any_command_history.save_command(command_text)
        if (
            command_and_args[0].startswith("yd-")
            and command_and_args[0] != "yd-version"
        ):
            # yd- commands: inject UI namespace/tag/user vars as normal
            self._run_command_in_subprocess(
                command=command_and_args[0],
                args=command_and_args[1:],
                yd_command=False,
                accept_stdin=True,
            )
        else:
            # Non-yd commands: run via shell to support wildcard expansion,
            # pipes, and other shell features
            shell, flag = ("cmd", "/c") if WINDOWS else ("sh", "-c")
            self._run_command_in_subprocess(
                command=shell,
                args=[flag, command_text],
                yd_command=False,
                accept_stdin=True,
            )

    @staticmethod
    def _set_cursor_to_end(edit_box):
        cursor = edit_box.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        edit_box.setTextCursor(cursor)

    def _edit_box_keypress_handler(self, edit_box):
        """
        Suppress the use of the tab and return keys in text edits.
        Issue the command if enter is pressed in the command box.
        """
        edit_box_contents = edit_box.toPlainText()

        if "\t" in edit_box_contents:
            edit_box_contents = edit_box_contents.replace("\t", "")
            edit_box.setPlainText(edit_box_contents)
            self._set_cursor_to_end(edit_box)

        if "\n" in edit_box_contents:
            edit_box_contents = edit_box_contents.replace("\n", "")
            edit_box.setPlainText(edit_box_contents)
            self._set_cursor_to_end(edit_box)

            # Special processing for the command window and stdin input
            if edit_box == self.any_command:
                self._run_any_command_core(edit_box_contents)
            elif edit_box == self.stdin_input:
                self._send_stdin_action(edit_box_contents)

    def _next_command_action(self):
        cmd = self._any_command_history.step_forward()
        if cmd is not None:
            self.any_command.setPlainText(cmd)
            self._set_cursor_to_end(self.any_command)

    def _prev_command_action(self):
        cmd = self._any_command_history.step_back()
        if cmd is not None:
            self.any_command.setPlainText(cmd)
            self._set_cursor_to_end(self.any_command)

    def _select_file(
        self,
        caption: str = "",
        directory: str = ".",
        file_pattern: str = "*",
    ) -> str | None:
        """
        Ask for an existing file to read, returning None if the dialog was
        dismissed. Carries the same preview pane as the browse dialog: picking
        the right configuration or definition file out of several similarly
        named ones is exactly the case a preview answers.
        """
        dialog = QFileDialog(self, caption, directory, file_pattern)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.Option.ReadOnly, True)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        # 'Select', not Qt's 'Open': these dialogs nominate a file for a later
        # command to read, and nothing is opened by pressing the button.
        dialog.setLabelText(QFileDialog.DialogLabel.Accept, "Select")
        self._add_preview_pane(dialog)
        self._apply_dialog_preferences(dialog)
        return self._run_file_dialog(dialog)

    def _save_file(
        self,
        caption: str = "",
        directory: str = ".",
        file_pattern: str = "*",
    ) -> str | None:
        """
        Ask for a file to write to, returning None if the dialog was dismissed.
        'directory' may name a file rather than a directory, which the dialog
        pre-fills as the suggested target.

        Mirrors _select_file, including DontUseNativeDialog, so the two dialogs
        look and behave alike; Qt's own dialog also prompts before overwriting an
        existing file, which is why no separate overwrite check is needed here.
        ReadOnly is deliberately absent — unlike _select_file, this one writes.

        No preview pane, unlike every other file dialog here: this one names a
        file that does not exist yet, so all a preview could show is a file the
        user is not saving to, at the cost of the width the pane takes up.
        """
        dialog = QFileDialog(self, caption, directory, file_pattern)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        self._apply_dialog_preferences(dialog)
        return self._run_file_dialog(dialog)


def run_app(config_file: str | None = None, disable_confirmations: bool = False):
    try:
        if WINDOWS:
            # noinspection PyUnresolvedReferences
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
                "yellowdog.commander"
            )
        if MACOS:
            # Silence macOS / Qt platform plugin system warnings
            os.environ["QT_LOGGING_RULES"] = "qt.qpa.*=false"
        app = QApplication(sys.argv)
        icon = QIcon(ICON_IMAGE)
        app.setWindowIcon(icon)
        win = YellowDogApp(config_file, disable_confirmations)
        win.setWindowIcon(icon)
        # Covers quits that don't close the window first (macOS Cmd-Q, the Dock)
        app.aboutToQuit.connect(win.shutdown)

        cast(QLayout, win.layout()).activate()
        win.setMinimumHeight(win.minimumSizeHint().height())
        win.setMinimumWidth(win.minimumSizeHint().width())
        win.resize(win.minimumWidth(), win.minimumHeight())

        win.show()
        sys.exit(app.exec())

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run_app()
