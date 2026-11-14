"""
Tests for Commander's Resubmit Failed Tasks button: 'yd workrequirement
resubmit' of a Work Requirement chosen from a list. The listing is stubbed at
_capture_json and the command at _run_command_in_subprocess; the chooser is the
real dialog, driven inside its real modal loop.
"""

import pytest
import qt_guard

qt_guard.require_qt()

import commander_dialogs

from yellowdog_cli.commander.commander import YellowDogApp
from yellowdog_cli.commander.selection import all_tasks_completed
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
    window._resubmit_failed_tasks_action()
    assert asked == [("yd list", ["--json"], ["work-requirements", "-t", "alice"])]


def test_the_name_pattern_narrows_the_listing(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [])
    window.name_glob_override.setPlainText("wr-*")
    window._resubmit_failed_tasks_action()
    assert asked[0][2] == ["work-requirements", "--name", "wr-*"]


def test_without_a_tag_nothing_is_listed(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [OLDER])
    window._discovery.tag = None
    window._resubmit_failed_tasks_action()
    assert asked == [] and captured == []
    assert NO_LISTING_TAG in log(window)


def test_one_whose_tasks_all_completed_is_not_offered(window, captured, monkeypatch):
    listed(window, monkeypatch, [ALL_COMPLETED])
    window._resubmit_failed_tasks_action()
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
    commander_dialogs.drive_single_choice(window, monkeypatch, commander_dialogs.ACCEPT)
    window._resubmit_failed_tasks_action()
    assert captured == [(COMMAND, [NEWER["id"], "-f"])]


def test_the_row_chosen_is_resubmitted(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER, NEWER, ALL_COMPLETED])
    commander_dialogs.drive_single_choice(
        window, monkeypatch, commander_dialogs.ACCEPT, choose=0
    )
    window._resubmit_failed_tasks_action()
    assert captured == [(COMMAND, [OLDER["id"], "-f"])]


def test_dry_run_is_carried_over_and_extra_options_are_not(
    window, captured, monkeypatch
):
    listed(window, monkeypatch, [OLDER])
    window.dry_run.setChecked(True)
    window.wr_submit_options.setPlainText("--foo bar")
    commander_dialogs.drive_single_choice(window, monkeypatch, commander_dialogs.ACCEPT)
    window._resubmit_failed_tasks_action()
    assert captured == [(COMMAND, [OLDER["id"], "-D"])]


def test_without_follow_progress_nothing_is_followed(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER])
    window.follow_progress.setChecked(False)
    commander_dialogs.drive_single_choice(window, monkeypatch, commander_dialogs.ACCEPT)
    window._resubmit_failed_tasks_action()
    assert captured == [(COMMAND, [OLDER["id"]])]


def test_cancelling_the_chooser_resubmits_nothing(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER, NEWER])
    commander_dialogs.drive_single_choice(window, monkeypatch, commander_dialogs.CANCEL)
    window._resubmit_failed_tasks_action()
    assert captured == []


# --- Refusing rather than guessing -------------------------------------------


def test_a_failed_listing_resubmits_nothing(window, captured, monkeypatch):
    listed(window, monkeypatch, None)
    window._resubmit_failed_tasks_action()
    assert captured == []
    assert "Could not list the Work Requirements to resubmit from" in log(window)


def test_rows_without_ydids_resubmit_nothing(window, captured, monkeypatch):
    listed(window, monkeypatch, [{"name": "wr-no-id", "status": "FAILED"}])
    window._resubmit_failed_tasks_action()
    assert captured == []
    assert "Could not list the Work Requirements to resubmit from" in log(window)


def test_an_operation_in_flight_refuses(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [OLDER])
    window._nested_depth = 1
    window._resubmit_failed_tasks_action()
    assert asked == [] and captured == []


def test_an_unbalanced_properties_field_refuses(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [OLDER])
    window.properties.setPlainText("workRequirement.name='unclosed")
    window._resubmit_failed_tasks_action()
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
    unattended._resubmit_failed_tasks_action()
    assert unattended_calls == [(COMMAND, [OLDER["id"], "-f"])]
    assert "resubmitting from the only Work Requirement" in log(unattended)


def test_yes_refuses_to_choose_between_several(
    unattended, unattended_calls, monkeypatch
):
    listed(unattended, monkeypatch, [OLDER, NEWER])
    unattended._resubmit_failed_tasks_action()
    assert unattended_calls == []
    assert "nothing resubmitted" in log(unattended)
