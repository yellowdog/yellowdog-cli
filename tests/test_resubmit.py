"""
Tests for 'yd workrequirement resubmit' (resubmit.py), against a fake
Platform whose Work Requirement HTTP posts are recorded.

Covers:
  - failed Tasks submitted as one new Work Requirement, in batches of the
    batch size, copied unchanged (a '{{x}}' argument stays '{{x}}')
  - '-o' writing what 'yd wr submit --json-raw' takes, and submitting the
    same document as the direct path
  - nothing selected, the warnings, '--dry-run', '--hold', '--json', '--quiet'
  - a failure adding Tasks cancelling the new Work Requirement
  - a missing Work Requirement, the option clashes and the verb
"""

import json
from datetime import timedelta
from gzip import decompress
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests
from requests import HTTPError, Response
from yellowdog_client.model import (
    RunSpecification,
    Task,
    TaskGroup,
    TaskStatus,
    WorkRequirement,
    WorkRequirementStatus,
)

import yellowdog_cli.resubmit as resubmit_module
import yellowdog_cli.utils.json_raw as json_raw_module
import yellowdog_cli.utils.output_settings as output_settings
import yellowdog_cli.utils.specs.loading as spec_loading_module
import yellowdog_cli.utils.task_batches as task_batches_module
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_utils import AmbiguousNameError
from yellowdog_cli.utils.exit_codes import ExitCode, NotFoundError, classify
from yellowdog_cli.utils.noun_registry import NOUNS
from yellowdog_cli.utils.results import flush_results, reset_results

WR_ID = "ydid:workreq:000000:00000000-0000-0000-0000-000000000001"
NEW_ID = "ydid:workreq:000000:00000000-0000-0000-0000-000000000002"
TARGET_ID = "ydid:workreq:000000:00000000-0000-0000-0000-000000000003"


def _http_error(status_code: int) -> HTTPError:
    response = Response()
    response.status_code = status_code
    return HTTPError(f"{status_code} Error", response=response)


def _task(name: str, status: str, group_id: str, argument: str = "echo {{x}}") -> Task:
    task = Task(
        name=name,
        taskType="bash",
        arguments=["-c", argument],
        environment={"A": "__{{y}}__"},
        timeout=timedelta(minutes=5),
    )
    task.id = f"{group_id}:{name}"
    task.status = TaskStatus(status)
    task.taskGroupId = group_id
    return task


def _wr(status=WorkRequirementStatus.FAILED) -> WorkRequirement:
    group = TaskGroup(name="render", runSpecification=RunSpecification(["bash"]))
    group.id = "g1"
    wr = WorkRequirement(
        namespace="ns", name="x", taskGroups=[group], tag="t", priority=3
    )
    wr.id = WR_ID
    wr.status = status
    return wr


class _Run:
    """
    One resubmission: the fake client, the recorded posts and the flags.
    """

    def __init__(self, tasks: list[Task], wr: WorkRequirement | None = None):
        self.wr = wr or _wr()
        self.tasks = tasks
        self.client = MagicMock()
        work = self.client.work_client
        work.get_work_requirement_by_id.return_value = self.wr
        work.get_work_requirement_by_name.side_effect = _http_error(404)
        work.get_tasks.side_effect = self._get_tasks
        work.get_task_by_id.side_effect = self._get_task
        self.target: WorkRequirement | None = None
        self.held: list[Task] = []
        work.get_work_requirement_by_id.side_effect = self._by_id
        work.update_work_requirement.side_effect = lambda wr: wr
        self.responses: list = []
        self.posts: list = []
        self.summary = SimpleNamespace(id=WR_ID, name="x", namespace="ns")

    def _by_id(self, wr_id):
        if self.target is not None and wr_id == TARGET_ID:
            return self.target
        return self.wr

    def _get_task(self, task_id):
        for task in [*self.tasks, *self.held]:
            if task.id == task_id:
                return task
        raise _http_error(404)

    def _get_tasks(self, search):
        wanted = {s.value for s in search.statuses} if search.statuses else None
        found = [
            t
            for t in [*self.tasks, *self.held]
            if t.taskGroupId == search.taskGroupId
            and (wanted is None or t.status.value in wanted)
        ]
        return SimpleNamespace(iterate=lambda: iter(found))

    def _post(self, **kwargs):
        self.posts.append(kwargs)
        if self.responses:
            item = self.responses.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        if len(self.posts) == 1:
            return _response(200, f'{{"id": "{NEW_ID}"}}')
        return _response(200)

    def run(self, *, batch_size=100, target="x", **flags) -> Exception | None:
        values = dict(
            failed=False,
            aborted=False,
            task_group_patterns=None,
            task_patterns=None,
            task_ids=None,
            add_to=None,
            resubmit_name=None,
            export_file=None,
            follow=False,
            progress=False,
            hold=False,
            dry_run=False,
            json_output=None,
            quiet=False,
            parallel_batches=1,
            pause_between_batches=None,
            resubmit_target=target,
        )
        args = SimpleNamespace(**{**values, **flags})
        output_settings.configure_output(args)
        config = SimpleNamespace(
            namespace="ns",
            url="https://x",
            key="k",
            secret="s",
            request_timeout=(1, 1),
        )
        ctx = RunContext(args=args, config=config, client=self.client)
        config_wr = SimpleNamespace(task_batch_size=batch_size, parallel_batches=None)
        self.follow = MagicMock()
        with (
            patch.object(json_raw_module.requests, "post", side_effect=self._post),
            patch.object(task_batches_module, "sleep"),
            patch.object(
                resubmit_module, "get_work_requirement_summary_by_name_or_id"
            ) as lookup,
            patch.object(resubmit_module, "_follow", self.follow),
        ):
            lookup.return_value = self.summary if target != "missing" else None
            try:
                resubmit_module.resubmit(ctx, config_wr)  # type: ignore[arg-type]
            except Exception as e:
                return e
        return None

    def bodies(self) -> list[dict]:
        """
        The body of each post: the Work Requirement's JSON, then each Task
        batch's list (sent gzipped).
        """
        return [
            p["json"] if "json" in p else json.loads(decompress(p["data"]))
            for p in self.posts
        ]

    def cancelled(self) -> bool:
        return self.client.work_client.cancel_work_requirement_by_id.called


def _response(status_code: int, text: str = "") -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.text = text
    return response


@pytest.fixture(autouse=True)
def _results():
    reset_results()
    yield
    reset_results()


def _flat(text: str) -> str:
    """
    Output with each wrapped line rejoined.
    """
    return " ".join(text.split())


def _failed(n: int, **kwargs) -> list[Task]:
    return [_task(f"t{i}", "FAILED", "g1", **kwargs) for i in range(n)]


class TestNewWorkRequirement:
    def test_failed_tasks_are_submitted_as_a_new_work_requirement(self):
        run = _Run([*_failed(3), _task("ok", "COMPLETED", "g1")])
        assert run.run() is None
        creation = run.bodies()[0]
        assert creation["name"] == "x-resubmit-1"
        assert creation["namespace"] == "ns"
        assert [g["name"] for g in creation["taskGroups"]] == ["render"]
        assert "tasks" not in creation["taskGroups"][0]
        # The Work Requirement, then one batch of the three failed Tasks
        assert len(run.posts) == 2
        assert [t["name"] for t in run.bodies()[1]] == ["t0", "t1", "t2"]
        [call] = run.follow.call_args_list
        assert call.args[1] == NEW_ID

    def test_the_tasks_are_sent_in_batches_of_the_batch_size(self):
        run = _Run(_failed(5))
        assert run.run(batch_size=2) is None
        batches = [len(body) for body in run.bodies()[1:]]
        assert batches == [2, 2, 1]
        # Never a request per Task, and each Task Group searched once
        searches = run.client.work_client.get_tasks.call_args_list
        assert len(searches) == 3  # selection, CANCELLED count, DISCARDED count

    def test_a_substitution_in_an_argument_is_submitted_unchanged(self):
        run = _Run(_failed(1, argument="__{{z}}__ {{x}}"))
        assert run.run() is None
        [task] = run.bodies()[1]
        assert task["arguments"] == ["-c", "__{{z}}__ {{x}}"]
        assert task["environment"] == {"A": "__{{y}}__"}

    def test_hold_creates_it_held(self):
        run = _Run(_failed(1))
        assert run.run(hold=True) is None
        run.client.work_client.hold_work_requirement_by_id.assert_called_once_with(
            NEW_ID
        )

    def test_a_failure_adding_tasks_cancels_the_new_work_requirement(self):
        run = _Run(_failed(2))
        run.responses = [
            _response(200, f'{{"id": "{NEW_ID}"}}'),
            _response(400, "bad task"),
        ]
        error = run.run()
        assert isinstance(error, HTTPError)
        run.client.work_client.cancel_work_requirement_by_id.assert_called_once_with(
            NEW_ID
        )
        run.follow.assert_not_called()

    def test_name_is_taken_from_the_option(self):
        run = _Run(_failed(1))
        assert run.run(resubmit_name="again") is None
        assert run.bodies()[0]["name"] == "again"


class TestOutputFile:
    def test_output_file_writes_json_raw_and_submits_nothing(self, tmp_path, capsys):
        run = _Run(_failed(2, argument="{{x}}"))
        file = str(tmp_path / "wr.json")
        assert run.run(export_file=file) is None
        assert run.posts == []
        written = json.loads((tmp_path / "wr.json").read_text(encoding="utf-8"))
        assert written["name"] == "x-resubmit-1"
        assert written["namespace"] == "ns"
        [group] = written["taskGroups"]
        assert len(group["tasks"]) == 2
        # Written raw, so that submitting it does not substitute
        assert group["tasks"][0]["arguments"] == ["-c", "{{raw:x}}"]
        assert "Wrote Work Requirement 'ns/x-resubmit-1'" in capsys.readouterr().out

    def test_output_file_records_the_file_under_json(self, tmp_path, capsys):
        run = _Run(_failed(2))
        file = str(tmp_path / "wr.json")
        assert run.run(export_file=file, json_output=True) is None
        flush_results()
        assert json.loads(capsys.readouterr().out) == [
            {"file": file, "resubmittedFrom": WR_ID, "taskCount": 2}
        ]

    def test_output_file_then_json_raw_submits_the_same_document(self, tmp_path):
        direct = _Run(_failed(3, argument="{{x}} __{{y}}__"))
        assert direct.run() is None
        written = _Run(_failed(3, argument="{{x}} __{{y}}__"))
        file = tmp_path / "wr.json"
        assert written.run(export_file=str(file)) is None

        via_file = _Run([])
        ctx = RunContext(
            args=SimpleNamespace(
                dry_run=False,
                hold=False,
                jsonnet_dry_run=False,
                json_output=None,
                pause_between_batches=None,
            ),
            config=SimpleNamespace(
                url="https://x", key="k", secret="s", request_timeout=(1, 1)
            ),
            client=via_file.client,
        )
        with (
            patch.object(json_raw_module.requests, "post", side_effect=via_file._post),
            patch.object(task_batches_module, "sleep"),
            patch.object(
                spec_loading_module,
                "load_json_file_with_variable_substitutions",
                side_effect=lambda *a, **k: json.loads(
                    file.read_text(encoding="utf-8")
                ),
            ),
        ):
            json_raw_module.submit_json_raw(
                ctx, str(file), batch_size=100, parallel_batches=1, follow=MagicMock()
            )
        assert via_file.bodies() == direct.bodies()


class TestNothingSelected:
    def test_nothing_selected_exits_0_and_creates_nothing(self, capsys):
        run = _Run([_task("ok", "COMPLETED", "g1")])
        assert run.run() is None
        assert run.posts == []
        assert (
            "No FAILED Tasks to resubmit in Work Requirement 'ns/x'"
            in capsys.readouterr().out
        )

    def test_nothing_selected_is_an_empty_result_under_json(self, capsys):
        run = _Run([])
        assert run.run(json_output=True) is None
        flush_results()
        assert json.loads(capsys.readouterr().out) == []


class TestMessages:
    def test_the_opening_line_counts_what_is_resubmitted(self, capsys):
        run = _Run(_failed(2))
        run.run()
        assert (
            f"Resubmitting 2 Tasks (FAILED) from 1 Task Group of Work Requirement"
            f" 'ns/x' ({WR_ID})"
        ) in _flat(capsys.readouterr().out)

    def test_left_behind_and_running_original_warnings_are_printed(self, capsys):
        run = _Run(
            [*_failed(1), _task("d", "DISCARDED", "g1")],
            wr=_wr(WorkRequirementStatus.RUNNING),
        )
        run.run()
        err = capsys.readouterr()
        text = _flat(err.out + err.err)
        assert "Task Group 'render' has 1 DISCARDED Task, not resubmitted" in text
        assert (
            "Work Requirement 'ns/x' is RUNNING: Tasks still running may yet fail,"
            " and are not resubmitted"
        ) in text

    def test_quiet_prints_the_new_id(self, capsys):
        run = _Run(_failed(1))
        run.run(quiet=True)
        assert capsys.readouterr().out.strip() == NEW_ID

    def test_json_records_the_new_wr_with_resubmitted_from_and_task_count(self, capsys):
        run = _Run(_failed(2))
        assert run.run(json_output=True) is None
        flush_results()
        assert json.loads(capsys.readouterr().out) == {
            "id": NEW_ID,
            "name": "x-resubmit-1",
            "namespace": "ns",
            "type": "work-requirements",
            "resubmittedFrom": WR_ID,
            "taskCount": 2,
        }


class TestDryRun:
    def test_dry_run_prints_the_document(self, capsys):
        run = _Run(_failed(2, argument="{{x}}"))
        assert run.run(dry_run=True) is None
        assert run.posts == []
        out = capsys.readouterr().out
        assert "x-resubmit-1" in out and "{{raw:x}}" in out

    def test_dry_run_json_records_the_document(self, capsys):
        run = _Run(_failed(2))
        assert run.run(dry_run=True, json_output=True) is None
        assert run.posts == []
        flush_results()
        document = json.loads(capsys.readouterr().out)
        assert document["name"] == "x-resubmit-1"
        assert len(document["taskGroups"][0]["tasks"]) == 2

    def test_dry_run_with_an_output_file_writes_nothing_and_says_so(
        self, tmp_path, capsys
    ):
        run = _Run(_failed(1))
        file = tmp_path / "wr.json"
        assert run.run(dry_run=True, export_file=str(file)) is None
        assert not file.exists()
        assert f"Would write the new Work Requirement to '{file}'" in _flat(
            capsys.readouterr().out
        )


class TestFailures:
    def test_an_ambiguous_name_is_a_value_error_from_it(self):
        ctx = RunContext(
            args=SimpleNamespace(resubmit_target="x"),
            config=SimpleNamespace(namespace="ns"),
            client=MagicMock(),
        )
        ambiguous = AmbiguousNameError("two Work Requirements are named 'x'")
        with (
            patch.object(
                resubmit_module,
                "get_work_requirement_summary_by_name_or_id",
                side_effect=ambiguous,
            ),
            pytest.raises(ValueError) as refused,
        ):
            resubmit_module._original(ctx)
        assert refused.value.__cause__ is ambiguous

    def test_a_work_requirement_given_by_id_is_fetched_once(self):
        run = _Run(_failed(1))
        assert run.run(target=WR_ID) is None
        full = run.client.work_client.get_work_requirement_by_id
        assert [c.args for c in full.call_args_list].count((WR_ID,)) == 1

    def test_a_missing_work_requirement_exits_6(self):
        run = _Run(_failed(1))
        error = run.run(target="missing")
        assert isinstance(error, NotFoundError)
        assert classify(error) == ExitCode.NOT_FOUND


def _target(
    groups: dict[str, list[str]] | None = None,
    status=WorkRequirementStatus.RUNNING,
) -> WorkRequirement:
    """
    A Work Requirement to add to, with Task Groups by name and task types.
    """
    task_groups = []
    for index, (name, types) in enumerate((groups or {"render": ["bash"]}).items()):
        group = TaskGroup(name=name, runSpecification=RunSpecification(types))
        group.id = f"tg{index}"
        task_groups.append(group)
    wr = WorkRequirement(namespace="ns", name="dest", taskGroups=task_groups)
    wr.id = TARGET_ID
    wr.status = status
    return wr


def _add_run(tasks: list[Task] | None = None, target: WorkRequirement | None = None):
    run = _Run(tasks if tasks is not None else _failed(2))
    run.target = target or _target()
    return run


def _task_posts(run: _Run) -> list[tuple[str, list]]:
    return [
        (p["url"], b) for p, b in zip(run.posts, run.bodies()) if isinstance(b, list)
    ]


class TestAddTo:
    def test_tasks_go_to_the_matching_task_groups_by_name(self):
        run = _add_run()
        assert run.run(add_to=TARGET_ID) is None
        [(url, body)] = _task_posts(run)
        assert url == (
            "https://x/work/namespaces/ns/requirements/dest/taskGroups/render/tasks"
        )
        assert [t["name"] for t in body] == ["t0", "t1"]
        run.client.work_client.update_work_requirement.assert_not_called()
        run.follow.assert_called_once()
        assert run.follow.call_args.args[1] == TARGET_ID

    def test_a_missing_task_group_is_appended_with_its_definition(self):
        run = _add_run(target=_target({"other": ["bash"]}))
        assert run.run(add_to=TARGET_ID) is None
        [call] = run.client.work_client.update_work_requirement.call_args_list
        groups = call.args[0].taskGroups
        assert [g.name for g in groups] == ["other", "render"]
        assert groups[1].runSpecification.taskTypes == ["bash"]
        assert len(_task_posts(run)) == 1

    def test_an_appended_groups_dependencies_keep_only_known_names(self):
        original = _wr()
        extra = TaskGroup(
            name="second",
            runSpecification=RunSpecification(["bash"]),
            dependencies=["render", "gone", "other"],
            dependentOn="gone",
        )
        extra.id = "g2"
        original.taskGroups = [*original.taskGroups, extra]
        run = _Run(
            [*_failed(1), _task("s0", "FAILED", "g2")],
            original,
        )
        run.target = _target({"other": ["bash"]})
        assert run.run(add_to=TARGET_ID) is None
        [call] = run.client.work_client.update_work_requirement.call_args_list
        appended = {g.name: g for g in call.args[0].taskGroups}
        assert appended["second"].dependencies == ["render", "other"]
        assert appended["second"].dependentOn is None

    def test_a_task_type_the_target_group_lacks_is_refused_before_anything(self):
        run = _add_run(target=_target({"render": ["python"]}))
        error = run.run(add_to=TARGET_ID)
        assert isinstance(error, ValueError)
        assert "taskTypes" in str(error)
        assert run.posts == []
        run.client.work_client.update_work_requirement.assert_not_called()

    def test_a_task_name_the_target_holds_is_refused_before_anything(self):
        run = _add_run(target=_target({"render": ["bash"], "other": ["bash"]}))
        run.held = [_task("t1", "COMPLETED", "tg0")]
        error = run.run(add_to=TARGET_ID)
        assert isinstance(error, ValueError)
        assert str(error) == (
            "Task Group 'render' of Work Requirement 'ns/dest' already holds a"
            " Task named 't1'"
        )
        assert run.posts == []
        run.client.work_client.update_work_requirement.assert_not_called()

    def test_unnamed_tasks_are_added_without_a_name_check(self):
        tasks = [_task("x", "FAILED", "g1") for _ in range(2)]
        for task in tasks:
            task.name = None
        run = _add_run(tasks)
        run.held = [_task("t1", "COMPLETED", "tg0")]
        assert run.run(add_to=TARGET_ID) is None
        [(_, body)] = _task_posts(run)
        assert len(body) == 2 and all("name" not in t for t in body)

    def test_a_target_that_cannot_take_tasks_is_refused(self):
        run = _add_run(target=_target(status=WorkRequirementStatus.FAILED))
        error = run.run(add_to=TARGET_ID)
        assert isinstance(error, ValueError)
        assert classify(error) == ExitCode.FAILURE
        assert run.posts == []

    def test_a_failure_part_way_leaves_the_target_and_says_so(self, capsys):
        run = _add_run()
        run.responses = [_response(400, "bad task")]
        error = run.run(add_to=TARGET_ID)
        assert isinstance(error, HTTPError)
        assert not run.cancelled()
        assert not run.client.work_client.cancel_work_requirement.called
        captured = capsys.readouterr()
        assert "already added remain in it" in _flat(captured.out + captured.err)
        run.follow.assert_not_called()

    def test_json_records_the_target_with_resubmitted_from(self, capsys):
        run = _add_run()
        assert run.run(add_to=TARGET_ID, json_output=True) is None
        flush_results()
        assert json.loads(capsys.readouterr().out) == {
            "id": TARGET_ID,
            "name": "dest",
            "namespace": "ns",
            "type": "work-requirements",
            "resubmittedFrom": WR_ID,
            "taskCount": 2,
        }

    def test_dry_run_json_records_the_target_and_its_appended_groups(self, capsys):
        run = _add_run(target=_target({"other": ["bash"]}))
        assert run.run(add_to=TARGET_ID, dry_run=True, json_output=True) is None
        assert run.posts == []
        flush_results()
        assert json.loads(capsys.readouterr().out) == {
            "id": TARGET_ID,
            "name": "dest",
            "namespace": "ns",
            "type": "work-requirements",
            "resubmittedFrom": WR_ID,
            "taskCount": 2,
            "appendedTaskGroups": ["render"],
        }

    def test_quiet_prints_the_targets_id(self, capsys):
        run = _add_run()
        assert run.run(add_to=TARGET_ID, quiet=True) is None
        assert capsys.readouterr().out.strip() == TARGET_ID


def _two_group_run(**kwargs) -> _Run:
    wr = _wr()
    other = TaskGroup(name="post", runSpecification=RunSpecification(["bash"]))
    other.id = "g2"
    wr.taskGroups = [*wr.taskGroups, other]
    tasks = [
        _task("frame-01", "FAILED", "g1"),
        _task("frame-02", "FAILED", "g1"),
        _task("mask-01", "FAILED", "g1"),
        _task("frame-03", "FAILED", "g2"),
    ]
    return _Run(tasks, wr)


class TestFilters:
    def test_filters_reach_select_tasks_and_the_copy(self, tmp_path):
        run = _two_group_run()
        assert (
            run.run(task_group_patterns=["render"], task_patterns=["frame-*"]) is None
        )
        creation = run.bodies()[0]
        assert [g["name"] for g in creation["taskGroups"]] == ["render"]
        assert [t["name"] for t in run.bodies()[1]] == ["frame-01", "frame-02"]

        path = tmp_path / "wr.json"
        run = _two_group_run()
        assert run.run(task_patterns=["mask-01"], export_file=str(path)) is None
        document = json.loads(path.read_text(encoding="utf-8"))
        [group] = document["taskGroups"]
        assert [t["name"] for t in group["tasks"]] == ["mask-01"]

    def test_filters_with_add_to(self):
        run = _two_group_run()
        run.target = _target({"render": ["bash"], "post": ["bash"]})
        assert run.run(add_to=TARGET_ID, task_patterns=["frame-03"]) is None
        [(url, body)] = _task_posts(run)
        assert url.endswith("/taskGroups/post/tasks")
        assert [t["name"] for t in body] == ["frame-03"]

    def test_unmatched_task_group_exits_6_and_creates_nothing(self):
        run = _two_group_run()
        error = run.run(task_group_patterns=["rendr"])
        assert isinstance(error, NotFoundError)
        assert classify(error) == ExitCode.NOT_FOUND
        assert run.posts == []
        assert not run.client.work_client.get_tasks.called


def _refusal(capsys, *argv: str) -> str:
    with pytest.raises(SystemExit) as exit_:
        CLIParser(command="yd wr resubmit", argv=list(argv))
    assert exit_.value.code == ExitCode.USAGE
    return capsys.readouterr().err


GROUP_1 = "ydid:taskgrp:000000:00000000-0000-0000-0000-000000000001:0"
GROUP_2 = "ydid:taskgrp:000000:00000000-0000-0000-0000-000000000001:1"
TASK_1 = "ydid:task:000000:00000000-0000-0000-0000-000000000001:0:1"
TASK_2 = "ydid:task:000000:00000000-0000-0000-0000-000000000001:0:2"
TASK_3 = "ydid:task:000000:00000000-0000-0000-0000-000000000001:1:3"
FOREIGN = "ydid:task:000000:00000000-0000-0000-0000-000000000009:0:1"


def _id_run(statuses=("COMPLETED", "CANCELLED", "FAILED")) -> _Run:
    wr = _wr()
    wr.taskGroups[0].id = GROUP_1
    other = TaskGroup(name="post", runSpecification=RunSpecification(["bash"]))
    other.id = GROUP_2
    wr.taskGroups = [*wr.taskGroups, other]
    tasks = []
    for task_id, group, status in zip(
        (TASK_1, TASK_2, TASK_3), (GROUP_1, GROUP_1, GROUP_2), statuses
    ):
        task = _task(task_id[-1], status, group)
        task.id = task_id
        tasks.append(task)
    return _Run(tasks, wr)


class TestTaskIds:
    def test_task_ids_without_wr_work_out_the_work_requirement(self):
        run = _id_run()
        assert run.run(target=None, task_ids=[TASK_1, TASK_3]) is None
        work = run.client.work_client
        work.get_work_requirement_by_id.assert_called_once_with(WR_ID)
        assert work.get_task_by_id.call_count == 2
        creation = run.bodies()[0]
        assert [g["name"] for g in creation["taskGroups"]] == ["render", "post"]
        assert [t["name"] for t in run.bodies()[1]] == ["1"]
        assert [t["name"] for t in run.bodies()[2]] == ["3"]

    def test_task_ids_with_wr_of_another_work_requirement_refused_before_task_reads(
        self,
    ):
        run = _id_run()
        error = run.run(task_ids=[FOREIGN])
        assert isinstance(error, ValueError)
        assert str(error) == f"Task '{FOREIGN}' is not in Work Requirement {WR_ID}"
        assert not run.client.work_client.get_task_by_id.called
        assert run.posts == []

    def test_task_ids_with_wr_of_its_own_work_requirement(self):
        run = _id_run()
        assert run.run(task_ids=[TASK_1]) is None
        assert [t["name"] for t in run.bodies()[1]] == ["1"]

    def test_by_id_opening_line_and_no_left_behind_warnings(self, capsys):
        run = _id_run()
        run.held = [_task("gone", "CANCELLED", GROUP_1)]
        assert run.run(target=None, task_ids=[TASK_1, TASK_3]) is None
        out = capsys.readouterr()
        assert _flat(out.out + out.err).count("(by ID)") == 1
        assert (
            "Resubmitting 2 Tasks (by ID) from 2 Task Groups of Work Requirement"
            f" 'ns/x' ({WR_ID})" in _flat(out.out)
        )
        assert "not resubmitted" not in out.out + out.err
        assert not run.client.work_client.get_tasks.called

    def test_task_ids_with_add_to(self):
        run = _id_run()
        run.target = _target({"render": ["bash"], "post": ["bash"]})
        assert run.run(add_to=TARGET_ID, target=None, task_ids=[TASK_1, TASK_3]) is None
        posts = _task_posts(run)
        assert [(u.rsplit("/", 2)[-2], [t["name"] for t in b]) for u, b in posts] == [
            ("render", ["1"]),
            ("post", ["3"]),
        ]

    def test_nothing_created_when_a_task_is_missing_or_unfinished(self):
        missing = TASK_1[:-1] + "7"
        run = _id_run()
        error = run.run(target=None, task_ids=[TASK_1, missing])
        assert isinstance(error, NotFoundError)
        assert classify(error) == ExitCode.NOT_FOUND
        assert run.posts == []
        run = _id_run(statuses=("COMPLETED", "EXECUTING", "FAILED"))
        error = run.run(target=None, task_ids=[TASK_1, TASK_2])
        assert isinstance(error, ValueError)
        assert str(error) == f"Task '{TASK_2}' is EXECUTING and has not finished"
        assert run.posts == []

    @pytest.mark.parametrize(
        "extra, flag",
        [
            (["--task-group", "a"], "--task-group"),
            (["--task", "a"], "--task"),
            (["--failed"], "--failed"),
            (["--aborted"], "--aborted"),
        ],
    )
    def test_task_id_clashes_refused_as_parsed(self, capsys, extra, flag):
        err = _refusal(capsys, "--task-id", TASK_1, *extra)
        assert f"--task-id cannot be used with {flag}" in err

    def test_neither_wr_nor_task_id_is_an_argument_error(self, capsys):
        err = _refusal(capsys)
        assert "give a Work Requirement, or Tasks with --task-id" in err

    def test_one_id_per_flag_repeated(self):
        parser = CLIParser(
            command="yd wr resubmit",
            argv=["--task-id", TASK_1, "--task-id", TASK_2],
        )
        assert parser.task_ids == [TASK_1, TASK_2]
        assert parser.resubmit_target is None

    def test_the_word_after_a_task_id_is_the_work_requirement(self):
        parser = CLIParser(
            command="yd wr resubmit", argv=["--task-id", TASK_1, "my-run"]
        )
        assert parser.task_ids == [TASK_1]
        assert parser.resubmit_target == "my-run"

    def test_the_work_requirement_may_come_before_a_task_id(self):
        parser = CLIParser(
            command="yd wr resubmit", argv=["my-run", "--task-id", TASK_1]
        )
        assert parser.task_ids == [TASK_1]
        assert parser.resubmit_target == "my-run"


class TestParsing:
    @pytest.mark.parametrize(
        "argv, flag",
        [
            (["--add-to", "y", "--name", "n"], "--name"),
            (["--add-to", "y", "-o", "f.json"], "--output-file"),
            (["--add-to", "y", "--hold"], "--hold"),
        ],
    )
    def test_add_to_clashes_are_refused_as_parsed(self, capsys, argv, flag):
        assert f"--add-to cannot be used with {flag}" in _refusal(capsys, "x", *argv)

    @pytest.mark.parametrize("flag", ["--follow", "--progress", "--hold"])
    def test_output_file_with_following_is_refused(self, capsys, flag):
        err = _refusal(capsys, "x", "-o", "f.json", flag)
        assert f"--output-file cannot be used with {flag}" in err

    def test_the_options_are_read(self):
        parser = CLIParser(
            command="yd wr resubmit",
            argv=["x", "--failed", "--aborted", "--name", "n", "-o", "f"],
        )
        assert parser.failed and parser.aborted
        assert parser.resubmit_name == "n"
        assert parser.export_file == "f"
        assert parser.resubmit_target == "x"

    def test_the_verb_is_registered_on_workrequirement(self):
        noun = next(n for n in NOUNS if n.name == "workrequirement")
        verb = next(v for v in noun.verbs if v.name == "resubmit")
        assert verb.command == "yd-resubmit"
