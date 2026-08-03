"""
Tests for selecting which entities a Commander bulk destructive action affects:
the checkable dialog listing, the confirmation's return value, and the YDIDs
that reach the yd-* command.
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
)

from yellowdog_cli.commander.commander import (
    ENTITY_LIST_PADDING,
    MAX_DIALOG_LIST_ROWS,
    SKIP_CONFIRMATION_BUTTON_TEXT,
    EntitySummary,
    YellowDogApp,
    checked_entity_ids,
)


@pytest.fixture
def window(qapp):
    return YellowDogApp()


def entities() -> list[EntitySummary]:
    return [
        EntitySummary(id="ydid:workreq:1", name="wr-alpha", status="RUNNING"),
        EntitySummary(id="ydid:workreq:22", name="wr-b", status="HELD"),
    ]


# --- Dialog listing ----------------------------------------------------------


def test_rows_are_padded_off_the_frame(window):
    # Qt folds stylesheet padding into frameWidth(), so assert through that
    # rather than by matching the stylesheet string.
    dialog, _yes, _skip = window._build_destructive_dialog(
        "Cancel", "Cancel?", None, entities()
    )
    listing = dialog.findChild(QListWidget, "entity_selection")
    assert listing.frameWidth() >= ENTITY_LIST_PADDING


def test_height_cap_accounts_for_the_padding(window):
    # The cap must be computed from the padded frame. Derived from an unpadded
    # one it would be short by 2 * ENTITY_LIST_PADDING, clipping the last
    # visible row — the specific way this padding could have gone wrong.
    many = [
        EntitySummary(id=f"ydid:workreq:{n}", name=f"wr-{n}", status="RUNNING")
        for n in range(MAX_DIALOG_LIST_ROWS + 5)
    ]
    dialog, _yes, _skip = window._build_destructive_dialog(
        "Cancel", "Cancel?", None, many
    )
    listing = dialog.findChild(QListWidget, "entity_selection")
    row_height = listing.sizeHintForRow(0)
    assert listing.maximumHeight() == (
        row_height * MAX_DIALOG_LIST_ROWS + 2 * listing.frameWidth()
    )
    assert listing.maximumHeight() >= (
        row_height * MAX_DIALOG_LIST_ROWS + 2 * ENTITY_LIST_PADDING
    )


def test_all_entities_listed_and_checked(window):
    dialog, _yes, _skip = window._build_destructive_dialog(
        "Cancel", "Cancel?", None, entities()
    )
    listing = dialog.findChild(QListWidget, "entity_selection")
    assert listing is not None
    assert listing.count() == 2
    assert [listing.item(i).checkState() for i in range(2)] == [
        Qt.CheckState.Checked,
        Qt.CheckState.Checked,
    ]


def test_rows_show_name_and_status_with_ydid_off_screen(window):
    dialog, _yes, _skip = window._build_destructive_dialog(
        "Cancel", "Cancel?", None, entities()
    )
    listing = dialog.findChild(QListWidget, "entity_selection")
    first, second = listing.item(0), listing.item(1)
    assert first.text() == "wr-alpha  RUNNING"
    # names are padded to a common width so the status column lines up
    assert second.text() == "wr-b      HELD"
    # the YDID is a machine handle: UserRole, never the row text; the tooltip
    # carries the name too, so an elided row still resolves to its full name
    assert "ydid" not in first.text()
    assert first.toolTip() == "wr-alpha\nydid:workreq:1"
    assert first.data(Qt.ItemDataRole.UserRole) == "ydid:workreq:1"


def test_checked_entity_ids_reads_ticked_rows_in_order(window):
    dialog, _yes, _skip = window._build_destructive_dialog(
        "Cancel", "Cancel?", None, entities()
    )
    listing = dialog.findChild(QListWidget, "entity_selection")
    assert checked_entity_ids(listing) == ["ydid:workreq:1", "ydid:workreq:22"]
    listing.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert checked_entity_ids(listing) == ["ydid:workreq:22"]


def test_count_label_tracks_selection_and_gates_yes(window):
    dialog, yes_btn, _skip = window._build_destructive_dialog(
        "Cancel", "Cancel?", None, entities()
    )
    label = dialog.findChild(QLabel, "selection_count")
    listing = dialog.findChild(QListWidget, "entity_selection")
    assert label.text() == "2 of 2 selected"
    assert yes_btn.isEnabled() is True

    listing.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert label.text() == "1 of 2 selected"
    assert yes_btn.isEnabled() is True

    listing.item(1).setCheckState(Qt.CheckState.Unchecked)
    assert label.text() == "0 of 2 selected"
    assert yes_btn.isEnabled() is False  # cannot confirm a no-op run


def test_all_and_none_buttons_set_every_row(window):
    dialog, _yes, _skip = window._build_destructive_dialog(
        "Cancel", "Cancel?", None, entities()
    )
    listing = dialog.findChild(QListWidget, "entity_selection")
    dialog.findChild(QPushButton, "select_none").click()
    assert checked_entity_ids(listing) == []
    dialog.findChild(QPushButton, "select_all").click()
    assert checked_entity_ids(listing) == ["ydid:workreq:1", "ydid:workreq:22"]


def test_skip_button_says_it_acts_on_all(window):
    dialog, _yes, _skip = window._build_destructive_dialog(
        "Cancel", "Cancel?", None, entities()
    )
    box = dialog.findChild(QDialogButtonBox)
    assert {b.text() for b in box.buttons()} == {
        "No",
        "Yes",
        SKIP_CONFIRMATION_BUTTON_TEXT,
    }
    assert SKIP_CONFIRMATION_BUTTON_TEXT == "Yes to All (Don't Ask Again)"


def test_names_listing_is_read_only_and_not_selectable(window):
    # Delete Objects lists object paths, which have no YDID to target.
    dialog, _yes, _skip = window._build_destructive_dialog(
        "Delete", "Delete?", ["a.txt", "sub/"], None
    )
    assert dialog.findChild(QListWidget, "entity_selection") is None
    listing = dialog.findChild(QPlainTextEdit, "entity_listing")
    assert listing is not None
    assert listing.toPlainText() == "a.txt\nsub/"


def test_no_listing_at_all_when_neither_given(window):
    dialog, _yes, _skip = window._build_destructive_dialog("Delete", "Delete?")
    assert dialog.findChild(QListWidget, "entity_selection") is None
    assert dialog.findChild(QPlainTextEdit, "entity_listing") is None


# --- Confirmation return value -----------------------------------------------


def drive_dialog(window, monkeypatch, choose: str | None, uncheck: tuple = ()):
    """
    Let _confirm_destructive run without blocking on exec(): replace the
    dialog's exec() with a callback that unticks the given row indices and
    clicks a button, exactly as a user would. 'choose' is 'yes', 'skip', or
    None to dismiss without clicking anything.
    """
    real_build = window._build_destructive_dialog

    def build(title, message, names=None, entities=None):
        dialog, yes_btn, skip_btn = real_build(title, message, names, entities)

        def fake_exec():
            listing = dialog.findChild(QListWidget, "entity_selection")
            if listing is not None:
                for index in uncheck:
                    listing.item(index).setCheckState(Qt.CheckState.Unchecked)
            if choose == "yes":
                yes_btn.click()
            elif choose == "skip":
                skip_btn.click()
            return 0

        monkeypatch.setattr(dialog, "exec", fake_exec)
        return dialog, yes_btn, skip_btn

    monkeypatch.setattr(window, "_build_destructive_dialog", build)


def test_confirm_returns_only_the_ticked_entities(window, monkeypatch):
    all_entities = entities()
    drive_dialog(window, monkeypatch, "yes", uncheck=(0,))
    assert window._confirm_destructive("cancel", "t", "b", entities=all_entities) == [
        all_entities[1]
    ]


def test_confirm_returns_all_when_nothing_unticked(window, monkeypatch):
    all_entities = entities()
    drive_dialog(window, monkeypatch, "yes")
    assert (
        window._confirm_destructive("cancel", "t", "b", entities=all_entities)
        == all_entities
    )


def test_confirm_dismissed_returns_none(window, monkeypatch):
    drive_dialog(window, monkeypatch, None)
    assert window._confirm_destructive("cancel", "t", "b", entities=entities()) is None


def test_skip_acts_on_all_ignoring_ticks_and_registers_bypass(window, monkeypatch):
    # 'Yes to All' means all: the tick states are deliberately ignored, since
    # one dialog's ad-hoc subset must not appear to govern the suppressed runs
    # that follow it.
    all_entities = entities()
    drive_dialog(window, monkeypatch, "skip", uncheck=(0,))
    assert (
        window._confirm_destructive("cancel", "t", "b", entities=all_entities)
        == all_entities
    )
    assert "cancel" in window._skip_confirmations


def test_confirm_with_names_returns_empty_list_on_yes(window, monkeypatch):
    # Nothing is individually selectable, but the action is confirmed: [] and
    # None are distinct, so callers must test 'is not None'.
    drive_dialog(window, monkeypatch, "yes")
    assert window._confirm_destructive("delete", "t", "b", names=["a.txt"]) == []


def test_confirm_with_names_returns_none_when_dismissed(window, monkeypatch):
    drive_dialog(window, monkeypatch, None)
    assert window._confirm_destructive("delete", "t", "b", names=["a.txt"]) is None


def test_bypass_returns_empty_list_without_a_dialog(window):
    window._skip_confirmations = {"cancel"}
    assert window._confirm_destructive("cancel", "t", "b", entities=entities()) == []


def test_disabled_confirmations_return_empty_list(qapp):
    win = YellowDogApp(disable_confirmations=True)
    assert win._confirm_destructive("terminate", "t", "b") == []
    assert win._confirm_destructive("delete", "t", "b") == []


# --- Wiring: what actually reaches the yd-* command --------------------------


@pytest.fixture
def captured(window, monkeypatch):
    """Capture (command, args, kwargs) an action would run, without spawning it."""
    calls: list[tuple[str, list[str], dict]] = []
    monkeypatch.setattr(
        window,
        "_run_command_in_subprocess",
        lambda command, args, **kwargs: calls.append((command, args, kwargs)),
    )
    return calls


def stub_flow(window, monkeypatch, enumerated, selected):
    """
    Stub enumeration and confirmation: '_capture_dry_run_summaries' returns
    'enumerated' (recording the extra args it was given), and the confirmation
    returns 'selected'. Returns the list of enumeration extra-arg lists seen.
    """
    seen: list = []
    monkeypatch.setattr(
        window,
        "_capture_dry_run_summaries",
        lambda command, extra_args=None: seen.append(extra_args) or enumerated,
    )
    monkeypatch.setattr(
        window,
        "_confirm_destructive",
        lambda action_key, title, body, names=None, entities=None: selected,
    )
    return seen


def test_action_targets_only_the_selected_ydids(window, captured, monkeypatch):
    all_entities = entities()
    stub_flow(window, monkeypatch, all_entities, [all_entities[1]])
    window._cancel_work_requirements_action()
    command, args, _kwargs = captured[0]
    assert (command, args) == ("yd-cancel", ["-y", "ydid:workreq:22"])


def test_all_four_actions_pass_ydids_with_their_own_flags(
    window, captured, monkeypatch
):
    all_entities = entities()
    stub_flow(window, monkeypatch, all_entities, all_entities)
    ids = ["ydid:workreq:1", "ydid:workreq:22"]
    for method, command, flags in [
        ("_cancel_work_requirements_action", "yd-cancel", ["-y"]),
        ("_cancel_work_requirements_and_abort_action", "yd-cancel", ["-ay"]),
        ("_shutdown_all_worker_pools_action", "yd-shutdown", ["-y"]),
        ("_terminate_all_compute_requirements_action", "yd-terminate", ["-y"]),
    ]:
        captured.clear()
        getattr(window, method)()
        assert captured[0][0] == command
        assert captured[0][1] == flags + ids


def test_name_pattern_narrows_enumeration_but_never_the_run(
    window, captured, monkeypatch
):
    # The CLI rejects mixing glob patterns with literal names/IDs ("cannot mix
    # name glob patterns with explicit names/IDs"), so the Name pattern must
    # reach the enumeration and must not reach the run.
    all_entities = entities()
    seen = stub_flow(window, monkeypatch, all_entities, all_entities)
    window.name_glob_override.setPlainText("job-*")
    window._cancel_work_requirements_action()
    assert seen == [["job-*"]]
    _command, args, _kwargs = captured[0]
    assert "job-*" not in args
    assert args == ["-y", "ydid:workreq:1", "ydid:workreq:22"]


def test_declined_selection_does_not_run(window, captured, monkeypatch):
    stub_flow(window, monkeypatch, entities(), None)
    window._cancel_work_requirements_action()
    assert captured == []


def test_empty_enumeration_logs_and_skips(window, captured, monkeypatch):
    # Must log and return *before* confirming: a stub that raises if the
    # confirmation is ever reached proves the ordering, not just the outcome.
    monkeypatch.setattr(
        window, "_capture_dry_run_summaries", lambda command, extra_args=None: []
    )

    def fail(action_key, title, body, names=None, entities=None):
        raise AssertionError("must not confirm when the enumeration is empty")

    monkeypatch.setattr(window, "_confirm_destructive", fail)
    window.log_output.setPlainText("")
    window._terminate_all_compute_requirements_action()
    assert captured == []
    assert "No matching Compute Requirements" in window.log_output.toPlainText()


def test_nonempty_enumeration_with_nothing_selected_runs_nothing(
    window, captured, monkeypatch
):
    # A non-None, non-empty enumeration whose confirmation returns [] must run
    # nothing: 'run_args + []' IS the whole-scope destructive command, so
    # falling through here would silently destroy everything in scope.
    stub_flow(window, monkeypatch, entities(), [])
    window._cancel_work_requirements_action()
    assert captured == []


def test_enumeration_failure_runs_the_confirmed_scope(window, captured, monkeypatch):
    # No YDIDs exist to target, so the run falls back to the scope the user just
    # confirmed — including the Name pattern, which is the only scope it has.
    stub_flow(window, monkeypatch, None, [])
    window.name_glob_override.setPlainText("cr-*")
    window._terminate_all_compute_requirements_action()
    _command, args, _kwargs = captured[0]
    assert args == ["-y", "cr-*"]


def test_entities_are_passed_to_the_confirmation(window, captured, monkeypatch):
    all_entities = entities()
    monkeypatch.setattr(
        window,
        "_capture_dry_run_summaries",
        lambda command, extra_args=None: all_entities,
    )
    seen: list = []
    monkeypatch.setattr(
        window,
        "_confirm_destructive",
        lambda action_key, title, body, names=None, entities=None: (
            seen.append((body, names, entities)) or list(entities)
        ),
    )
    window._namespace, window._tag = "yd-demo", "pyex"
    window._cancel_work_requirements_action()
    body, names, passed = seen[0]
    assert "Cancelling Work Requirements in namespace 'yd-demo'" in body
    assert "with tags including 'pyex'" in body
    assert names is None  # the entity actions use the selectable listing
    assert passed == all_entities


def test_suppressed_run_logs_and_uses_the_whole_scope(window, captured, monkeypatch):
    def fail(command, extra_args=None):
        raise AssertionError("enumeration must not run when confirmations are skipped")

    monkeypatch.setattr(window, "_capture_dry_run_summaries", fail)
    window._skip_confirmations = {"terminate"}
    window.name_glob_override.setPlainText("cr-*")
    window.log_output.setPlainText("")
    window._terminate_all_compute_requirements_action()
    _command, args, _kwargs = captured[0]
    assert args == ["-y", "cr-*"]
    assert "Confirmations suppressed for 'terminate'" in window.log_output.toPlainText()


def test_yes_to_all_still_targets_ydids_on_this_invocation(
    window, captured, monkeypatch
):
    # The skip button returns every listed entity, so this run is still exact;
    # only the *subsequent* suppressed runs fall back to the scope.
    all_entities = entities()
    monkeypatch.setattr(
        window,
        "_capture_dry_run_summaries",
        lambda command, extra_args=None: all_entities,
    )
    drive_dialog(window, monkeypatch, "skip", uncheck=(0,))
    window._cancel_work_requirements_action()
    _command, args, _kwargs = captured[0]
    assert args == ["-y", "ydid:workreq:1", "ydid:workreq:22"]
    assert "cancel" in window._skip_confirmations

    # the next click is suppressed: no enumeration, whole scope
    captured.clear()
    window._cancel_work_requirements_action()
    assert captured[0][1] == ["-y"]


def test_unticked_entity_is_not_acted_on(window, captured, monkeypatch):
    # The end-to-end guarantee: a row the user unticks in the real dialog must
    # not reach the command line. Everything between the dialog and the run is
    # real here; only the two process boundaries are stubbed.
    all_entities = entities()
    monkeypatch.setattr(
        window,
        "_capture_dry_run_summaries",
        lambda command, extra_args=None: all_entities,
    )
    drive_dialog(window, monkeypatch, "yes", uncheck=(0,))
    window._cancel_work_requirements_action()
    _command, args, _kwargs = captured[0]
    assert args == ["-y", "ydid:workreq:22"]


def test_small_selection_is_echoed_in_full(window, captured, monkeypatch):
    all_entities = entities()
    stub_flow(window, monkeypatch, all_entities, all_entities)
    window._cancel_work_requirements_action()
    assert captured[0][2]["log_args"] is None


def test_large_selection_is_echoed_as_a_count(window, captured, monkeypatch):
    many = [
        EntitySummary(id=f"ydid:workreq:{n}", name=f"wr-{n}", status="RUNNING")
        for n in range(4)
    ]
    stub_flow(window, monkeypatch, many, many)
    window._cancel_work_requirements_action()
    _command, args, kwargs = captured[0]
    assert args == ["-y"] + [entity.id for entity in many]
    assert kwargs["log_args"] == ["-y", "<4 Work Requirements>"]
