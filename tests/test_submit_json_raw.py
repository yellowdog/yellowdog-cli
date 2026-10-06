"""
Tests for 'yd-submit --json-raw' (submit_json_raw in submit.py): a failure
is raised as an HTTPError carrying the Platform's response, so that the exit
code names it, and a Work Requirement left with only some of its Tasks is
cancelled, as one built from a specification is.
"""

from contextlib import ExitStack
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import requests

import yellowdog_cli.submit as submit_module
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import ExitCode, classify
from yellowdog_cli.utils.limits import MAX_BATCH_SUBMIT_ATTEMPTS, RAW_REQUEST_TIMEOUT


def _ctx() -> RunContext:
    """
    The context a command is given: the wrapper's values, as patched.
    """
    return RunContext(
        wrapper_module.ARGS_PARSER, wrapper_module.CONFIG_COMMON, wrapper_module.CLIENT
    )


WR_ID = "ydid:workreq:000000:00000000-0000-0000-0000-000000000000"


def _response(status_code: int, text: str = "") -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.text = text
    return response


def _wr_data() -> dict:
    return {
        "name": "raw-wr",
        "namespace": "ns",
        "taskGroups": [
            {"name": "tg-1", "tasks": [{"taskType": "bash"}] * 3},
            {"name": "tg-2", "tasks": [{"taskType": "bash"}]},
        ],
    }


def _submit(responses: list[MagicMock], **flag_overrides) -> dict:
    """
    Run submit_json_raw with each POST answered by the next response in
    turn, the last repeating once the list is used up: the Work
    Requirement's first, then its Task batches and their retries. Batches of
    one Task, submitted one at a time, so the order is fixed.
    """
    remaining = list(responses)

    def answer(*args, **kwargs):
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    post = MagicMock(side_effect=answer)
    client = MagicMock()
    sleep = MagicMock()
    outcome: dict = {"post": post, "client": client, "sleep": sleep}
    flags = {
        "dry_run": False,
        "hold": False,
        "follow": False,
        "progress": False,
        "parallel_batches": None,
        **flag_overrides,
    }
    with ExitStack() as stack:
        for patcher in (
            patch.object(submit_module.requests, "post", post),
            patch.object(wrapper_module, "CLIENT", client),
            patch.object(wrapper_module, "CONFIG_COMMON", MagicMock(url="https://x")),
            patch.object(submit_module, "TASK_BATCH_SIZE", 1),
            patch.object(submit_module, "sleep", sleep),
            patch.object(
                submit_module,
                "load_json_file_with_variable_substitutions",
                return_value=_wr_data(),
            ),
            patch.object(submit_module, "add_substitutions_without_overwriting"),
            patch.object(submit_module, "record_entity"),
            patch.object(submit_module, "print_quiet_result"),
            *(
                patch.object(
                    CLIParser, flag, new_callable=PropertyMock, return_value=value
                )
                for flag, value in flags.items()
            ),
        ):
            stack.enter_context(patcher)
        try:
            submit_module.submit_json_raw(_ctx(), "raw.json")
        except Exception as e:
            outcome["raised"] = e
    return outcome


def _created() -> MagicMock:
    return _response(200, f'{{"id": "{WR_ID}"}}')


class TestJsonRawSuccess:
    def test_every_batch_is_posted_and_nothing_is_cancelled(self):
        outcome = _submit([_created()] + [_response(200)] * 4)
        assert "raised" not in outcome
        assert outcome["post"].call_count == 5
        outcome["client"].work_client.cancel_work_requirement_by_id.assert_not_called()


class TestJsonRawWorkRequirementRefused:
    def test_the_failure_carries_its_status_to_the_exit_code(self):
        outcome = _submit([_response(401, "Unauthorized")])
        assert isinstance(outcome["raised"], requests.HTTPError)
        assert classify(outcome["raised"]) == ExitCode.AUTHENTICATION

    def test_the_platform_explanation_is_the_message(self):
        outcome = _submit([_response(400, "name is invalid")])
        assert "name is invalid" in str(outcome["raised"])

    def test_nothing_was_created_so_nothing_is_cancelled(self):
        outcome = _submit([_response(500, "boom")])
        outcome["client"].work_client.cancel_work_requirement_by_id.assert_not_called()


class TestJsonRawBatchFails:
    """
    A batch that failed used to print an error and count as zero Tasks, and
    the command exited 0 with the Work Requirement left part-populated.
    """

    @pytest.fixture
    def outcome(self) -> dict:
        # tg-1's second batch fails on every attempt (as does its third)
        return _submit([_created(), _response(200), _response(500, "boom")])

    def test_the_failure_is_raised(self, outcome):
        assert isinstance(outcome["raised"], requests.HTTPError)

    def test_its_exit_code_names_a_platform_failure(self, outcome):
        assert classify(outcome["raised"]) == ExitCode.PLATFORM

    def test_the_work_requirement_is_cancelled(self, outcome):
        cancel = outcome["client"].work_client.cancel_work_requirement_by_id
        cancel.assert_called_once_with(WR_ID)

    def test_no_later_task_group_is_attempted(self, outcome):
        # The Work Requirement, tg-1's first two batches, and none of tg-2's
        urls = [c.kwargs["url"] for c in outcome["post"].call_args_list]
        assert not any("tg-2" in url for url in urls)

    def test_a_platform_failure_is_retried_as_the_main_path_retries(self, outcome):
        # 1 Work Requirement + 1 batch + 1 failing batch of every attempt: the
        # third batch, not yet started when the second failed, is cancelled
        # rather than submitted to a Work Requirement about to be cancelled
        assert outcome["post"].call_count == 2 + MAX_BATCH_SUBMIT_ATTEMPTS


class TestJsonRawBatchRetries:
    def test_a_transient_failure_is_retried_to_success(self):
        outcome = _submit([_created(), _response(503, "busy")] + [_response(200)] * 4)
        assert "raised" not in outcome
        assert outcome["sleep"].call_count == 1

    def test_a_refused_batch_is_not_retried(self):
        outcome = _submit([_created(), _response(400, "bad task")])
        assert isinstance(outcome["raised"], requests.HTTPError)
        # tg-1's first batch posted once and not again, and its other two
        # not at all: they would only go to a Work Requirement being cancelled
        assert outcome["post"].call_count == 1 + 1
        outcome["sleep"].assert_not_called()

    def test_a_request_to_slow_down_is_retried(self):
        outcome = _submit([_created(), _response(429, "slow")] + [_response(200)] * 4)
        assert "raised" not in outcome
        assert outcome["sleep"].call_count == 1

    def test_requests_carry_a_timeout(self):
        outcome = _submit([_created()] + [_response(200)] * 4)
        for call in outcome["post"].call_args_list:
            assert call.kwargs["timeout"] == RAW_REQUEST_TIMEOUT


class TestJsonRawProgress:
    def test_progress_follows_with_the_progress_bar(self):
        with patch.object(submit_module, "follow_progress_bar") as progress_bar:
            outcome = _submit([_created()] + [_response(200)] * 4, progress=True)
        assert "raised" not in outcome
        progress_bar.assert_called_once()


class TestJsonRawMissingProperties:
    @pytest.mark.parametrize(
        "data, message",
        [
            ({"taskGroups": []}, "Property 'name' is not defined in 'raw.json'"),
            ({"name": "wr"}, "Property 'taskGroups' is not defined"),
            (
                {"name": "wr", "taskGroups": [{"name": "a"}, {"tasks": []}]},
                "Task Group 2 of 2 has no 'name' property",
            ),
        ],
    )
    def test_a_missing_property_is_named(self, data, message):
        with (
            patch.object(
                submit_module,
                "load_json_file_with_variable_substitutions",
                return_value=data,
            ),
            patch.object(submit_module, "add_substitutions_without_overwriting"),
            patch.object(
                CLIParser, "dry_run", new_callable=PropertyMock, return_value=False
            ),
            pytest.raises(ValueError, match=message),
        ):
            submit_module.submit_json_raw(_ctx(), "raw.json")
