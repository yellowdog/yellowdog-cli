"""
The parts of Commander's file dialogs that stand on their own: the preview
pane, the proxy that keeps every level of the listing in order, and the
store the dialogs' preferences are kept in. The window assembles the
dialogs from them.
"""

from codecs import getincrementaldecoder
from os.path import basename, exists, getsize, isdir

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
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
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
    """

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._collator = QCollator()
        self._collator.setNumericMode(True)
        self._collator.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        # Ordered as rows arrive, rather than once when the level is opened: a
        # level is delivered in batches, and only the first batch would be sorted.
        self.setDynamicSortFilter(True)
        self.sort(LISTING_SORT_COLUMN, LISTING_SORT_ORDER)

    def lessThan(self, source_left: QModelIndex, source_right: QModelIndex) -> bool:
        if source_left.column() != LISTING_SORT_COLUMN:
            return super().lessThan(source_left, source_right)
        return (
            self._collator.compare(str(source_left.data()), str(source_right.data()))
            < 0
        )
