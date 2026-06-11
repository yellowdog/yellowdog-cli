"""
Unit tests for start_hold_common.py.

Covers:
  - _start_or_hold_work_requirements_by_name_or_id  (named/ID path)
  - _start_or_hold_work_requirements                (tag-based path + dispatch)
"""

from unittest.mock import MagicMock, patch

from yellowdog_client.model import WorkRequirementStatus

import yellowdog_cli.utils.start_hold_common as shc_module
from yellowdog_cli.utils.start_hold_common import (
    _start_or_hold_work_requirements,
    _start_or_hold_work_requirements_by_name_or_id,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_wr_summary(
    id_: str = "ydid:wrkrq:test:aaa",
    name: str = "test-wr",
    namespace: str = "test-ns",
    status: WorkRequirementStatus = WorkRequirementStatus.HELD,
) -> MagicMock:
    summary = MagicMock()
    summary.id = id_
    summary.name = name
    summary.namespace = namespace
    summary.status = status
    return summary


def _config_common(
    namespace: str = "test-ns",
    name_tag: str = "test-tag",
    url: str = "https://test",
) -> MagicMock:
    return MagicMock(namespace=namespace, name_tag=name_tag, url=url)


# ---------------------------------------------------------------------------
# _start_or_hold_work_requirements_by_name_or_id
# ---------------------------------------------------------------------------


class TestByNameOrId:
    """
    Tests for _start_or_hold_work_requirements_by_name_or_id.
    """

    def _call(
        self,
        names_or_ids: list[str],
        lookup_results,
        required_state: WorkRequirementStatus = WorkRequirementStatus.HELD,
        confirm_result: bool = True,
        action_raises: Exception | None = None,
    ) -> tuple:
        """
        Helper: drive _start_or_hold_work_requirements_by_name_or_id with
        mocked dependencies.  lookup_results may be a single value (used as
        return_value) or a list (used as side_effect).
        """
        action_fn = MagicMock()
        if action_raises is not None:
            action_fn.side_effect = action_raises

        lookup_kwargs = (
            {"return_value": lookup_results}
            if not isinstance(lookup_results, list)
            else {"side_effect": lookup_results}
        )

        with (
            patch.object(
                shc_module,
                "get_work_requirement_summary_by_name_or_id",
                **lookup_kwargs,
            ),
            patch.object(shc_module, "confirmed", return_value=confirm_result),
            patch.object(shc_module, "print_error") as mock_error,
            patch.object(shc_module, "print_warning") as mock_warning,
            patch.object(shc_module, "print_info"),
            patch.object(shc_module, "CONFIG_COMMON", _config_common()),
        ):
            result = _start_or_hold_work_requirements_by_name_or_id(
                action="Start",
                required_state=required_state,
                action_function=action_fn,
                names_or_ids=names_or_ids,
            )
        return result, action_fn, mock_error, mock_warning

    def test_not_found_prints_error_and_returns_empty(self):
        result, action_fn, mock_error, _ = self._call(["missing-wr"], None)
        assert result == []
        action_fn.assert_not_called()
        mock_error.assert_called_once()

    def test_wrong_status_prints_warning_and_returns_empty(self):
        summary = _make_wr_summary(status=WorkRequirementStatus.RUNNING)
        result, action_fn, _, mock_warning = self._call(
            ["my-wr"], summary, required_state=WorkRequirementStatus.HELD
        )
        assert result == []
        action_fn.assert_not_called()
        mock_warning.assert_called_once()

    def test_not_confirmed_returns_empty_without_calling_action(self):
        summary = _make_wr_summary(status=WorkRequirementStatus.HELD)
        result, action_fn, _, _ = self._call(["my-wr"], summary, confirm_result=False)
        assert result == []
        action_fn.assert_not_called()

    def test_found_correct_status_confirmed_calls_action_and_returns_id(self):
        summary = _make_wr_summary(
            id_="ydid:wrkrq:test:abc", status=WorkRequirementStatus.HELD
        )
        result, action_fn, _, _ = self._call(["my-wr"], summary)
        assert result == ["ydid:wrkrq:test:abc"]
        action_fn.assert_called_once_with("ydid:wrkrq:test:abc")

    def test_action_raises_prints_error_and_id_not_in_result(self):
        summary = _make_wr_summary(
            id_="ydid:wrkrq:test:abc", status=WorkRequirementStatus.HELD
        )
        result, _action_fn, mock_error, _ = self._call(
            ["my-wr"], summary, action_raises=RuntimeError("API failure")
        )
        assert result == []
        mock_error.assert_called_once()

    def test_hold_action_uses_running_as_required_state(self):
        summary = _make_wr_summary(
            id_="ydid:wrkrq:test:abc", status=WorkRequirementStatus.RUNNING
        )
        result, action_fn, _, _ = self._call(
            ["my-wr"], summary, required_state=WorkRequirementStatus.RUNNING
        )
        assert result == ["ydid:wrkrq:test:abc"]
        action_fn.assert_called_once_with("ydid:wrkrq:test:abc")

    def test_multiple_names_first_not_found_second_actioned(self):
        summary_b = _make_wr_summary(
            id_="ydid:wrkrq:test:bbb", status=WorkRequirementStatus.HELD
        )
        result, action_fn, mock_error, _ = self._call(
            ["missing-wr", "found-wr"], [None, summary_b]
        )
        assert result == ["ydid:wrkrq:test:bbb"]
        action_fn.assert_called_once_with("ydid:wrkrq:test:bbb")
        mock_error.assert_called_once()

    def test_multiple_names_wrong_status_then_correct_status(self):
        summary_a = _make_wr_summary(
            id_="ydid:wrkrq:test:aaa", status=WorkRequirementStatus.RUNNING
        )
        summary_b = _make_wr_summary(
            id_="ydid:wrkrq:test:bbb", status=WorkRequirementStatus.HELD
        )
        result, action_fn, _, mock_warning = self._call(
            ["wrong-wr", "good-wr"],
            [summary_a, summary_b],
            required_state=WorkRequirementStatus.HELD,
        )
        assert result == ["ydid:wrkrq:test:bbb"]
        action_fn.assert_called_once_with("ydid:wrkrq:test:bbb")
        mock_warning.assert_called_once()

    def test_both_found_and_actioned(self):
        summary_a = _make_wr_summary(
            id_="ydid:wrkrq:test:aaa", status=WorkRequirementStatus.HELD
        )
        summary_b = _make_wr_summary(
            id_="ydid:wrkrq:test:bbb", status=WorkRequirementStatus.HELD
        )
        result, action_fn, _, _ = self._call(["wr-a", "wr-b"], [summary_a, summary_b])
        assert sorted(result) == ["ydid:wrkrq:test:aaa", "ydid:wrkrq:test:bbb"]
        assert action_fn.call_count == 2


# ---------------------------------------------------------------------------
# _start_or_hold_work_requirements  (tag-based path)
# ---------------------------------------------------------------------------


class TestTagBasedPath:
    """
    Tests for the tag-based path in _start_or_hold_work_requirements
    (when ARGS_PARSER.work_requirement_names is falsy).
    """

    def _call(
        self,
        filtered_summaries: list,
        selected_summaries: list | None = None,
        confirm_result: bool = True,
        required_state: WorkRequirementStatus = WorkRequirementStatus.HELD,
        action_raises: Exception | None = None,
    ) -> tuple:
        if selected_summaries is None:
            selected_summaries = filtered_summaries

        action_fn = MagicMock()
        if action_raises is not None:
            action_fn.side_effect = action_raises

        mock_args = MagicMock()
        mock_args.work_requirement_names = None

        mock_client = MagicMock()
        mock_client.work_client.get_work_requirement_by_id.return_value = MagicMock()

        with (
            patch.object(shc_module, "ARGS_PARSER", mock_args),
            patch.object(shc_module, "CLIENT", mock_client),
            patch.object(shc_module, "CONFIG_COMMON", _config_common()),
            patch.object(
                shc_module,
                "get_filtered_work_requirement_summaries",
                return_value=filtered_summaries,
            ),
            patch.object(shc_module, "select", return_value=selected_summaries),
            patch.object(shc_module, "confirmed", return_value=confirm_result),
            patch.object(shc_module, "print_error") as mock_error,
            patch.object(shc_module, "print_info"),
            patch.object(shc_module, "link_entity", return_value="<link>"),
        ):
            result = _start_or_hold_work_requirements(
                action="Start",
                required_state=required_state,
                action_function=action_fn,
            )
        return result, action_fn, mock_error

    def test_no_wrs_found_returns_empty_list(self):
        result, action_fn, _ = self._call(filtered_summaries=[])
        assert result == []
        action_fn.assert_not_called()

    def test_wrs_found_but_not_confirmed_returns_empty_list(self):
        summary = _make_wr_summary(status=WorkRequirementStatus.HELD)
        result, action_fn, _ = self._call(
            filtered_summaries=[summary], confirm_result=False
        )
        assert result == []
        action_fn.assert_not_called()

    def test_wrs_confirmed_action_called_and_id_returned(self):
        summary = _make_wr_summary(
            id_="ydid:wrkrq:test:abc", status=WorkRequirementStatus.HELD
        )
        result, action_fn, _ = self._call(filtered_summaries=[summary])
        assert "ydid:wrkrq:test:abc" in result
        action_fn.assert_called_once_with("ydid:wrkrq:test:abc")

    def test_status_changed_since_filter_skips_action_and_id_not_returned(self):
        """
        If a WR's status changed between the initial filter and the action loop
        (e.g. HELD → RUNNING), the action is skipped and the ID is not
        returned (it must not be followed).
        """
        summary = _make_wr_summary(
            id_="ydid:wrkrq:test:abc", status=WorkRequirementStatus.RUNNING
        )
        result, action_fn, _ = self._call(
            filtered_summaries=[summary],
            required_state=WorkRequirementStatus.HELD,
        )
        assert "ydid:wrkrq:test:abc" not in result
        action_fn.assert_not_called()

    def test_action_exception_prints_error_id_not_returned(self):
        summary = _make_wr_summary(
            id_="ydid:wrkrq:test:abc", status=WorkRequirementStatus.HELD
        )
        result, _action_fn, mock_error = self._call(
            filtered_summaries=[summary],
            action_raises=RuntimeError("fail"),
        )
        assert "ydid:wrkrq:test:abc" not in result
        mock_error.assert_called_once()

    def test_multiple_wrs_all_actioned(self):
        summaries = [
            _make_wr_summary(
                id_="ydid:wrkrq:test:aaa", status=WorkRequirementStatus.HELD
            ),
            _make_wr_summary(
                id_="ydid:wrkrq:test:bbb", status=WorkRequirementStatus.HELD
            ),
        ]
        result, action_fn, _ = self._call(filtered_summaries=summaries)
        assert sorted(result) == ["ydid:wrkrq:test:aaa", "ydid:wrkrq:test:bbb"]
        assert action_fn.call_count == 2

    def test_select_filters_summaries_before_confirmation(self):
        """
        Only the summaries returned by select() are confirmed and actioned.
        """
        all_summaries = [
            _make_wr_summary(
                id_="ydid:wrkrq:test:aaa", status=WorkRequirementStatus.HELD
            ),
            _make_wr_summary(
                id_="ydid:wrkrq:test:bbb", status=WorkRequirementStatus.HELD
            ),
        ]
        selected = [all_summaries[0]]  # user selected only the first
        _result, action_fn, _ = self._call(
            filtered_summaries=all_summaries, selected_summaries=selected
        )
        assert action_fn.call_count == 1
        action_fn.assert_called_once_with("ydid:wrkrq:test:aaa")


# ---------------------------------------------------------------------------
# Dispatch: named path vs tag-based path
# ---------------------------------------------------------------------------


class TestDispatch:
    """
    Tests that _start_or_hold_work_requirements routes to the correct sub-path.
    """

    def test_dispatches_to_named_path_when_names_provided(self):
        mock_args = MagicMock()
        mock_args.work_requirement_names = ["my-wr"]

        with (
            patch.object(shc_module, "ARGS_PARSER", mock_args),
            patch.object(shc_module, "CONFIG_COMMON", _config_common()),
            patch.object(
                shc_module,
                "_start_or_hold_work_requirements_by_name_or_id",
                return_value=["ydid:wrkrq:test:abc"],
            ) as mock_by_name,
            patch.object(
                shc_module, "get_filtered_work_requirement_summaries"
            ) as mock_filtered,
        ):
            result = _start_or_hold_work_requirements(
                action="Start",
                required_state=WorkRequirementStatus.HELD,
                action_function=MagicMock(),
            )

        mock_by_name.assert_called_once()
        mock_filtered.assert_not_called()
        assert result == ["ydid:wrkrq:test:abc"]

    def test_dispatches_to_tag_based_path_when_no_names(self):
        mock_args = MagicMock()
        mock_args.work_requirement_names = None

        with (
            patch.object(shc_module, "ARGS_PARSER", mock_args),
            patch.object(shc_module, "CLIENT", MagicMock()),
            patch.object(shc_module, "CONFIG_COMMON", _config_common()),
            patch.object(
                shc_module,
                "get_filtered_work_requirement_summaries",
                return_value=[],
            ) as mock_filtered,
            patch.object(
                shc_module,
                "_start_or_hold_work_requirements_by_name_or_id",
            ) as mock_by_name,
            patch.object(shc_module, "print_info"),
        ):
            _start_or_hold_work_requirements(
                action="Start",
                required_state=WorkRequirementStatus.HELD,
                action_function=MagicMock(),
            )

        mock_filtered.assert_called_once()
        mock_by_name.assert_not_called()
