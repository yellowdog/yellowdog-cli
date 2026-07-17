"""
Unit tests for follow_utils.py.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

import yellowdog_cli.utils.follow_utils as fu


def _http_404() -> requests.HTTPError:
    response = MagicMock()
    response.status_code = 404
    return requests.HTTPError(response=response)


@pytest.fixture(autouse=True)
def _reset_follow_errors():
    fu.reset_follow_errors()
    yield
    fu.reset_follow_errors()


class TestFollowWorkRequirementWithProgress:
    """
    Tests for follow_work_requirement_with_progress().
    """

    def test_not_found_prints_error_without_starting_progress(self):
        client = MagicMock()
        client.work_client.get_work_requirement_by_id.side_effect = _http_404()
        with (
            patch.object(fu, "CLIENT", client),
            patch.object(fu, "print_error") as mock_error,
            patch.object(fu, "follow_events") as mock_follow,
            patch.object(fu, "Progress") as mock_progress,
        ):
            fu.follow_work_requirement_with_progress("ydid:workreq:000000:aaa:bbb")
        mock_error.assert_called_once()
        assert "not found" in mock_error.call_args.args[0]
        mock_follow.assert_not_called()
        mock_progress.assert_not_called()
        assert fu.follow_errors_occurred() is True

    def test_other_fetch_errors_still_follow_events(self):
        client = MagicMock()
        client.work_client.get_work_requirement_by_id.side_effect = (
            requests.ConnectionError("boom")
        )
        with (
            patch.object(fu, "CLIENT", client),
            patch.object(fu, "print_error") as mock_error,
            patch.object(fu, "follow_events") as mock_follow,
        ):
            fu.follow_work_requirement_with_progress("ydid:workreq:000000:aaa:bbb")
        mock_error.assert_not_called()
        mock_follow.assert_called_once()
        assert fu.follow_errors_occurred() is False


class TestFollowErrorFlag:
    """
    Tests for the follow-error flag consulted by yd-follow's exit code.
    """

    def test_flag_initially_clear(self):
        assert fu.follow_errors_occurred() is False

    def test_invalid_ydid_sets_flag(self):
        args_parser = MagicMock(progress=False, print_pid=False)
        with (
            patch.object(fu, "ARGS_PARSER", args_parser),
            patch.object(fu, "print_error") as mock_error,
        ):
            valid = fu.follow_ids(["ydid:nonsense:000000:aaa:bbb"])
        mock_error.assert_called_once()
        assert valid == []
        assert fu.follow_errors_occurred() is True

    def test_stream_not_found_sets_flag(self):
        response = MagicMock()
        response.status_code = 404
        response.json.return_value = {"message": "Work requirement not found"}
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        with (
            patch.object(fu.requests, "get", return_value=response),
            patch.object(fu, "print_error") as mock_error,
            patch.object(fu, "print_info"),
        ):
            fu.follow_events(
                "ydid:workreq:000000:aaa:bbb", fu.YDIDType.WORK_REQUIREMENT
            )
        mock_error.assert_called_once()
        assert fu.follow_errors_occurred() is True

    def test_stream_connection_failure_sets_flag(self):
        with (
            patch.object(
                fu.requests,
                "get",
                side_effect=requests.exceptions.ConnectionError("boom"),
            ),
            patch.object(fu, "print_error") as mock_error,
            patch.object(fu, "print_info"),
        ):
            fu.follow_events(
                "ydid:workreq:000000:aaa:bbb", fu.YDIDType.WORK_REQUIREMENT
            )
        mock_error.assert_called_once()
        assert fu.follow_errors_occurred() is True
