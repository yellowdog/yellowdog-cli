"""
Unit tests for the Commander display-elision helpers used to cap the length of
text shown in the left-hand column: the selected configuration file path, and
the selected definition filenames shown on the 'Select' buttons.
"""

import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")  # commander imports QtWidgets at module top

from yellowdog_cli.commander.commander import (
    MAX_DISPLAYED_NAME_LENGTH,
    MAX_DISPLAYED_PATH_LENGTH,
    PATH_ELLIPSIS,
    elide_middle,
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


def test_short_name_is_unchanged():
    assert elide_middle("tasks.json") == "tasks.json"


def test_name_at_limit_is_unchanged():
    name = "n" * MAX_DISPLAYED_NAME_LENGTH
    assert elide_middle(name) == name


def test_long_name_is_elided_in_the_middle():
    elided = elide_middle("a_rather_long_definition_name.jsonnet")
    assert len(elided) == MAX_DISPLAYED_NAME_LENGTH
    assert elided.startswith("a_rather")  # start kept
    assert elided.endswith(".jsonnet")  # extension kept
    assert PATH_ELLIPSIS in elided


def test_elide_middle_max_length_can_be_overridden():
    assert len(elide_middle("x" * 100, max_length=11)) == 11
    assert elide_middle("x" * 100, max_length=11) == f"xxxxx{PATH_ELLIPSIS}xxxxx"
