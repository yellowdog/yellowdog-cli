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
    Confirmation,
    EntitySummary,
    YellowDogApp,
    checked_handles,
    entity_rows,
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
        "Cancel", "Cancel?", rows=entity_rows(entities())
    )
    listing = dialog.findChild(QListWidget, "selection_list")
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
        "Cancel", "Cancel?", rows=entity_rows(many)
    )
    listing = dialog.findChild(QListWidget, "selection_list")
    row_height = listing.sizeHintForRow(0)
    assert listing.maximumHeight() == (
        row_height * MAX_DIALOG_LIST_ROWS + 2 * listing.frameWidth()
    )
    assert listing.maximumHeight() >= (
        row_height * MAX_DIALOG_LIST_ROWS + 2 * ENTITY_LIST_PADDING
    )


def test_all_entities_listed_and_checked(window):
    dialog, _yes, _skip = window._build_destructive_dialog(
        "Cancel", "Cancel?", rows=entity_rows(entities())
    )
    listing = dialog.findChild(QListWidget, "selection_list")
    assert listing is not None
    assert listing.count() == 2
    assert [listing.item(i).checkState() for i in range(2)] == [
        Qt.CheckState.Checked,
        Qt.CheckState.Checked,
    ]


def test_rows_show_name_and_status_with_ydid_off_screen(window):
    dialog, _yes, _skip = window._build_destructive_dialog(
        "Cancel", "Cancel?", rows=entity_rows(entities())
    )
    listing = dialog.findChild(QListWidget, "selection_list")
    first, second = listing.item(0), listing.item(1)
    assert first.text() == "wr-alpha  RUNNING"
    # names are padded to a common width so the status column lines up
    assert second.text() == "wr-b      HELD"
    # the YDID is a machine handle: UserRole, never the row text; the tooltip
    # carries the name too, so an elided row still resolves to its full name
    assert "ydid" not in first.text()
    assert first.toolTip() == "wr-alpha\nydid:workreq:1"
    assert first.data(Qt.ItemDataRole.UserRole) == "ydid:workreq:1"


def test_checked_handles_reads_ticked_rows_in_order(window):
    dialog, _yes, _skip = window._build_destructive_dialog(
        "Cancel", "Cancel?", rows=entity_rows(entities())
    )
    listing = dialog.findChild(QListWidget, "selection_list")
    assert checked_handles(listing) == ["ydid:workreq:1", "ydid:workreq:22"]
    listing.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert checked_handles(listing) == ["ydid:workreq:22"]


def test_count_label_tracks_selection_and_gates_yes(window):
    dialog, yes_btn, _skip = window._build_destructive_dialog(
        "Cancel", "Cancel?", rows=entity_rows(entities())
    )
    label = dialog.findChild(QLabel, "selection_count")
    listing = dialog.findChild(QListWidget, "selection_list")
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
        "Cancel", "Cancel?", rows=entity_rows(entities())
    )
    listing = dialog.findChild(QListWidget, "selection_list")
    dialog.findChild(QPushButton, "select_none").click()
    assert checked_handles(listing) == []
    dialog.findChild(QPushButton, "select_all").click()
    assert checked_handles(listing) == ["ydid:workreq:1", "ydid:workreq:22"]


def test_skip_button_says_it_acts_on_all(window):
    dialog, _yes, _skip = window._build_destructive_dialog(
        "Cancel", "Cancel?", rows=entity_rows(entities())
    )
    box = dialog.findChild(QDialogButtonBox)
    assert {b.text() for b in box.buttons()} == {
        "No",
        "Yes",
        SKIP_CONFIRMATION_BUTTON_TEXT,
    }
    assert SKIP_CONFIRMATION_BUTTON_TEXT == "Yes to All (Don't Ask Again)"


def test_no_listing_at_all_when_rows_not_given(window):
    # Nothing individually selectable ('rows=None'): no listing widget of any
    # kind, and the caller falls back to acting over its whole scope.
    dialog, _yes, _skip = window._build_destructive_dialog("Delete", "Delete?")
    assert dialog.findChild(QListWidget, "selection_list") is None
    assert dialog.findChild(QPlainTextEdit, "entity_listing") is None


# --- Confirmation return value -----------------------------------------------


def test_confirmation_truthiness_is_refused():
    # The old return value here was a list-or-None sentinel, where both '[]'
    # and 'None' were falsy — a truthiness slip failed *safe* by declining.
    # 'Confirmation' is a dataclass, which pyright treats as always truthy, so
    # the same slip would now fail *dangerously*, proceeding even when the
    # user clicked No. Raising on __bool__ turns that into a loud, immediate
    # failure instead of a silent one.
    with pytest.raises(TypeError):
        bool(Confirmation(proceed=False, handles=None))
    with pytest.raises(TypeError):
        bool(Confirmation(proceed=True, handles=None))


def drive_dialog(window, monkeypatch, choose: str | None, uncheck: tuple = ()):
    """
    Let _confirm_destructive run without blocking on exec(): replace the
    dialog's exec() with a callback that unticks the given row indices and
    clicks a button, exactly as a user would. 'choose' is 'yes', 'skip', or
    None to dismiss without clicking anything.
    """
    real_build = window._build_destructive_dialog

    def build(title, message, rows=None):
        dialog, yes_btn, skip_btn = real_build(title, message, rows=rows)

        def fake_exec():
            listing = dialog.findChild(QListWidget, "selection_list")
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


def test_confirm_returns_all_when_nothing_unticked(window, monkeypatch):
    all_entities = entities()
    drive_dialog(window, monkeypatch, "yes")
    result = window._confirm_destructive(
        "cancel", "t", "b", rows=entity_rows(all_entities)
    )
    assert (result.proceed, result.handles) == (True, [e.id for e in all_entities])


def test_skip_acts_on_all_ignoring_ticks_and_registers_bypass(window, monkeypatch):
    # 'Yes to All' means all: the tick states are deliberately ignored, since
    # one dialog's ad-hoc subset must not appear to govern the suppressed runs
    # that follow it.
    all_entities = entities()
    drive_dialog(window, monkeypatch, "skip", uncheck=(0,))
    result = window._confirm_destructive(
        "cancel", "t", "b", rows=entity_rows(all_entities)
    )
    assert (result.proceed, result.handles) == (
        True,
        ["ydid:workreq:1", "ydid:workreq:22"],
    )
    assert "cancel" in window._skip_confirmations


def test_no_listing_returns_none_when_dismissed(window, monkeypatch):
    # 'rows=None' (nothing individually selectable — the sole listing case
    # left now that the read-only 'names' listing is gone) still reports
    # 'handles=None' when dismissed.
    drive_dialog(window, monkeypatch, None)
    result = window._confirm_destructive("delete", "t", "b")
    assert (result.proceed, result.handles) == (False, None)


def test_disabled_confirmations_return_whole_scope(qapp):
    win = YellowDogApp(disable_confirmations=True)
    assert win._confirm_destructive("terminate", "t", "b") == Confirmation(
        proceed=True, handles=None
    )
    assert win._confirm_destructive("delete", "t", "b") == Confirmation(
        proceed=True, handles=None
    )


def test_declined_confirmation_reports_no_proceed(window, monkeypatch):
    drive_dialog(window, monkeypatch, None)
    result = window._confirm_destructive(
        "cancel", "t", "b", rows=entity_rows(entities())
    )
    assert result.proceed is False
    assert result.handles is None


def test_no_listing_reports_whole_scope(window, monkeypatch):
    # Nothing individually selectable ('rows=None'), but the user said yes:
    # 'handles is None' is what tells the caller to act over its whole scope.
    drive_dialog(window, monkeypatch, "yes")
    result = window._confirm_destructive("delete", "t", "b")
    assert (result.proceed, result.handles) == (True, None)


def test_bypass_reports_whole_scope_not_empty_selection(window):
    # The distinction that matters: a suppressed confirmation means 'everything
    # in scope', which must not be confusable with 'nothing was ticked'.
    window._skip_confirmations = {"cancel"}
    result = window._confirm_destructive(
        "cancel", "t", "b", rows=entity_rows(entities())
    )
    assert (result.proceed, result.handles) == (True, None)


def test_a_ticked_subset_reports_exactly_those_handles(window, monkeypatch):
    drive_dialog(window, monkeypatch, "yes", uncheck=(0,))
    result = window._confirm_destructive(
        "cancel", "t", "b", rows=entity_rows(entities())
    )
    assert (result.proceed, result.handles) == (True, ["ydid:workreq:22"])


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


def stub_flow(window, monkeypatch, enumerated, confirmation):
    """
    Stub enumeration and confirmation: '_capture_dry_run_summaries' returns
    'enumerated' (recording the extra args it was given), and the confirmation
    returns 'confirmation' directly, so the caller controls 'proceed' and
    'handles' independently rather than inferring them from a single value.
    Returns the list of enumeration extra-arg lists seen.
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
        lambda action_key, title, body, rows=None: confirmation,
    )
    return seen


def test_action_targets_only_the_selected_ydids(window, captured, monkeypatch):
    all_entities = entities()
    stub_flow(
        window,
        monkeypatch,
        all_entities,
        Confirmation(proceed=True, handles=[all_entities[1].id]),
    )
    window._cancel_work_requirements_action()
    command, args, _kwargs = captured[0]
    assert (command, args) == ("yd-cancel", ["-y", "ydid:workreq:22"])


def test_all_four_actions_pass_ydids_with_their_own_flags(
    window, captured, monkeypatch
):
    all_entities = entities()
    ids = ["ydid:workreq:1", "ydid:workreq:22"]
    stub_flow(
        window, monkeypatch, all_entities, Confirmation(proceed=True, handles=ids)
    )
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
    seen = stub_flow(
        window,
        monkeypatch,
        all_entities,
        Confirmation(proceed=True, handles=[e.id for e in all_entities]),
    )
    window.name_glob_override.setPlainText("job-*")
    window._cancel_work_requirements_action()
    assert seen == [["job-*"]]
    _command, args, _kwargs = captured[0]
    assert "job-*" not in args
    assert args == ["-y", "ydid:workreq:1", "ydid:workreq:22"]


def test_declined_selection_does_not_run(window, captured, monkeypatch):
    stub_flow(
        window, monkeypatch, entities(), Confirmation(proceed=False, handles=None)
    )
    window._cancel_work_requirements_action()
    assert captured == []


def test_empty_enumeration_logs_and_skips(window, captured, monkeypatch):
    # Must log and return *before* confirming: a stub that raises if the
    # confirmation is ever reached proves the ordering, not just the outcome.
    monkeypatch.setattr(
        window, "_capture_dry_run_summaries", lambda command, extra_args=None: []
    )

    def fail(action_key, title, body, rows=None):
        raise AssertionError("must not confirm when the enumeration is empty")

    monkeypatch.setattr(window, "_confirm_destructive", fail)
    window.log_output.setPlainText("")
    window._terminate_all_compute_requirements_action()
    assert captured == []
    assert "No matching Compute Requirements" in window.log_output.toPlainText()


def test_nonempty_enumeration_with_nothing_selected_runs_nothing(
    window, captured, monkeypatch
):
    # A non-None, non-empty enumeration whose confirmation returns
    # 'handles=[]' must run nothing: 'run_args + []' IS the whole-scope
    # destructive command, so falling through here would silently destroy
    # everything in scope.
    stub_flow(window, monkeypatch, entities(), Confirmation(proceed=True, handles=[]))
    window._cancel_work_requirements_action()
    assert captured == []


def test_enumeration_failure_runs_the_confirmed_scope(window, captured, monkeypatch):
    # No YDIDs exist to target, so the run falls back to the scope the user just
    # confirmed — including the Name pattern, which is the only scope it has.
    stub_flow(window, monkeypatch, None, Confirmation(proceed=True, handles=None))
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
        lambda action_key, title, body, rows=None: (
            seen.append((body, rows))
            or Confirmation(proceed=True, handles=[row.handle for row in rows])
        ),
    )
    window._namespace, window._tag = "yd-demo", "pyex"
    window._cancel_work_requirements_action()
    body, passed = seen[0]
    assert "Cancelling Work Requirements in namespace 'yd-demo'" in body
    assert "with tags including 'pyex'" in body
    assert [row.handle for row in passed] == [e.id for e in all_entities]


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
    stub_flow(
        window,
        monkeypatch,
        all_entities,
        Confirmation(proceed=True, handles=[e.id for e in all_entities]),
    )
    window._cancel_work_requirements_action()
    assert captured[0][2]["log_args"] is None


def test_large_selection_is_echoed_as_a_count(window, captured, monkeypatch):
    many = [
        EntitySummary(id=f"ydid:workreq:{n}", name=f"wr-{n}", status="RUNNING")
        for n in range(4)
    ]
    stub_flow(
        window,
        monkeypatch,
        many,
        Confirmation(proceed=True, handles=[entity.id for entity in many]),
    )
    window._cancel_work_requirements_action()
    _command, args, kwargs = captured[0]
    assert args == ["-y"] + [entity.id for entity in many]
    assert kwargs["log_args"] == ["-y", "<4 Work Requirements>"]
