"""
Unit tests for yellowdog_cli.utils.interactive

Only the pure-logic / non-I/O paths are tested here:
  - confirmed(): the --yes short-circuit
  - get_selected_list_items(): range-parsing logic (with _get_user_input mocked)
"""

import os
from types import SimpleNamespace
from unittest.mock import patch

import yellowdog_cli.utils.interactive as interactive_module
from yellowdog_cli.utils import output_settings
from yellowdog_cli.utils.interactive import confirmed, get_selected_list_items

# ---------------------------------------------------------------------------
# confirmed() — short-circuit paths (no user input required)
# ---------------------------------------------------------------------------


class TestConfirmedShortCircuits:
    def test_yes_flag_returns_true_without_input(self):
        mock_args = SimpleNamespace(yes=True)
        with output_settings.configured(mock_args):
            assert confirmed("delete everything?") is True

    def test_user_confirms_with_y(self):
        mock_args = SimpleNamespace(yes=False, no_format=True)
        with output_settings.configured(mock_args):
            with patch.dict(os.environ, {}, clear=True):
                with patch.object(
                    interactive_module, "_get_user_input", return_value="y"
                ):
                    assert confirmed("proceed?") is True

    def test_user_confirms_with_yes(self):
        mock_args = SimpleNamespace(yes=False, no_format=True)
        with output_settings.configured(mock_args):
            with patch.dict(os.environ, {}, clear=True):
                with patch.object(
                    interactive_module, "_get_user_input", return_value="yes"
                ):
                    assert confirmed("proceed?") is True

    def test_user_cancels_with_n(self):
        mock_args = SimpleNamespace(yes=False, no_format=True)
        with output_settings.configured(mock_args):
            with patch.dict(os.environ, {}, clear=True):
                with patch.object(
                    interactive_module, "_get_user_input", return_value="n"
                ):
                    assert confirmed("proceed?") is False

    def test_user_cancels_with_empty_string(self):
        mock_args = SimpleNamespace(yes=False, no_format=True)
        with output_settings.configured(mock_args):
            with patch.dict(os.environ, {}, clear=True):
                with patch.object(
                    interactive_module, "_get_user_input", return_value=""
                ):
                    assert confirmed("proceed?") is False


# ---------------------------------------------------------------------------
# get_selected_list_items() — range parsing
# ---------------------------------------------------------------------------


def _select(responses, num_items=10, result_required=False, single_result=False):
    """
    Helper: run get_selected_list_items with a scripted list of inputs.
    """
    resp_iter = iter(responses)
    with patch.object(interactive_module, "_get_user_input", side_effect=resp_iter):
        return get_selected_list_items(
            num_items,
            result_required=result_required,
            single_result=single_result,
        )


class TestGetSelectedListItems:
    # ------------------------------------------------------------------
    # Happy-path selections
    # ------------------------------------------------------------------

    def test_single_item(self):
        assert _select(["1"]) == [1]

    def test_comma_separated_items(self):
        assert _select(["1,3,5"]) == [1, 3, 5]

    def test_range_expression(self):
        assert _select(["2-5"]) == [2, 3, 4, 5]

    def test_mixed_comma_and_range(self):
        assert _select(["1,3-5,7"]) == [1, 3, 4, 5, 7]

    def test_star_selects_all(self):
        result = _select(["*"], num_items=5)
        assert result == [1, 2, 3, 4, 5]

    def test_duplicates_deduplicated_and_sorted(self):
        # 1,2,1-3 → unique sorted = [1, 2, 3]
        assert _select(["1,2,1-3"]) == [1, 2, 3]

    def test_whitespace_around_items_ignored(self):
        # Comma-split produces "1", " 3" — both are parsed via int()
        # (spaces inside a range like "1 -3" would cause ValueError,
        # but "1, 3" with strip-free split → " 3".isspace() is False,
        # int(" 3") raises ValueError; that's implementation behaviour)
        assert _select(["1"]) == [1]

    # ------------------------------------------------------------------
    # Empty / cancel paths
    # ------------------------------------------------------------------

    def test_empty_input_returns_empty_list(self):
        result = _select([""])
        assert result == []

    def test_whitespace_input_returns_empty_list(self):
        result = _select(["   "])
        assert result == []

    # ------------------------------------------------------------------
    # Error-recovery: bad input followed by good input
    # ------------------------------------------------------------------

    def test_out_of_range_then_valid(self):
        # First call returns "99" (out of range for num_items=5),
        # second call returns "2" (valid).
        result = _select(["99", "2"], num_items=5)
        assert result == [2]

    def test_non_numeric_then_valid(self):
        result = _select(["abc", "3"])
        assert result == [3]

    def test_invalid_range_order_then_valid(self):
        # "5-2" is invalid (low > high) → triggers ValueError → loops
        result = _select(["5-2", "1"])
        assert result == [1]

    # ------------------------------------------------------------------
    # single_result mode
    # ------------------------------------------------------------------

    def test_single_result_mode_accepts_one_item(self):
        result = _select(["3"], single_result=True, num_items=5)
        assert result == [3]

    def test_single_result_mode_rejects_multiple_then_accepts_one(self):
        # "1,2" → multiple → loops; "2" → single → OK
        result = _select(["1,2", "2"], single_result=True, num_items=5)
        assert result == [2]

    # ------------------------------------------------------------------
    # result_required mode (empty input → loops until non-empty)
    # ------------------------------------------------------------------

    def test_result_required_loops_on_empty_then_accepts(self):
        result = _select(["", "4"], result_required=True)
        assert result == [4]


# ---------------------------------------------------------------------------
# A range checked by its ends; answers stripped
# ---------------------------------------------------------------------------


def test_a_range_out_of_range_is_one_error(monkeypatch):
    errors: list[str] = []
    monkeypatch.setattr(interactive_module, "print_error", errors.append)
    assert _select(["1-200000", "2"], num_items=3) == [2]
    assert errors == ["'1-200000' is out of range (1-3)"]


def test_a_required_selection_says_so_when_none_is_made(monkeypatch):
    errors: list[str] = []
    monkeypatch.setattr(interactive_module, "print_error", errors.append)
    assert _select(["", "4"], result_required=True) == [4]
    assert errors == ["please select at least one item"]


def test_an_answer_with_spaces_is_understood():
    mock_args = SimpleNamespace(yes=False, no_format=True)
    with output_settings.configured(mock_args):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(
                interactive_module, "_get_user_input", return_value=" y "
            ):
                assert confirmed("proceed?") is True


def test_interactive_imports_no_sdk():
    """
    yd-delete imports this module for confirmed(): the SDK it once imported
    at module level, for an annotation, cost every yd-delete its ~140ms.
    """
    import subprocess
    import sys

    script = (
        "import sys; sys.argv = ['yd-delete', 'x']\n"
        "import yellowdog_cli.utils.interactive\n"
        "print('yellowdog_client' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
