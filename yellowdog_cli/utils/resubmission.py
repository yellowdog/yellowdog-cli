"""
Resubmitting a Work Requirement's failed or aborted Tasks: choosing the Tasks
(one status-filtered search per Task Group), the Platform document that
copies them into a new Work Requirement, that Work Requirement's name, and
the warnings about what is not copied.

The document is the SDK's own serialisation of the original's Task Groups and
Tasks, kept to the fields a definition is made of, so timeouts and
enumerations come out in the Platform's format, as 'yd workrequirement submit
--json-raw' posts them. Every field of Task and TaskGroup is classified as
copied or dropped, which tests/test_resubmission.py holds to the SDK's
models, so a field an SDK upgrade adds is decided on before it is silently
lost.
"""

import re
from dataclasses import dataclass, replace
from typing import Any, cast

from yellowdog_client.common.json import Json
from yellowdog_client.model import (
    FailurePolicy,
    RunSpecification,
    Task,
    TaskGroup,
    WorkRequirement,
    WorkRequirementStatus,
)

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_utils import (
    FINISHED_WORK_REQUIREMENT_STATUSES,
    iterate_tasks_in_task_group,
)
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.printing import counted, print_warning
from yellowdog_cli.utils.settings import RESUBMIT_SUFFIX
from yellowdog_cli.utils.task_groups import check_task_types_allowed

FAILED = "FAILED"
ABORTED = "ABORTED"

# Tasks that finished without running to completion, but are not resubmitted:
# the user's own decision or the Platform's
LEFT_BEHIND_STATUSES = ("CANCELLED", "DISCARDED")

# A Task's definition is copied; where it ran and how it fared is not
TASK_COPIED = frozenset(
    {
        "name",
        "tag",
        "taskType",
        "arguments",
        "taskData",
        "environment",
        "data",
        "timeout",
    }
)
TASK_DROPPED = frozenset(
    {
        "id",
        "status",
        "retryCount",
        "taskGroupId",
        "nodeId",
        "workerId",
        "errors",
        "resubmittedToTaskId",
        "resubmittedFromTaskId",
        "startedTime",
        "finishedTime",
        "workingTime",
        "abortRequestedTime",
    }
)

TASK_GROUP_COPIED = frozenset(
    {
        "name",
        "tag",
        "priority",
        "runSpecification",
        "dependencies",
        "dependentOn",
        "finishIfAllTasksFinished",
        "finishIfAnyTaskFailed",
        "completedTaskTtl",
        "taskTemplate",
    }
)
TASK_GROUP_DROPPED = frozenset(
    {
        "id",
        "status",
        "statusChangedTime",
        "taskSummary",
        "starved",
        "waitingOnDependency",
    }
)

WORK_REQUIREMENT_COPIED = ("namespace", "tag", "priority")


@dataclass
class SelectedGroup:
    """
    A Task Group of the original and its Tasks that are to be resubmitted.
    """

    task_group: TaskGroup
    tasks: list[Task]


@dataclass
class Selection:
    """
    The Tasks to resubmit from a Work Requirement, by Task Group in the
    original's order, and the Tasks left behind: 'left_behind' is Task Group
    name -> status -> count, for the statuses never resubmitted.
    """

    work_requirement: WorkRequirement
    statuses: tuple[str, ...]
    groups: list[SelectedGroup]
    left_behind: dict[str, dict[str, int]]

    @property
    def task_count(self) -> int:
        return sum(len(group.tasks) for group in self.groups)


def selected_statuses(failed: bool, aborted: bool) -> tuple[str, ...]:
    """
    The Task statuses to resubmit: FAILED unless only '--aborted' is given,
    both where both are.
    """
    if failed and aborted:
        return (FAILED, ABORTED)
    if aborted:
        return (ABORTED,)
    return (FAILED,)


def _count_tasks(ctx: RunContext, task_group_id: str, status: str) -> int:
    """
    The Tasks of a Task Group in a status, counted a page at a time.
    """
    return sum(
        1
        for _ in iterate_tasks_in_task_group(
            ctx.client, task_group_id, statuses=(status,)
        )
    )


def select_tasks(
    ctx: RunContext, work_requirement: WorkRequirement, statuses: tuple[str, ...]
) -> Selection:
    """
    The Tasks of a Work Requirement in 'statuses': one status-filtered search
    per Task Group, read a page at a time. Task Groups without any are
    omitted. The CANCELLED and DISCARDED Tasks are counted, for the warnings.
    """
    groups: list[SelectedGroup] = []
    left_behind: dict[str, dict[str, int]] = {}
    for task_group in work_requirement.taskGroups or []:
        assert task_group.id is not None
        tasks = list(
            iterate_tasks_in_task_group(ctx.client, task_group.id, statuses=statuses)
        )
        if tasks:
            groups.append(SelectedGroup(task_group, tasks))
        for status in LEFT_BEHIND_STATUSES:
            count = _count_tasks(ctx, task_group.id, status)
            if count > 0:
                left_behind.setdefault(task_group.name, {})[status] = count
    return Selection(work_requirement, statuses, groups, left_behind)


def _copied(obj: Any, copied: frozenset[str]) -> dict[str, Any]:
    """
    The Platform JSON of an SDK object, less the fields not copied and the
    properties holding None.
    """
    return {
        key: value
        for key, value in cast(dict[str, Any], Json.dump(obj)).items()
        if key in copied and value is not None
    }


def _warn_destination_dropped(group_name: str, destination: str) -> None:
    """
    Warn that a failure policy destination is not carried over.
    """
    print_warning(
        f"Task Group '{group_name}': failure policy destination '{destination}'"
        " was not resubmitted, and is dropped"
    )


def _restrict_failure_policy(
    group_name: str, run_specification: dict, known: set[str]
) -> None:
    """
    Drop the failure policy destinations of a copied Task Group's run
    specification that name a Task Group outside 'known' (the Platform
    refuses a Work Requirement with one), warning of each, and the failure
    policy itself when none remains.
    """
    policy = run_specification.get("failurePolicy")
    if not policy:
        return
    destinations = policy.get("resubmissionDestinations") or []
    kept = []
    for destination in destinations:
        if destination.get("destinationTaskGroup") in known:
            kept.append(destination)
        else:
            _warn_destination_dropped(group_name, destination["destinationTaskGroup"])
    if kept:
        policy["resubmissionDestinations"] = kept
    else:
        del run_specification["failurePolicy"]


def _restricted_run_specification(
    group_name: str, run_specification: RunSpecification, known: set[str]
) -> RunSpecification:
    """
    The run specification less the failure policy destinations outside
    'known', as _restrict_failure_policy() does; the original unchanged.
    """
    policy = run_specification.failurePolicy
    if policy is None:
        return run_specification
    kept = []
    for destination in policy.resubmissionDestinations or []:
        if destination.destinationTaskGroup in known:
            kept.append(destination)
        else:
            _warn_destination_dropped(group_name, destination.destinationTaskGroup)
    return replace(
        run_specification,
        failurePolicy=FailurePolicy(kept) if kept else None,
    )


def resubmission_document(selection: Selection, name: str) -> dict:
    """
    The Platform's Work Requirement document for the selected Tasks, named
    'name': the original's namespace, tag and priority, the Task Groups
    holding Tasks and the Tasks themselves. A dependency on a Task Group not
    copied is dropped, as is a failure policy destination in one (warned of),
    which the Platform refuses.
    """
    original = selection.work_requirement
    kept = {group.task_group.name for group in selection.groups}
    document: dict[str, Any] = {"name": name}
    for key in WORK_REQUIREMENT_COPIED:
        value = getattr(original, key, None)
        if value is not None:
            document[key] = value
    task_groups = []
    for group in selection.groups:
        task_group = _copied(group.task_group, TASK_GROUP_COPIED)
        _restrict_failure_policy(
            group.task_group.name, task_group.get("runSpecification", {}), kept
        )
        if "dependencies" in task_group:
            dependencies = [d for d in task_group["dependencies"] if d in kept]
            if dependencies:
                task_group["dependencies"] = dependencies
            else:
                del task_group["dependencies"]
        if task_group.get("dependentOn") not in kept:
            task_group.pop("dependentOn", None)
        task_group["tasks"] = [_copied(task, TASK_COPIED) for task in group.tasks]
        task_groups.append(task_group)
    document["taskGroups"] = task_groups
    return document


def _check_matching_template(
    target: WorkRequirement, existing: TaskGroup, original: TaskGroup
) -> None:
    """
    Raise a ValueError if the target's Task Group has a Task template other
    than the original's, since the copied Tasks, which rely on the
    original's, could then run differently.
    """
    if Json.dump(existing.taskTemplate) != Json.dump(original.taskTemplate):
        raise ValueError(
            f"Task Group '{existing.name}' of Work Requirement"
            f" '{target.namespace}/{target.name}' has a different Task template"
            " from the original's, so its Tasks could run differently: resubmit"
            " them as a new Work Requirement instead"
        )


def extension_plan(
    target: WorkRequirement, selection: Selection
) -> tuple[list[TaskGroup], dict[str, list[dict]]]:
    """
    How the selected Tasks join an existing Work Requirement: the Task
    Groups to append to it (a copied Task Group the target lacks, built from
    its copied fields, its dependencies kept only where they name a Task
    Group the target has or that is appended) and the Tasks to add, as
    Platform JSON, by Task Group name. A Task Group the target has is left
    as it is. Raises ValueError for a matched Task Group whose Task template differs
    from the original's, or that does not allow a Task's type.
    """
    existing = {group.name: group for group in target.taskGroups or []}
    appended_names = {
        group.task_group.name
        for group in selection.groups
        if group.task_group.name not in existing
    }
    known = set(existing) | appended_names
    task_lists = {
        group.task_group.name: [_copied(task, TASK_COPIED) for task in group.tasks]
        for group in selection.groups
    }
    new_groups: list[TaskGroup] = []
    for group in selection.groups:
        name = group.task_group.name
        if name in existing:
            _check_matching_template(target, existing[name], group.task_group)
            check_task_types_allowed(
                existing[name],
                {
                    task["taskType"]
                    for task in task_lists[name]
                    if task.get("taskType") is not None
                },
            )
            continue
        original = group.task_group
        dependencies = [d for d in original.dependencies or [] if d in known]
        new_groups.append(
            TaskGroup(
                name=name,
                runSpecification=_restricted_run_specification(
                    name, original.runSpecification, known
                ),
                tag=original.tag,
                priority=original.priority,
                dependentOn=original.dependentOn
                if original.dependentOn in known
                else None,
                dependencies=dependencies or None,
                finishIfAllTasksFinished=original.finishIfAllTasksFinished,
                finishIfAnyTaskFailed=original.finishIfAnyTaskFailed,
                completedTaskTtl=original.completedTaskTtl,
                taskTemplate=original.taskTemplate,
            )
        )
    return new_groups, task_lists


def refuse_task_name_clashes(
    ctx: RunContext, target: WorkRequirement, task_lists: dict[str, list[dict]]
) -> None:
    """
    Raise a ValueError naming the first Task whose name a Task Group of the
    target already holds, which the Platform would refuse part-way through
    adding. Each matched Task Group's Task names are read once, a page at a
    time; a Task without a name cannot clash.
    """
    for group in target.taskGroups or []:
        names = [
            task["name"] for task in task_lists.get(group.name, []) if "name" in task
        ]
        if not names:
            continue
        assert group.id is not None
        held = {task.name for task in iterate_tasks_in_task_group(ctx.client, group.id)}
        for name in names:
            if name in held:
                raise ValueError(
                    f"Task Group '{group.name}' of Work Requirement"
                    f" '{target.namespace}/{target.name}' already holds a Task"
                    f" named '{name}'"
                )


def resubmission_name(ctx: RunContext, namespace: str, original: str) -> str:
    """
    '<base>-resubmit-<n>', <base> the original's name without a resubmission
    suffix of its own, <n> the lowest from 1 for which no Work Requirement of
    that name exists in the namespace. A failed lookup other than 'not
    found' is raised.
    """
    base = re.sub(rf"{re.escape(RESUBMIT_SUFFIX)}\d+$", "", original)
    number = 1
    while True:
        candidate = f"{base}{RESUBMIT_SUFFIX}{number}"
        try:
            ctx.client.work_client.get_work_requirement_by_name(namespace, candidate)
        except Exception as e:
            if is_http_not_found(e):
                return candidate
            raise
        number += 1


def print_selection_warnings(selection: Selection) -> None:
    """
    Warn of the Tasks left behind, and that a Work Requirement still running
    may yet have more to resubmit.
    """
    original = selection.work_requirement
    for group_name, by_status in selection.left_behind.items():
        for status, count in by_status.items():
            print_warning(
                f"Task Group '{group_name}' has {counted(count, f'{status} Task')}"
                ", not resubmitted"
            )
    if original.status not in FINISHED_WORK_REQUIREMENT_STATUSES:
        status = (
            original.status.value
            if isinstance(original.status, WorkRequirementStatus)
            else original.status
        )
        print_warning(
            f"Work Requirement '{original.namespace}/{original.name}' is {status}: "
            "Tasks still running may yet fail, and are not resubmitted"
        )
