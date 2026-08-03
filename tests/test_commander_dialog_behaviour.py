"""
Commander's dialogs exercised as dialogs: real exec(), real clicks, real geometry.

These cover the bug classes that reached a user rather than the tests — buttons
that did nothing, a default button quietly stolen by another, and a list squeezed
until no row could be seen. Each was invisible to tests that stubbed exec() and
asserted on arguments, so nothing here does either.
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

import commander_dialogs
import gui_harness
from PyQt6.QtWidgets import QDialog, QListWidget

from yellowdog_cli.commander.commander import (
    MAX_DIALOG_LIST_ROWS,
    EntitySummary,
    ObjectSummary,
    YellowDogApp,
    entity_rows,
    object_rows,
)

ACCEPTED = QDialog.DialogCode.Accepted.value
REJECTED = QDialog.DialogCode.Rejected.value


@pytest.fixture
def window(qapp):
    return YellowDogApp()


def entity_listing_rows(count: int = 3, name_length: int = 8):
    return entity_rows(
        [
            EntitySummary(
                id=f"ydid:workreq:{n}",
                name=f"wr-{n:0{max(name_length - 3, 1)}d}",
                status="RUNNING",
            )
            for n in range(count)
        ]
    )


def object_listing_rows(count: int = 3):
    return object_rows(
        [
            ObjectSummary(path=f"S3:b/pfx/item{n}", name=f"item{n}", is_dir=n == 0)
            for n in range(count)
        ]
    )


def listing_of(dialog) -> QListWidget:
    listing = dialog.findChild(QListWidget, "selection_list")
    assert listing is not None, "the dialog has no selectable listing"
    return listing


# --- The buttons must actually resolve the dialog ----------------------------
#
# The destructive dialog is driven through _confirm_destructive rather than from
# the builder, because the builder does not wire its own button box: the caller
# attaches a 'clicked' handler, since it needs to know which button was pressed.
# A dialog straight from the builder therefore has inert buttons and a meaningless
# result code — testing it in isolation would assert nothing about what a user
# experiences.


def test_confirmation_yes_returns_the_ticked_selection(window, monkeypatch):
    rows = entity_listing_rows(count=3)
    commander_dialogs.drive_confirmation(window, monkeypatch, commander_dialogs.YES)
    result = window._confirm_destructive("cancel", "Cancel", "Cancel?", rows=rows)
    assert result.proceed is True
    assert result.handles == [row.handle for row in rows]


def test_confirmation_no_does_not_proceed(window, monkeypatch):
    commander_dialogs.drive_confirmation(window, monkeypatch, commander_dialogs.NO)
    result = window._confirm_destructive(
        "cancel", "Cancel", "Cancel?", rows=entity_listing_rows()
    )
    assert result.proceed is False


def test_closing_the_confirmation_does_not_proceed(window, monkeypatch):
    commander_dialogs.drive_confirmation(window, monkeypatch, commander_dialogs.DISMISS)
    result = window._confirm_destructive(
        "cancel", "Cancel", "Cancel?", rows=entity_listing_rows()
    )
    assert result.proceed is False


def test_confirmation_yes_to_all_proceeds_over_every_row(window, monkeypatch):
    rows = entity_listing_rows(count=3)
    commander_dialogs.drive_confirmation(
        window, monkeypatch, commander_dialogs.SKIP, untick_rows=(0, 1)
    )
    result = window._confirm_destructive("cancel", "Cancel", "Cancel?", rows=rows)
    # 'Yes to All' ignores the ticks, as its label says.
    assert result.handles == [row.handle for row in rows]
    assert "cancel" in window._skip_confirmations


def test_chooser_download_resolves_the_dialog(window):
    dialog, accept_btn = window._build_chooser_dialog(
        "Download Objects", "Downloading.", "Download", object_listing_rows()
    )
    assert gui_harness.run_modal(dialog, lambda _d: accept_btn.click()) == ACCEPTED


def test_chooser_cancel_rejects_the_dialog(window):
    dialog, _accept = window._build_chooser_dialog(
        "Download Objects", "Downloading.", "Download", object_listing_rows()
    )
    result = gui_harness.run_modal(
        dialog, lambda d: gui_harness.button_labelled(d, "Cancel").click()
    )
    assert result == REJECTED


# --- The intended button must hold the default ------------------------------


def test_a_confirmation_defaults_to_no(window):
    # Return must not confirm an irreversible action. All / None are the first
    # focusable widgets, and an autoDefault button that gains focus takes the
    # default over — which is how this was silently defeated once.
    dialog, _yes, _skip = window._build_destructive_dialog(
        "Cancel", "Cancel?", rows=entity_listing_rows()
    )
    gui_harness.shown(dialog)
    default = gui_harness.default_button(dialog)
    assert default is not None and default.text() == "No"


def test_a_chooser_defaults_to_its_accept_button(window):
    dialog, accept_btn = window._build_chooser_dialog(
        "Download Objects", "Downloading.", "Download", object_listing_rows()
    )
    gui_harness.shown(dialog)
    assert gui_harness.default_button(dialog) is accept_btn


# --- Rows must be visible, at any sensible dialog width ---------------------


@pytest.mark.parametrize("width", [260, 320, 480, 900])
def test_confirmation_rows_stay_visible_at_every_width(window, width):
    # The Windows failure: a long name overflowed a narrow dialog, Qt added a
    # horizontal scrollbar, and the scrollbar consumed the height budgeted for the
    # rows. The arithmetic still looked right; nothing could be seen.
    rows = entity_rows(
        [
            EntitySummary(
                id=f"ydid:workreq:{n}",
                name=f"a-very-long-work-requirement-name-{n:04d}",
                status="RUNNING",
            )
            for n in range(3)
        ]
    )
    dialog, _yes, _skip = window._build_destructive_dialog(
        "Cancel", "Cancel?", rows=rows
    )
    gui_harness.shown(dialog, width=width)
    listing = listing_of(dialog)

    assert listing.horizontalScrollBar().isVisible() is False
    assert gui_harness.visible_rows(listing) == 3


@pytest.mark.parametrize("width", [260, 320, 900])
def test_chooser_rows_stay_visible_at_every_width(window, width):
    dialog, _accept = window._build_chooser_dialog(
        "Download Objects",
        "Downloading objects matching 'pyex-bash-peter_toft*' into 'results'.",
        "Download",
        object_rows(
            [
                ObjectSummary(
                    path=f"S3:b/pfx/pyex-bash-peter_toft_{n:04d}",
                    name=f"pyex-bash-peter_toft_{n:04d}/",
                    is_dir=True,
                )
                for n in range(2)
            ]
        ),
    )
    gui_harness.shown(dialog, width=width)
    listing = listing_of(dialog)

    assert listing.horizontalScrollBar().isVisible() is False
    assert gui_harness.visible_rows(listing) == 2


def test_a_long_listing_shows_the_full_cap_and_scrolls(window):
    dialog, _yes, _skip = window._build_destructive_dialog(
        "Cancel", "Cancel?", rows=entity_listing_rows(count=MAX_DIALOG_LIST_ROWS + 8)
    )
    gui_harness.shown(dialog, width=420)
    listing = listing_of(dialog)

    assert gui_harness.visible_rows(listing) == MAX_DIALOG_LIST_ROWS
    assert listing.count() == MAX_DIALOG_LIST_ROWS + 8
    assert listing.verticalScrollBar().maximum() > 0


# --- A selection made in a real dialog must be what comes back --------------


def test_the_selection_read_back_is_what_was_left_ticked(window, monkeypatch):
    rows = entity_listing_rows(count=3)
    commander_dialogs.drive_confirmation(
        window, monkeypatch, commander_dialogs.YES, untick_rows=(1,)
    )
    result = window._confirm_destructive("cancel", "Cancel", "Cancel?", rows=rows)
    assert result.handles == [rows[0].handle, rows[2].handle]


def test_unticking_everything_disables_the_accept_button(window, monkeypatch):
    # Observed from inside the real modal loop, where the user would see it.
    observed: list[bool] = []

    def inspect(dialog):
        observed.append(gui_harness.button_labelled(dialog, "Yes").isEnabled())

    commander_dialogs.drive_confirmation(
        window,
        monkeypatch,
        commander_dialogs.NO,
        untick_rows=(0, 1, 2),
        inspect=inspect,
    )
    window._confirm_destructive(
        "cancel", "Cancel", "Cancel?", rows=entity_listing_rows(count=3)
    )
    assert observed == [False]
