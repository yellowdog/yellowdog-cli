"""
Tests for Commander's Add to button: 'yd-submit --add-to' against a Work
Requirement chosen from a list. The listing is stubbed at _capture_json and the
command at _run_command_in_subprocess; the chooser is the real dialog, driven
inside its real modal loop.
"""

import pytest
import qt_guard

qt_guard.require_qt()

import commander_dialogs
import gui_harness
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication

from yellowdog_cli.commander.commander import YellowDogApp
from yellowdog_cli.commander.output_model import OutputRun
from yellowdog_cli.commander.selection import newest_entity_id
from yellowdog_cli.commander.startup import StartupSettings
from yellowdog_cli.commander.window_base import NO_LISTING_TAG

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
CANCELLING = {
    "id": "ydid:workreq:3",
    "name": "wr-cancelling",
    "status": "CANCELLING",
    "createdTime": "2026-09-29T11:00:00.000000+00:00",
}


@pytest.fixture
def window(qapp):
    window = YellowDogApp()
    window._discovery.tag = "pwt"
    return window


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


def test_lists_the_active_work_requirements(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [])
    window._add_to_work_requirement_action()
    assert asked == [
        ("yd-list", ["--json"], ["work-requirements", "--active-only", "-t", "pwt"])
    ]


def test_the_tag_field_overrides_the_discovered_tag(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [])
    window.tag_override.setPlainText("other")
    window._add_to_work_requirement_action()
    assert asked[0][2][-2:] == ["-t", "other"]


def test_without_a_tag_nothing_is_listed(window, captured, monkeypatch):
    # 'yd-list' defaults its tag to '', so a listing without one would offer
    # every Work Requirement in the namespace under a dialog naming the tag.
    asked = listed(window, monkeypatch, [OLDER])
    window._discovery.tag = None
    window._add_to_work_requirement_action()
    assert asked == [] and captured == []
    assert NO_LISTING_TAG in log(window)


def test_the_name_pattern_narrows_the_listing(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [])
    window.name_glob_override.setPlainText("wr-*")
    window._add_to_work_requirement_action()
    assert asked[0][2] == ["work-requirements", "--active-only", "--name", "wr-*"]
    assert "matching name pattern 'wr-*'" in log(window)


# --- Choosing and submitting -------------------------------------------------


def test_the_newest_is_chosen_by_default(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER, NEWER])
    commander_dialogs.drive_single_choice(window, monkeypatch, commander_dialogs.ACCEPT)
    window._add_to_work_requirement_action()
    assert captured == [("yd-submit", ["-A", NEWER["id"], "-f"])]


def test_the_row_chosen_is_the_target(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER, NEWER])
    commander_dialogs.drive_single_choice(
        window, monkeypatch, commander_dialogs.ACCEPT, choose=0
    )
    window._add_to_work_requirement_action()
    assert captured == [("yd-submit", ["-A", OLDER["id"], "-f"])]


def test_the_submit_settings_are_carried_over(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER])
    window._wr_file = "/abs/wr.json"
    window.dry_run.setChecked(True)
    window.wr_submit_options.setPlainText("--foo bar")
    commander_dialogs.drive_single_choice(window, monkeypatch, commander_dialogs.ACCEPT)
    window._add_to_work_requirement_action()
    assert captured == [
        ("yd-submit", ["-A", OLDER["id"], "-r", "/abs/wr.json", "-D", "--foo", "bar"])
    ]


def test_cancelling_the_chooser_submits_nothing(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER, NEWER])
    commander_dialogs.drive_single_choice(window, monkeypatch, commander_dialogs.CANCEL)
    window._add_to_work_requirement_action()
    assert captured == []


def test_rows_show_name_and_status_with_the_ydid_in_the_tooltip(
    window, captured, monkeypatch
):
    listed(window, monkeypatch, [OLDER, NEWER])
    seen: dict = {}

    def inspect(dialog):
        rows = commander_dialogs.choice_listing(dialog)
        seen["text"] = [rows.item(i).text() for i in range(rows.count())]
        seen["tooltip"] = rows.item(0).toolTip()

    commander_dialogs.drive_single_choice(
        window, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )
    window._add_to_work_requirement_action()
    assert seen["text"] == ["wr-older  RUNNING", "wr-newer  HELD"]
    assert OLDER["id"] in seen["tooltip"]


def test_add_is_disabled_while_nothing_is_selected(window, captured, monkeypatch):
    listed(window, monkeypatch, [OLDER, NEWER])
    states: list[bool] = []

    def inspect(dialog):
        add = gui_harness.button_labelled(dialog, "Add")
        states.append(add.isEnabled())
        commander_dialogs.choice_listing(dialog).clearSelection()
        states.append(add.isEnabled())

    commander_dialogs.drive_single_choice(
        window, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )
    window._add_to_work_requirement_action()
    assert states == [True, False]


def test_double_clicking_a_row_accepts_it(window, captured, monkeypatch):
    # The offscreen platform delivers no double-click to an item view, so emit
    # the signal the click would, which is the wiring under test.
    listed(window, monkeypatch, [OLDER, NEWER])

    def inspect(dialog):
        rows = commander_dialogs.choice_listing(dialog)
        rows.setCurrentRow(0)
        rows.itemDoubleClicked.emit(rows.item(0))

    commander_dialogs.drive_single_choice(
        window, monkeypatch, commander_dialogs.NOTHING, inspect=inspect
    )
    window._add_to_work_requirement_action()
    assert captured == [("yd-submit", ["-A", OLDER["id"], "-f"])]


# --- Refusing rather than guessing -------------------------------------------


def test_a_failed_listing_submits_nothing(window, captured, monkeypatch):
    # Unlike the destructive actions, there is no scope to fall back to: a plain
    # submission would create a Work Requirement nobody asked for.
    listed(window, monkeypatch, None)
    window._add_to_work_requirement_action()
    assert captured == []
    assert "Could not list the Work Requirements to add to" in log(window)


def test_rows_without_ydids_submit_nothing(window, captured, monkeypatch):
    listed(window, monkeypatch, [{"name": "wr-no-id", "status": "RUNNING"}])
    window._add_to_work_requirement_action()
    assert captured == []
    assert "Could not list the Work Requirements to add to" in log(window)


def test_nothing_to_add_to_is_a_log_line(window, captured, monkeypatch):
    listed(window, monkeypatch, [])
    shown = commander_dialogs.drive_notice(window, monkeypatch)
    window._add_to_work_requirement_action()
    assert captured == []
    assert shown["count"] == 0
    assert "No active Work Requirements" in log(window)


def test_a_cancelling_work_requirement_is_not_offered(window, captured, monkeypatch):
    listed(window, monkeypatch, [CANCELLING])
    window._add_to_work_requirement_action()
    assert captured == []
    assert "No active Work Requirements" in log(window)


def test_the_newest_default_skips_a_cancelling_one(window, captured, monkeypatch):
    # The newest overall is CANCELLING and not listed, so the default falls back
    # to the first row offered rather than to nothing.
    listed(window, monkeypatch, [OLDER, CANCELLING])
    commander_dialogs.drive_single_choice(window, monkeypatch, commander_dialogs.ACCEPT)
    window._add_to_work_requirement_action()
    assert captured == [("yd-submit", ["-A", OLDER["id"], "-f"])]


def test_an_operation_in_flight_refuses(window, captured, monkeypatch):
    asked = listed(window, monkeypatch, [OLDER])
    window._nested_depth = 1
    window._add_to_work_requirement_action()
    assert asked == [] and captured == []
    assert "ignoring Add to Work Requirement" in log(window)


# --- A Work Requirement already followed ------------------------------------

# As the Platform writes them, which is what a run's output is scanned for
FOLLOWED = {
    "id": "ydid:workreq:000000:00000000-0000-0000-0000-000000000001",
    "name": "wr-followed",
    "status": "RUNNING",
    "createdTime": "2026-09-29T10:00:00.000000+00:00",
}
FOLLOWED_TASK = "ydid:task:000000:00000000-0000-0000-0000-000000000001:1:1"


def started(window, command: str, arguments: list[str]) -> OutputRun:
    """
    Register a command as Commander does when it starts one; still running.
    """
    return window._output.start_run(
        command, " ".join([command, *arguments]), "", arguments=arguments
    )


def test_a_submit_following_it_is_not_followed_again(window, captured, monkeypatch):
    # The Submit that created it printed its YDID, and is following it
    run = started(window, "yd-submit", ["-r", "/abs/wr.json", "-f"])
    window._output._log_lines([f"YellowDog ID is '{FOLLOWED['id']}'"], run)
    listed(window, monkeypatch, [FOLLOWED])
    commander_dialogs.drive_single_choice(window, monkeypatch, commander_dialogs.ACCEPT)
    window._add_to_work_requirement_action()
    assert captured == [("yd-submit", ["-A", FOLLOWED["id"]])]
    assert "Not following Work Requirement 'wr-followed' again" in log(window)
    assert f"{run.bar_subject} is following it already" in log(window)


def test_an_add_to_following_it_is_not_followed_again(window, captured, monkeypatch):
    started(window, "yd-submit", ["-A", FOLLOWED["id"], "-f"])
    listed(window, monkeypatch, [FOLLOWED])
    commander_dialogs.drive_single_choice(window, monkeypatch, commander_dialogs.ACCEPT)
    window._add_to_work_requirement_action()
    assert captured == [("yd-submit", ["-A", FOLLOWED["id"]])]


def test_a_yd_follow_of_it_counts(window, captured, monkeypatch):
    started(window, "yd-follow", [FOLLOWED["id"]])
    listed(window, monkeypatch, [FOLLOWED])
    commander_dialogs.drive_single_choice(window, monkeypatch, commander_dialogs.ACCEPT)
    window._add_to_work_requirement_action()
    assert captured == [("yd-submit", ["-A", FOLLOWED["id"]])]


@pytest.mark.parametrize(
    "arguments, finished",
    [
        (["-r", "/abs/wr.json", "-f"], True),  # its follow has ended
        (["-r", "/abs/wr.json"], False),  # never followed it
        (["-r", "/abs/wr.json", "-f", "-D"], False),  # a dry run follows nothing
    ],
    ids=["finished", "not-following", "dry-run"],
)
def test_otherwise_it_is_followed(window, captured, monkeypatch, arguments, finished):
    run = started(window, "yd-submit", arguments)
    window._output._log_lines([f"YellowDog ID is '{FOLLOWED['id']}'"], run)
    if finished:
        run.outcome = "exit 0"
    listed(window, monkeypatch, [FOLLOWED])
    commander_dialogs.drive_single_choice(window, monkeypatch, commander_dialogs.ACCEPT)
    window._add_to_work_requirement_action()
    assert captured == [("yd-submit", ["-A", FOLLOWED["id"], "-f"])]
    assert "Not following" not in log(window)


def test_another_work_requirement_followed_does_not_count(
    window, captured, monkeypatch
):
    started(window, "yd-submit", ["-A", OLDER["id"], "-f"])
    listed(window, monkeypatch, [FOLLOWED])
    commander_dialogs.drive_single_choice(window, monkeypatch, commander_dialogs.ACCEPT)
    window._add_to_work_requirement_action()
    assert captured == [("yd-submit", ["-A", FOLLOWED["id"], "-f"])]


def test_follow_in_the_extra_options_is_left_alone(window, captured, monkeypatch):
    # Follow Progress unticked: the user's own '--follow' is theirs to give
    started(window, "yd-submit", ["-A", FOLLOWED["id"], "-f"])
    window.follow_progress.setChecked(False)
    window.wr_submit_options.setPlainText("--follow")
    listed(window, monkeypatch, [FOLLOWED])
    commander_dialogs.drive_single_choice(window, monkeypatch, commander_dialogs.ACCEPT)
    window._add_to_work_requirement_action()
    assert captured == [("yd-submit", ["-A", FOLLOWED["id"], "--follow"])]


class TestFollowedWorkRequirements:
    """
    What a run is following: only a Work Requirement's YDID is noted from its
    output, a Task's (which carries the same UUID) is not, and the follow
    flags count only for a command that has them.
    """

    def test_only_work_requirement_ydids_are_noted(self):
        run = OutputRun(1, "yd-submit", arguments=("-f",))
        run.note_output(f"Added Task {FOLLOWED_TASK}")
        assert run.work_requirements_printed == set()
        run.note_output(f"... '{FOLLOWED['id']}' ...")
        assert run.work_requirements_printed == {FOLLOWED["id"]}

    @pytest.mark.parametrize(
        "command, arguments, follows",
        [
            ("yd-submit", ("-f",), True),
            ("yd-submit", ("--follow",), True),
            ("yd-submit", ("--progress",), True),
            ("yd-submit", ("-f", "--dry-run"), False),
            ("yd-submit", ("-fD",), False),  # a cluster is not read
            ("yd-follow", (), True),
            ("yd-list", ("-f",), False),  # no '--follow' to give
            ("ls", ("-f",), False),
        ],
    )
    def test_follows_events(self, command, arguments, follows):
        assert OutputRun(1, command, arguments=arguments).follows_events is follows


# --- '--yes' -----------------------------------------------------------------


@pytest.fixture
def unattended(qapp):
    window = YellowDogApp(StartupSettings(disable_confirmations=True))
    window._discovery.tag = "pwt"
    return window


def test_yes_adds_to_the_only_candidate(unattended, monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        unattended,
        "_run_command_in_subprocess",
        lambda command, args, **kwargs: calls.append((command, args)),
    )
    listed(unattended, monkeypatch, [OLDER])
    unattended._add_to_work_requirement_action()
    assert calls == [("yd-submit", ["-A", OLDER["id"], "-f"])]
    assert "adding to the only active Work Requirement" in log(unattended)


def test_yes_refuses_to_choose_between_several(unattended, monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        unattended,
        "_run_command_in_subprocess",
        lambda command, args, **kwargs: calls.append((command, args)),
    )
    listed(unattended, monkeypatch, [OLDER, NEWER])
    unattended._add_to_work_requirement_action()
    assert calls == []
    assert "no way to choose between them" in log(unattended)


# --- The newest ---------------------------------------------------------------


def test_newest_entity_id():
    assert newest_entity_id([OLDER, NEWER]) == NEWER["id"]
    assert newest_entity_id([NEWER, OLDER]) == NEWER["id"]
    assert newest_entity_id([{"id": "x"}]) is None
    assert newest_entity_id([]) is None


# --- Layout ------------------------------------------------------------------


def test_add_to_sits_beside_submit(qapp):
    win = gui_harness.shown(YellowDogApp())
    QApplication.processEvents()
    submit = win.submit_work_requirement.mapTo(win, QPoint(0, 0))
    add_to = win.add_to_work_requirement.mapTo(win, QPoint(0, 0))
    assert add_to.y() == submit.y()
    assert win.add_to_work_requirement.height() == win.submit_work_requirement.height()
    assert add_to.x() > submit.x()


def test_neither_button_in_the_submit_row_is_squeezed(qapp):
    # The pair is wider than any other button in the left column, so it is what
    # sets the column's width. A window opened narrower than its layout asks for
    # would squeeze one of them below its label instead.
    win = gui_harness.shown(YellowDogApp())
    QApplication.processEvents()
    for button in (win.submit_work_requirement, win.add_to_work_requirement):
        assert button.width() >= button.sizeHint().width(), button.objectName()


def test_a_long_name_does_not_elide_the_status(window, captured, monkeypatch):
    long_name = dict(OLDER, name="wr-" + "x" * 60)
    listed(window, monkeypatch, [long_name, NEWER])
    fits: list[bool] = []

    def inspect(dialog):
        rows = commander_dialogs.choice_listing(dialog)
        fits.append(rows.viewport().width() >= rows.sizeHintForColumn(0))

    commander_dialogs.drive_single_choice(
        window, monkeypatch, commander_dialogs.CANCEL, inspect=inspect
    )
    window._add_to_work_requirement_action()
    assert fits == [True]
