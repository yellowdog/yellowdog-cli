"""
Tests for the check indicators in Commander's selection lists: every row of a
bulk destructive action's tick-list must paint its own check state, both on a
style that places the indicator where it is told to and on one that does not.

In a process whose main executable is linked against the macOS 26 SDK or later,
Qt's macOS style draws an item view's check indicator as macOS 26's redesigned
control at the painter's origin, ignoring the rect it computed. An item view
clips each row's painting to that row, so every indicator but the top row's was
clipped away: a ten-row confirmation showed one checkbox, and the nine rows below
it looked unticked and untickable however they were clicked. See
check_indicator_is_misplaced() for the mechanism and how it was established.
"""

import pytest
import qt_guard

qt_guard.require_qt()

import gui_harness
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (
    QListWidget,
    QProxyStyle,
    QStyle,
    QStyleFactory,
    QStyleOptionViewItem,
)

from yellowdog_cli.commander import check_indicator
from yellowdog_cli.commander.check_indicator import check_indicator_is_misplaced
from yellowdog_cli.commander.commander import YellowDogApp
from yellowdog_cli.commander.selection import (
    EntitySummary,
    entity_rows,
    set_all_check_states,
)

# Enough rows for the bug to have somewhere to hide: it is only ever the top row
# that is painted correctly, so a one-row listing looks right either way.
ROWS = 6


class IndicatorAtTheOrigin(QProxyStyle):
    """
    A stand-in for Qt's macOS style under the macOS 26 control redesign: paints a
    check indicator at the painter's origin, ignoring where the rect it was
    handed sits.

    The real thing cannot be reached here. This suite runs under the offscreen
    platform, whose macOS style paints no check indicator at all — so selecting
    that style would assert nothing — and no other style has the bug. This proxy
    is what makes the correction testable, exactly as MacButtonLayout is for the
    platform viewer button's placement.
    """

    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck:
            option = QStyleOptionViewItem(option)
            option.rect = QRect(0, 0, option.rect.width(), option.rect.height())
        super().drawPrimitive(element, option, painter, widget)


@pytest.fixture
def window(qapp):
    return YellowDogApp()


def misplacing() -> IndicatorAtTheOrigin:
    return IndicatorAtTheOrigin(QStyleFactory.create("Fusion"))


@pytest.fixture
def misplacing_style(qapp, monkeypatch):
    """
    Make the application misplace its check indicators the way Qt's macOS style
    does in a process linked against the macOS 26 SDK, and hand Commander an
    instance of the same style to correct.

    Both halves are needed, and for the same reason the correction takes a style
    from platform_style() rather than constructing a base-less QProxyStyle: what
    such a proxy wraps is a fresh instance of the platform's style, never the
    application's own object, so a stand-in set on the application would not be
    reached through the correction, nor a stand-in behind the correction reached
    without it. A test with only one of them passes whether Commander corrects
    anything or not.

    The application's style is restored by name rather than by holding the
    object: QApplication.setStyle deletes the style it replaces, so the one taken
    out here is gone by the time the fixture unwinds.
    """
    previous = qapp.style().objectName()
    qapp.setStyle(misplacing())
    monkeypatch.setattr(check_indicator, "platform_style", misplacing)
    yield
    qapp.setStyle(QStyleFactory.create(previous))


def entities(count: int = ROWS) -> list[EntitySummary]:
    return [
        EntitySummary(id=f"ydid:workreq:{n}", name=f"wr-{n}", status="RUNNING")
        for n in range(count)
    ]


def rows_that_show_their_check_state(listing: QListWidget) -> list[bool]:
    """
    Which rows of the listing paint differently ticked and unticked — which is
    the whole of what a check indicator is for.

    The pixels are the outcome here: an indicator either reaches its row or it
    does not. Nothing below reads a colour or a count out of them, only the same
    row against itself in the other state, so a substituted font changes nothing.
    """
    set_all_check_states(listing, Qt.CheckState.Checked)
    ticked = row_images(listing)
    set_all_check_states(listing, Qt.CheckState.Unchecked)
    unticked = row_images(listing)
    return [on != off for on, off in zip(ticked, unticked)]


def row_images(listing: QListWidget) -> list[QImage]:
    painted = listing.viewport().grab().toImage()
    return [
        painted.copy(listing.visualItemRect(listing.item(index)))
        for index in range(listing.count())
    ]


def selection_list(window: YellowDogApp) -> QListWidget:
    listing = window._build_selection_list_widget(entity_rows(entities()))
    gui_harness.shown(listing)
    return listing


def test_every_row_shows_its_check_state_on_a_misplacing_style(
    window, misplacing_style
):
    shown = rows_that_show_their_check_state(selection_list(window))
    assert all(shown), f"rows painted the same ticked as unticked: {shown}"


def test_every_row_shows_its_check_state_on_a_sound_style(window):
    # The same assertion, and the one that holds the correction to styles that
    # need it: applied to a style that places the indicator correctly it would
    # offset it twice — out of the row, and clipped away exactly as before.
    shown = rows_that_show_their_check_state(selection_list(window))
    assert all(shown), f"rows painted the same ticked as unticked: {shown}"


def test_the_probe_reports_a_misplaced_indicator(qapp):
    assert check_indicator_is_misplaced(
        IndicatorAtTheOrigin(QStyleFactory.create("Fusion"))
    )


def test_the_probe_passes_a_style_that_places_the_indicator(qapp):
    assert not check_indicator_is_misplaced(QStyleFactory.create("Fusion"))
