"""
Tests for Commander's Resubmit Tasks button: 'yd workrequirement resubmit' of
a Work Requirement chosen from a list, with the Task statuses ticked in the
same dialog. The listing is stubbed at _capture_json and the command at
_run_command_in_subprocess; the dialog is the real one, driven inside its real
modal loop.
"""

import pytest
import qt_guard

qt_guard.require_qt()

import commander_dialogs
import gui_harness

from yellowdog_cli.commander.commander import YellowDogApp
from yellowdog_cli.commander.selection import (
    all_tasks_completed,
    entity_rows,
    parse_entity_summaries,
)
from yellowdog_cli.commander.startup import StartupSettings
from yellowdog_cli.commander.window_base import NO_LISTING_TAG

COMMAND = "yd workrequirement resubmit"

OLDER = {
    "id": "ydid:workreq:1",
    "name": "wr-older",
    "status": "FAILED",
    "completedTaskCount": 8,
    "totalTaskCount": 10,
    "createdTime": "2026-09-28T10:00:00.000000+00:00",
}
NEWER = {
    "id": "ydid:workreq:2",
    "name": "wr-newer",
    "status": "RUNNING",
    "completedTaskCount": 3,
    "totalTaskCount": 10,
    "createdTime": "2026-09-29T10:00:00.000000+00:00",
}
ALL_COMPLETED = {
    "id": "ydid:workreq:3",
    "name": "wr-done",
    "status": "COMPLETED",
    "completedTaskCount": 10,
    "totalTaskCount": 10,
    "createdTime": "2026-09-29T11:00:00.000000+00:00",
}


@pytest.fixture
def window(qapp):
    window = YellowDogApp()
    window._discovery.tag = "alice"
    yield window
    window.shutdown()
    window.close()


@pytest.fixture
def captured(window, monkeypatch):
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        window,
        "_run_command_in_subprocess",
        lambda command, args, **kwargs: calls.append((command, args)),
    )
    return calls


def listed(window, monkeypatch, rows) -> list:
    """
    Stub the listing to return 'rows'; returns the listings asked for.
    """
    asked: list = []

    def capture(command, flags, extra_args=None):
        asked.append((command, flags, extra_args))
        return rows

    monkeypatch.setattr(window, "_capture_json", capture)
    return asked


def log(window) -> str:
    return window.log_output.toPlainText()


# --- The listing -------------------------------------------------------------


def test_lists_work_requirements_in_any_status(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [])
    window._resubmit_tasks_action()
    assert asked == [("yd list", ["--json"], ["work-requirements", "-t", "alice"])]


def test_the_name_pattern_narrows_the_listing(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [])
    window.name_glob_override.setPlainText("wr-*")
    window._resubmit_tasks_action()
    assert asked[0][2] == ["work-requirements", "--name", "wr-*"]


def test_without_a_tag_nothing_is_listed(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [OLDER])
    window._discovery.tag = None
    window._resubmit_tasks_action()
    assert asked == [] and captured == []
    assert NO_LISTING_TAG in log(window)


def test_one_whose_tasks_all_completed_is_not_offered(window, captured, monkeypatch):
    listed(window, monkeypatch, [ALL_COMPLETED])
    window._resubmit_tasks_action()
    assert captured == []
    assert "No Work Requirements" in log(window)


@pytest.mark.parametrize(
    "row, completed",
    [
        ({"completedTaskCount": 10, "totalTaskCount": 10}, True),
        ({"completedTaskCount": 9, "totalTaskCount": 10}, False),
        ({"completedTaskCount": 0, "totalTaskCount": 0}, False),
        ({"totalTaskCount": 10}, False),  # cannot say, so offered
        ({}, False),
    ],
)
def test_all_tasks_completed(row, completed):
    assert all_tasks_completed(row) is completed


# --- Choosing and resubmitting -----------------------------------------------


def test_the_newest_is_chosen_by_default(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER, NEWER])
    commander_dialogs.drive_resubmit(window, monkeypatch, commander_dialogs.ACCEPT)
    window._resubmit_tasks_action()
    assert captured == [(COMMAND, [NEWER["id"], "--failed", "-f"])]


def test_the_row_chosen_is_resubmitted(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER, NEWER, ALL_COMPLETED])
    commander_dialogs.drive_resubmit(
        window, monkeypatch, commander_dialogs.ACCEPT, choose=0
    )
    window._resubmit_tasks_action()
    assert captured == [(COMMAND, [OLDER["id"], "--failed", "-f"])]


def test_dry_run_is_carried_over_and_extra_options_are_not(
    window, captured, monkeypatch
):
    listed(window, monkeypatch, [OLDER])
    window.dry_run.setChecked(True)
    window.wr_submit_options.setPlainText("--foo bar")
    commander_dialogs.drive_resubmit(window, monkeypatch, commander_dialogs.ACCEPT)
    window._resubmit_tasks_action()
    assert captured == [(COMMAND, [OLDER["id"], "--failed", "-D"])]


def test_without_follow_progress_nothing_is_followed(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER])
    window.follow_progress.setChecked(False)
    commander_dialogs.drive_resubmit(window, monkeypatch, commander_dialogs.ACCEPT)
    window._resubmit_tasks_action()
    assert captured == [(COMMAND, [OLDER["id"], "--failed"])]


def test_cancelling_the_chooser_resubmits_nothing(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER, NEWER])
    commander_dialogs.drive_resubmit(window, monkeypatch, commander_dialogs.CANCEL)
    window._resubmit_tasks_action()
    assert captured == []


# --- The statuses ------------------------------------------------------------


def test_failed_alone_is_ticked_at_first(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER])
    ticked: dict = {}

    def inspect(dialog):
        for status in ("FAILED", "ABORTED", "CANCELLED"):
            box = commander_dialogs.resubmit_status_box(dialog, status)
            ticked[status] = box.isChecked()

    commander_dialogs.drive_resubmit(
        window, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )
    window._resubmit_tasks_action()
    assert ticked == {"FAILED": True, "ABORTED": False, "CANCELLED": False}


def test_the_statuses_ticked_are_passed_in_order(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER])
    commander_dialogs.drive_resubmit(
        window,
        monkeypatch,
        commander_dialogs.ACCEPT,
        statuses={"CANCELLED", "FAILED", "ABORTED"},
    )
    window._resubmit_tasks_action()
    assert captured == [
        (COMMAND, [OLDER["id"], "--failed", "--aborted", "--cancelled", "-f"])
    ]


def test_cancelled_alone(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER])
    commander_dialogs.drive_resubmit(
        window, monkeypatch, commander_dialogs.ACCEPT, statuses={"CANCELLED"}
    )
    window._resubmit_tasks_action()
    assert captured == [(COMMAND, [OLDER["id"], "--cancelled", "-f"])]


def test_resubmit_is_greyed_with_no_status_ticked(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER])
    states: list[bool] = []

    def inspect(dialog):
        resubmit = gui_harness.button_labelled(dialog, "Resubmit")
        states.append(resubmit.isEnabled())
        commander_dialogs.resubmit_status_box(dialog, "FAILED").setChecked(False)
        states.append(resubmit.isEnabled())
        commander_dialogs.resubmit_status_box(dialog, "ABORTED").setChecked(True)
        states.append(resubmit.isEnabled())

    commander_dialogs.drive_resubmit(
        window, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )
    window._resubmit_tasks_action()
    assert states == [True, False, True]


def test_resubmit_is_greyed_with_no_row_selected(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER, NEWER])
    states: list[bool] = []

    def inspect(dialog):
        resubmit = gui_harness.button_labelled(dialog, "Resubmit")
        commander_dialogs.choice_listing(dialog).clearSelection()
        states.append(resubmit.isEnabled())

    commander_dialogs.drive_resubmit(
        window, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )
    window._resubmit_tasks_action()
    assert states == [False]


def test_double_clicking_with_no_status_ticked_does_not_accept(
    window, captured, monkeypatch
):
    # The offscreen platform delivers no double-click to an item view, so emit
    # the signal the click would
    listed(window, monkeypatch, [OLDER])

    def inspect(dialog):
        rows = commander_dialogs.choice_listing(dialog)
        rows.itemDoubleClicked.emit(rows.item(0))

    commander_dialogs.drive_resubmit(
        window,
        monkeypatch,
        commander_dialogs.CANCEL,
        statuses=set(),
        inspect=inspect,
    )
    window._resubmit_tasks_action()
    assert captured == []


def test_double_clicking_a_row_accepts_it(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER, NEWER])

    def inspect(dialog):
        rows = commander_dialogs.choice_listing(dialog)
        rows.setCurrentRow(0)
        rows.itemDoubleClicked.emit(rows.item(0))

    commander_dialogs.drive_resubmit(
        window, monkeypatch, commander_dialogs.NOTHING, inspect=inspect
    )
    window._resubmit_tasks_action()
    assert captured == [(COMMAND, [OLDER["id"], "--failed", "-f"])]


def test_the_statuses_are_remembered_for_the_session(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER])
    commander_dialogs.drive_resubmit(
        window,
        monkeypatch,
        commander_dialogs.ACCEPT,
        statuses={"ABORTED", "CANCELLED"},
    )
    window._resubmit_tasks_action()
    assert window._resubmit_statuses == ("ABORTED", "CANCELLED")
    # The next dialog, built unpatched (the driver above still wraps the
    # window's builder), opens ticked as the last was left
    dialog, _button = type(window)._build_resubmit_dialog(
        window, "message", entity_rows([parse_entity_summaries([OLDER])[0]])
    )
    try:
        ticked = {
            status: commander_dialogs.resubmit_status_box(dialog, status).isChecked()
            for status in ("FAILED", "ABORTED", "CANCELLED")
        }
    finally:
        dialog.deleteLater()
    assert ticked == {"FAILED": False, "ABORTED": True, "CANCELLED": True}


def test_a_cancelled_dialog_does_not_change_the_statuses(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER])
    commander_dialogs.drive_resubmit(
        window, monkeypatch, commander_dialogs.CANCEL, statuses={"CANCELLED"}
    )
    window._resubmit_tasks_action()
    assert window._resubmit_statuses == ("FAILED",)


def test_a_new_window_starts_with_failed_alone(qapp, monkeypatch):
    first = YellowDogApp()
    first._resubmit_statuses = ("CANCELLED",)
    second = YellowDogApp()
    try:
        assert second._resubmit_statuses == ("FAILED",)
    finally:
        for window in (first, second):
            window.shutdown()
            window.close()


# --- Refusing rather than guessing -------------------------------------------


def test_a_failed_listing_resubmits_nothing(window, captured, monkeypatch):
    listed(window, monkeypatch, None)
    window._resubmit_tasks_action()
    assert captured == []
    assert "Could not list the Work Requirements to resubmit from" in log(window)


def test_rows_without_ydids_resubmit_nothing(window, captured, monkeypatch):
    listed(window, monkeypatch, [{"name": "wr-no-id", "status": "FAILED"}])
    window._resubmit_tasks_action()
    assert captured == []
    assert "Could not list the Work Requirements to resubmit from" in log(window)


def test_an_operation_in_flight_refuses(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [OLDER])
    window._nested_depth = 1
    window._resubmit_tasks_action()
    assert asked == [] and captured == []


def test_an_unbalanced_properties_field_refuses(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [OLDER])
    window.properties.setPlainText("workRequirement.name='unclosed")
    window._resubmit_tasks_action()
    assert asked == [] and captured == []


# --- '--yes' -----------------------------------------------------------------


@pytest.fixture
def unattended(qapp):
    window = YellowDogApp(StartupSettings(disable_confirmations=True))
    window._discovery.tag = "alice"
    yield window
    window.shutdown()
    window.close()


@pytest.fixture
def unattended_calls(unattended, monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        unattended,
        "_run_command_in_subprocess",
        lambda command, args, **kwargs: calls.append((command, args)),
    )
    return calls


def test_yes_resubmits_from_the_only_candidate(
    unattended, unattended_calls, monkeypatch
):
    listed(unattended, monkeypatch, [OLDER, ALL_COMPLETED])
    unattended._resubmit_tasks_action()
    assert unattended_calls == [(COMMAND, [OLDER["id"], "--failed", "-f"])]
    assert "resubmitting the FAILED Tasks of the only Work Requirement" in log(
        unattended
    )


def test_yes_refuses_to_choose_between_several(
    unattended, unattended_calls, monkeypatch
):
    listed(unattended, monkeypatch, [OLDER, NEWER])
    unattended._resubmit_tasks_action()
    assert unattended_calls == []
    assert "nothing resubmitted" in log(unattended)
