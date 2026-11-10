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
from yellowdog_cli.utils.resubmission import (
    TASK_COPIED,
    TASK_DROPPED,
    TASK_GROUP_COPIED,
    TASK_GROUP_DROPPED,
    extension_plan,
    print_selection_warnings,
    resubmission_document,
    resubmission_name,
    select_tasks,
    selected_statuses,
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
        self.lookup_error: Exception | None = None
        self.client = MagicMock()
        self.client.work_client.get_tasks.side_effect = self._get_tasks
        self.client.work_client.get_work_requirement_by_name.side_effect = self._by_name

    def _get_tasks(self, search):
        self.searches.append(search)
        wanted = {s.value for s in search.statuses}
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
