"""
Unit tests for utils/resubmission.py, against a fake Platform.

Covers:
  - every Task and Task Group field classified as copied or dropped, so an
    SDK upgrade adding one fails here
  - the statuses selected, and one status-filtered search per Task Group
  - Tasks left behind (CANCELLED, DISCARDED) counted, and the warnings
  - the document: a Task's definition kept and its Platform state lost,
    dependencies on Task Groups not copied dropped
  - the name: the lowest free number, no stacked suffix, a failed lookup
    other than 404 raised
"""

from dataclasses import fields
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from requests import HTTPError, Response
from yellowdog_client.model import (
    FailurePolicy,
    ResubmissionDestination,
    RunSpecification,
    Task,
    TaskData,
    TaskDataInput,
    TaskDataOutput,
    TaskGroup,
    TaskStatus,
    TaskTemplate,
    WorkRequirement,
    WorkRequirementStatus,
)

from yellowdog_cli.utils import resubmission
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import NotFoundError
from yellowdog_cli.utils.glob_utils import glob_literal_hint
from yellowdog_cli.utils.resubmission import (
    TASK_COPIED,
    TASK_DROPPED,
    TASK_GROUP_COPIED,
    TASK_GROUP_DROPPED,
    extension_plan,
    print_selection_warnings,
    resubmission_document,
    resubmission_name,
    select_named_tasks,
    select_tasks,
    selected_statuses,
    work_requirement_id_of_tasks,
)


def _http_error(status_code: int) -> HTTPError:
    response = Response()
    response.status_code = status_code
    return HTTPError(f"{status_code} Error", response=response)


def _task_group(name: str, id_: str, **kwargs) -> TaskGroup:
    group = TaskGroup(name=name, runSpecification=RunSpecification(["bash"]), **kwargs)
    group.id = id_
    return group


def _task(name: str, status: str, group_id: str) -> Task:
    task = Task(
        name=name,
        taskType="bash",
        arguments=["-c", "echo {{x}}"],
        environment={"A": "__{{y}}__"},
        timeout=timedelta(minutes=5),
        tag="t",
    )
    task.id = f"{group_id}:{name}"
    task.status = TaskStatus(status)
    task.errors = []
    task.nodeId = "node"
    task.workerId = "worker"
    task.retryCount = 2
    task.taskGroupId = group_id
    return task


class _Platform:
    """
    A fake work client: get_tasks() returns the Tasks of the search's Task
    Group in its statuses, and records each search.
    """

    def __init__(self, tasks: list[Task], existing: set[str] = frozenset()):
        self.tasks = tasks
        self.existing = set(existing)
        self.searches: list = []
        self.names: list = []
        self.lookup_error: Exception | None = None
        self.client = MagicMock()
        self.client.work_client.get_tasks.side_effect = self._get_tasks
        self.client.work_client.get_work_requirement_by_name.side_effect = self._by_name

    def _get_tasks(self, search):
        self.searches.append(search)
        wanted = {s.value for s in search.statuses}
        self.names.append(search.name)
        found = [
            t
            for t in self.tasks
            if t.taskGroupId == search.taskGroupId and t.status.value in wanted
        ]
        return SimpleNamespace(iterate=lambda: iter(found))

    def _by_name(self, namespace, name):
        if self.lookup_error is not None:
            raise self.lookup_error
        if name in self.existing:
            return WorkRequirement(namespace=namespace, name=name)
        raise _http_error(404)

    def ctx(self) -> RunContext:
        return RunContext(
            args=SimpleNamespace(), config=MagicMock(), client=self.client
        )


def _work_requirement(groups, status=WorkRequirementStatus.COMPLETED):
    wr = WorkRequirement(
        namespace="ns", name="x", taskGroups=groups, tag="wr-tag", priority=3
    )
    wr.id = "ydid:workreq:000000:aaaa"
    wr.status = status
    return wr


def test_every_task_field_is_classified():
    assert TASK_COPIED | TASK_DROPPED == {f.name for f in fields(Task)}
    assert not TASK_COPIED & TASK_DROPPED


def test_every_task_group_field_is_classified():
    assert TASK_GROUP_COPIED | TASK_GROUP_DROPPED == {f.name for f in fields(TaskGroup)}
    assert not TASK_GROUP_COPIED & TASK_GROUP_DROPPED


def test_failed_is_the_default_and_both_options_select_both():
    assert selected_statuses(False, False) == ("FAILED",)
    assert selected_statuses(True, False) == ("FAILED",)
    assert selected_statuses(False, True) == ("ABORTED",)
    assert set(selected_statuses(True, True)) == {"FAILED", "ABORTED"}


def _two_groups_platform():
    tasks = [
        _task("a", "FAILED", "g1"),
        _task("b", "COMPLETED", "g1"),
        _task("c", "ABORTED", "g3"),
        _task("d", "COMPLETED", "g2"),
    ]
    groups = [
        _task_group("one", "g1"),
        _task_group("two", "g2"),
        _task_group("three", "g3"),
    ]
    return _Platform(tasks), _work_requirement(groups)


def test_only_task_groups_with_selected_tasks_are_kept_in_order():
    platform, wr = _two_groups_platform()
    selection = select_tasks(platform.ctx(), wr, ("FAILED", "ABORTED"))
    assert [g.task_group.name for g in selection.groups] == ["one", "three"]
    assert [t.name for t in selection.groups[0].tasks] == ["a"]
    assert selection.task_count == 2


def test_the_search_is_filtered_by_status_once_per_task_group():
    platform, wr = _two_groups_platform()
    select_tasks(platform.ctx(), wr, ("FAILED", "ABORTED"))
    selecting = [
        s
        for s in platform.searches
        if {x.value for x in s.statuses} == {"FAILED", "ABORTED"}
    ]
    assert sorted(s.taskGroupId for s in selecting) == ["g1", "g2", "g3"]


def test_cancelled_and_discarded_tasks_are_counted_as_left_behind():
    tasks = [
        _task("a", "FAILED", "g1"),
        _task("b", "CANCELLED", "g1"),
        _task("c", "DISCARDED", "g1"),
        _task("d", "DISCARDED", "g1"),
        _task("e", "COMPLETED", "g2"),
    ]
    wr = _work_requirement([_task_group("one", "g1"), _task_group("two", "g2")])
    selection = select_tasks(_Platform(tasks).ctx(), wr, ("FAILED",))
    assert selection.left_behind == {"one": {"CANCELLED": 1, "DISCARDED": 2}}


def test_warnings_name_what_is_left_behind_and_a_running_original(monkeypatch):
    tasks = [_task("a", "FAILED", "g1")] + [
        _task(f"d{i}", "DISCARDED", "g1") for i in range(2)
    ]
    wr = _work_requirement([_task_group("one", "g1")], WorkRequirementStatus.RUNNING)
    selection = select_tasks(_Platform(tasks).ctx(), wr, ("FAILED",))
    printed: list[str] = []
    monkeypatch.setattr(resubmission, "print_warning", printed.append)
    print_selection_warnings(selection)
    assert printed == [
        "Task Group 'one' has 2 DISCARDED Tasks, not resubmitted",
        "Work Requirement 'ns/x' is RUNNING: Tasks still running may yet fail, "
        "and are not resubmitted",
    ]


def test_a_finished_original_with_nothing_left_behind_warns_of_nothing(monkeypatch):
    platform, wr = _two_groups_platform()
    selection = select_tasks(platform.ctx(), wr, ("FAILED",))
    printed: list[str] = []
    monkeypatch.setattr(resubmission, "print_warning", printed.append)
    print_selection_warnings(selection)
    assert printed == []


def test_a_copied_task_keeps_its_definition_and_loses_platform_state():
    platform, wr = _two_groups_platform()
    selection = select_tasks(platform.ctx(), wr, ("FAILED",))
    document = resubmission_document(selection, "x-resubmit-1")
    task = document["taskGroups"][0]["tasks"][0]
    original = selection.groups[0].tasks[0]
    for lost in (
        "id",
        "status",
        "errors",
        "nodeId",
        "workerId",
        "startedTime",
        "retryCount",
        "resubmittedFromTaskId",
        "taskGroupId",
    ):
        assert lost not in task
    assert task == {
        "name": original.name,
        "tag": "t",
        "taskType": "bash",
        "arguments": ["-c", "echo {{x}}"],
        "environment": {"A": "__{{y}}__"},
        "timeout": "PT5M",
    }


def test_dependencies_on_uncopied_task_groups_are_dropped():
    tasks = [_task("a", "FAILED", "g1"), _task("c", "FAILED", "g3")]
    groups = [
        _task_group("one", "g1"),
        _task_group("two", "g2"),
        _task_group("three", "g3", dependencies=["one", "two"], dependentOn="two"),
    ]
    selection = select_tasks(
        _Platform(tasks).ctx(), _work_requirement(groups), ("FAILED",)
    )
    three = resubmission_document(selection, "n")["taskGroups"][1]
    assert three["dependencies"] == ["one"]
    assert "dependentOn" not in three
    assert "id" not in three and "status" not in three and "taskSummary" not in three
    assert three["runSpecification"]["taskTypes"] == ["bash"]


def test_the_document_has_the_originals_namespace_tag_and_priority():
    platform, wr = _two_groups_platform()
    selection = select_tasks(platform.ctx(), wr, ("FAILED",))
    document = resubmission_document(selection, "new-name")
    assert document["name"] == "new-name"
    assert document["namespace"] == "ns"
    assert document["tag"] == "wr-tag"
    assert document["priority"] == 3
    assert "id" not in document and "status" not in document


def test_the_name_is_the_lowest_free_resubmit_number():
    platform = _Platform([], existing={"x-resubmit-1"})
    assert resubmission_name(platform.ctx(), "ns", "x") == "x-resubmit-2"


def test_a_taken_number_is_skipped_not_the_next_free_after_a_gap():
    platform = _Platform([], existing={"x-resubmit-1", "x-resubmit-3"})
    assert resubmission_name(platform.ctx(), "ns", "x") == "x-resubmit-2"


def test_a_resubmit_of_a_resubmit_does_not_stack_the_suffix():
    platform = _Platform([], existing={"x-resubmit-1"})
    assert resubmission_name(platform.ctx(), "ns", "x-resubmit-1") == "x-resubmit-2"


@pytest.mark.parametrize("status", [401, 403, 500])
def test_a_lookup_failure_other_than_404_is_raised(status):
    platform = _Platform([])
    platform.lookup_error = _http_error(status)
    with pytest.raises(HTTPError):
        resubmission_name(platform.ctx(), "ns", "x")


def _policy(*destinations: str) -> FailurePolicy:
    return FailurePolicy([ResubmissionDestination(d) for d in destinations])


def test_failure_policy_destinations_outside_the_copy_are_dropped_with_a_warning(
    monkeypatch,
):
    # The Platform refuses a Work Requirement whose failure policy names a
    # Task Group it lacks
    tasks = [_task("a", "FAILED", "g1")]
    one = _task_group("one", "g1")
    one.runSpecification.failurePolicy = _policy("elsewhere", "one")
    two = _task_group("two", "g2")
    selection = select_tasks(
        _Platform(tasks).ctx(), _work_requirement([one, two]), ("FAILED",)
    )
    printed: list[str] = []
    monkeypatch.setattr(resubmission, "print_warning", printed.append)
    document = resubmission_document(selection, "n")
    destinations = document["taskGroups"][0]["runSpecification"]["failurePolicy"][
        "resubmissionDestinations"
    ]
    assert [d["destinationTaskGroup"] for d in destinations] == ["one"]
    assert printed == [
        "Task Group 'one': failure policy destination 'elsewhere' was not "
        "resubmitted, and is dropped"
    ]


def test_a_failure_policy_left_without_destinations_is_dropped(monkeypatch):
    tasks = [_task("a", "FAILED", "g1")]
    one = _task_group("one", "g1")
    one.runSpecification.failurePolicy = _policy("elsewhere")
    selection = select_tasks(
        _Platform(tasks).ctx(), _work_requirement([one]), ("FAILED",)
    )
    monkeypatch.setattr(resubmission, "print_warning", lambda _message: None)
    run_specification = resubmission_document(selection, "n")["taskGroups"][0][
        "runSpecification"
    ]
    assert "failurePolicy" not in run_specification
    # The original is left as it was
    assert one.runSpecification.failurePolicy is not None


def test_an_appended_task_group_keeps_only_destinations_the_target_will_have(
    monkeypatch,
):
    tasks = [_task("a", "FAILED", "g1")]
    one = _task_group("one", "g1")
    one.runSpecification.failurePolicy = _policy("gone", "kept")
    selection = select_tasks(
        _Platform(tasks).ctx(), _work_requirement([one]), ("FAILED",)
    )
    printed: list[str] = []
    monkeypatch.setattr(resubmission, "print_warning", printed.append)
    target = _work_requirement([_task_group("kept", "t1")])
    new_groups, _ = extension_plan(target, selection)
    policy = new_groups[0].runSpecification.failurePolicy
    assert policy is not None
    assert [d.destinationTaskGroup for d in policy.resubmissionDestinations] == ["kept"]
    assert len(printed) == 1 and "'gone'" in printed[0]


def test_every_copied_field_reaches_the_document_exactly():
    task = _task("n", "FAILED", "g2")
    task.taskData = "td"
    task.data = TaskData(
        inputs=[TaskDataInput("a", "b")], outputs=[TaskDataOutput("c", "d", True)]
    )
    template = TaskTemplate("bash", "tdata", {"E": "v"})
    group = _task_group(
        "g",
        "g2",
        tag="gt",
        priority=2.5,
        dependentOn="dep",
        dependencies=["dep"],
        finishIfAllTasksFinished=False,
        finishIfAnyTaskFailed=True,
        completedTaskTtl=timedelta(hours=1),
        taskTemplate=template,
    )
    dep = _task_group("dep", "g1")
    selection = select_tasks(
        _Platform([_task("a", "FAILED", "g1"), task]).ctx(),
        _work_requirement([dep, group]),
        ("FAILED",),
    )
    task_group = resubmission_document(selection, "x-resubmit-1")["taskGroups"][1]
    assert set(task_group["tasks"][0]) == TASK_COPIED
    assert set(task_group) - {"tasks"} == TASK_GROUP_COPIED
    assert task_group == {
        "name": "g",
        "runSpecification": {"taskTypes": ["bash"]},
        "tag": "gt",
        "priority": 2.5,
        "dependentOn": "dep",
        "dependencies": ["dep"],
        "finishIfAllTasksFinished": False,
        "finishIfAnyTaskFailed": True,
        "completedTaskTtl": "PT1H",
        "taskTemplate": {
            "taskType": "bash",
            "taskData": "tdata",
            "environment": {"E": "v"},
        },
        "tasks": [
            {
                "name": "n",
                "tag": "t",
                "taskType": "bash",
                "arguments": ["-c", "echo {{x}}"],
                "taskData": "td",
                "environment": {"A": "__{{y}}__"},
                "data": {
                    "inputs": [{"source": "a", "destination": "b"}],
                    "outputs": [
                        {"source": "c", "destination": "d", "alwaysUpload": True}
                    ],
                },
                "timeout": "PT5M",
            }
        ],
    }


def _matched_plan(original_template, target_template, task_type=True):
    task = _task("a", "FAILED", "g1")
    if not task_type:
        task.taskType = None
    original = _task_group("one", "g1", taskTemplate=original_template)
    selection = select_tasks(
        _Platform([task]).ctx(), _work_requirement([original]), ("FAILED",)
    )
    target = _work_requirement([_task_group("one", "t1", taskTemplate=target_template)])
    return extension_plan(target, selection)


def test_a_template_only_task_added_to_a_matched_group_does_not_crash():
    template = TaskTemplate(taskType="bash")
    new_groups, task_lists = _matched_plan(template, template, task_type=False)
    assert new_groups == [] and "taskType" not in task_lists["one"][0]


def test_differing_task_templates_are_refused():
    with pytest.raises(ValueError) as refused:
        _matched_plan(TaskTemplate(taskType="bash"), None)
    assert str(refused.value) == (
        "Task Group 'one' of Work Requirement 'ns/x' has a different Task template"
        " from the original's, so its Tasks could run differently: resubmit them"
        " as a new Work Requirement instead"
    )


def test_equal_task_templates_are_accepted():
    new_groups, _ = _matched_plan(TaskTemplate("bash"), TaskTemplate("bash"))
    assert new_groups == []
    assert _matched_plan(None, None)[0] == []


def _filter_platform():
    tasks = [
        _task("frame-01", "FAILED", "g1"),
        _task("frame-02", "ABORTED", "g1"),
        _task("frame-02-ok", "COMPLETED", "g1"),
        _task("mask-01", "FAILED", "g1"),
        _task("frame-03", "FAILED", "g2"),
        _task("frame-04", "CANCELLED", "g2"),
        _task("other", "FAILED", "g3"),
    ]
    unnamed = _task("x", "FAILED", "g1")
    unnamed.name = None
    groups = [
        _task_group("render", "g1"),
        _task_group("render-2", "g2"),
        _task_group("post", "g3"),
    ]
    return _Platform([*tasks, unnamed]), _work_requirement(groups)


def _names(selection):
    return [[t.name for t in g.tasks] for g in selection.groups]


BOTH = ("FAILED", "ABORTED")


def test_only_matching_task_groups_are_searched():
    platform, wr = _filter_platform()
    selection = select_tasks(platform.ctx(), wr, ("FAILED",), ("post",))
    assert [g.task_group.name for g in selection.groups] == ["post"]
    assert {s.taskGroupId for s in platform.searches} == {"g3"}


def test_two_task_group_patterns_are_alternatives():
    platform, wr = _filter_platform()
    selection = select_tasks(platform.ctx(), wr, ("FAILED",), ("render-*", "post"))
    assert [g.task_group.name for g in selection.groups] == ["render-2", "post"]


def test_a_task_group_pattern_matching_nothing_raises_not_found_before_any_search():
    platform, wr = _filter_platform()
    with pytest.raises(NotFoundError) as e:
        select_tasks(platform.ctx(), wr, ("FAILED",), ("post", "Render"))
    assert str(e.value) == "No Task Group of Work Requirement 'ns/x' matches 'Render'"
    assert platform.searches == []


def test_left_behind_counts_only_for_chosen_task_groups():
    tasks = [
        _task("a", "CANCELLED", "g1"),
        _task("b", "CANCELLED", "g2"),
        _task("c", "FAILED", "g2"),
    ]
    wr = _work_requirement([_task_group("one", "g1"), _task_group("two", "g2")])
    selection = select_tasks(_Platform(tasks).ctx(), wr, ("FAILED",), ("two",))
    assert selection.left_behind == {"two": {"CANCELLED": 1}}


def test_task_pattern_glob_and_exact_name():
    platform, wr = _filter_platform()
    selection = select_tasks(platform.ctx(), wr, BOTH, (), ("frame-0*",))
    assert _names(selection) == [["frame-01", "frame-02"], ["frame-03"]]
    selection = select_tasks(platform.ctx(), wr, BOTH, (), ("mask-01",))
    assert _names(selection) == [["mask-01"]]


def test_one_task_pattern_sends_its_literal_hint():
    platform, wr = _filter_platform()
    select_tasks(platform.ctx(), wr, ("FAILED",), (), ("frame-0*",))
    assert set(platform.names) == {glob_literal_hint("frame-0*")} == {"frame-0"}


def test_a_pattern_without_a_literal_prefix_sends_its_run_as_the_filter():
    platform, wr = _filter_platform()
    selection = select_tasks(platform.ctx(), wr, BOTH, (), ("*-01",))
    assert set(platform.names) == {"-01"}
    assert "frame-01" in [n for names in _names(selection) for n in names]


def test_an_empty_hint_sends_no_name_filter():
    platform, wr = _filter_platform()
    select_tasks(platform.ctx(), wr, ("FAILED",), (), ("*",))
    assert set(platform.names) == {None}


def test_several_task_patterns_send_no_name_filter():
    platform, wr = _filter_platform()
    select_tasks(platform.ctx(), wr, ("FAILED",), (), ("mask-01", "other"))
    assert set(platform.names) == {None}


def test_an_unnamed_task_never_matches():
    platform, wr = _filter_platform()
    selection = select_tasks(platform.ctx(), wr, ("FAILED",), (), ("*",))
    assert "x" not in [n for names in _names(selection) for n in names]
    assert None not in [n for names in _names(selection) for n in names]


def test_a_task_pattern_matching_nothing_is_warned_once(monkeypatch):
    platform, wr = _filter_platform()
    printed: list[str] = []
    monkeypatch.setattr(resubmission, "print_warning", printed.append)
    selection = select_tasks(platform.ctx(), wr, BOTH, (), ("frame-9*", "mask-01"))
    print_selection_warnings(selection)
    assert printed == ["No FAILED or ABORTED Task matches 'frame-9*'"]


def test_no_left_behind_counts_under_task():
    platform, wr = _filter_platform()
    selection = select_tasks(platform.ctx(), wr, ("FAILED",), (), ("frame-*",))
    assert selection.left_behind == {}
    assert all({x.value for x in s.statuses} == {"FAILED"} for s in platform.searches)


def test_both_filters_intersect():
    platform, wr = _filter_platform()
    selection = select_tasks(platform.ctx(), wr, BOTH, ("render",), ("frame-0*",))
    assert _names(selection) == [["frame-01", "frame-02"]]


def test_a_completed_task_matching_task_is_not_copied():
    platform, wr = _filter_platform()
    selection = select_tasks(platform.ctx(), wr, ("FAILED",), (), ("frame-02-ok",))
    assert selection.task_count == 0
    assert selection.unmatched_task_patterns == ("frame-02-ok",)


WR = "ydid:workreq:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TG1 = "ydid:taskgrp:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:0"
TG2 = "ydid:taskgrp:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:1"
OTHER_WR_TASK = "ydid:task:000000:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb:0:1"


def _tid(group: int, n: int) -> str:
    return f"ydid:task:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:{group}:{n}"


def _named_platform(statuses: dict[str, str]):
    """
    A fake work client holding one Task per ID, in the status given.
    """
    platform = _Platform([])
    tasks = {}
    for task_id, status in statuses.items():
        group = task_group_of(task_id)
        task = _task(task_id.rsplit(":", 1)[1], status, group)
        task.id = task_id
        tasks[task_id] = task
    reads: list[str] = []

    def get_task_by_id(task_id):
        reads.append(task_id)
        if task_id not in tasks:
            raise _http_error(404)
        return tasks[task_id]

    platform.client.work_client.get_task_by_id.side_effect = get_task_by_id
    platform.reads = reads  # type: ignore[attr-defined]
    return platform


def task_group_of(task_id: str) -> str:
    return task_id.rsplit(":", 1)[0].replace(":task:", ":taskgrp:", 1)


def _two_groups():
    return _work_requirement([_task_group("one", TG1), _task_group("two", TG2)])


def test_ids_of_two_work_requirements_are_refused():
    with pytest.raises(ValueError) as e:
        work_requirement_id_of_tasks([_tid(0, 1), OTHER_WR_TASK])
    assert str(e.value) == f"Task '{OTHER_WR_TASK}' is not in Work Requirement {WR}"


def test_the_work_requirement_is_worked_out_from_the_ids():
    assert work_requirement_id_of_tasks([_tid(0, 1), _tid(1, 2)]) == WR


@pytest.mark.parametrize(
    "bad",
    [
        TG1,
        WR,
        "x",
        "ydid:node:000000:" + WR[-36:],
        "ydid:task:000000:" + WR[-36:],
        "ydid:task:000000:" + WR[-36:] + ":0",
    ],
)
def test_a_non_task_id_is_refused(bad):
    with pytest.raises(ValueError) as e:
        work_requirement_id_of_tasks([_tid(0, 1), bad])
    assert str(e.value) == f"'{bad}' is not a Task ID"


def test_named_tasks_in_any_finished_state_are_copied():
    ids = {_tid(0, 1): "COMPLETED", _tid(0, 2): "CANCELLED", _tid(1, 3): "FAILED"}
    platform = _named_platform(ids)
    selection = select_named_tasks(platform.ctx(), _two_groups(), list(ids))
    assert selection.by_id
    assert selection.statuses == ()
    assert selection.left_behind == {}
    assert _names(selection) == [["1", "2"], ["3"]]
    assert platform.searches == []


def test_an_unfinished_task_is_refused():
    platform = _named_platform({_tid(0, 1): "EXECUTING"})
    with pytest.raises(ValueError) as e:
        select_named_tasks(platform.ctx(), _two_groups(), [_tid(0, 1)])
    assert str(e.value) == f"Task '{_tid(0, 1)}' is EXECUTING and has not finished"


def test_a_missing_task_raises_not_found():
    platform = _named_platform({_tid(0, 1): "FAILED"})
    with pytest.raises(NotFoundError) as e:
        select_named_tasks(platform.ctx(), _two_groups(), [_tid(0, 1), _tid(0, 9)])
    assert str(e.value) == f"Cannot find Task {_tid(0, 9)}"


def test_a_duplicate_id_is_read_once_and_groups_keep_wr_order():
    ids = {_tid(1, 3): "FAILED", _tid(0, 2): "FAILED", _tid(0, 1): "FAILED"}
    platform = _named_platform(ids)
    named = [_tid(1, 3), _tid(0, 2), _tid(1, 3), _tid(0, 1)]
    selection = select_named_tasks(platform.ctx(), _two_groups(), named)
    assert platform.reads == [_tid(1, 3), _tid(0, 2), _tid(0, 1)]
    assert [g.task_group.name for g in selection.groups] == ["one", "two"]
    assert _names(selection) == [["2", "1"], ["3"]]
