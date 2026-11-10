"""
Tests for 'yd-submit --json-raw' (utils/json_raw.py): a failure
is raised as an HTTPError carrying the Platform's response, so that the exit
code names it, and a Work Requirement left with only some of its Tasks is
cancelled, as one built from a specification is.
"""

from contextlib import ExitStack
from gzip import decompress
from json import loads as json_loads
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import requests

import yellowdog_cli.utils.json_raw as json_raw_module
import yellowdog_cli.utils.specs.loading as spec_loading_module
import yellowdog_cli.utils.task_batches as task_batches_module
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import ExitCode, classify
from yellowdog_cli.utils.limits import (
    MAX_BATCH_SUBMIT_ATTEMPTS,
    PLATFORM_READ_TIMEOUT,
    RAW_CONNECT_TIMEOUT,
)

REQUEST_TIMEOUT = (RAW_CONNECT_TIMEOUT, PLATFORM_READ_TIMEOUT)


def _ctx() -> RunContext:
    """
    The context a command is given: the wrapper's values, as patched.
    """
    return RunContext(
        wrapper_module.ARGS_PARSER, wrapper_module.CONFIG_COMMON, wrapper_module.CLIENT
    )


def _submit_json_raw(follow=None) -> None:
    """
    Submit 'raw.json' as yd-submit does: one Task to a batch, one batch at
    a time, so the order of the requests is fixed.
    """
    json_raw_module.submit_json_raw(
        _ctx(),
        "raw.json",
        batch_size=1,
        parallel_batches=1,
        follow=MagicMock() if follow is None else follow,
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
        # An exception in the list is raised, as requests raises a timeout
        item = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if isinstance(item, BaseException):
            raise item
        return item

    post = MagicMock(side_effect=answer)
    client = MagicMock()
    sleep = MagicMock()
    follow = MagicMock()
    outcome: dict = {"post": post, "client": client, "sleep": sleep, "follow": follow}
    flags = {
        "dry_run": False,
        "hold": False,
        **flag_overrides,
    }
    with ExitStack() as stack:
        for patcher in (
            patch.object(json_raw_module.requests, "post", post),
            patch.object(wrapper_module, "CLIENT", client),
            patch.object(
                wrapper_module,
                "CONFIG_COMMON",
                MagicMock(url="https://x", request_timeout=REQUEST_TIMEOUT),
            ),
            patch.object(task_batches_module, "sleep", sleep),
            patch.object(
                spec_loading_module,
                "load_json_file_with_variable_substitutions",
                return_value=_wr_data(),
            ),
            patch.object(json_raw_module, "add_substitutions_without_overwriting"),
            patch.object(json_raw_module, "record_entity"),
            patch.object(json_raw_module, "print_quiet_result"),
            *(
                patch.object(
                    CLIParser, flag, new_callable=PropertyMock, return_value=value
                )
                for flag, value in flags.items()
            ),
        ):
            stack.enter_context(patcher)
        try:
            _submit_json_raw(follow)
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
    A batch that fails is raised, rather than printed as an error and counted
    as zero Tasks, which would exit 0 with the Work Requirement left
    part-populated.
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

    def test_a_timed_out_batch_of_unnamed_tasks_is_not_resent(self):
        # Raw Tasks here have no names: a resent batch could be added twice
        timeout = requests.exceptions.ReadTimeout("timed out")
        outcome = _submit([_created(), timeout, _response(200)])
        assert outcome["raised"] is timeout
        assert outcome["post"].call_count == 1 + 1
        outcome["sleep"].assert_not_called()

    def test_requests_carry_a_timeout(self):
        outcome = _submit([_created()] + [_response(200)] * 4)
        for call in outcome["post"].call_args_list:
            assert call.kwargs["timeout"] == REQUEST_TIMEOUT


class TestJsonRawFollow:
    def test_the_new_work_requirement_is_handed_to_follow(self):
        # yd-submit's callback follows it as '--follow' or '--progress' asks
        outcome = _submit([_created()] + [_response(200)] * 4)
        assert "raised" not in outcome
        outcome["follow"].assert_called_once_with(WR_ID)

    def test_one_whose_tasks_failed_is_not(self):
        outcome = _submit([_created(), _response(200), _response(500, "boom")])
        assert "raised" in outcome
        outcome["follow"].assert_not_called()


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
                spec_loading_module,
                "load_json_file_with_variable_substitutions",
                return_value=data,
            ),
            patch.object(json_raw_module, "add_substitutions_without_overwriting"),
            patch.object(
                CLIParser, "dry_run", new_callable=PropertyMock, return_value=False
            ),
            pytest.raises(ValueError, match=message),
        ):
            _submit_json_raw()


class TestSubmitPlatformDocument:
    def _run(self, document: dict, posts: list, **kwargs):
        post = MagicMock(side_effect=posts)
        follow = MagicMock()
        with (
            patch.object(json_raw_module.requests, "post", post),
            patch.object(
                wrapper_module,
                "CONFIG_COMMON",
                MagicMock(url="https://x", request_timeout=REQUEST_TIMEOUT),
            ),
            patch.object(wrapper_module, "CLIENT", MagicMock()),
            patch.object(json_raw_module, "record_entity") as record_entity,
            patch.object(json_raw_module, "print_quiet_result"),
            patch.object(
                CLIParser, "dry_run", new_callable=PropertyMock, return_value=False
            ),
            patch.object(
                CLIParser, "hold", new_callable=PropertyMock, return_value=False
            ),
        ):
            wr_id = json_raw_module.submit_platform_document(
                _ctx(),
                document,
                batch_size=10,
                parallel_batches=1,
                follow=follow,
                **kwargs,
            )
        return wr_id, post, follow, record_entity

    def test_the_document_is_posted_unchanged(self):
        document = {
            "name": "wr",
            "namespace": "ns",
            "taskGroups": [
                {
                    "name": "tg",
                    "tasks": [
                        {"taskType": "bash", "arguments": ["{{x}}", "__{{y}}__"]}
                    ],
                }
            ],
        }
        wr_id, post, follow, record_entity = self._run(
            document,
            [_created(), _response(200)],
            record_extra={"resubmittedFrom": "ydid:old"},
        )
        assert wr_id == WR_ID
        follow.assert_called_once_with(WR_ID)
        created = post.call_args_list[0].kwargs["json"]
        assert created == {
            "name": "wr",
            "namespace": "ns",
            "taskGroups": [{"name": "tg"}],
        }
        assert document["taskGroups"][0]["tasks"][0]["arguments"] == [
            "{{x}}",
            "__{{y}}__",
        ]
        sent = json_loads(decompress(post.call_args_list[1].kwargs["data"]))
        assert sent == [{"taskType": "bash", "arguments": ["{{x}}", "__{{y}}__"]}]
        record_entity.assert_called_once_with(
            WR_ID, "wr", "ns", "work-requirements", resubmittedFrom="ydid:old"
        )


class TestAddPlatformTasks:
    def test_each_task_group_is_posted_to_and_the_total_returned(self):
        post = MagicMock(return_value=_response(200))
        with (
            patch.object(json_raw_module.requests, "post", post),
            patch.object(
                wrapper_module,
                "CONFIG_COMMON",
                MagicMock(url="https://x", request_timeout=REQUEST_TIMEOUT),
            ),
        ):
            total = json_raw_module.add_platform_tasks(
                _ctx(),
                "ns",
                "wr",
                {"a": [{"taskType": "bash"}] * 3, "b": [], "c": [{"taskType": "bash"}]},
                batch_size=2,
                parallel_batches=1,
            )
        assert total == 4
        urls = sorted(call.kwargs["url"] for call in post.call_args_list)
        assert urls == [
            "https://x/work/namespaces/ns/requirements/wr/taskGroups/a/tasks",
            "https://x/work/namespaces/ns/requirements/wr/taskGroups/a/tasks",
            "https://x/work/namespaces/ns/requirements/wr/taskGroups/c/tasks",
        ]
