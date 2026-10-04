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


# ---------------------------------------------------------------------------
# Reconnection, a clean close, the exit code and the order of the streams
# ---------------------------------------------------------------------------

WR = "ydid:workreq:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _stream(lines=(), raises: Exception | None = None, status: int = 200):
    """A response to requests.get(): 'lines', then 'raises' if given."""
    response = MagicMock()
    response.status_code = status
    response.encoding = "utf-8"
    response.json.return_value = {"message": f"HTTP {status}"}
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)

    def iter_lines(decode_unicode=True):
        yield from lines
        if raises is not None:
            raise raises

    response.iter_lines.side_effect = iter_lines
    return response


class _Clock:
    """monotonic() and sleep() together: sleeping advances the clock."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(fu, "monotonic", clock.monotonic)
    monkeypatch.setattr(fu, "sleep", clock.sleep)
    monkeypatch.setattr(fu, "print_info", lambda *a, **k: None)
    monkeypatch.setattr(fu, "print_warning", lambda *a, **k: None)
    monkeypatch.setattr(fu, "print_error", lambda *a, **k: None)
    monkeypatch.setattr(fu, "print_event", lambda *a, **k: None)
    return clock


def _finished(monkeypatch, *answers: bool) -> MagicMock:
    finished = MagicMock(side_effect=list(answers))
    monkeypatch.setattr(fu, "_entity_finished", finished)
    return finished


class TestReconnection:
    def test_a_drop_is_reconnected_with_growing_waits(self, clock, monkeypatch):
        dropped = requests.exceptions.ConnectionError("dropped")
        # Connected, dropped; then three failed reconnections; then back
        responses = [
            _stream(["data: 1"], raises=dropped),
            dropped,
            dropped,
            dropped,
            _stream(["data: 2"]),
        ]
        monkeypatch.setattr(fu.requests, "get", MagicMock(side_effect=responses))
        _finished(monkeypatch, True)
        fu.follow_events(WR, fu.YDIDType.WORK_REQUIREMENT)
        assert clock.sleeps == [5.0, 10.0, 20.0, 30.0]
        assert fu.follow_exit_code() == fu.ExitCode.SUCCESS

    def test_an_outage_over_five_minutes_gives_up_with_exit_8(self, clock, monkeypatch):
        dropped = requests.exceptions.ConnectionError("dropped")
        monkeypatch.setattr(
            fu.requests,
            "get",
            MagicMock(side_effect=[_stream(raises=dropped)] + [dropped] * 100),
        )
        fu.follow_events(WR, fu.YDIDType.WORK_REQUIREMENT)
        assert clock.now >= 300
        assert clock.now < 300 + 30
        assert fu.follow_exit_code() == fu.ExitCode.CONNECTION

    def test_a_first_connection_that_fails_is_not_retried(self, clock, monkeypatch):
        get = MagicMock(side_effect=requests.exceptions.ConnectionError("no"))
        monkeypatch.setattr(fu.requests, "get", get)
        fu.follow_events(WR, fu.YDIDType.WORK_REQUIREMENT)
        assert get.call_count == 1
        assert clock.sleeps == []
        assert fu.follow_exit_code() == fu.ExitCode.CONNECTION


class TestCleanClose:
    def test_a_close_while_the_entity_is_live_reconnects(self, clock, monkeypatch):
        get = MagicMock(side_effect=[_stream(["data: 1"]), _stream(["data: 2"])])
        monkeypatch.setattr(fu.requests, "get", get)
        finished = _finished(monkeypatch, False, True)
        fu.follow_events(WR, fu.YDIDType.WORK_REQUIREMENT)
        assert get.call_count == 2
        assert finished.call_count == 2

    @pytest.mark.parametrize(
        "ydid_type, client_call, status, finished",
        [
            (
                "WORK_REQUIREMENT",
                "work_client.get_work_requirement_by_id",
                "RUNNING",
                False,
            ),
            (
                "WORK_REQUIREMENT",
                "work_client.get_work_requirement_by_id",
                "COMPLETED",
                True,
            ),
            (
                "WORKER_POOL",
                "worker_pool_client.get_worker_pool_by_id",
                "SHUTDOWN",
                True,
            ),
            ("WORKER_POOL", "worker_pool_client.get_worker_pool_by_id", "IDLE", False),
            (
                "COMPUTE_REQUIREMENT",
                "compute_client.get_compute_requirement_by_id",
                "TERMINATED",
                True,
            ),
            (
                "COMPUTE_REQUIREMENT",
                "compute_client.get_compute_requirement_by_id",
                "STOPPED",
                False,
            ),
        ],
    )
    def test_whether_an_entity_has_finished(
        self, monkeypatch, ydid_type, client_call, status, finished
    ):
        from yellowdog_client.model import (
            ComputeRequirementStatus,
            WorkerPoolStatus,
            WorkRequirementStatus,
        )

        enum = {
            "WORK_REQUIREMENT": WorkRequirementStatus,
            "WORKER_POOL": WorkerPoolStatus,
            "COMPUTE_REQUIREMENT": ComputeRequirementStatus,
        }[ydid_type]
        client = MagicMock()
        target = client
        for part in client_call.split("."):
            target = getattr(target, part)
        target.return_value = MagicMock(status=enum(status))
        monkeypatch.setattr(fu, "CLIENT", client)
        assert fu._entity_finished("x", getattr(fu.YDIDType, ydid_type)) is finished

    def test_a_status_that_cannot_be_fetched_is_taken_as_finished(self, monkeypatch):
        client = MagicMock()
        client.work_client.get_work_requirement_by_id.side_effect = RuntimeError("no")
        monkeypatch.setattr(fu, "CLIENT", client)
        monkeypatch.setattr(fu, "print_warning", lambda *a, **k: None)
        assert fu._entity_finished("x", fu.YDIDType.WORK_REQUIREMENT) is True


class TestExitCode:
    @pytest.mark.parametrize(
        "status, code",
        [
            (404, fu.ExitCode.NOT_FOUND),
            (401, fu.ExitCode.AUTHENTICATION),
            (500, fu.ExitCode.PLATFORM),
        ],
    )
    def test_a_refused_stream_has_its_own_code(self, clock, monkeypatch, status, code):
        monkeypatch.setattr(
            fu.requests, "get", MagicMock(return_value=_stream(status=status))
        )
        fu.follow_events(WR, fu.YDIDType.WORK_REQUIREMENT)
        assert fu.follow_exit_code() == code

    def test_failures_with_different_causes_exit_1(self, clock, monkeypatch):
        monkeypatch.setattr(
            fu.requests,
            "get",
            MagicMock(side_effect=[_stream(status=404), _stream(status=401)]),
        )
        fu.follow_events(WR, fu.YDIDType.WORK_REQUIREMENT)
        fu.follow_events(WR, fu.YDIDType.WORK_REQUIREMENT)
        assert fu.follow_exit_code() == fu.ExitCode.FAILURE


class TestFollowIds:
    def test_the_order_given_is_kept(self, monkeypatch):
        started = []
        monkeypatch.setattr(
            fu, "ARGS_PARSER", MagicMock(progress=False, print_pid=False)
        )
        monkeypatch.setattr(fu, "print_info", lambda *a, **k: None)
        monkeypatch.setattr(fu, "print_warning", lambda *a, **k: None)
        monkeypatch.setattr(
            fu, "follow_events", lambda ydid, ydid_type: started.append(ydid)
        )
        ids = [
            f"ydid:workreq:000000:{c * 8}-aaaa-aaaa-aaaa-aaaaaaaaaaaa" for c in "edcba"
        ]
        valid = fu.follow_ids(ids + ids[:2])
        assert valid == ids

    def test_an_auto_cr_lookup_failure_is_recorded(self, monkeypatch):
        client = MagicMock()
        client.worker_pool_client.get_worker_pool_by_id.side_effect = _http_404()
        monkeypatch.setattr(fu, "CLIENT", client)
        monkeypatch.setattr(fu, "print_error", lambda *a, **k: None)
        assert fu._compute_requirement_of_worker_pool("ydid:wrkrpool:000000:x") is None
        assert fu.follow_exit_code() == fu.ExitCode.NOT_FOUND


class TestCommandLine:
    @pytest.mark.parametrize(
        "argv, message",
        [
            ([], "required"),
            (["ydid:node:000000:x"], "not a Work Requirement, Worker Pool or Compute"),
            (["not-an-id"], "not a Work Requirement, Worker Pool or Compute"),
        ],
    )
    def test_refused_as_parsed(self, argv, message, capsys):
        from yellowdog_cli.utils.args import CLIParser

        with pytest.raises(SystemExit) as raised:
            CLIParser(command="yd-follow", argv=argv)
        assert raised.value.code == 2
        assert message in capsys.readouterr().err

    def test_followable_ids_are_accepted(self):
        from yellowdog_cli.utils.args import CLIParser

        CLIParser(
            command="yd-follow",
            argv=[
                WR,
                "ydid:wrkrpool:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "ydid:compreq:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            ],
        )
