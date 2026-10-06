"""
Tests for the sequential vs parallel batch task submission logic in
add_tasks_to_task_group (submit.py), and for the retrying of a batch that
fails in submit_batch_of_tasks_to_task_group.
"""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import requests
from yellowdog_client.model import TaskGroup, WorkRequirement
from yellowdog_client.model.exceptions.invalid_request_exception import (
    InvalidRequestException,
)
from yellowdog_client.model.exceptions.not_authorised_exception import (
    NotAuthorisedException,
)

import yellowdog_cli.submit as submit_module
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.exit_codes import ExitCode, classify
from yellowdog_cli.utils.limits import (
    BATCH_SUBMIT_RETRY_DELAY,
    MAX_BATCH_SUBMIT_ATTEMPTS,
    TASK_BATCH_SIZE_DEFAULT,
)
from yellowdog_cli.utils.property_names import TASK_GROUPS, TASKS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_wr_data(num_tasks: int) -> dict:
    return {TASK_GROUPS: [{TASKS: [{} for _ in range(num_tasks)]}]}


def _make_tg(name: str = "grp") -> TaskGroup:
    tg = MagicMock(spec=TaskGroup)
    tg.name = name
    return tg


def _make_wr(name: str = "my-wr") -> WorkRequirement:
    wr = MagicMock(spec=WorkRequirement)
    wr.name = name
    return wr


def _run_add_tasks(
    num_tasks: int,
    batch_size: int,
    parallel_batches: int,
    pause_flag: int | None = None,
    task_count: int | None = None,
) -> dict:
    """
    Call add_tasks_to_task_group with generate/submit mocked out.

    Returns:
      generate_calls: list of (start, end) tuples — one per batch, in call order
      submit_calls:   list of task-counts per batch (order may vary in parallel mode)
      pause_mock:     the mock replacing the pause_between_batches function
      wr_data:        the Work Requirement data, as add_tasks_to_task_group left it

    'task_count' is passed as the no-specification path passes it, with the
    configuration's 'taskCount' the same.
    """
    config_wr_mock = MagicMock()
    config_wr_mock.task_count = task_count
    config_wr_mock.parallel_batches = None
    wr_data = _make_wr_data(num_tasks)
    pause_mock = MagicMock()

    generate_calls: list[tuple[int, int]] = []
    submit_calls: list[int] = []

    def fake_generate(start, end, *args, **kwargs):
        generate_calls.append((start, end))
        return [MagicMock()] * (end - start)

    def fake_submit(tasks_list, *args, **kwargs):
        submit_calls.append(len(tasks_list))
        return len(tasks_list)

    with (
        patch.object(submit_module, "TASK_BATCH_SIZE", batch_size),
        patch.object(submit_module, "CONFIG_WR", config_wr_mock),
        patch.object(
            submit_module,
            "generate_batch_of_tasks_for_task_group",
            side_effect=fake_generate,
        ),
        patch.object(
            submit_module,
            "submit_batch_of_tasks_to_task_group",
            side_effect=fake_submit,
        ),
        patch.object(submit_module, "pause_between_batches", pause_mock),
        patch.object(
            CLIParser,
            "parallel_batches",
            new_callable=PropertyMock,
            return_value=parallel_batches,
        ),
        patch.object(
            CLIParser,
            "pause_between_batches",
            new_callable=PropertyMock,
            return_value=pause_flag,
        ),
        patch.object(
            CLIParser,
            "dry_run",
            new_callable=PropertyMock,
            return_value=False,
        ),
    ):
        submit_module.add_tasks_to_task_group(
            tg_number=0,
            task_group=_make_tg(),
            wr_data=wr_data,
            task_count=task_count,
            work_requirement=_make_wr(),
            files_directory=".",
        )

    return {
        "generate_calls": generate_calls,
        "submit_calls": submit_calls,
        "pause_mock": pause_mock,
        "wr_data": wr_data,
    }


def _run_add_tasks_tracking_tpe(
    num_tasks: int,
    batch_size: int,
    parallel_batches: int,
) -> list[int]:
    """
    Like _run_add_tasks but wraps ThreadPoolExecutor to capture the
    max_workers value(s) it was constructed with.
    """
    captured_max_workers: list[int] = []
    original_tpe = ThreadPoolExecutor

    def tracking_tpe(max_workers=None):
        captured_max_workers.append(max_workers)
        return original_tpe(max_workers=max_workers)

    config_wr_mock = MagicMock()
    config_wr_mock.task_count = None
    config_wr_mock.parallel_batches = None

    def fake_generate(start, end, *args, **kwargs):
        return [MagicMock()] * (end - start)

    def fake_submit(tasks_list, *args, **kwargs):
        return len(tasks_list)

    with (
        patch.object(submit_module, "TASK_BATCH_SIZE", batch_size),
        patch.object(submit_module, "CONFIG_WR", config_wr_mock),
        patch.object(
            submit_module,
            "generate_batch_of_tasks_for_task_group",
            side_effect=fake_generate,
        ),
        patch.object(
            submit_module,
            "submit_batch_of_tasks_to_task_group",
            side_effect=fake_submit,
        ),
        patch.object(submit_module, "pause_between_batches"),
        patch.object(submit_module, "ThreadPoolExecutor", side_effect=tracking_tpe),
        patch.object(
            CLIParser,
            "parallel_batches",
            new_callable=PropertyMock,
            return_value=parallel_batches,
        ),
        patch.object(
            CLIParser,
            "pause_between_batches",
            new_callable=PropertyMock,
            return_value=None,
        ),
        patch.object(
            CLIParser,
            "dry_run",
            new_callable=PropertyMock,
            return_value=False,
        ),
    ):
        submit_module.add_tasks_to_task_group(
            tg_number=0,
            task_group=_make_tg(),
            wr_data=_make_wr_data(num_tasks),
            task_count=None,
            work_requirement=_make_wr(),
            files_directory=".",
        )

    return captured_max_workers


# ---------------------------------------------------------------------------
# Sequential path
# ---------------------------------------------------------------------------


class TestSequentialBatching:
    """
    Sequential path: parallel_batches == 1, or num_task_batches == 1.
    """

    def test_single_batch_calls_generate_and_submit_once(self):
        result = _run_add_tasks(num_tasks=5, batch_size=10, parallel_batches=1)
        assert len(result["generate_calls"]) == 1
        assert len(result["submit_calls"]) == 1

    def test_multiple_batches_calls_generate_and_submit_per_batch(self):
        # 9 tasks / batch_size 3 → 3 batches
        result = _run_add_tasks(num_tasks=9, batch_size=3, parallel_batches=1)
        assert len(result["generate_calls"]) == 3
        assert len(result["submit_calls"]) == 3

    def test_batch_ranges_are_contiguous_and_correct(self):
        result = _run_add_tasks(num_tasks=9, batch_size=3, parallel_batches=1)
        assert result["generate_calls"] == [(0, 3), (3, 6), (6, 9)]

    def test_last_batch_covers_remaining_tasks(self):
        # 7 tasks / batch_size 3 → [0,3), [3,6), [6,7)
        result = _run_add_tasks(num_tasks=7, batch_size=3, parallel_batches=1)
        assert result["generate_calls"] == [(0, 3), (3, 6), (6, 7)]

    def test_pause_between_batches_called_for_each_batch(self):
        result = _run_add_tasks(
            num_tasks=9, batch_size=3, parallel_batches=1, pause_flag=5
        )
        assert result["pause_mock"].call_count == 3

    def test_pause_between_batches_not_called_when_flag_is_none(self):
        result = _run_add_tasks(
            num_tasks=9, batch_size=3, parallel_batches=1, pause_flag=None
        )
        result["pause_mock"].assert_not_called()

    def test_single_batch_forces_sequential_even_with_high_parallel_setting(self):
        # num_task_batches == 1 → sequential path, regardless of parallel_batches
        result = _run_add_tasks(num_tasks=3, batch_size=10, parallel_batches=8)
        assert len(result["generate_calls"]) == 1
        assert len(result["submit_calls"]) == 1

    def test_total_submitted_matches_num_tasks(self):
        result = _run_add_tasks(num_tasks=7, batch_size=3, parallel_batches=1)
        assert sum(result["submit_calls"]) == 7


# ---------------------------------------------------------------------------
# Parallel path
# ---------------------------------------------------------------------------


class TestParallelBatching:
    """
    Parallel path: parallel_batches > 1 and num_task_batches > 1.
    """

    def test_generate_called_once_per_batch(self):
        result = _run_add_tasks(num_tasks=9, batch_size=3, parallel_batches=3)
        assert len(result["generate_calls"]) == 3

    def test_submit_called_once_per_batch(self):
        result = _run_add_tasks(num_tasks=9, batch_size=3, parallel_batches=3)
        assert len(result["submit_calls"]) == 3

    def test_generation_is_sequential_in_main_thread(self):
        # generate_batch_of_tasks_for_task_group is called in the for loop
        # before executor.submit, so calls are always in ascending order
        result = _run_add_tasks(num_tasks=9, batch_size=3, parallel_batches=3)
        assert result["generate_calls"] == [(0, 3), (3, 6), (6, 9)]

    def test_last_batch_covers_remaining_tasks(self):
        result = _run_add_tasks(num_tasks=7, batch_size=3, parallel_batches=3)
        assert sorted(result["generate_calls"]) == [(0, 3), (3, 6), (6, 7)]

    def test_total_submitted_matches_num_tasks(self):
        result = _run_add_tasks(num_tasks=7, batch_size=3, parallel_batches=3)
        assert sum(result["submit_calls"]) == 7

    def test_pause_between_batches_not_called(self):
        result = _run_add_tasks(
            num_tasks=9, batch_size=3, parallel_batches=3, pause_flag=5
        )
        result["pause_mock"].assert_not_called()

    def test_max_workers_capped_at_num_task_batches(self):
        # 9 tasks / batch_size 3 = 3 batches; parallel_batches=10 → max_workers=3
        captured = _run_add_tasks_tracking_tpe(
            num_tasks=9, batch_size=3, parallel_batches=10
        )
        assert captured == [3]

    def test_max_workers_equals_parallel_batches_when_less_than_num_batches(self):
        # 6 batches, parallel_batches=2 → max_workers=2
        captured = _run_add_tasks_tracking_tpe(
            num_tasks=18, batch_size=3, parallel_batches=2
        )
        assert captured == [2]

    def test_max_workers_equals_num_batches_when_equal_to_parallel_setting(self):
        # 4 batches, parallel_batches=4 → max_workers=4
        captured = _run_add_tasks_tracking_tpe(
            num_tasks=12, batch_size=3, parallel_batches=4
        )
        assert captured == [4]


# ---------------------------------------------------------------------------
# A Task Group with no Tasks
# ---------------------------------------------------------------------------


class TestNoTasks:
    """
    A Task Group with no Tasks has no batches. With parallel batches asked
    for, it used to reach the parallel path and build a ThreadPoolExecutor of
    no workers, which raises.
    """

    def test_no_pool_is_built_with_parallel_batches(self):
        assert (
            _run_add_tasks_tracking_tpe(num_tasks=0, batch_size=3, parallel_batches=4)
            == []
        )

    def test_nothing_is_generated_or_submitted(self):
        result = _run_add_tasks(num_tasks=0, batch_size=3, parallel_batches=4)
        assert result["generate_calls"] == []
        assert result["submit_calls"] == []


# ---------------------------------------------------------------------------
# Expanding 'taskCount'
# ---------------------------------------------------------------------------


class TestTaskCountExpansion:
    """
    With 'task_count' given (no specification file), every Task is generated
    from the first, so copying it 'taskCount' times only built dicts to go
    unread. From a specification, the copies are what is generated from.
    """

    def test_no_copies_are_made_when_task_count_is_given(self):
        result = _run_add_tasks(
            num_tasks=1, batch_size=10, parallel_batches=1, task_count=1000
        )
        assert len(result["wr_data"][TASK_GROUPS][0][TASKS]) == 1
        assert sum(result["submit_calls"]) == 1000

    def test_copies_are_still_made_from_a_specification(self):
        # task_count None, but the specification's taskCount, read here
        # through the configuration, is 5
        config_wr_mock = MagicMock(
            task_count=5, parallel_batches=None, task_batch_size=TASK_BATCH_SIZE_DEFAULT
        )
        wr_data = _make_wr_data(1)
        with (
            patch.object(submit_module, "CONFIG_WR", config_wr_mock),
            patch.object(
                submit_module,
                "generate_batch_of_tasks_for_task_group",
                side_effect=lambda start, end, *a, **k: [MagicMock()] * (end - start),
            ),
            patch.object(
                submit_module,
                "submit_batch_of_tasks_to_task_group",
                side_effect=lambda tasks_list, *a, **k: len(tasks_list),
            ),
            patch.object(
                CLIParser, "parallel_batches", new_callable=PropertyMock, return_value=1
            ),
            patch.object(
                CLIParser,
                "pause_between_batches",
                new_callable=PropertyMock,
                return_value=None,
            ),
            patch.object(
                CLIParser, "dry_run", new_callable=PropertyMock, return_value=False
            ),
        ):
            submit_module.add_tasks_to_task_group(
                tg_number=0,
                task_group=_make_tg(),
                wr_data=wr_data,
                task_count=None,
                work_requirement=_make_wr(),
            )
        assert len(wr_data[TASK_GROUPS][0][TASKS]) == 5


# ---------------------------------------------------------------------------
# Retrying a batch that fails
# ---------------------------------------------------------------------------


_DUPLICATE_NAMES = "Task names must be unique within task group"


class TestBatchSubmitRetries:
    """
    submit_batch_of_tasks_to_task_group() against a stubbed Platform call.
    """

    def _submit(self, side_effect) -> dict:
        add_tasks = MagicMock(side_effect=side_effect)
        sleep_mock = MagicMock()
        outcome: dict = {"add_tasks": add_tasks, "sleep": sleep_mock}
        with (
            patch.object(
                submit_module.CLIENT.work_client,
                "add_tasks_to_task_group_by_name",
                add_tasks,
            ),
            patch.object(submit_module, "sleep", sleep_mock),
            patch.object(
                CLIParser, "dry_run", new_callable=PropertyMock, return_value=False
            ),
        ):
            try:
                outcome["result"] = submit_module.submit_batch_of_tasks_to_task_group(
                    [MagicMock(), MagicMock()],
                    _make_wr(),
                    _make_tg(),
                    num_task_batches=1,
                    batch_number=0,
                    task_batch_size=10,
                    total_num_tasks=2,
                )
            except Exception as e:
                outcome["raised"] = e
        return outcome

    def test_duplicate_names_on_the_first_attempt_is_a_failure(self):
        # A second answer is there to be taken, and must not be: a retry
        # would see the same collision and report it as success
        error = Exception(_DUPLICATE_NAMES)
        outcome = self._submit([error, Exception(_DUPLICATE_NAMES)])
        assert outcome["raised"] is error
        assert outcome["add_tasks"].call_count == 1

    def test_duplicate_names_on_a_retry_is_the_earlier_attempt_succeeding(self):
        outcome = self._submit(
            [Exception("502 Bad Gateway"), Exception(_DUPLICATE_NAMES)]
        )
        assert "raised" not in outcome
        assert outcome["result"] == 2

    def test_duplicate_names_as_an_invalid_request_on_a_retry_is_success_too(self):
        outcome = self._submit(
            [Exception("502 Bad Gateway"), InvalidRequestException(_DUPLICATE_NAMES)]
        )
        assert outcome["result"] == 2

    def test_refused_credentials_are_not_retried(self):
        error = NotAuthorisedException("Unauthorized")
        outcome = self._submit([error, None])
        assert outcome["raised"] is error
        assert outcome["add_tasks"].call_count == 1
        outcome["sleep"].assert_not_called()
        assert classify(outcome["raised"]) == ExitCode.AUTHENTICATION

    def test_an_invalid_request_is_not_retried(self):
        outcome = self._submit([InvalidRequestException("bad task"), None])
        assert isinstance(outcome["raised"], InvalidRequestException)
        assert outcome["add_tasks"].call_count == 1

    def test_a_transient_failure_is_retried_with_a_growing_delay(self):
        outcome = self._submit([Exception("502"), Exception("502"), None])
        assert outcome["result"] == 2
        assert [c.args[0] for c in outcome["sleep"].call_args_list] == [
            BATCH_SUBMIT_RETRY_DELAY,
            BATCH_SUBMIT_RETRY_DELAY * 2,
        ]

    def test_the_last_failure_is_raised_as_it_is_so_its_kind_reaches_the_exit_code(
        self,
    ):
        errors = [
            requests.ConnectionError(f"attempt {n}")
            for n in range(MAX_BATCH_SUBMIT_ATTEMPTS)
        ]
        outcome = self._submit(errors)
        assert outcome["raised"] is errors[-1]
        assert outcome["add_tasks"].call_count == MAX_BATCH_SUBMIT_ATTEMPTS
        assert classify(outcome["raised"]) == ExitCode.CONNECTION


class TestBatchesStopAfterAFailure:
    """
    Once a batch fails, those not yet started are skipped: the Work
    Requirement is about to be cancelled. Each batch checks as it starts, so
    this holds even for a single thread, which takes the next batch before
    the failure could be seen and the queue cancelled.
    """

    @pytest.mark.parametrize("threads", [1, 2])
    def test_later_batches_are_skipped(self, threads):
        started: list[int] = []

        def batch(number: int) -> int:
            started.append(number)
            if number == 1:
                raise RuntimeError("refused")
            return 10

        with ThreadPoolExecutor(max_workers=threads) as executor:
            batches = submit_module._Batches(executor)
            for number in range(6):
                batches.submit(batch, number)
            with pytest.raises(RuntimeError, match="refused"):
                batches.total()
        assert 1 in started
        if threads == 1:
            assert started == [0, 1]
        assert len(started) < 6

    def test_all_batches_succeeding_are_totalled(self):
        with ThreadPoolExecutor(max_workers=3) as executor:
            batches = submit_module._Batches(executor)
            for number in range(5):
                batches.submit(lambda n: n + 1, number)
            assert batches.total() == 15
