"""
Commander's file dialogs (FileDialogs), and the parts they are built from: the
preview pane, the proxy that keeps every level of the listing in order, and the
store the dialogs' preferences are kept in.
"""

import re
from codecs import getincrementaldecoder
from os.path import basename, exists, getsize, isdir
from shlex import quote
from typing import cast

from PyQt6.QtCore import (
    QCollator,
    QModelIndex,
    QObject,
    QSettings,
    QSize,
    QSortFilterProxyModel,
    Qt,
)
from PyQt6.QtGui import QFont, QImage, QImageReader, QPixmap
from PyQt6.QtWidgets import (
    QBoxLayout,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QLabel,
    QListView,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from yellowdog_cli.commander.host import LINUX, MACOS, WINDOWS

if MACOS or LINUX:
    from os import system as os_system
elif WINDOWS:
    from os import (
        startfile as os_startfile,  # pyright: ignore[reportAttributeAccessIssue]
    )

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
# How the file dialogs' listing is ordered, at every level; see
# NaturalOrderProxy. The name column, ascending, which is the order Qt's own file
# model gives the one level it sorts — and with the header hidden there is no way
# for a user to ask for another, so this is the only order the listing is ever in.
LISTING_SORT_COLUMN = 0
LISTING_SORT_ORDER = Qt.SortOrder.AscendingOrder
# Where Commander keeps the file-dialog choices that outlive a dialog; see
# dialog_settings().
COMMANDER_SETTINGS_ORGANISATION = "YellowDog"
COMMANDER_SETTINGS_APPLICATION = "Commander"
SETTING_DIALOG_SIDEBAR_WIDTH = "fileDialog/sidebarWidth"
SETTING_DIALOG_VIEW_MODE = "fileDialog/viewMode"


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


class NaturalOrderProxy(QSortFilterProxyModel):
    """
    Keeps a file dialog's listing in order at every level, not just the one it
    opens at.

    QFileSystemModel sorts the level it is rooted at and nothing beneath it. A
    directory expanded in place therefore arrives in filesystem order — a hash
    order on APFS and on ext4, so 'task_005, task_002, task_003' — and stays in
    it: verified that neither sort() on the model nor the header's own sort
    indicator reorders such a level, and that it is still unsorted twelve seconds
    later, so it is not a race that settles. Commander turned expansion on, which
    is what made those levels reachable and the ordering visible; the behaviour
    beneath is Qt's, and the same in a stock dialog.

    Interposing a proxy is Qt's own answer to it (QFileDialog.setProxyModel), and
    a dynamically sorted one orders each level as its rows arrive, which is what
    an expanded level needs. It costs a Python comparison per pair: ~130ms of the
    ~0.5s a 5,000-entry directory takes to list, paid once as the level opens.

    The comparison is a QCollator in numeric mode, not the default string
    compare, because that is what QFileSystemModel itself does for the level it
    sorts: 'task_1, task_2, task_10', never 'task_1, task_10, task_2'. A plain
    sort would put every expanded level in a different order from the directory
    above it — worse than the bug — and would disagree with the platform's file
    viewer, which the browse dialog hands over to.

    Except where the collator will not order numerically, which is under the C
    locale — what a Linux session with LANG unset runs in, a headless test node
    included. There Qt ignores numeric mode and compares plain strings, so the
    proxy asks the collator once whether '2' comes before '10' and, if not,
    orders by natural_sort_key() instead. Measured rather than keyed off the
    locale's name, since whether a locale collates numerically is Qt's backend's
    business (ICU, macOS, Windows, POSIX), not something the name says. Qt's
    own sort of the level it opens at is subject to the same limitation, but
    the proxy orders that level too, so every level agrees either way.
    """

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._collator = QCollator()
        self._collator.setNumericMode(True)
        self._collator.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._collator_is_numeric = self._collator.compare("2", "10") < 0
        # Ordered as rows arrive, rather than once when the level is opened: a
        # level is delivered in batches, and only the first batch would be sorted.
        self.setDynamicSortFilter(True)
        self.sort(LISTING_SORT_COLUMN, LISTING_SORT_ORDER)

    def lessThan(self, source_left: QModelIndex, source_right: QModelIndex) -> bool:
        if source_left.column() != LISTING_SORT_COLUMN:
            return super().lessThan(source_left, source_right)
        left, right = str(source_left.data()), str(source_right.data())
        if self._collator_is_numeric:
            return self._collator.compare(left, right) < 0
        return natural_sort_key(left) < natural_sort_key(right)


_DIGIT_RUNS = re.compile(r"(\d+)")


def natural_sort_key(name: str) -> list[str | int]:
    """
    A key ordering names as a numeric-mode, case-insensitive collator does:
    'task_2' before 'task_10'. The split always yields text at even indices and
    numbers at odd ones, so two keys never compare a str against an int.
    """
    return [
        int(part) if index % 2 else part
        for index, part in enumerate(_DIGIT_RUNS.split(name.casefold()))
    ]


SIDEBAR_PANE_WIDTH = 180  # px: the width a file dialog's places sidebar opens at


# The tree, because that is the view a hierarchy can be shown in — Qt's other one
# is a QListView, which has no disclosure. Its size/kind/date columns are hidden
# and its header with them; see _make_listing_a_names_only_tree().
DIALOG_VIEW_MODE = QFileDialog.ViewMode.Detail


# What the browse dialog's button for handing over to the platform's own file
# viewer says. Qt's dialog is read-only, so this is the route to deleting or
# renaming anything in the directory being browsed.
NATIVE_VIEWER_BUTTON_TEXT = (
    "Use Finder" if MACOS else "Use Explorer" if WINDOWS else "Use File Manager"
)


class FileDialogs:
    """
    Commander's file dialogs: Qt's own, non-native, each with the names-only
    listing and the preferences the user last left one with, and — for the ones
    that read an existing file — a preview pane. The window asks for a file to
    select, a file to save to, or a directory to browse, and is handed back a
    path or None.

    Owns the one dialog preference that is kept for the session only, the
    preview pane's width; the others are in dialog_settings(), which is called
    through this module's own global so that a test's patch of it is the one
    every dialog reads.
    """

    def __init__(self, parent: QWidget, font: QFont):
        self._parent = parent  # every dialog's parent; see _run_file_dialog
        self._font = font  # the preview's text, in the output window's font
        # The width of the preview pane, for the session: set it once by
        # dragging, and every later dialog opens at that width.
        self._preview_width = PREVIEW_PANE_WIDTH

    def select_file(
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
        dialog = QFileDialog(self._parent, caption, directory, file_pattern)
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

    def save_file(
        self,
        caption: str = "",
        directory: str = ".",
        file_pattern: str = "*",
    ) -> str | None:
        """
        Ask for a file to write to, returning None if the dialog was dismissed.
        'directory' may name a file rather than a directory, which the dialog
        pre-fills as the suggested target.

        Mirrors select_file, including DontUseNativeDialog, so the two dialogs
        look and behave alike; Qt's own dialog also prompts before overwriting an
        existing file, which is why no separate overwrite check is needed here.
        ReadOnly is deliberately absent — unlike select_file, this one writes.

        No preview pane, unlike every other file dialog here: this one names a
        file that does not exist yet, so all a preview could show is a file the
        user is not saving to, at the cost of the width the pane takes up.
        """
        dialog = QFileDialog(self._parent, caption, directory, file_pattern)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        self._apply_dialog_preferences(dialog)
        return self._run_file_dialog(dialog)

    def browse(self, caption: str, directory: str) -> str | None:
        """
        Browse 'directory' and return the file the user opened, or None if the
        dialog was dismissed.
        """
        return self._run_file_dialog(self.build_browse_dialog(caption, directory))

    def build_browse_dialog(self, caption: str, directory: str) -> QFileDialog:
        """
        Build (but do not show) the read-only browse dialog: Qt's own file
        dialog rooted at 'directory', previewing whatever is highlighted.

        Read-only because this is a viewer, not a file manager: Qt's dialog
        otherwise offers renaming, deleting and creating folders inside the
        results directory, none of which is what the button promises.
        """
        dialog = QFileDialog(self._parent, caption, directory)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.Option.ReadOnly, True)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        dialog.setLabelText(QFileDialog.DialogLabel.Accept, "Open")
        self._add_preview_pane(dialog)
        self._apply_dialog_preferences(dialog)
        self._add_platform_viewer_button(dialog)
        return dialog

    @staticmethod
    def open_with_default_application(path: str):
        if MACOS:
            os_system(f"open {quote(path)}")
        elif LINUX:
            os_system(f"xdg-open {quote(path)} &")
        elif WINDOWS:
            os_startfile(path)

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

        The sorting proxy goes in before the listing is set up, not after: it
        replaces the views' model, and the hidden columns and the stretched name
        are properties of the view against that model.
        """
        dialog.setProxyModel(NaturalOrderProxy())
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
        self.open_with_default_application(dialog.directory().absolutePath())
        dialog.reject()
