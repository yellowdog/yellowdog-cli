"""
Unit tests for the Commander CommandHistory helper (pure Python; no Qt event
loop). Guards the command-recall pointer logic against off-by-one regressions.
"""

import qt_guard

qt_guard.require_qt()  # commander imports QtWidgets at module top

from yellowdog_cli.commander.commander import CommandHistory


def test_empty_history_returns_none():
    h = CommandHistory()
    assert h.step_back() is None
    assert h.step_forward() is None


def test_consecutive_duplicates_are_not_stored():
    h = CommandHistory()
    h.save_command("a")
    h.save_command("a")
    assert h._commands == ["a"]


def test_non_consecutive_duplicates_are_stored():
    h = CommandHistory()
    h.save_command("a")
    h.save_command("b")
    h.save_command("a")
    assert h._commands == ["a", "b", "a"]


def test_max_size_evicts_oldest():
    h = CommandHistory(max_size=2)
    h.save_command("a")
    h.save_command("b")
    h.save_command("c")
    assert h._commands == ["b", "c"]


def test_step_back_walks_to_start_and_stays():
    h = CommandHistory()
    for cmd in ("a", "b", "c"):
        h.save_command(cmd)
    # Pointer starts at the most-recent command.
    assert h.step_back() == "b"
    assert h.step_back() == "a"
    assert h.step_back() == "a"  # stays at the start


def test_step_forward_at_end_returns_empty_then_step_back_returns_last():
    h = CommandHistory()
    for cmd in ("a", "b", "c"):
        h.save_command(cmd)
    # Already at the end (most-recent) -> forward yields the empty entry.
    assert h.step_forward() == ""
    # After the empty entry, stepping back returns the most-recent command.
    assert h.step_back() == "c"


def test_forward_after_stepping_back():
    h = CommandHistory()
    for cmd in ("a", "b", "c"):
        h.save_command(cmd)
    h.step_back()  # -> "b"
    h.step_back()  # -> "a"
    assert h.step_forward() == "b"
    assert h.step_forward() == "c"
