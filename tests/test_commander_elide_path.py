"""
Unit tests for the Commander path elision helper used to cap the length of the
selected configuration file displayed in the left-hand column.
"""

import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")  # commander imports QtWidgets at module top

from yellowdog_cli.commander.commander import (
    MAX_DISPLAYED_PATH_LENGTH,
    PATH_ELLIPSIS,
    elide_path,
)

SEP = os.sep


def test_short_path_is_unchanged():
    path = SEP.join(["a", "b", "config.toml"])
    assert elide_path(path) == path


def test_path_at_limit_is_unchanged():
    path = "x" * MAX_DISPLAYED_PATH_LENGTH
    assert elide_path(path) == path


def test_long_path_is_elided_to_the_limit():
    path = SEP.join(["averylongdirectoryname"] * 8 + ["config.toml"])
    elided = elide_path(path)
    assert len(elided) <= MAX_DISPLAYED_PATH_LENGTH
    assert elided.startswith(PATH_ELLIPSIS)
    assert elided.endswith("config.toml")


def test_elided_path_starts_at_a_separator_boundary():
    path = SEP.join(["directory-with-a-long-name"] * 4 + ["config.toml"])
    elided = elide_path(path)
    # No partial directory name after the ellipsis
    assert elided.startswith(f"{PATH_ELLIPSIS}{SEP}")


def test_long_filename_without_separators_is_truncated():
    path = "c" * 80 + ".toml"
    elided = elide_path(path)
    assert len(elided) == MAX_DISPLAYED_PATH_LENGTH
    assert elided.startswith(PATH_ELLIPSIS)
    assert elided.endswith(".toml")


def test_max_length_can_be_overridden():
    path = SEP.join(["one", "two", "three", "four", "config.toml"])
    assert elide_path(path, max_length=len(path)) == path
    assert len(elide_path(path, max_length=20)) <= 20
