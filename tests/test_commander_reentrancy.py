"""
Tests for the re-entrancy guard on Commander's enumerating actions.

Every one of these actions enumerates in a nested Qt event loop before it acts,
and a nested loop keeps the main window interactive — so without a guard a second
action could be started while the first was still listing what it would affect.
The dangerous case is a destructive one: a re-entrant enumeration returning None
would be read as 'enumeration failed', which means falling back to acting over the
whole scope.
"""

import pytest
import qt_guard

qt_guard.require_qt()

from yellowdog_cli.commander.commander import (
    Confirmation,
    EntitySummary,
    ObjectSummary,
    YellowDogApp,
)

ACTIONS = [
    ("_cancel_work_requirements_action", "Cancel Work Requirements"),
    (
        "_cancel_work_requirements_and_abort_action",
        "Cancel and Abort Work Requirements",
    ),
    ("_shutdown_all_worker_pools_action", "Shut Down Worker Pools"),
    ("_terminate_all_compute_requirements_action", "Terminate Compute Requirements"),
    ("_download_results_action", "Download Matching Objects"),
    ("_delete_objects_action", "Delete Matching Objects"),
]


@pytest.fixture
def window(qapp):
    return YellowDogApp()


@pytest.fixture
def captured(window, monkeypatch):
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        window,
        "_run_command_in_subprocess",
        lambda command, args, **kwargs: calls.append((command, args)),
    )
    return calls


@pytest.mark.parametrize("method,action_name", ACTIONS)
def test_no_action_starts_while_a_nested_loop_is_blocking(
    window, captured, monkeypatch, method, action_name
):
    def fail(*args, **kwargs):
        raise AssertionError(f"{method} must not enumerate while one is in flight")

    monkeypatch.setattr(window, "_capture_dry_run_summaries", fail)
    monkeypatch.setattr(window, "_capture_dry_run_objects", fail)
    monkeypatch.setattr(window, "_capture_dry_run_json", fail)
    window._nested_depth = 1  # as _run_nested holds it
    window._tag = "pyex"
    window.log_output.setPlainText("")

    getattr(window, method)()

    assert captured == []
    assert f"Another operation is still in progress; ignoring {action_name}" in (
        window.log_output.toPlainText()
    )


def test_a_second_destructive_action_during_an_enumeration_is_refused(
    window, captured, monkeypatch
):
    # The composed scenario: while the cancel enumeration blocks, the user manages
    # to trigger terminate. Only the outer action may reach a command.
    entity = EntitySummary(id="ydid:workreq:1", name="wr", status="RUNNING")
    inner_ran: list[str] = []

    def enumerate_then_reenter(command, extra_args=None):
        # mimic _run_nested holding the depth for as long as it blocks
        window._nested_depth += 1
        try:
            window._terminate_all_compute_requirements_action()
            inner_ran.append("returned")
        finally:
            window._nested_depth -= 1
        return [entity]

    monkeypatch.setattr(window, "_capture_dry_run_summaries", enumerate_then_reenter)
    monkeypatch.setattr(
        window,
        "_confirm_destructive",
        lambda *a, **k: Confirmation(proceed=True, handles=[entity.id]),
    )

    window._cancel_work_requirements_action()

    assert inner_ran == ["returned"]  # the inner call returned, it did not raise
    assert captured == [("yd-cancel", ["-y", "ydid:workreq:1"])]
    assert "ignoring Terminate Compute Requirements" in window.log_output.toPlainText()


def test_the_depth_is_a_counter_not_a_flag(window):
    # Nested loops really do nest. The config parse deferred at construction with
    # singleShot(0) runs in the first event loop to spin, which can be one an
    # enumeration has already entered — driving the real _run_nested once was
    # observed reaching depth 2. A flag cleared when the inner parse finished
    # would unlock the window while the outer loop was still blocking, so the
    # guard must stay closed until the depth is back to zero.
    window._nested_depth = 2
    window._nested_depth -= 1  # inner loop finishes
    assert window._operation_in_flight("X") is True
    window._nested_depth -= 1  # outer loop finishes
    assert window._operation_in_flight("X") is False


def test_the_action_buttons_are_greyed_and_restored(window):
    buttons = window._action_buttons()
    assert len(buttons) == 6
    assert all(b.isEnabled() for b in buttons)

    window._set_action_buttons_enabled(False)
    assert not any(b.isEnabled() for b in buttons)

    window._set_action_buttons_enabled(True)
    assert all(b.isEnabled() for b in buttons)


def test_submit_and_provision_are_not_blocked(window, captured, monkeypatch):
    # They launch a command and return, with no nested loop and no pre-flight
    # listing to be confused by a second click, so the guard must leave them alone.
    window._nested_depth = 1
    window._submit_work_requirement_action()
    window._create_worker_pool_action()
    assert [command for command, _args in captured] == ["yd-submit", "yd-provision"]
    assert window.submit_work_requirement not in window._action_buttons()
    assert window.create_worker_pool not in window._action_buttons()


def test_the_guard_precedes_the_dry_run_shortcut(window, captured, monkeypatch):
    # Dry-run download/delete still launch a subprocess, so they must not slip past
    # the guard just because they skip the enumeration.
    window._nested_depth = 1
    window.dry_run_objects.setChecked(True)
    window._tag = "pyex"

    window._download_results_action()
    window._delete_objects_action()

    assert captured == []


def test_normal_operation_is_unaffected(window, captured, monkeypatch):
    # With no nested loop in flight, every action proceeds as before.
    objects = [ObjectSummary(path="S3:b/pfx/o", name="o", is_dir=False)]
    monkeypatch.setattr(
        window, "_capture_dry_run_objects", lambda command, extra_args: objects
    )
    monkeypatch.setattr(
        window,
        "_confirm_destructive",
        lambda *a, **k: Confirmation(proceed=True, handles=["S3:b/pfx/o"]),
    )
    window._tag = "pyex"

    window._delete_objects_action()

    assert captured == [("yd-delete", ["-Ry", "S3:b/pfx/o"])]
