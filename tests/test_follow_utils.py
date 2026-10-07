"""
Unit tests for follow_utils.py.
"""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests
from yellowdog_client.model import TaskStatus, WorkRequirementStatus

import yellowdog_cli.utils.follow_utils as fu
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import ExitCode, ReportedFailure, classify
from yellowdog_cli.utils.ydid_utils import YDIDType


def _ctx() -> RunContext:
    """
    The context a command is given: the wrapper globals, as patched.
    """
    return RunContext(
        wrapper_module.ARGS_PARSER, wrapper_module.CONFIG_COMMON, wrapper_module.CLIENT
    )


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
            patch.object(wrapper_module, "CLIENT", client),
            patch.object(fu, "print_error") as mock_error,
            patch.object(fu, "follow_events") as mock_follow,
            patch.object(fu, "Progress") as mock_progress,
        ):
            fu.follow_work_requirement_with_progress(
                _ctx(), "ydid:workreq:000000:aaa:bbb"
            )
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
            patch.object(wrapper_module, "CLIENT", client),
            patch.object(fu, "print_error") as mock_error,
            patch.object(fu, "follow_events") as mock_follow,
        ):
            fu.follow_work_requirement_with_progress(
                _ctx(), "ydid:workreq:000000:aaa:bbb"
            )
        mock_error.assert_not_called()
        mock_follow.assert_called_once()
        assert fu.follow_errors_occurred() is False


class _RecordingProgress:
    """
    Stands in for Rich's Progress, recording each update and whether the bar
    was stopped.
    """

    def __init__(self, *columns, **kwargs):
        self.updates: list[dict] = []
        self.stopped = False
        self.tasks = [SimpleNamespace(start_time=None)]
        _RecordingProgress.last = self

    def add_task(self, description, total=None, **fields):
        return 0

    def stop_task(self, task_id):
        self.stopped = True

    def update(self, task_id, **fields):
        self.updates.append(fields)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _task_group(total: int, **counts: int) -> SimpleNamespace:
    return SimpleNamespace(
        taskSummary=SimpleNamespace(
            taskCount=total,
            statusCounts={TaskStatus[name.upper()]: n for name, n in counts.items()},
        )
    )


def _event(status: str, *task_groups: tuple[int, dict]) -> str:
    return "data:" + json.dumps(
        {
            "status": status,
            "taskGroups": [
                {"taskSummary": {"taskCount": total, "statusCounts": counts}}
                for total, counts in task_groups
            ],
        }
    )


class TestProgressCounts:
    """
    The counts the progress bar shows, from the Work Requirement as fetched
    and then from each event, and the warning of failed Tasks at the end.
    """

    def _follow(self, wr, events=(), ydid_type=None):
        client = MagicMock()
        client.work_client.get_work_requirement_by_id.return_value = wr

        def follow_events(ctx, ydid, follow_type, on_event):
            for event in events:
                on_event(event, ydid_type or YDIDType.WORK_REQUIREMENT)

        with (
            patch.object(wrapper_module, "CLIENT", client),
            patch.object(fu, "Progress", _RecordingProgress),
            patch.object(fu, "follow_events", follow_events),
            patch.object(fu, "print_info"),
            patch.object(fu, "print_warning") as warning,
        ):
            fu.follow_work_requirement_with_progress(
                _ctx(), "ydid:workreq:000000:aaa:bbb"
            )
        return _RecordingProgress.last, warning

    def _wr(self, *task_groups, status=WorkRequirementStatus.RUNNING, **times):
        return SimpleNamespace(
            name="wr",
            status=status,
            taskGroups=list(task_groups),
            createdTime=times.get("created"),
            statusChangedTime=times.get("changed"),
        )

    def test_the_fetched_counts_are_shown_first(self):
        wr = self._wr(_task_group(6, completed=2, failed=1), _task_group(4, aborted=1))
        progress, warning = self._follow(wr)
        assert progress.updates == [
            {
                "total": 10,
                "completed": 2,
                "description": "RUNNING  4/10  2 completed · 1 failed · 1 aborted",
            }
        ]
        assert not progress.stopped
        warning.assert_called_once_with(
            "Work Requirement finished with 1 failed · 1 aborted task(s)"
        )

    def test_a_task_group_without_a_summary_counts_nothing(self):
        wr = self._wr(SimpleNamespace(taskSummary=None), status=None)
        progress, warning = self._follow(wr)
        assert progress.updates == [
            {"total": None, "completed": 0, "description": "  0/0"}
        ]
        warning.assert_not_called()

    def test_each_event_replaces_the_counts(self):
        wr = self._wr(_task_group(10, failed=3))
        events = [
            "id: 1",  # Not a data line
            "data:{not json",
            _event("RUNNING", (10, {"COMPLETED": 4, "RESUBMITTED": 1})),
            _event(
                "COMPLETED",
                (10, {"COMPLETED": 7, "CANCELLED": 2}),
                (5, {"COMPLETED": 5}),
            ),
        ]
        progress, warning = self._follow(wr, events)
        assert [update["description"] for update in progress.updates] == [
            "RUNNING  3/10  3 failed",
            "RUNNING  5/10  4 completed · 1 resubmitted",
            "COMPLETED  14/15  12 completed · 2 cancelled",
        ]
        assert progress.updates[-1]["total"] == 15
        assert progress.updates[-1]["completed"] == 12
        # The fetched Work Requirement's failures were replaced by the events'
        warning.assert_called_once_with(
            "Work Requirement finished with 2 cancelled task(s)"
        )

    def test_an_event_for_another_type_is_ignored(self):
        wr = self._wr(_task_group(1))
        events = [_event("RUNNING", (1, {"FAILED": 1}))]
        progress, warning = self._follow(wr, events, ydid_type=YDIDType.TASK)
        assert len(progress.updates) == 1
        warning.assert_not_called()

    def test_a_finished_work_requirement_shows_how_long_it_ran(self, monkeypatch):
        created = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        wr = self._wr(
            _task_group(1, completed=1),
            status=WorkRequirementStatus.COMPLETED,
            created=created,
            changed=created + timedelta(minutes=5),
        )
        monkeypatch.setattr(fu, "monotonic", lambda: 1000.0)
        progress, _ = self._follow(wr)
        assert progress.stopped
        assert progress.tasks[0].start_time == 1000.0 - 300


class TestExitOnFailureCode:
    """
    yd-submit -E's exit code once the Work Requirement has been followed:
    its failure, or, if it has not finished because following it failed,
    that failure's code, its outcome never having been seen.
    """

    def _code(self, status, follow_failure=None):
        client = MagicMock()
        client.work_client.get_work_requirement_by_id.return_value = SimpleNamespace(
            status=status
        )
        if follow_failure is not None:
            fu._record_follow_failure(follow_failure)
        with (
            patch.object(wrapper_module, "CLIENT", client),
            patch.object(fu, "print_error") as error,
            patch.object(fu, "print_warning"),
        ):
            code = fu.work_requirement_exit_code(_ctx(), "ydid:workreq:000000:aaa:bbb")
        return code, error

    @pytest.mark.parametrize(
        "status", [WorkRequirementStatus.FAILED, WorkRequirementStatus.CANCELLED]
    )
    def test_a_failed_work_requirement_exits_1(self, status):
        assert self._code(status)[0] == ExitCode.FAILURE

    def test_a_completed_one_exits_0(self):
        assert self._code(WorkRequirementStatus.COMPLETED)[0] == ExitCode.SUCCESS

    def test_one_not_followed_to_its_end_exits_with_the_follow_failure(self):
        code, error = self._code(WorkRequirementStatus.RUNNING, ExitCode.CONNECTION)
        assert code == ExitCode.CONNECTION
        assert "could not be followed to its end" in error.call_args.args[0]

    def test_one_that_finished_though_the_stream_failed_exits_0(self):
        # Its outcome is known after all
        code, _ = self._code(WorkRequirementStatus.COMPLETED, ExitCode.CONNECTION)
        assert code == ExitCode.SUCCESS

    def test_one_still_running_without_a_follow_failure_exits_0(self):
        assert self._code(WorkRequirementStatus.RUNNING)[0] == ExitCode.SUCCESS


class TestSessionFailuresAfterTheStream:
    """
    An authentication or connection failure once a stream has ended exits
    with its own code: in yd-submit -E's final status check, and in the check
    of whether a cleanly closed stream's entity has finished.
    """

    def _client(self, error: Exception) -> MagicMock:
        client = MagicMock()
        client.work_client.get_work_requirement_by_id.side_effect = error
        return client

    def test_the_final_status_check_raises_a_session_failure(self):
        error = requests.ConnectionError("gone")
        with (
            patch.object(wrapper_module, "CLIENT", self._client(error)),
            patch.object(fu, "print_error"),
            pytest.raises(ReportedFailure) as raised,
        ):
            fu.work_requirement_exit_code(_ctx(), "ydid:workreq:000000:aaa:bbb")
        assert classify(raised.value) == ExitCode.CONNECTION

    def test_the_final_status_check_takes_another_failure_as_failed(self):
        error = RuntimeError("odd")
        with (
            patch.object(wrapper_module, "CLIENT", self._client(error)),
            patch.object(fu, "print_error"),
        ):
            code = fu.work_requirement_exit_code(_ctx(), "ydid:workreq:000000:aaa:bbb")
        assert code == ExitCode.FAILURE

    def test_a_session_failure_checking_a_closed_stream_is_recorded(self):
        response = requests.Response()
        response.status_code = 401
        error = requests.HTTPError("401", response=response)
        with (
            patch.object(wrapper_module, "CLIENT", self._client(error)),
            patch.object(fu, "print_error") as mock_error,
            patch.object(fu, "print_warning") as mock_warning,
        ):
            finished = fu._entity_finished(
                _ctx(), "ydid:workreq:000000:aaa:bbb", YDIDType.WORK_REQUIREMENT
            )
        assert finished is None
        mock_error.assert_called_once()
        mock_warning.assert_not_called()
        assert fu.follow_exit_code() == ExitCode.AUTHENTICATION

    def test_another_failure_checking_a_closed_stream_is_taken_as_finished(self):
        with (
            patch.object(wrapper_module, "CLIENT", self._client(RuntimeError("odd"))),
            patch.object(fu, "print_warning") as mock_warning,
        ):
            finished = fu._entity_finished(
                _ctx(), "ydid:workreq:000000:aaa:bbb", YDIDType.WORK_REQUIREMENT
            )
        assert finished is True
        mock_warning.assert_called_once()
        assert fu.follow_errors_occurred() is False

    def test_the_stream_stops_without_concluding_on_a_session_failure(self):
        response = MagicMock(status_code=200, encoding="utf-8")
        response.__enter__.return_value = response
        response.iter_lines.return_value = iter([])  # Closed cleanly
        with (
            patch.object(fu.requests, "get", return_value=response),
            # Finished on a second check, so that a loop which carried on
            # past the None would end, as a failure, rather than hang
            patch.object(fu, "_entity_finished", side_effect=[None, True]) as finished,
            patch.object(fu, "print_info") as mock_info,
            patch.object(fu, "sleep"),
        ):
            fu.follow_events(
                _ctx(), "ydid:workreq:000000:aaa:bbb", YDIDType.WORK_REQUIREMENT
            )
        finished.assert_called_once()
        assert not any(
            "concluded" in str(call.args[0]) for call in mock_info.call_args_list
        )


class TestFollowErrorFlag:
    """
    Tests for the follow-error flag consulted by yd-follow's exit code.
    """

    def test_flag_initially_clear(self):
        assert fu.follow_errors_occurred() is False

    def test_invalid_ydid_sets_flag(self):
        args_parser = MagicMock(progress=False, print_pid=False)
        with (
            patch.object(wrapper_module, "ARGS_PARSER", args_parser),
            patch.object(fu, "print_error") as mock_error,
        ):
            valid = fu.follow_ids(_ctx(), ["ydid:nonsense:000000:aaa:bbb"])
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
                _ctx(), "ydid:workreq:000000:aaa:bbb", fu.YDIDType.WORK_REQUIREMENT
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
                _ctx(), "ydid:workreq:000000:aaa:bbb", fu.YDIDType.WORK_REQUIREMENT
            )
        mock_error.assert_called_once()
        assert fu.follow_errors_occurred() is True


# ---------------------------------------------------------------------------
# Reconnection, a clean close, the exit code and the order of the streams
# ---------------------------------------------------------------------------

WR = "ydid:workreq:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _stream(lines=(), raises: Exception | None = None, status: int = 200):
    """
    A response to requests.get(): 'lines', then 'raises' if given.
    """
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
    """
    monotonic() and sleep() together: sleeping advances the clock.
    """

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
        fu.follow_events(_ctx(), WR, fu.YDIDType.WORK_REQUIREMENT)
        assert clock.sleeps == [5.0, 10.0, 20.0, 30.0]
        assert fu.follow_exit_code() == fu.ExitCode.SUCCESS

    def test_an_outage_over_five_minutes_gives_up_with_exit_8(self, clock, monkeypatch):
        dropped = requests.exceptions.ConnectionError("dropped")
        monkeypatch.setattr(
            fu.requests,
            "get",
            MagicMock(side_effect=[_stream(raises=dropped)] + [dropped] * 100),
        )
        fu.follow_events(_ctx(), WR, fu.YDIDType.WORK_REQUIREMENT)
        assert clock.now >= 300
        assert clock.now < 300 + 30
        assert fu.follow_exit_code() == fu.ExitCode.CONNECTION

    def test_a_connection_that_keeps_dropping_at_once_is_given_up(
        self, clock, monkeypatch
    ):
        # Accepted each time, and dropped before any event: one outage, which
        # ends in exit 8 like a connection refused, not a reconnection for ever
        dropped = requests.exceptions.ConnectionError("dropped")
        responses = [_stream(["data: 1"], raises=dropped)] + [
            _stream(raises=dropped) for _ in range(100)
        ]
        get = MagicMock(side_effect=responses)
        monkeypatch.setattr(fu.requests, "get", get)
        errors: list[str] = []
        monkeypatch.setattr(fu, "print_error", lambda m, **k: errors.append(m))
        fu.follow_events(_ctx(), WR, fu.YDIDType.WORK_REQUIREMENT)
        assert 300 <= clock.now < 300 + 30
        assert get.call_count < 100
        assert errors == [f"Unable to reconnect to the event stream for '{WR}'"]
        assert fu.follow_exit_code() == fu.ExitCode.CONNECTION

    def test_a_stream_delivering_between_drops_is_kept_up(self, clock, monkeypatch):
        # Each connection delivers before it drops: each drop is a new outage,
        # waited out from the first interval again
        dropped = requests.exceptions.ConnectionError("dropped")
        responses = [_stream([f"data: {n}"], raises=dropped) for n in range(5)]
        monkeypatch.setattr(
            fu.requests,
            "get",
            MagicMock(side_effect=[*responses, _stream(["data: 5"])]),
        )
        _finished(monkeypatch, True)
        fu.follow_events(_ctx(), WR, fu.YDIDType.WORK_REQUIREMENT)
        assert clock.sleeps == [5.0] * 5
        assert fu.follow_exit_code() == fu.ExitCode.SUCCESS

    def test_a_first_connection_that_fails_is_not_retried(self, clock, monkeypatch):
        get = MagicMock(side_effect=requests.exceptions.ConnectionError("no"))
        monkeypatch.setattr(fu.requests, "get", get)
        fu.follow_events(_ctx(), WR, fu.YDIDType.WORK_REQUIREMENT)
        assert get.call_count == 1
        assert clock.sleeps == []
        assert fu.follow_exit_code() == fu.ExitCode.CONNECTION


class TestCleanClose:
    def test_a_close_while_the_entity_is_live_reconnects(self, clock, monkeypatch):
        get = MagicMock(side_effect=[_stream(["data: 1"]), _stream(["data: 2"])])
        monkeypatch.setattr(fu.requests, "get", get)
        finished = _finished(monkeypatch, False, True)
        fu.follow_events(_ctx(), WR, fu.YDIDType.WORK_REQUIREMENT)
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
        monkeypatch.setattr(wrapper_module, "CLIENT", client)
        assert (
            fu._entity_finished(_ctx(), "x", getattr(fu.YDIDType, ydid_type))
            is finished
        )

    def test_a_status_that_cannot_be_fetched_is_taken_as_finished(self, monkeypatch):
        client = MagicMock()
        client.work_client.get_work_requirement_by_id.side_effect = RuntimeError("no")
        monkeypatch.setattr(wrapper_module, "CLIENT", client)
        monkeypatch.setattr(fu, "print_warning", lambda *a, **k: None)
        assert fu._entity_finished(_ctx(), "x", fu.YDIDType.WORK_REQUIREMENT) is True


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
        fu.follow_events(_ctx(), WR, fu.YDIDType.WORK_REQUIREMENT)
        assert fu.follow_exit_code() == code

    def test_failures_with_different_causes_exit_1(self, clock, monkeypatch):
        monkeypatch.setattr(
            fu.requests,
            "get",
            MagicMock(side_effect=[_stream(status=404), _stream(status=401)]),
        )
        fu.follow_events(_ctx(), WR, fu.YDIDType.WORK_REQUIREMENT)
        fu.follow_events(_ctx(), WR, fu.YDIDType.WORK_REQUIREMENT)
        assert fu.follow_exit_code() == fu.ExitCode.FAILURE


class TestFollowIds:
    def test_the_order_given_is_kept(self, monkeypatch):
        started = []
        monkeypatch.setattr(
            wrapper_module, "ARGS_PARSER", MagicMock(progress=False, print_pid=False)
        )
        monkeypatch.setattr(fu, "print_info", lambda *a, **k: None)
        monkeypatch.setattr(fu, "print_warning", lambda *a, **k: None)
        monkeypatch.setattr(
            fu, "follow_events", lambda _ctx, ydid, ydid_type: started.append(ydid)
        )
        ids = [
            f"ydid:workreq:000000:{c * 8}-aaaa-aaaa-aaaa-aaaaaaaaaaaa" for c in "edcba"
        ]
        valid = fu.follow_ids(_ctx(), ids + ids[:2])
        assert valid == ids

    def test_a_timeout_stops_every_stream(self, monkeypatch):
        # yd-wait --timeout: the main thread gives up at the deadline and
        # tells the streams to stop, rather than waiting for them
        warnings = []
        monkeypatch.setattr(
            wrapper_module, "ARGS_PARSER", MagicMock(progress=False, print_pid=False)
        )
        monkeypatch.setattr(fu, "print_info", lambda *a, **k: None)
        monkeypatch.setattr(fu, "print_warning", lambda m, **k: warnings.append(m))
        stopped = []

        def stream(_ctx, ydid, ydid_type):
            fu._STOP_FOLLOWING.wait(5)
            stopped.append(fu._STOP_FOLLOWING.is_set())

        monkeypatch.setattr(fu, "follow_events", stream)
        fu.follow_ids(_ctx(), [WR], timeout=0.2)
        assert fu._STOP_FOLLOWING.is_set()
        assert warnings == ["Stopped following after 0.2 second(s)"]
        for _ in range(50):
            if stopped:
                break
            fu.sleep(0.02)
        assert stopped == [True]

    def test_following_again_clears_the_stop(self, monkeypatch):
        monkeypatch.setattr(
            wrapper_module, "ARGS_PARSER", MagicMock(progress=False, print_pid=False)
        )
        monkeypatch.setattr(fu, "print_info", lambda *a, **k: None)
        fu._STOP_FOLLOWING.set()
        seen = []
        monkeypatch.setattr(
            fu,
            "follow_events",
            lambda _ctx, ydid, ydid_type: seen.append(fu._STOP_FOLLOWING.is_set()),
        )
        fu.follow_ids(_ctx(), [WR])
        assert seen == [False]

    def test_an_auto_cr_lookup_failure_is_recorded(self, monkeypatch):
        client = MagicMock()
        client.worker_pool_client.get_worker_pool_by_id.side_effect = _http_404()
        monkeypatch.setattr(wrapper_module, "CLIENT", client)
        monkeypatch.setattr(fu, "print_error", lambda *a, **k: None)
        assert (
            fu._compute_requirement_of_worker_pool(_ctx(), "ydid:wrkrpool:000000:x")
            is None
        )
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


class TestStreamFailures:
    """
    follow_events()'s other ways out of a stream: a quiet one's read timeout
    reconnected silently, an unexpected error stopping it with its own exit
    code, a refused one whose body says nothing readable, and a stop asked
    for during or after a stream.
    """

    def test_a_read_timeout_reconnects_without_a_warning(self, clock, monkeypatch):
        quiet = _stream(["data: 1"], raises=requests.exceptions.ReadTimeout("quiet"))
        quiet.encoding = None  # Set to UTF-8 when a stream names none
        get = MagicMock(side_effect=[quiet, _stream(["data: 2"])])
        monkeypatch.setattr(fu.requests, "get", get)
        warnings: list[str] = []
        monkeypatch.setattr(fu, "print_warning", lambda m, **k: warnings.append(m))
        _finished(monkeypatch, True)
        fu.follow_events(_ctx(), WR, fu.YDIDType.WORK_REQUIREMENT)
        assert get.call_count == 2
        assert quiet.encoding == "utf-8"
        assert warnings == []
        assert clock.sleeps == []  # Straight back, not as an outage
        assert fu.follow_exit_code() == fu.ExitCode.SUCCESS

    def test_an_unexpected_error_stops_the_stream_with_its_code(
        self, clock, monkeypatch
    ):
        get = MagicMock(side_effect=[_stream(["data: 1"], raises=ValueError("odd"))])
        monkeypatch.setattr(fu.requests, "get", get)
        errors: list[str] = []
        monkeypatch.setattr(fu, "print_error", lambda m, **k: errors.append(m))
        finished = _finished(monkeypatch)
        fu.follow_events(_ctx(), WR, fu.YDIDType.WORK_REQUIREMENT)
        assert get.call_count == 1  # Not reconnected
        finished.assert_not_called()
        assert errors == ["Event stream error: odd"]
        assert fu.follow_exit_code() == fu.ExitCode.FAILURE

    def test_a_refused_stream_with_an_unreadable_body_keeps_its_status(
        self, clock, monkeypatch
    ):
        refused = _stream(status=404)
        refused.json.side_effect = ValueError("not JSON")
        monkeypatch.setattr(fu.requests, "get", MagicMock(return_value=refused))
        errors: list[str] = []
        monkeypatch.setattr(fu, "print_error", lambda m, **k: errors.append(m))
        fu.follow_events(_ctx(), WR, fu.YDIDType.WORK_REQUIREMENT)
        assert errors == [f"'{WR}': (JSON error cannot be decoded)"]
        assert fu.follow_exit_code() == fu.ExitCode.NOT_FOUND

    def test_a_stop_during_a_stream_ends_it_unconcluded(self, clock, monkeypatch):
        seen: list[str] = []

        def on_event(event, ydid_type):
            seen.append(event)
            fu._STOP_FOLLOWING.set()  # As --timeout does, from the main thread

        get = MagicMock(side_effect=[_stream(["data: 1", "data: 2"])])
        monkeypatch.setattr(fu.requests, "get", get)
        infos: list[str] = []
        monkeypatch.setattr(fu, "print_info", lambda m, **k: infos.append(m))
        finished = _finished(monkeypatch)
        try:
            fu.follow_events(
                _ctx(), WR, fu.YDIDType.WORK_REQUIREMENT, on_event=on_event
            )
        finally:
            fu._STOP_FOLLOWING.clear()
        assert seen == ["data: 1"]  # Given to on_event, and the rest not read
        finished.assert_not_called()
        assert not any("concluded" in info for info in infos)

    def test_a_stop_after_a_clean_close_is_not_reconnected(self, clock, monkeypatch):
        closed = _stream(["data: 1"])
        closed.iter_lines.side_effect = lambda decode_unicode=True: (
            fu._STOP_FOLLOWING.set() or iter([])
        )
        get = MagicMock(side_effect=[closed])
        monkeypatch.setattr(fu.requests, "get", get)
        finished = _finished(monkeypatch)
        try:
            fu.follow_events(_ctx(), WR, fu.YDIDType.WORK_REQUIREMENT)
        finally:
            fu._STOP_FOLLOWING.clear()
        assert get.call_count == 1
        finished.assert_not_called()

    @pytest.mark.parametrize(
        "ydid_type, path",
        [
            ("WORK_REQUIREMENT", "work/requirements"),
            ("WORKER_POOL", "workerPools"),
            ("COMPUTE_REQUIREMENT", "compute/requirements"),
        ],
    )
    def test_each_type_has_its_own_event_url(self, ydid_type, path):
        ctx = SimpleNamespace(config=SimpleNamespace(url="https://api.example"))
        url = fu.get_event_url(ctx, "id", fu.YDIDType[ydid_type])  # type: ignore[arg-type]
        assert url == f"https://api.example/{path}/id/updates"


class TestFollowIdsChoices:
    """
    follow_ids()'s choices before the streams start: a Provisioned Worker
    Pool's Compute Requirement followed too under auto_cr, '--progress' given
    up for more than one Work Requirement, and a thread that cannot start.
    """

    @pytest.fixture
    def started(self, monkeypatch):
        started: list[str] = []
        monkeypatch.setattr(fu, "print_info", lambda *a, **k: None)
        monkeypatch.setattr(
            fu, "follow_events", lambda _ctx, ydid, ydid_type: started.append(ydid)
        )
        return started

    def _args(self, monkeypatch, progress=False):
        monkeypatch.setattr(
            wrapper_module,
            "ARGS_PARSER",
            MagicMock(progress=progress, print_pid=False),
        )

    def test_no_ids_follow_nothing(self, started):
        assert fu.follow_ids(_ctx(), []) == []
        assert started == []

    def test_auto_cr_follows_the_worker_pools_compute_requirement(
        self, started, monkeypatch
    ):
        self._args(monkeypatch)
        pool = "ydid:wrkrpool:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        compute = "ydid:compreq:000000:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        monkeypatch.setattr(
            fu, "_compute_requirement_of_worker_pool", lambda _ctx, ydid: compute
        )
        valid = fu.follow_ids(_ctx(), [pool], auto_cr=True)
        assert valid == [pool]  # The IDs given, before the expansion
        assert sorted(started) == sorted([pool, compute])

    def test_progress_is_given_up_for_two_work_requirements(self, started, monkeypatch):
        self._args(monkeypatch, progress=True)
        warnings: list[str] = []
        monkeypatch.setattr(fu, "print_warning", lambda m, **k: warnings.append(m))
        other = WR.replace("aaaaaaaa-", "cccccccc-")
        fu.follow_ids(_ctx(), [WR, other])
        assert sorted(started) == sorted([WR, other])  # Plain following
        assert any("single Work Requirement" in w for w in warnings)

    def test_a_thread_that_cannot_start_is_recorded(self, started, monkeypatch):
        self._args(monkeypatch)
        errors: list[str] = []
        monkeypatch.setattr(fu, "print_error", lambda m, **k: errors.append(m))

        class _Refused:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                raise RuntimeError("can't start new thread")

        monkeypatch.setattr(fu, "Thread", _Refused)
        assert fu.follow_ids(_ctx(), [WR]) == [WR]
        assert errors and "Unable to start event thread" in errors[0]
        assert fu.follow_exit_code() == fu.ExitCode.FAILURE

    def test_progress_follows_a_single_work_requirement_with_the_bar(
        self, started, monkeypatch
    ):
        self._args(monkeypatch, progress=True)
        barred: list[str] = []
        monkeypatch.setattr(
            fu,
            "follow_work_requirement_with_progress",
            lambda _ctx, ydid: barred.append(ydid),
        )
        fu.follow_ids(_ctx(), [WR])
        assert barred == [WR]
        assert started == []

    def test_only_a_provisioned_worker_pool_has_a_compute_requirement(
        self, monkeypatch
    ):
        from yellowdog_client.model import ConfiguredWorkerPool, ProvisionedWorkerPool

        provisioned = object.__new__(ProvisionedWorkerPool)
        provisioned.computeRequirementId = "ydid:compreq:000000:x"
        configured = object.__new__(ConfiguredWorkerPool)
        client = MagicMock()
        monkeypatch.setattr(wrapper_module, "CLIENT", client)
        client.worker_pool_client.get_worker_pool_by_id.return_value = provisioned
        assert (
            fu._compute_requirement_of_worker_pool(_ctx(), "pool")
            == "ydid:compreq:000000:x"
        )
        client.worker_pool_client.get_worker_pool_by_id.return_value = configured
        assert fu._compute_requirement_of_worker_pool(_ctx(), "pool") is None
