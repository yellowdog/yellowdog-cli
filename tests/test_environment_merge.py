"""
Unit tests for yellowdog_cli.utils.submit_utils.merge_environment

Tests the merging of addEnvironment entries into a task's environment dict.
"""

import pytest

from yellowdog_cli.utils.submit_utils import merge_environment


class TestMergeEnvironment:
    """
    merge_environment(base, additions) merges additions into base, the
    Task's environment as inheritance gives it: a key in both keeps the
    environment's value, so additions only add the keys it lacks.
    Returns base unchanged when additions is empty/None.
    """

    # ------------------------------------------------------------------
    # No additions — pass-through
    # ------------------------------------------------------------------

    def test_no_additions_returns_base_unchanged(self):
        base = {"A": "1", "B": "2"}
        assert merge_environment(base, None) is base

    def test_empty_additions_returns_base_unchanged(self):
        base = {"A": "1"}
        assert merge_environment(base, {}) is base

    def test_none_base_no_additions_returns_none(self):
        assert merge_environment(None, None) is None

    def test_none_base_empty_additions_returns_none(self):
        assert merge_environment(None, {}) is None

    # ------------------------------------------------------------------
    # Additions only (no base)
    # ------------------------------------------------------------------

    def test_none_base_with_additions(self):
        assert merge_environment(None, {"X": "1"}) == {"X": "1"}

    def test_empty_base_with_additions(self):
        assert merge_environment({}, {"X": "1"}) == {"X": "1"}

    # ------------------------------------------------------------------
    # Non-overlapping keys — all keys preserved
    # ------------------------------------------------------------------

    def test_disjoint_keys_merged(self):
        assert merge_environment({"A": "1"}, {"B": "2"}) == {"A": "1", "B": "2"}

    def test_multiple_disjoint_keys(self):
        base = {"A": "1", "B": "2"}
        additions = {"C": "3", "D": "4"}
        assert merge_environment(base, additions) == {
            "A": "1",
            "B": "2",
            "C": "3",
            "D": "4",
        }

    # ------------------------------------------------------------------
    # Overlapping keys — the environment's value kept
    # ------------------------------------------------------------------

    def test_an_overlapping_key_keeps_the_environments_value(self):
        assert merge_environment({"A": "original"}, {"A": "added"}) == {"A": "original"}

    def test_partial_overlap_adds_only_the_missing_keys(self):
        base = {"A": "original", "B": "kept"}
        additions = {"A": "ignored", "C": "new"}
        result = merge_environment(base, additions)
        assert result == {"A": "original", "B": "kept", "C": "new"}

    def test_all_keys_overlapping_change_nothing(self):
        base = {"A": "1", "B": "2"}
        additions = {"A": "x", "B": "y"}
        assert merge_environment(base, additions) == {"A": "1", "B": "2"}

    # ------------------------------------------------------------------
    # Base is not mutated
    # ------------------------------------------------------------------

    def test_base_dict_not_mutated(self):
        base = {"A": "original"}
        additions = {"A": "ignored", "B": "new"}
        result = merge_environment(base, additions)
        assert base == {"A": "original"}
        assert result == {"A": "original", "B": "new"}

    # ------------------------------------------------------------------
    # Return type is always a new dict when additions are applied
    # ------------------------------------------------------------------

    def test_returns_new_dict_not_base(self):
        base = {"A": "1"}
        additions = {"B": "2"}
        result = merge_environment(base, additions)
        assert result is not base

    # ------------------------------------------------------------------
    # Realistic use case
    # ------------------------------------------------------------------

    def test_realistic_task_environment_merge(self):
        base = {"MY_VAR": "original", "KEEP": "kept", "LOG_LEVEL": "INFO"}
        additions = {"MY_VAR": "ignored", "EXTRA": "new_value"}
        result = merge_environment(base, additions)
        assert result == {
            "MY_VAR": "original",
            "KEEP": "kept",
            "LOG_LEVEL": "INFO",
            "EXTRA": "new_value",
        }

    @pytest.mark.parametrize(
        "base, additions, expected",
        [
            ({"A": "1"}, {"B": "2"}, {"A": "1", "B": "2"}),
            ({"A": "1"}, {"A": "2"}, {"A": "1"}),
            ({}, {"A": "1"}, {"A": "1"}),
            (
                {"A": "1", "B": "2"},
                {"B": "x", "C": "3"},
                {"A": "1", "B": "2", "C": "3"},
            ),
        ],
    )
    def test_parametrized_merge(self, base, additions, expected):
        assert merge_environment(base, additions) == expected
