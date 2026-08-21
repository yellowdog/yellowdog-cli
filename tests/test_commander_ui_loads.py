"""
Smoke test that the Commander UI actually loads. Constructing YellowDogApp runs
loadUi() against commander.ui and wires every action signal to a named widget,
so a successful construction proves the .ui file is compatible with the
installed PyQt6 and that no code-referenced widget is missing. Guards against
Qt-version incompatibilities and accidental .ui edits.
"""

import qt_guard

qt_guard.require_qt()

import gui_harness
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QLayout,
    QPlainTextEdit,
    QPushButton,
    QStyleFactory,
    QWidget,
)

from yellowdog_cli._version import __version__
from yellowdog_cli.commander.commander import YellowDogApp


def test_ui_loads_and_binds_expected_widgets(qapp):
    win = YellowDogApp()

    # loadUi succeeded and the window is the branded Commander window, with the
    # CLI version in the title. Asserted word by word rather than as a phrase:
    # 'YellowDog Commander' became 'YellowDog CLI Commander' without the branding
    # or the version changing, and only this assertion noticed.
    title = win.windowTitle()
    assert title.startswith("YellowDog")
    assert "Commander" in title
    assert __version__ in title

    # A representative sample of code-referenced widgets exist with the right
    # types (loadUi would have failed, or __init__'s signal wiring would have
    # raised AttributeError, if any were missing).
    assert isinstance(win.log_output, QPlainTextEdit)
    assert isinstance(win.name_glob_override, QPlainTextEdit)
    assert isinstance(win.submit_work_requirement, QPushButton)
    assert isinstance(win.create_worker_pool, QPushButton)
    assert isinstance(win.download_results, QPushButton)


def test_a_separator_divides_the_view_row_from_the_run_command_row(qapp):
    # Found by shape and position rather than by name, so it survives whatever
    # Designer calls it, and asserts the thing that matters: that a horizontal
    # rule lies between the two rows rather than merely existing somewhere.
    win = gui_harness.shown(YellowDogApp())

    def top(widget) -> int:
        return widget.mapTo(win, QPoint(0, 0)).y()

    def bottom(widget) -> int:
        return top(widget) + widget.height()

    between = [
        frame
        for frame in win.findChildren(QFrame)
        if frame.frameShape() == QFrame.Shape.HLine
        and bottom(win.view_config_directory) <= top(frame) <= top(win.run_any_command)
    ]

    assert between, "no horizontal separator below the View Config Directory row"
    assert all(
        bottom(separator) <= top(win.run_any_command) for separator in between
    ), "the separator overlaps the row beneath it"


# The rows that share a grid row, left paired with right. Named rather than found
# by position: which row is meant to line up with which is a design decision, not
# something geometry can be asked.
ALIGNED_ROWS = [
    ("horizontalLayout_select_config", "horizontalLayout_8"),  # heading / Namespace
    ("select_config_label", "horizontalLayout"),  # selection / User variables
    ("line_7", "line_4"),  # and the separator beneath them
]


def row_rect(win, name: str) -> QRect:
    """
    Where the named row sits in the window, whether it is a widget or the layout
    holding a row of them. A layout's geometry is in its parent widget's
    coordinates, so it is mapped like the widgets to make the two comparable.
    """
    widget = win.findChild(QWidget, name)
    if widget is not None:
        return QRect(widget.mapTo(win, QPoint(0, 0)), widget.size())
    layout = win.findChild(QLayout, name)
    assert layout is not None, f"no widget or layout named {name!r}"
    geometry = layout.geometry()
    central = win.centralWidget()
    assert central is not None
    return QRect(central.mapTo(win, geometry.topLeft()), geometry.size())


def test_the_paired_rows_align_across_the_two_columns(qapp):
    # Two independent column layouts have no shared notion of a row, so these
    # only ever lined up by accident: the separators sat 7px apart, and the rows
    # above them 6px and 10px. Exact equality is the point of putting them in
    # shared grid rows, and it says nothing about any particular font size.
    win = gui_harness.shown(YellowDogApp())

    misaligned = []
    for left, right in ALIGNED_ROWS:
        left_rect, right_rect = row_rect(win, left), row_rect(win, right)
        if (left_rect.top(), left_rect.bottom()) != (
            right_rect.top(),
            right_rect.bottom(),
        ):
            misaligned.append(
                f"{left} {left_rect.top()}..{left_rect.bottom()} vs "
                f"{right} {right_rect.top()}..{right_rect.bottom()}"
            )

    assert not misaligned, "rows do not share a grid row: " + "; ".join(misaligned)


def test_the_window_opens_tall_enough_for_its_own_layout(qapp):
    # It opened 720 tall against a layout that needed 822, so Qt compressed the
    # left column below its minimum size hint. Compared with the hint rather than
    # with a number, so it stays true whatever the platform's metrics are.
    win = gui_harness.shown(YellowDogApp())

    assert win.height() >= win.minimumSizeHint().height()


def test_no_button_is_squeezed_or_stretched_out_of_step(qapp):
    # What the compression looked like: buttons wanting 25px given 18 or 19, and
    # unevenly, so adjacent buttons sat a pixel off each other. Surplus space has
    # to land somewhere other than the buttons too, or they grow just as unevenly.
    win = gui_harness.shown(YellowDogApp())

    wrong = {
        button.objectName(): (button.height(), button.sizeHint().height())
        for button in win.findChildren(QPushButton)
        if button.height() != button.sizeHint().height()
    }

    assert not wrong, f"buttons not at their natural height: {wrong}"


# One widget from each row of the right-hand column, the leftmost in the row.
RIGHT_COLUMN_ROWS = [
    "label_7",  # Namespace:
    "label_4",  # User-Defined Variables:
    "view_config_directory",
    "run_any_command",
    "command_output_title",
    "stdin_label",
    "clear_command_output",
]


def test_the_right_column_rows_start_at_the_same_edge(qapp):
    # The top two rows were indented 15px further than the rest, half of it a
    # dropped wrapper's margin and half two labels' leading spaces.
    win = gui_harness.shown(YellowDogApp())

    starts = {}
    for name in RIGHT_COLUMN_ROWS:
        widget = win.findChild(QWidget, name)
        assert widget is not None, f"no widget named {name!r}"
        starts[name] = widget.mapTo(win, QPoint(0, 0)).x()

    assert len(set(starts.values())) == 1, f"ragged left edges: {starts}"


def test_no_label_is_indented_with_leading_spaces(qapp):
    # Layout is the layout's business: a label padded with spaces cannot be
    # aligned with anything, and hides why it does not line up.
    win = gui_harness.shown(YellowDogApp())

    padded = {
        label.objectName(): label.text()
        for label in win.findChildren(QLabel)
        if label.text() != label.text().strip()
    }

    assert not padded, f"labels padded with whitespace: {padded}"


# The labelled input rows of the left-hand column, field by field.
LEFT_COLUMN_FIELDS = [
    "wr_submit_options",  # Extra Options: (panel 2)
    "wp_provision_options",  # Extra Options: (panel 3)
    "object_path_override",  # Path: (panel 4)
]


def test_the_left_column_fields_start_at_the_same_edge(qapp):
    # Their labels are of different widths, so left to itself each field started
    # wherever its own label happened to end: 110, 110 and 56.
    win = gui_harness.shown(YellowDogApp())

    starts = {}
    for name in LEFT_COLUMN_FIELDS:
        field = win.findChild(QWidget, name)
        assert field is not None, f"no widget named {name!r}"
        starts[name] = field.mapTo(win, QPoint(0, 0)).x()

    assert len(set(starts.values())) == 1, f"ragged field edges: {starts}"


# One row from each panel of the left-hand column, top to bottom.
LEFT_COLUMN_ROWS = [
    "submit_work_requirement",
    "select_work_requirement",
    "cancel_work_requirements",
    "create_worker_pool",
    "download_results",
    "view_results",
]


def test_the_left_column_does_not_spread_as_the_window_grows(qapp):
    # A QVBoxLayout with nothing in it that can grow does not leave the surplus at
    # the end: it spreads it evenly between the items. So without a stretch at the
    # bottom of the column, making the window taller pushed its buttons apart —
    # measured 33px between the first two at 840 and 46px at 1200.
    win = gui_harness.shown(YellowDogApp())

    def offsets() -> list[int]:
        QApplication.processEvents()
        top = win.submit_work_requirement.mapTo(win, QPoint(0, 0)).y()
        return [
            win.findChild(QWidget, name).mapTo(win, QPoint(0, 0)).y() - top
            for name in LEFT_COLUMN_ROWS
        ]

    win.resize(win.width(), 840)
    at_840 = offsets()
    win.resize(win.width(), 1200)
    at_1200 = offsets()

    assert at_840 == at_1200, (
        f"the column spread as the window grew: {at_840} then {at_1200}"
    )


def test_a_style_change_re_aligns_the_checkboxes(qapp):
    # The left column's checkboxes are indented by however far the current style
    # insets a push button's bevel, so the indent belongs to the style — and Dark
    # Mode switches the application style. A stale indent left behind by the
    # previous style would push them past the buttons instead of level with them.
    #
    # Only this direction can be checked here: the inset itself is resolved
    # against the real platform, and offscreen every style paints the bevel flush,
    # which is why there is no test of the indent being applied.
    win = YellowDogApp()
    win.dry_run.setStyleSheet("margin-left: 9px")

    win.setStyle(QStyleFactory.create("Fusion"))
    QApplication.processEvents()

    assert win.dry_run.styleSheet() == "", "a stale indent survived the style change"
