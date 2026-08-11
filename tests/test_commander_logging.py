"""
Tests for how Commander echoes a command into its output window. A run that
targets many entities by YDID would otherwise print a wall of identifiers.
"""

import pytest
import qt_guard

qt_guard.require_qt()

from yellowdog_cli.commander.commander import (
    EntitySummary,
    YellowDogApp,
    command_line_text,
)


@pytest.fixture
def window(qapp):
    return YellowDogApp()


def summaries(count: int) -> list[EntitySummary]:
    return [
        EntitySummary(id=f"ydid:workreq:{n}", name=f"wr-{n}", status="RUNNING")
        for n in range(count)
    ]


def test_command_line_text_joins_command_and_args():
    assert command_line_text("yd-cancel", ["-y", "wr-1"]) == "yd-cancel -y wr-1"


def test_command_line_text_strips_when_no_args():
    assert command_line_text("yd-version", []) == "yd-version"


def test_no_abbreviation_at_or_below_the_threshold(window):
    # Three or fewer YDIDs are short enough to read in full.
    assert (
        window._abbreviated_run_args(["-y"], summaries(3), "Work Requirements") is None
    )


def test_abbreviation_above_the_threshold(window):
    assert window._abbreviated_run_args(["-y"], summaries(4), "Work Requirements") == [
        "-y",
        "<4 Work Requirements>",
    ]


def test_abbreviation_preserves_the_leading_run_args(window):
    assert window._abbreviated_run_args(["-ay"], summaries(9), "Work Requirements") == [
        "-ay",
        "<9 Work Requirements>",
    ]
