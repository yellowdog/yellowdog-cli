"""
Unit tests for priority.py (yd-priority), against a fake Platform that keeps
Work Requirements and serves copies of them, as the Platform does.

Covers:
  - a Work Requirement and a Task Group, by ID and by every named form,
    resolved in the order given, each once, confirmed once
  - one update per Work Requirement, to a copy fetched just before it, so
    that a change made since resolution is not overwritten
  - what each outcome records: 'prioritised' with the previous and new
    priority; 'skipped' for a finished Work Requirement or a target already
    at the priority, or when declined; 'failed' for one not found, of
    another kind, or malformed
  - '--dry-run' recording what would change and changing nothing
  - a session failure stopping the run, the rest recorded as not attempted
  - the command line: a finite number, negative ones included
"""

from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError, Response
from yellowdog_client.model import (
    RunSpecification,
    TaskGroup,
    WorkRequirement,
    WorkRequirementStatus,
)

import yellowdog_cli.priority as yd_priority
import yellowdog_cli.utils.work_targets as work_targets
from yellowdog_cli.utils import action_runner
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_utils import work_requirement_summary_of
from yellowdog_cli.utils.exit_codes import ReportedFailure
from yellowdog_cli.utils.ydid_utils import get_ydid_type

WR_A = "ydid:workreq:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
WR_B = "ydid:workreq:000000:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TG_A1 = "ydid:taskgrp:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:1"
TG_A2 = "ydid:taskgrp:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:2"


def _http_error(status_code: int) -> HTTPError:
    response = Response()
    response.status_code = status_code
    return HTTPError(f"{status_code} Client Error", response=response)


def _task_group(id_: str, name: str) -> TaskGroup:
    task_group = TaskGroup(
        name=name, runSpecification=RunSpecification(taskTypes=["bash"])
    )
    task_group.id = id_
    task_group.priority = 0.0
    return task_group


def _wr(id_, name, status=WorkRequirementStatus.RUNNING, groups=()) -> WorkRequirement:
    # The SDK's models take neither 'id' nor 'status' as arguments
    work_requirement = WorkRequirement(
        name=name,
        namespace="ns",
        priority=0.0,
        taskGroups=[
            _task_group(group_id, group_name) for group_id, group_name in groups
        ],
    )
    work_requirement.id = id_
    work_requirement.status = status
    return work_requirement


class FakePlatform:
    def __init__(self):
        self.wrs: dict[str, WorkRequirement] = {
            WR_A: _wr(WR_A, "wr-a", groups=[(TG_A1, "render"), (TG_A2, "encode")]),
        }
        self.updates: list[WorkRequirement] = []
        self.records: list[dict] = []
        self.update_failure: Exception | None = None
        self.config = SimpleNamespace(namespace="ns")
        self.confirm = MagicMock(return_value=True)

        client = MagicMock()
        client.work_client.get_work_requirement_by_id.side_effect = self._get
        client.work_client.update_work_requirement.side_effect = self._update
        self.client = client

    def _get(self, wr_id):
        if wr_id not in self.wrs:
            raise _http_error(404)
        return deepcopy(self.wrs[wr_id])

    def _update(self, work_requirement):
        if self.update_failure is not None:
            raise self.update_failure
        self.updates.append(deepcopy(work_requirement))
        self.wrs[work_requirement.id] = deepcopy(work_requirement)
        return work_requirement

    def by_name(self, client, name, namespace=None):
        for wr in self.wrs.values():
            if wr.name == name and wr.namespace == namespace:
                return work_requirement_summary_of(wr)
        return None

    def task_groups(self, client, wr_id):
        return self._get(wr_id).taskGroups

    def priorities(self, wr_id=WR_A) -> tuple:
        wr = self.wrs[wr_id]
        return (wr.priority, *(group.priority for group in wr.taskGroups or []))

    def outcomes(self) -> list[tuple]:
        return [(r["id"], r["type"], r["outcome"]) for r in self.records]


@pytest.fixture
def platform(monkeypatch):
    fake = FakePlatform()
    monkeypatch.setattr(action_runner, "confirmed", fake.confirm)
    monkeypatch.setattr(
        work_targets, "get_work_requirement_summary_by_name_or_id", fake.by_name
    )
    monkeypatch.setattr(work_targets, "get_task_groups_from_wr_by_id", fake.task_groups)

    def record_action(entity, entity_type, action, outcome, error=None, **extra):
        if isinstance(entity, str):
            is_ydid = get_ydid_type(entity) is not None
            entity = {
                "id": entity if is_ydid else None,
                "name": None if is_ydid else entity,
            }
        elif not isinstance(entity, dict):
            entity = {"id": entity.id, "name": getattr(entity, "name", None)}
        fake.records.append(
            {
                **entity,
                "type": entity_type,
                "action": action,
                "outcome": outcome,
                "error": error,
                **extra,
            }
        )

    monkeypatch.setattr(yd_priority, "record_action", record_action)
    return fake


def _run(platform, priority: float, targets: list[str], dry_run: bool = False):
    yd_priority.set_priorities(
        RunContext(
            args=SimpleNamespace(dry_run=dry_run),
            config=platform.config,
            client=platform.client,
        ),
        priority,
        targets,
    )


class TestTargets:
    def test_a_work_requirement_by_id(self, platform):
        _run(platform, 5.0, [WR_A])
        assert platform.priorities() == (5.0, 0.0, 0.0)
        assert platform.outcomes() == [(WR_A, "work-requirements", "prioritised")]
        record = platform.records[0]
        assert (record["previousPriority"], record["priority"]) == (0.0, 5.0)
        assert record["action"] == "prioritise"

    def test_a_task_group_by_id(self, platform):
        _run(platform, 2.5, [TG_A2])
        assert platform.priorities() == (0.0, 0.0, 2.5)
        assert platform.outcomes() == [(TG_A2, "task-groups", "prioritised")]
        assert platform.records[0]["name"] == "encode"

    @pytest.mark.parametrize(
        "target, expected",
        [
            ("wr-a", (5.0, 0.0, 0.0)),
            ("ns/wr-a", (5.0, 0.0, 0.0)),
            ("wr-a/render", (0.0, 5.0, 0.0)),
            ("ns/wr-a/encode", (0.0, 0.0, 5.0)),
        ],
    )
    def test_named_forms(self, platform, target, expected):
        _run(platform, 5.0, [target])
        assert platform.priorities() == expected

    def test_a_negative_priority(self, platform):
        _run(platform, -1.0, [WR_A])
        assert platform.priorities() == (-1.0, 0.0, 0.0)


class TestUpdates:
    def test_one_update_per_work_requirement(self, platform):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b")
        _run(platform, 3.0, ["wr-a/render", WR_B, TG_A2, WR_A])
        assert [update.id for update in platform.updates] == [WR_A, WR_B]
        assert platform.priorities() == (3.0, 3.0, 3.0)
        assert platform.priorities(WR_B) == (3.0,)
        platform.confirm.assert_called_once()

    def test_a_target_named_twice_is_changed_once(self, platform):
        _run(platform, 3.0, [WR_A, WR_A])
        assert len(platform.updates) == 1
        assert len(platform.records) == 1

    def test_a_change_made_since_resolution_is_kept(self, platform, monkeypatch):
        # Another client raises the render Task Group between resolution and
        # the update: the update is to a fresh copy, so it is not reverted
        def confirm(message):
            platform.wrs[WR_A].taskGroups[0].priority = 9.0
            return True

        monkeypatch.setattr(action_runner, "confirmed", confirm)
        _run(platform, 3.0, [WR_A])
        assert platform.priorities() == (3.0, 9.0, 0.0)

    def test_the_previous_priority_is_the_one_replaced(self, platform, monkeypatch):
        def confirm(message):
            platform.wrs[WR_A].priority = 7.0
            return True

        monkeypatch.setattr(action_runner, "confirmed", confirm)
        _run(platform, 3.0, [WR_A])
        assert platform.records[0]["previousPriority"] == 7.0

    def test_the_confirmation_says_what_changes(self, platform):
        _run(platform, 5.0, ["wr-a/render"])
        message = platform.confirm.call_args.args[0]
        assert "'wr-a/render' 0.0 -> 5.0" in message


class TestSkippedAndFailed:
    def test_a_finished_work_requirement_is_skipped(self, platform):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b", WorkRequirementStatus.COMPLETED)
        _run(platform, 5.0, [WR_B, "wr-b"])
        assert platform.updates == []
        assert [r["outcome"] for r in platform.records] == ["skipped", "skipped"]
        assert "COMPLETED" in platform.records[0]["error"]

    def test_already_at_the_priority_is_skipped(self, platform):
        _run(platform, 0.0, [WR_A])
        assert platform.updates == []
        assert platform.outcomes() == [(WR_A, "work-requirements", "skipped")]
        assert "already 0.0" in platform.records[0]["error"]

    @pytest.mark.parametrize(
        "target, entity_type",
        [
            (WR_B, "work-requirements"),
            (
                "ydid:taskgrp:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:9",
                "task-groups",
            ),
            ("nope", "work-requirements"),
            ("wr-a/nope", "task-groups"),
            ("a/b/c/d", "task-groups"),
            ("ydid:node:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "task-groups"),
        ],
    )
    def test_unresolvable_targets_fail_and_the_rest_go_ahead(
        self, platform, target, entity_type
    ):
        _run(platform, 5.0, [target, WR_A])
        assert platform.records[0]["outcome"] == "failed"
        assert platform.records[1]["outcome"] == "prioritised"
        assert platform.priorities() == (5.0, 0.0, 0.0)

    def test_declining_changes_nothing(self, platform):
        platform.confirm.return_value = False
        _run(platform, 5.0, [WR_A, TG_A1])
        assert platform.updates == []
        assert [r["outcome"] for r in platform.records] == ["skipped", "skipped"]


class TestDryRun:
    def test_a_dry_run_records_and_changes_nothing(self, platform):
        _run(platform, 5.0, [WR_A, "wr-a/render"], dry_run=True)
        assert platform.updates == []
        platform.confirm.assert_not_called()
        assert [r["outcome"] for r in platform.records] == [
            "would prioritise",
            "would prioritise",
        ]
        assert platform.records[1]["previousPriority"] == 0.0


class TestSessionFailure:
    def test_a_session_failure_stops_the_run(self, platform):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b")
        platform.update_failure = RequestsConnectionError("down")
        with pytest.raises(ReportedFailure):
            _run(platform, 5.0, [WR_A, WR_B])
        assert [r["outcome"] for r in platform.records] == ["failed", "skipped"]
        assert platform.records[1]["error"].startswith("not attempted")

    def test_another_update_failure_fails_only_its_work_requirement(self, platform):
        platform.wrs[WR_B] = _wr(WR_B, "wr-b")
        update = platform.client.work_client.update_work_requirement

        def fail_a(work_requirement):
            if work_requirement.id == WR_A:
                raise _http_error(400)
            platform.updates.append(work_requirement)
            return work_requirement

        update.side_effect = fail_a
        _run(platform, 5.0, [WR_A, "wr-a/render", WR_B])
        assert [(r["name"], r["outcome"]) for r in platform.records] == [
            ("wr-a", "failed"),
            ("render", "failed"),
            ("wr-b", "prioritised"),
        ]


class TestCommandLine:
    @pytest.mark.parametrize("value", ["nan", "inf", "-inf", "high"])
    def test_the_priority_must_be_a_finite_number(self, value, capsys):
        from yellowdog_cli.utils.args import CLIParser

        with pytest.raises(SystemExit) as raised:
            CLIParser(command="yd-priority", argv=[value, WR_A])
        assert raised.value.code == 2

    def test_a_negative_priority_is_a_number_not_an_option(self):
        from yellowdog_cli.utils.args import CLIParser

        parsed: Any = CLIParser(command="yd-priority", argv=["-2.5", WR_A])
        assert parsed.priority == -2.5
        assert parsed.priority_targets == [WR_A]
