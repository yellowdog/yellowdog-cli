"""
Tests for the preview column in Commander's directory-browsing dialog, and for
what the dialog does with the file the user picks.

The preview replaces what the platform's own file viewer used to provide (on
macOS, Finder and Quick Look), so the cases that matter are the ones a viewer
handles without being asked: an image, a log file, a binary, a directory, and a
file that has gone away. Each has its own branch here, because each of them
reaching the wrong branch shows the user either nothing or gibberish.

The dialog cases run the real exec() with the real Qt file dialog, and drive it
by highlighting a row in its actual listing rather than by emitting its
currentChanged signal — the signal connection is the thing most likely to be
wrong, so a test that emits it by hand proves nothing.
"""

import pytest
import qt_guard

qt_guard.require_qt()

from time import monotonic

import gui_harness
from PyQt6.QtCore import QEventLoop, QPoint, QRect
from PyQt6.QtGui import QColor, QFont, QImage
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QLineEdit,
    QPushButton,
    QSplitter,
    QWidget,
)

from yellowdog_cli.commander.commander import (
    PREVIEW_MAX_LINES,
    PREVIEW_MIN_WIDTH,
    PREVIEW_NO_SELECTION,
    PREVIEW_PANE_WIDTH,
    PREVIEW_READ_BYTES,
    FilePreview,
    YellowDogApp,
    format_file_size,
)

# QFileSystemModel populates on its own thread, so a freshly opened dialog does
# not have the directory's rows yet. Generous for a slow CI node; a real failure
# to list the file still fails the test rather than hanging the suite.
LISTING_TIMEOUT_S = 5.0


@pytest.fixture
def window(qapp):
    return YellowDogApp()


@pytest.fixture
def preview(qapp):
    # Shown offscreen, so that isVisible() reports what the pane is actually
    # displaying: on a widget whose parent was never shown it is always False,
    # which would make every 'this body is hidden' assertion pass for free.
    pane = FilePreview(QFont())
    gui_harness.shown(pane)
    return pane


def write_image(path, width: int, height: int) -> str:
    """Write a real PNG of the given size and return its path as a string."""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("yellow"))
    assert image.save(str(path), "PNG"), f"could not write {path}"
    return str(path)


def listing_view(dialog) -> QAbstractItemView:
    """
    Whichever of the file dialog's two views is on show. It opens in Detail
    mode, so the list view is the hidden page — driving that one would not be
    the path a user takes, however well it happens to work.
    """
    for name in ("treeView", "listView"):
        view = dialog.findChild(QAbstractItemView, name)
        if view is not None and view.isVisible():
            return view
    raise AssertionError("neither of the file dialog's views is visible")


def _row_index(view: QAbstractItemView, name: str):
    """The model index of the named row in a file dialog's listing, or None."""
    model = view.model()
    assert model is not None, "the file dialog's listing has no model"
    root = view.rootIndex()
    for row in range(model.rowCount(root)):
        index = model.index(row, 0, root)
        if model.data(index) == name:
            return index
    return None


def highlight(dialog, name: str) -> None:
    """
    Highlight a row in the dialog's own listing, the way an arrow key does,
    waiting for the asynchronous listing to include it first.
    """
    view = listing_view(dialog)
    deadline = monotonic() + LISTING_TIMEOUT_S
    index = _row_index(view, name)
    while index is None and monotonic() < deadline:
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        index = _row_index(view, name)
    assert index is not None, f"{name!r} never appeared in the listing"
    view.setCurrentIndex(index)
    QApplication.processEvents()


def rect_in(widget: QWidget, ancestor: QWidget) -> QRect:
    """
    A widget's rectangle in an ancestor's coordinates. geometry() is relative to
    the immediate parent, and the file dialog's listing is nested inside a frame
    of its own, so two raw geometries cannot be compared with each other.
    """
    return QRect(widget.mapTo(ancestor, QPoint(0, 0)), widget.size())


def dialog_preview(dialog) -> FilePreview:
    """The dialog's preview pane; fails loudly when there is none."""
    found = dialog.findChild(FilePreview, "file_preview")
    assert found is not None, "the browse dialog has no preview pane"
    return found


def press(dialog, label: str) -> None:
    """
    Click a file dialog's button by its label, ignoring the mnemonic Qt puts
    there — its accept button reads '&Open' or '&Save', which gui_harness's
    exact-label lookup would not match.
    """
    for button in dialog.findChildren(QPushButton):
        if button.text().replace("&", "") == label:
            button.click()
            return
    labels = sorted(b.text() for b in dialog.findChildren(QPushButton))
    raise AssertionError(f"no button labelled {label!r}; found {labels}")


def pane_splitter(dialog) -> tuple[QSplitter, int]:
    """The splitter holding the preview pane, and the pane's index in it."""
    splitter = dialog.findChild(QSplitter, "splitter")
    assert splitter is not None, "the file dialog has no splitter"
    index = splitter.indexOf(dialog_preview(dialog))
    assert index >= 0, "the preview pane is not in the splitter"
    return splitter, index


def drive_file_dialog(window, monkeypatch, interact) -> dict:
    """
    Arm whichever file dialog the next _select_file / _save_file / browse call
    builds, so 'interact' runs inside that dialog's real exec(). Returns a dict
    that the dialog is recorded in, for assertions after it has closed.
    """
    captured: dict = {}
    real_run = window._run_file_dialog

    def run(dialog):
        captured["dialog"] = dialog
        gui_harness.arm_modal(dialog, interact)
        return real_run(dialog)

    monkeypatch.setattr(window, "_run_file_dialog", run)
    return captured


@pytest.mark.parametrize(
    "size, expected",
    [
        (0, "0 bytes"),
        (1, "1 byte"),
        (999, "999 bytes"),
        (1000, "1.0 kB"),
        (4200, "4.2 kB"),
        (999_949, "999.9 kB"),
        (1_500_000, "1.5 MB"),
        (2_500_000_000, "2.5 GB"),
        (3_500_000_000_000, "3.5 TB"),
        (9_000_000_000_000_000, "9,000.0 TB"),
    ],
)
def test_file_sizes_are_reported_in_the_units_a_file_viewer_uses(size, expected):
    assert format_file_size(size) == expected


def test_nothing_highlighted_shows_the_placeholder_and_no_body(preview):
    assert preview.name_label.text() == PREVIEW_NO_SELECTION
    assert not preview.text_view.isVisible()
    assert not preview.image_view.isVisible()


def test_a_text_file_is_previewed_as_its_first_lines(preview, tmp_path):
    target = tmp_path / "task_1.log"
    target.write_text("Task started\nFetching input\nDone in 4.1s\n")

    preview.show_path(str(target))

    assert preview.name_label.text() == "task_1.log"
    assert "text" in preview.meta_label.text()
    assert format_file_size(target.stat().st_size) in preview.meta_label.text()
    assert preview.text_view.toPlainText() == (
        "Task started\nFetching input\nDone in 4.1s"
    )
    assert preview.image_view.pixmap().isNull()


def test_a_file_with_no_extension_is_still_previewed_as_text(preview, tmp_path):
    # Task output arrives named whatever the task named it, so the decision
    # cannot be taken from the extension.
    target = tmp_path / "stdout"
    target.write_text("worker: done\n")

    preview.show_path(str(target))

    assert preview.text_view.toPlainText() == "worker: done"


def test_a_long_text_file_is_elided_rather_than_read_whole(preview, tmp_path):
    target = tmp_path / "big.log"
    target.write_text("".join(f"line {n}\n" for n in range(PREVIEW_MAX_LINES + 20)))

    preview.show_path(str(target))

    body = preview.text_view.toPlainText().splitlines()
    assert body[0] == "line 0"
    assert body[PREVIEW_MAX_LINES - 1] == f"line {PREVIEW_MAX_LINES - 1}"
    assert body[-1] == "…", "an elided preview must say so"
    assert len(body) == PREVIEW_MAX_LINES + 1


def test_a_multibyte_character_across_the_read_cap_is_not_taken_for_binary(
    preview, tmp_path
):
    # The cap is a byte count, so it can fall inside a UTF-8 sequence. Decoding
    # that strictly in one go raises, which would report a text file as binary.
    target = tmp_path / "unicode.log"
    filler = "a" * (PREVIEW_READ_BYTES - 1)
    target.write_text(f"{filler}—more text", encoding="utf-8")

    preview.show_path(str(target))

    assert "text" in preview.meta_label.text()
    assert preview.text_view.toPlainText().startswith("aaa")
    assert preview.text_view.toPlainText().endswith("…")


def test_a_binary_file_is_not_previewed_as_text(preview, tmp_path):
    target = tmp_path / "core.bin"
    target.write_bytes(bytes(range(256)) * 8)

    preview.show_path(str(target))

    assert preview.name_label.text() == "core.bin"
    assert "no preview available" in preview.meta_label.text()
    assert format_file_size(target.stat().st_size) in preview.meta_label.text()
    assert not preview.text_view.isVisible()
    assert not preview.image_view.isVisible()


def test_a_utf16_file_is_not_previewed_as_text(preview, tmp_path):
    # UTF-16 ASCII decodes as UTF-8 without raising, so only the NUL check keeps
    # it out of the text branch — where it would show as interleaved NULs.
    target = tmp_path / "utf16.txt"
    target.write_text("Task started\nDone\n", encoding="utf-16")

    preview.show_path(str(target))

    assert "no preview available" in preview.meta_label.text()


def test_an_image_is_previewed_as_a_thumbnail_with_its_dimensions(preview, tmp_path):
    path = write_image(tmp_path / "plot.png", 40, 30)

    preview.show_path(path)

    assert preview.name_label.text() == "plot.png"
    assert "PNG image" in preview.meta_label.text()
    assert "40 x 30" in preview.meta_label.text()
    assert preview.image_view.isVisible()
    assert not preview.image_view.pixmap().isNull()
    assert not preview.text_view.isVisible()


def test_a_large_image_is_scaled_down_to_fit_the_pane(preview, tmp_path):
    path = write_image(tmp_path / "wide.png", 4000, 1000)

    preview.show_path(path)

    pixmap = preview.image_view.pixmap()
    # Bounded by the space the pane actually gives it, not by a pixel count:
    # the pane's width is the user's to set, so there is no fixed answer.
    assert pixmap.width() <= preview.image_view.width()
    assert pixmap.height() <= preview.image_view.height()
    # Scaled, not squashed: 4:1 in, 4:1 out, to within rounding.
    assert abs(pixmap.width() / pixmap.height() - 4.0) < 0.1


def test_widening_the_pane_rescales_the_thumbnail_from_the_original(preview, tmp_path):
    # Rescaling the thumbnail instead would magnify an already-shrunken image,
    # so a pane dragged wider would show a blurrier picture, not a bigger one.
    path = write_image(tmp_path / "wide.png", 4000, 1000)
    preview.resize(PREVIEW_MIN_WIDTH, preview.height())
    preview.show_path(path)
    narrow = preview.image_view.pixmap().width()

    preview.resize(PREVIEW_MIN_WIDTH * 3, preview.height())

    widened = preview.image_view.pixmap()
    assert widened.width() > narrow
    assert widened.width() <= preview.image_view.width()
    assert abs(widened.width() / widened.height() - 4.0) < 0.1


def test_narrowing_the_pane_rescales_the_thumbnail_back_down(preview, tmp_path):
    path = write_image(tmp_path / "wide.png", 4000, 1000)
    preview.resize(PREVIEW_MIN_WIDTH * 3, preview.height())
    preview.show_path(path)
    wide = preview.image_view.pixmap().width()

    preview.resize(PREVIEW_MIN_WIDTH, preview.height())

    assert preview.image_view.pixmap().width() < wide


def test_a_small_image_is_shown_at_its_own_size(preview, tmp_path):
    # Blowing a 16x16 icon up to the width of the pane makes it less
    # recognisable, not more.
    path = write_image(tmp_path / "icon.png", 16, 16)

    preview.show_path(path)

    pixmap = preview.image_view.pixmap()
    assert (pixmap.width(), pixmap.height()) == (16, 16)


def test_a_directory_is_named_as_one_with_no_body(preview, tmp_path):
    (tmp_path / "results").mkdir()

    preview.show_path(str(tmp_path / "results"))

    assert preview.name_label.text() == "results"
    assert preview.meta_label.text() == "Directory"
    assert not preview.text_view.isVisible()
    assert not preview.image_view.isVisible()


def test_a_path_that_has_gone_away_falls_back_to_the_placeholder(preview, tmp_path):
    preview.show_path(str(tmp_path / "deleted.log"))

    assert preview.name_label.text() == PREVIEW_NO_SELECTION
    assert not preview.text_view.isVisible()


def test_moving_between_kinds_leaves_no_trace_of_the_previous_one(preview, tmp_path):
    # Both bodies live in the pane at once, so a branch that reveals one without
    # hiding the other shows the last file's contents beside this file's name.
    image = write_image(tmp_path / "plot.png", 40, 30)
    text = tmp_path / "task_1.log"
    text.write_text("Task started\n")

    preview.show_path(image)
    preview.show_path(str(text))
    assert preview.text_view.isVisible()
    assert not preview.image_view.isVisible()
    assert preview.image_view.pixmap().isNull()

    preview.show_path(image)
    assert preview.image_view.isVisible()
    assert not preview.text_view.isVisible()
    assert preview.text_view.toPlainText() == ""


def test_highlighting_a_file_in_the_real_dialog_fills_the_preview(window, tmp_path):
    (tmp_path / "task_1.log").write_text("Task started\nDone in 4.1s\n")
    dialog = window._build_browse_dialog("Browse", str(tmp_path))
    seen = {}

    def interact(open_dialog):
        highlight(open_dialog, "task_1.log")
        pane = dialog_preview(open_dialog)
        seen["name"] = pane.name_label.text()
        seen["body"] = pane.text_view.toPlainText()
        seen["visible"] = pane.text_view.isVisible()
        gui_harness.button_labelled(open_dialog, "Cancel").click()

    gui_harness.run_modal(dialog, interact)

    assert seen["name"] == "task_1.log"
    assert seen["body"] == "Task started\nDone in 4.1s"
    assert seen["visible"], "the preview body was filled but never shown"


def test_the_preview_sits_beside_the_listing_rather_than_over_it(window, tmp_path):
    (tmp_path / "task_1.log").write_text("Task started\n")
    dialog = window._build_browse_dialog("Browse", str(tmp_path))
    geometry = {}

    def interact(open_dialog):
        view = listing_view(open_dialog)
        pane = dialog_preview(open_dialog)
        geometry["view"] = rect_in(view, open_dialog)
        geometry["pane"] = rect_in(pane, open_dialog)
        geometry["pane_visible"] = pane.isVisible()
        gui_harness.button_labelled(open_dialog, "Cancel").click()

    gui_harness.run_modal(dialog, interact)

    view, pane = geometry["view"], geometry["pane"]
    assert geometry["pane_visible"]
    assert pane.left() >= view.right(), "the preview overlaps the file listing"
    assert pane.width() >= PREVIEW_MIN_WIDTH
    # It shares the splitter with the listing, so the two are the same height —
    # a relationship rather than a pixel count, which travels across fonts.
    assert pane.height() >= view.height()


def test_the_file_the_user_opens_is_handed_to_the_default_application(
    window, tmp_path, monkeypatch
):
    (tmp_path / "task_1.log").write_text("Task started\n")
    (tmp_path / "task_2.log").write_text("Task started\n")
    opened: list[str] = []
    monkeypatch.setattr(window, "_open_with_default_application", opened.append)

    real_build = window._build_browse_dialog

    def build(caption, directory):
        dialog = real_build(caption, directory)

        def interact(open_dialog):
            highlight(open_dialog, "task_2.log")
            gui_harness.button_labelled(open_dialog, "Open").click()

        gui_harness.arm_modal(dialog, interact)
        return dialog

    monkeypatch.setattr(window, "_build_browse_dialog", build)

    window._open_file_viewer(str(tmp_path))

    assert opened == [str(tmp_path / "task_2.log")]


def test_dismissing_the_dialog_opens_nothing(window, tmp_path, monkeypatch):
    (tmp_path / "task_1.log").write_text("Task started\n")
    opened: list[str] = []
    monkeypatch.setattr(window, "_open_with_default_application", opened.append)

    real_build = window._build_browse_dialog

    def build(caption, directory):
        dialog = real_build(caption, directory)

        def interact(open_dialog):
            highlight(open_dialog, "task_1.log")
            gui_harness.button_labelled(open_dialog, "Cancel").click()

        gui_harness.arm_modal(dialog, interact)
        return dialog

    monkeypatch.setattr(window, "_build_browse_dialog", build)

    window._open_file_viewer(str(tmp_path))

    assert opened == []


def test_a_directory_that_does_not_exist_is_reported_and_no_dialog_opens(
    window, tmp_path, monkeypatch
):
    def refuse(*_args, **_kwargs):
        raise AssertionError("a dialog was opened for a non-existent directory")

    monkeypatch.setattr(window, "_build_browse_dialog", refuse)
    missing = tmp_path / "results"

    window._open_file_viewer(str(missing))

    assert (
        f"Directory '{missing}' does not (yet) exist" in window.log_output.toPlainText()
    )


def test_the_browse_dialog_is_read_only_and_opens_only_existing_files(window, tmp_path):
    dialog = window._build_browse_dialog("Browse", str(tmp_path))

    # Read-only because this is a viewer: Qt's dialog otherwise offers renaming,
    # deleting and creating folders inside the results directory.
    assert dialog.testOption(QFileDialog.Option.ReadOnly)
    assert dialog.testOption(QFileDialog.Option.DontUseNativeDialog)
    assert dialog.fileMode() == QFileDialog.FileMode.ExistingFile


def test_the_file_selector_previews_the_highlighted_file(window, tmp_path, monkeypatch):
    # The selector picks configuration and definition files, which is where a
    # preview does most work: several similarly named TOML files in one directory.
    (tmp_path / "config.toml").write_text('[common]\nnamespace = "pyex"\n')
    seen = {}

    def interact(dialog):
        highlight(dialog, "config.toml")
        pane = dialog_preview(dialog)
        seen["name"] = pane.name_label.text()
        seen["body"] = pane.text_view.toPlainText()
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, interact)

    assert (
        window._select_file(
            caption="Pick", directory=str(tmp_path), file_pattern="*.toml"
        )
        is None
    )
    assert seen["name"] == "config.toml"
    assert seen["body"] == '[common]\nnamespace = "pyex"'


def test_the_file_selector_returns_the_file_the_user_opened(
    window, tmp_path, monkeypatch
):
    (tmp_path / "wr.jsonnet").write_text("{ }\n")

    def interact(dialog):
        highlight(dialog, "wr.jsonnet")
        press(dialog, "Open")

    drive_file_dialog(window, monkeypatch, interact)

    chosen = window._select_file(caption="Pick", directory=str(tmp_path))

    assert chosen == str(tmp_path / "wr.jsonnet")


def test_the_save_dialog_has_no_preview_and_still_suggests_its_name(
    window, tmp_path, monkeypatch
):
    # The one dialog deliberately without a pane: it names a file that does not
    # exist yet, so a preview could only show one the user is not saving to. It
    # is built directly now rather than through getSaveFileName, though, and the
    # suggested timestamped filename is what that helper used to pre-fill.
    suggested = tmp_path / "commander-output-20260818-120000.txt"
    seen = {}

    def interact(dialog):
        edit = dialog.findChild(QLineEdit, "fileNameEdit")
        assert edit is not None, "the save dialog has no filename field"
        seen["prefilled"] = edit.text()
        seen["pane"] = dialog.findChild(FilePreview, "file_preview")
        press(dialog, "Save")

    drive_file_dialog(window, monkeypatch, interact)

    chosen = window._save_file(
        caption="Save Command Output",
        directory=str(suggested),
        file_pattern="Text files (*.txt);;All files (*)",
    )

    assert seen["pane"] is None, "the save dialog should carry no preview pane"
    assert seen["prefilled"] == suggested.name
    assert chosen == str(suggested)


def test_the_pane_opens_at_its_default_width_and_cannot_be_dragged_shut(
    window, tmp_path, monkeypatch
):
    measured = {}

    def interact(dialog):
        splitter, index = pane_splitter(dialog)
        measured["width"] = splitter.sizes()[index]
        measured["collapsible"] = splitter.isCollapsible(index)
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, interact)
    window._select_file(caption="Pick", directory=str(tmp_path))

    assert measured["width"] == PREVIEW_PANE_WIDTH
    assert not measured["collapsible"], "a pane dragged shut cannot be found again"


def test_the_preview_is_added_beside_the_listing_not_out_of_it(
    window, tmp_path, monkeypatch
):
    # The dialog widens to make room for the pane. Taking the pane's width out of
    # the splitter instead would shrink the listing — the part the user came for.
    listing_widths = {}

    def measure(key):
        def interact(dialog):
            splitter = dialog.findChild(QSplitter, "splitter")
            assert splitter is not None, "the file dialog has no splitter"
            listing_widths[key] = splitter.sizes()[1]
            listing_widths["handle"] = splitter.handleWidth()
            press(dialog, "Cancel")

        return interact

    with monkeypatch.context() as no_preview:
        no_preview.setattr(window, "_add_preview_pane", lambda dialog: None)
        drive_file_dialog(window, no_preview, measure("plain"))
        window._select_file(caption="Pick", directory=str(tmp_path))

    drive_file_dialog(window, monkeypatch, measure("with_preview"))
    window._select_file(caption="Pick", directory=str(tmp_path))

    # All the listing gives up is the new splitter handle itself, which has to
    # come from somewhere; the pane's own width comes from the wider dialog.
    lost = listing_widths["plain"] - listing_widths["with_preview"]
    assert 0 <= lost <= listing_widths["handle"]


def test_the_width_the_user_drags_the_pane_to_is_used_by_the_next_dialog(
    window, tmp_path, monkeypatch
):
    dragged_to = PREVIEW_PANE_WIDTH + 180
    reopened = {}

    def drag(dialog):
        splitter, index = pane_splitter(dialog)
        sizes = splitter.sizes()
        sizes[index] = dragged_to
        sizes[index - 1] = max(PREVIEW_MIN_WIDTH, sizes[index - 1] - 180)
        splitter.setSizes(sizes)
        press(dialog, "Cancel")

    def reopen(dialog):
        splitter, index = pane_splitter(dialog)
        reopened["width"] = splitter.sizes()[index]
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, drag)
    window._select_file(caption="Pick", directory=str(tmp_path))
    assert window._preview_width == dragged_to

    drive_file_dialog(window, monkeypatch, reopen)
    window._open_file_viewer(str(tmp_path))

    # Remembered across dialog *kinds*: the width is a property of the session,
    # not of the button that happened to open a dialog.
    assert reopened["width"] == dragged_to
