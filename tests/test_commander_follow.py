"""
Tests for Commander's Follow… button: 'yd workrequirement follow' of an active
Work Requirement chosen from a list. The listing is stubbed at _capture_json
and the command at _run_command_in_subprocess; the chooser is the real dialog,
driven inside its real modal loop.
"""

import pytest
import qt_guard

qt_guard.require_qt()

import commander_dialogs

from yellowdog_cli.commander.commander import YellowDogApp
from yellowdog_cli.commander.output_model import OutputRun
from yellowdog_cli.commander.startup import StartupSettings
from yellowdog_cli.commander.window_base import NO_LISTING_TAG

COMMAND = "yd workrequirement follow"

OLDER = {
    "id": "ydid:workreq:1",
    "name": "wr-older",
    "status": "RUNNING",
    "createdTime": "2026-09-28T10:00:00.000000+00:00",
}
NEWER = {
    "id": "ydid:workreq:2",
    "name": "wr-newer",
    "status": "HELD",
    "createdTime": "2026-09-29T10:00:00.000000+00:00",
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
    asked: list = []

    def capture(command, flags, extra_args=None):
        asked.append((command, flags, extra_args))
        return rows

    monkeypatch.setattr(window, "_capture_json", capture)
    return asked


def log(window) -> str:
    return window.log_output.toPlainText()


def test_lists_the_active_work_requirements(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [])
    window._follow_work_requirement_action()
    assert asked == [
        ("yd list", ["--json"], ["work-requirements", "--active-only", "-t", "alice"])
    ]


def test_the_name_pattern_narrows_the_listing(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [])
    window.name_glob_override.setPlainText("wr-*")
    window._follow_work_requirement_action()
    assert asked[0][2] == ["work-requirements", "--active-only", "--name", "wr-*"]


def test_without_a_tag_nothing_is_listed(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [OLDER])
    window._discovery.tag = None
    window._follow_work_requirement_action()
    assert asked == [] and captured == []
    assert NO_LISTING_TAG in log(window)


def test_the_newest_is_chosen_by_default(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER, NEWER])
    commander_dialogs.drive_single_choice(window, monkeypatch, commander_dialogs.ACCEPT)
    window._follow_work_requirement_action()
    assert captured == [(COMMAND, [NEWER["id"]])]


def test_the_row_chosen_is_followed(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER, NEWER])
    commander_dialogs.drive_single_choice(
        window, monkeypatch, commander_dialogs.ACCEPT, choose=0
    )
    window._follow_work_requirement_action()
    assert captured == [(COMMAND, [OLDER["id"]])]


def test_cancelling_the_chooser_follows_nothing(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER, NEWER])
    commander_dialogs.drive_single_choice(window, monkeypatch, commander_dialogs.CANCEL)
    window._follow_work_requirement_action()
    assert captured == []


def test_one_followed_already_is_not_followed_again(window, captured, monkeypatch):
    # A second stream would show every event twice
    listed(window, monkeypatch, [OLDER])
    following = OutputRun(
        7, "yd workrequirement follow", pid=4242, arguments=(OLDER["id"],)
    )
    window._output._output_runs[following.run_id] = following
    commander_dialogs.drive_single_choice(window, monkeypatch, commander_dialogs.ACCEPT)
    window._follow_work_requirement_action()
    assert captured == []
    assert "Not following Work Requirement 'wr-older' again" in log(window)


def test_nothing_active_is_a_log_line(window, captured, monkeypatch):
    listed(window, monkeypatch, [])
    window._follow_work_requirement_action()
    assert captured == []
    assert "No active Work Requirements" in log(window)


def test_a_failed_listing_follows_nothing(window, captured, monkeypatch):
    listed(window, monkeypatch, None)
    window._follow_work_requirement_action()
    assert captured == []
    assert "Could not list the Work Requirements to follow" in log(window)


def test_rows_without_ydids_follow_nothing(window, captured, monkeypatch):
    listed(window, monkeypatch, [{"name": "wr-no-id", "status": "RUNNING"}])
    window._follow_work_requirement_action()
    assert captured == []


def test_an_operation_in_flight_refuses(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [OLDER])
    window._nested_depth = 1
    window._follow_work_requirement_action()
    assert asked == [] and captured == []


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


def test_yes_follows_the_only_candidate(unattended, unattended_calls, monkeypatch):
    listed(unattended, monkeypatch, [OLDER])
    unattended._follow_work_requirement_action()
    assert unattended_calls == [(COMMAND, [OLDER["id"]])]


def test_yes_refuses_to_choose_between_several(
    unattended, unattended_calls, monkeypatch
):
    listed(unattended, monkeypatch, [OLDER, NEWER])
    unattended._follow_work_requirement_action()
    assert unattended_calls == []
    assert "nothing followed" in log(unattended)
