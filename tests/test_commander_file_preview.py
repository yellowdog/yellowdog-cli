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

from os.path import realpath
from time import monotonic

import gui_harness
from PyQt6.QtCore import QEventLoop, QPoint, QRect
from PyQt6.QtGui import QColor, QFont, QImage
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QDialogButtonBox,
    QFileDialog,
    QLineEdit,
    QListView,
    QProxyStyle,
    QPushButton,
    QSplitter,
    QStyle,
    QWidget,
)

from yellowdog_cli.commander.commander import (
    DIALOG_VIEW_MODE,
    NATIVE_VIEWER_BUTTON_TEXT,
    PREVIEW_ELIDED_BYTES,
    PREVIEW_ELIDED_LINES,
    PREVIEW_MAX_LINE_CHARS,
    PREVIEW_MAX_LINES,
    PREVIEW_MIN_WIDTH,
    PREVIEW_NO_SELECTION,
    PREVIEW_PANE_WIDTH,
    PREVIEW_READ_BYTES,
    SETTING_DIALOG_SIDEBAR_WIDTH,
    SETTING_DIALOG_VIEW_MODE,
    SIDEBAR_PANE_WIDTH,
    FilePreview,
    YellowDogApp,
    format_file_size,
)

# QFileSystemModel populates on its own thread, so a freshly opened dialog does
# not have the directory's rows yet. Generous for a slow CI node; a real failure
# to list the file still fails the test rather than hanging the suite.
LISTING_TIMEOUT_S = 5.0

# A pane taller than its own content, so that the layout has spare height to put
# somewhere: the point of the heading cases below is where that spare height goes.
TALL_PANE_HEIGHT = 400


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


class MacButtonLayout(QProxyStyle):
    """
    A style that lays a dialog's button box out the way macOS does: the accept and
    reject buttons in a vertical column, with an ActionRole button appended after
    them.

    Needed because the offscreen platform's own style puts an ActionRole button
    first whatever the code does, so without this the placement is untestable
    here — the assertion would pass whether or not Commander places the button
    itself. Which is exactly how 'on the Mac it sits below Open' got past a green
    suite once already.
    """

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_DialogButtonLayout:
            return QDialogButtonBox.ButtonLayout.MacLayout.value
        return super().styleHint(hint, option, widget, returnData)


@pytest.fixture
def mac_button_layout(qapp):
    """
    Lay dialog button boxes out as macOS does, for one test.

    Restored by name rather than by holding the old style object: setStyle takes
    ownership of what it is given and deletes the style it replaces, so keeping a
    reference to put back would leave a dangling one.
    """
    previous = qapp.style().objectName()
    qapp.setStyle(MacButtonLayout())
    yield
    qapp.setStyle(previous)


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
    assert len(body) == PREVIEW_MAX_LINES + 1


def test_a_line_capped_preview_says_how_many_lines_it_is_showing(preview, tmp_path):
    # A bare ellipsis says only 'there is more', which for task output could mean
    # twenty more lines or twenty thousand. What is knowable without reading the
    # whole file is how much was shown, so that is what it says.
    target = tmp_path / "big.log"
    target.write_text("".join(f"line {n}\n" for n in range(PREVIEW_MAX_LINES + 20)))

    preview.show_path(str(target))

    body = preview.text_view.toPlainText().splitlines()
    assert body[-1] == PREVIEW_ELIDED_LINES.format(lines=f"{PREVIEW_MAX_LINES:,}")


def test_a_byte_capped_preview_says_how_much_of_the_file_it_read(preview, tmp_path):
    # Few lines, but long ones: the byte cap bites where the line cap does not, and
    # 'first 500 lines' would be a lie about a file with three of them.
    target = tmp_path / "one-long-record.json"
    target.write_text("".join("x" * 100_000 + "\n" for _ in range(3)))
    assert target.stat().st_size > PREVIEW_READ_BYTES

    preview.show_path(str(target))

    body = preview.text_view.toPlainText().splitlines()
    assert len(body) - 1 <= PREVIEW_MAX_LINES, "the line cap should not have bitten"
    assert body[-1] == PREVIEW_ELIDED_BYTES.format(
        size=format_file_size(PREVIEW_READ_BYTES)
    )


def test_a_very_long_line_is_cut_rather_than_laid_out_whole(preview, tmp_path):
    # Not cosmetic: QPlainTextEdit lays a single line out at superlinear cost, so
    # the head of a minified JSON file — one line, no newlines — took 110ms to
    # show, and show_path runs on every arrow-key move through the listing. Cut to
    # PREVIEW_MAX_LINE_CHARS it is 1.4ms even when every line is at the cap.
    target = tmp_path / "minified.json"
    target.write_text("x" * (PREVIEW_MAX_LINE_CHARS * 4) + "\n")

    preview.show_path(str(target))

    body = preview.text_view.toPlainText().splitlines()
    assert body[0].startswith("xxx")
    assert body[0].endswith("…"), "a line that was cut must say so"
    assert all(len(line) <= PREVIEW_MAX_LINE_CHARS + 1 for line in body)


def test_a_whole_short_file_is_shown_without_an_elision_note(preview, tmp_path):
    target = tmp_path / "task_1.log"
    target.write_text("Task started\nDone in 4.1s\n")

    preview.show_path(str(target))

    assert preview.text_view.toPlainText() == "Task started\nDone in 4.1s"


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
    assert preview.text_view.toPlainText().endswith(
        PREVIEW_ELIDED_BYTES.format(size=format_file_size(PREVIEW_READ_BYTES))
    )


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


def test_the_headings_stay_at_the_top_when_there_is_no_body_to_show(preview, tmp_path):
    # A directory has no body, which leaves the two headings as the only things in
    # the layout — and Qt, with nothing able to grow, spreads the pane's spare
    # height evenly around them: the name a third of the way down, the kind
    # another third below it, and a hand's width of nothing in between.
    (tmp_path / "results").mkdir()
    preview.resize(PREVIEW_PANE_WIDTH, TALL_PANE_HEIGHT)

    preview.show_path(str(tmp_path / "results"))
    preview.layout().activate()

    name = preview.name_label.geometry()
    meta = preview.meta_label.geometry()
    assert name.top() < name.height(), "the headings do not start at the top"
    assert name.height() < preview.height() // 4, (
        "a heading holds more height than its text needs"
    )
    assert 0 <= meta.top() - name.bottom() <= name.height(), (
        "the two heading lines have drifted apart"
    )
    assert preview.height() - meta.bottom() > preview.height() // 2, (
        "the spare height is not below the headings"
    )


def test_the_body_still_runs_to_the_bottom_of_the_pane(preview, tmp_path):
    # The other half of grouping the headings at the top: whatever holds the spare
    # height down there must give all of it back once there is a body to show.
    log = tmp_path / "task_1.log"
    log.write_text("Task started\n")
    preview.resize(PREVIEW_PANE_WIDTH, TALL_PANE_HEIGHT)

    preview.show_path(str(log))
    preview.layout().activate()

    body = preview.text_view.geometry()
    meta = preview.meta_label.geometry()
    assert 0 <= body.top() - meta.bottom() <= meta.height(), (
        "the body does not follow the headings"
    )
    assert preview.height() - body.bottom() <= preview.layout().spacing(), (
        "the body has been robbed of the pane's spare height"
    )


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


def test_the_file_selector_returns_the_file_the_user_selected(
    window, tmp_path, monkeypatch
):
    (tmp_path / "wr.jsonnet").write_text("{ }\n")

    def interact(dialog):
        highlight(dialog, "wr.jsonnet")
        press(dialog, "Select")

    drive_file_dialog(window, monkeypatch, interact)

    chosen = window._select_file(caption="Pick", directory=str(tmp_path))

    assert chosen == str(tmp_path / "wr.jsonnet")


def test_the_file_selector_accepts_with_select_not_open(window, tmp_path, monkeypatch):
    # These dialogs nominate a file for a later command to read; nothing is opened
    # by pressing the button, unlike the browse dialog's 'Open'.
    labels: dict = {}

    def interact(dialog):
        labels["buttons"] = [
            button.text().replace("&", "")
            for button in dialog.findChildren(QPushButton)
        ]
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, interact)
    window._select_file(caption="Pick", directory=str(tmp_path))

    assert "Select" in labels["buttons"]
    assert "Open" not in labels["buttons"]


def test_the_browse_dialog_still_says_open(window, tmp_path, monkeypatch):
    # It really does open the file it is given, in the platform's default
    # application, so 'Open' is the honest label there.
    labels: dict = {}

    def interact(dialog):
        labels["buttons"] = [
            button.text().replace("&", "")
            for button in dialog.findChildren(QPushButton)
        ]
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, interact)
    window._browse_with_preview("Browse", str(tmp_path))

    assert "Open" in labels["buttons"]


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


def sidebar_width(dialog) -> int:
    """
    How wide the dialog's places sidebar — 'Computer', the home directory — has
    opened. It is the first pane of the same splitter the preview goes into.
    """
    splitter = dialog.findChild(QSplitter, "splitter")
    assert splitter is not None, "the file dialog has no splitter"
    return splitter.sizes()[0]


def plain_dialog_widths(directory) -> tuple[int, int]:
    """
    The sidebar and listing widths of a stock Qt file dialog over 'directory',
    built and shown the way Commander's are but with none of its additions.

    The baseline the sidebar cases measure against, rather than a Commander
    dialog with a method stubbed out: what matters is how this compares with
    the dialog Qt would have given the user unaided.
    """
    dialog = QFileDialog(None, "Plain", str(directory))
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    try:
        gui_harness.shown(dialog)
        return sidebar_width(dialog), dialog.findChild(QSplitter, "splitter").sizes()[1]
    finally:
        dialog.close()
        dialog.deleteLater()


def test_the_listing_shows_names_only_by_default(
    window, tmp_path, monkeypatch, commander_dialog_settings
):
    # Qt's Detail view spends most of the listing's width on size, kind and date,
    # and elides the one column that identifies the file. Its List view is names
    # only, and the two toolbar buttons still switch between them.
    (tmp_path / "a-file-with-a-name-long-enough-to-elide.log").write_text("x\n")
    seen = {}

    def interact(dialog):
        seen["mode"] = dialog.viewMode()
        seen["view"] = listing_view(dialog).objectName()
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, interact)
    window._select_file(caption="Pick", directory=str(tmp_path))

    assert seen["mode"] == DIALOG_VIEW_MODE == QFileDialog.ViewMode.List
    assert seen["view"] == "listView"


def test_the_view_mode_the_user_switches_to_is_used_by_the_next_dialog(
    window, tmp_path, monkeypatch, commander_dialog_settings
):
    # Switched with the dialog's own toolbar button, so the switch travels the
    # same wiring a user's click does.
    reopened = {}

    def switch(dialog):
        button = dialog.findChild(QAbstractButton, "detailModeButton")
        assert button is not None, "the dialog has no detail-mode button"
        button.click()
        press(dialog, "Cancel")

    def reopen(dialog):
        reopened["mode"] = dialog.viewMode()
        reopened["view"] = listing_view(dialog).objectName()
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, switch)
    window._select_file(caption="Pick", directory=str(tmp_path))

    drive_file_dialog(window, monkeypatch, reopen)
    window._open_file_viewer(str(tmp_path))

    # Remembered across dialog *kinds*, and across sessions: it is the user's
    # choice, not a property of the button that opened a dialog.
    assert reopened["mode"] == QFileDialog.ViewMode.Detail
    assert reopened["view"] == "treeView"
    assert commander_dialog_settings.value(SETTING_DIALOG_VIEW_MODE) == "Detail"


def test_the_places_sidebar_opens_wide_enough_to_read_its_entries(
    window, tmp_path, monkeypatch, qt_sidebar_width
):
    # Left to itself Qt opens it at the sidebar's size hint, which elides even
    # 'Computer' to 'Co...' — the one part of the dialog that says nothing.
    qt_sidebar_width(None)
    plain_sidebar, _ = plain_dialog_widths(tmp_path)
    measured = {}

    def interact(dialog):
        measured["sidebar"] = sidebar_width(dialog)
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, interact)
    window._select_file(caption="Pick", directory=str(tmp_path))

    assert plain_sidebar < SIDEBAR_PANE_WIDTH, (
        "Qt already opens the sidebar wide enough, so this proves nothing"
    )
    assert measured["sidebar"] >= SIDEBAR_PANE_WIDTH


def test_the_save_dialog_widens_its_sidebar_too(
    window, tmp_path, monkeypatch, qt_sidebar_width
):
    # It carries no preview pane, so it is the call site that a width set from
    # inside _add_preview_pane would quietly miss.
    qt_sidebar_width(None)
    measured = {}

    def interact(dialog):
        measured["sidebar"] = sidebar_width(dialog)
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, interact)
    window._save_file(
        caption="Save",
        directory=str(tmp_path / "output.txt"),
        file_pattern="All files (*)",
    )

    assert measured["sidebar"] >= SIDEBAR_PANE_WIDTH


@pytest.mark.parametrize(
    "remembered",
    [SIDEBAR_PANE_WIDTH - 60, SIDEBAR_PANE_WIDTH + 60],
    ids=["narrower", "wider"],
)
def test_a_sidebar_width_commander_remembers_is_used_as_it_stands(
    window, tmp_path, monkeypatch, commander_dialog_settings, remembered
):
    # Widening is a default, not a standing override: forced every time, a narrower
    # sidebar could never be kept, and a wider one would be clamped back.
    commander_dialog_settings.setValue(SETTING_DIALOG_SIDEBAR_WIDTH, remembered)
    measured = {}

    def interact(dialog):
        measured["sidebar"] = sidebar_width(dialog)
        sidebar = dialog.findChild(QListView, "sidebar")
        assert sidebar is not None, "the file dialog has no sidebar"
        measured["minimum"] = sidebar.minimumSizeHint().width()
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, interact)
    window._select_file(caption="Pick", directory=str(tmp_path))

    assert measured["sidebar"] == remembered
    # A width that happens to be the pane's minimum is the one width a squashed
    # sidebar also lands on, so it would prove nothing: that is how this case
    # first passed against code that discarded the remembered width entirely.
    assert remembered != measured["minimum"]


def test_the_sidebar_width_the_user_drags_to_is_used_by_the_next_dialog(
    window, tmp_path, monkeypatch, commander_dialog_settings
):
    dragged_to = SIDEBAR_PANE_WIDTH + 40
    reopened = {}

    def drag(dialog):
        splitter = dialog.findChild(QSplitter, "splitter")
        assert splitter is not None, "the file dialog has no splitter"
        sizes = splitter.sizes()
        sizes[1] = max(1, sizes[1] - (dragged_to - sizes[0]))
        sizes[0] = dragged_to
        splitter.setSizes(sizes)
        press(dialog, "Cancel")

    def reopen(dialog):
        reopened["sidebar"] = sidebar_width(dialog)
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, drag)
    window._select_file(caption="Pick", directory=str(tmp_path))
    assert commander_dialog_settings.value(SETTING_DIALOG_SIDEBAR_WIDTH) is not None

    drive_file_dialog(window, monkeypatch, reopen)
    window._open_file_viewer(str(tmp_path))

    assert reopened["sidebar"] == dragged_to


def test_qts_own_remembered_sidebar_width_is_ignored(
    window, tmp_path, monkeypatch, commander_dialog_settings, qt_sidebar_width
):
    # Qt writes its own remembered width whenever one of these dialogs closes, so
    # every machine that has ever opened one carries a value — 90 on any that ran
    # the version which squashed the sidebar to its minimum. Reading it was how
    # the widening came to be a no-op everywhere except a brand-new profile.
    qt_sidebar_width(90)
    measured = {}

    def interact(dialog):
        measured["sidebar"] = sidebar_width(dialog)
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, interact)
    window._select_file(caption="Pick", directory=str(tmp_path))

    assert measured["sidebar"] == SIDEBAR_PANE_WIDTH


def test_the_wider_sidebar_is_not_taken_out_of_the_listing(
    window, tmp_path, monkeypatch, qt_sidebar_width
):
    # Same bargain as the preview pane: the dialog grows by what the sidebar
    # gains, rather than the listing shrinking by it.
    qt_sidebar_width(None)
    _, plain_listing = plain_dialog_widths(tmp_path)
    measured = {}

    def interact(dialog):
        splitter = dialog.findChild(QSplitter, "splitter")
        assert splitter is not None, "the file dialog has no splitter"
        measured["listing"] = splitter.sizes()[1]
        measured["handle"] = splitter.handleWidth()
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, interact)
    window._select_file(caption="Pick", directory=str(tmp_path))

    # All the listing gives up is the preview pane's own splitter handle, which
    # has to come from somewhere; both panes' widths come from the wider dialog.
    lost = plain_listing - measured["listing"]
    assert 0 <= lost <= measured["handle"]


def test_the_listing_keeps_its_width_when_the_sidebar_is_already_wide(
    window, tmp_path, monkeypatch, commander_dialog_settings, qt_sidebar_width
):
    # The dialog must make room for the sidebar whether Commander is setting the
    # width for the first time or applying a remembered one. Uncompensated, the
    # listing was 84px narrower from the second dialog of the session onwards.
    qt_sidebar_width(None)
    _, plain_listing = plain_dialog_widths(tmp_path)
    commander_dialog_settings.setValue(SETTING_DIALOG_SIDEBAR_WIDTH, SIDEBAR_PANE_WIDTH)
    measured = {}

    def interact(dialog):
        splitter = dialog.findChild(QSplitter, "splitter")
        assert splitter is not None, "the file dialog has no splitter"
        measured["listing"] = splitter.sizes()[1]
        measured["handle"] = splitter.handleWidth()
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, interact)
    window._select_file(caption="Pick", directory=str(tmp_path))

    assert plain_listing - measured["listing"] <= measured["handle"]


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


# --- Switching to the platform's own file viewer ------------------------------
# Qt's dialog is read-only, so this button is the only way from here to delete or
# rename anything in the results directory.


def test_the_browse_dialog_offers_the_platform_file_viewer(
    window, tmp_path, monkeypatch
):
    handed: list[str] = []
    monkeypatch.setattr(window, "_open_with_default_application", handed.append)
    drive_file_dialog(
        window, monkeypatch, lambda dialog: press(dialog, NATIVE_VIEWER_BUTTON_TEXT)
    )

    chosen = window._browse_with_preview("Browse", str(tmp_path))

    assert [realpath(path) for path in handed] == [realpath(str(tmp_path))]
    # Switching hands over; it does not also report a file the user never picked.
    assert chosen is None


def test_the_platform_viewer_is_given_the_directory_on_screen(
    window, tmp_path, monkeypatch
):
    # Navigating first and then switching should hand over what is being looked
    # at, not wherever the dialog happened to open.
    (tmp_path / "task_1").mkdir()
    handed: list[str] = []
    monkeypatch.setattr(window, "_open_with_default_application", handed.append)

    def interact(dialog):
        dialog.setDirectory(str(tmp_path / "task_1"))
        press(dialog, NATIVE_VIEWER_BUTTON_TEXT)

    drive_file_dialog(window, monkeypatch, interact)
    window._browse_with_preview("Browse", str(tmp_path))

    assert [realpath(path) for path in handed] == [realpath(str(tmp_path / "task_1"))]


def test_the_platform_viewer_button_does_not_steal_the_default(
    window, tmp_path, monkeypatch
):
    # An autoDefault button that gains focus takes the default from the accept
    # button, which would make Return mean 'switch to Finder' instead of 'Open'.
    seen: dict = {}

    def interact(dialog):
        # With focus on it, an autoDefault button *becomes* the default — which is
        # the mechanism to guard against, so the check has to focus it first.
        for button in dialog.findChildren(QPushButton):
            if button.text().replace("&", "") == NATIVE_VIEWER_BUTTON_TEXT:
                button.setFocus()
        QApplication.processEvents()  # deliver the focus change before reading it
        assert dialog.focusWidget() is not None
        default = gui_harness.default_button(dialog)
        seen["default"] = None if default is None else default.text().replace("&", "")
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, interact)
    window._browse_with_preview("Browse", str(tmp_path))

    assert seen["default"] == "Open"


def test_the_file_selector_has_no_platform_viewer_button(window, tmp_path, monkeypatch):
    # Deliberate: a selector is for feeding a file to a command, not for managing
    # the directory it sits in.
    labels: dict = {}

    def interact(dialog):
        labels["buttons"] = [
            button.text().replace("&", "")
            for button in dialog.findChildren(QPushButton)
        ]
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, interact)
    window._select_file(caption="Pick", directory=str(tmp_path))

    assert NATIVE_VIEWER_BUTTON_TEXT not in labels["buttons"]


def test_the_platform_viewer_button_comes_ahead_of_the_accept_button(
    window, tmp_path, monkeypatch, mac_button_layout
):
    # Under the macOS button layout, Qt appends an ActionRole button after Cancel,
    # so it trailed the dialog's own answers. Commander places it first instead —
    # above Open in a vertical column, leftmost in a horizontal row.
    corners: dict = {}

    def interact(dialog):
        box = dialog.findChild(QDialogButtonBox)
        assert box is not None, "the file dialog has no button box"
        for button in box.buttons():
            label = button.text().replace("&", "")
            corners[label] = button.mapTo(dialog, button.rect().topLeft())
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, interact)
    window._browse_with_preview("Browse", str(tmp_path))

    finder, accept = corners[NATIVE_VIEWER_BUTTON_TEXT], corners["Open"]
    assert finder.y() < accept.y(), "the button trails the dialog's own answers"


def test_the_platform_viewer_button_is_first_in_the_button_box(
    window, tmp_path, monkeypatch
):
    # The layout-order counterpart of the geometric check above, which holds
    # whichever direction the platform's box runs in.
    order: dict = {}

    def interact(dialog):
        box = dialog.findChild(QDialogButtonBox)
        assert box is not None, "the file dialog has no button box"
        layout = box.layout()
        assert layout is not None, "the button box has no layout"
        button = next(
            b
            for b in box.buttons()
            if b.text().replace("&", "") == NATIVE_VIEWER_BUTTON_TEXT
        )
        order["index"] = layout.indexOf(button)
        # Still a proper member of the box, with its role: only its position moved.
        order["role"] = box.buttonRole(button)
        press(dialog, "Cancel")

    drive_file_dialog(window, monkeypatch, interact)
    window._browse_with_preview("Browse", str(tmp_path))

    assert order["index"] == 0
    assert order["role"] == QDialogButtonBox.ButtonRole.ActionRole
