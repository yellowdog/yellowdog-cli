"""
A Work Requirement or one of its Task Groups named on the command line, as
yd-abort and yd-priority read one: 'wr', 'wr/tg', 'namespace/wr' or
'namespace/wr/tg'. Of the two readings of 'a/b', the Task Group is tried
first; an ambiguous Work Requirement name rules out only that reading.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from yellowdog_cli.utils.entity_names import ET_TASK_GROUPS, ET_WORK_REQUIREMENTS
from yellowdog_cli.utils.entity_utils import (
    AmbiguousNameError,
    get_task_groups_from_wr_by_id,
    get_work_requirement_summary_by_name_or_id,
)

if TYPE_CHECKING:
    from yellowdog_client import PlatformClient
    from yellowdog_client.model import TaskGroup, WorkRequirementSummary


@dataclass(frozen=True)
class NamedTarget:
    """
    What a named target resolved to: a Work Requirement, and the Task Group
    in it when the target named one.
    """

    work_requirement: WorkRequirementSummary
    task_group: TaskGroup | None = None


class TargetNotFound(LookupError):
    """
    A named target that names nothing: 'what' says what was looked for
    ("Task Group 'tg' in Work Requirement 'wr'"), and 'entity_type' the type
    it is recorded as.
    """

    def __init__(self, what: str, entity_type: str):
        super().__init__(f"{what} not found")
        self.what = what
        self.entity_type = entity_type


class MalformedTarget(ValueError):
    """
    A named target of none of the forms.
    """

    def __init__(self, target: str):
        super().__init__(
            f"'{target}' is not of the form 'wr', 'wr/tg', 'namespace/wr' or"
            " 'namespace/wr/tg'"
        )


def named_target_entity_type(target: str) -> str:
    """
    The type a named target is recorded as before it is resolved: a Task
    Group if it may name one.
    """
    return ET_WORK_REQUIREMENTS if "/" not in target else ET_TASK_GROUPS


def resolve_named_target(
    client: PlatformClient, target: str, namespace: str | None
) -> NamedTarget:
    """
    The Work Requirement, or Task Group, a named target names. Raises
    TargetNotFound, MalformedTarget or AmbiguousNameError; any other failure
    is the lookup's own, and is raised as it is.
    """
    parts = target.split("/")
    if parts[0] == "" and len(parts) > 1:  # a leading '/' names no namespace
        parts = parts[1:]

    if len(parts) == 1:
        work_requirement = _work_requirement_named(client, parts[0], namespace)
        if work_requirement is None:
            raise TargetNotFound(f"Work Requirement '{target}'", ET_WORK_REQUIREMENTS)
        return NamedTarget(work_requirement)

    if len(parts) == 2:
        first, second = parts
        ambiguous: AmbiguousNameError | None = None
        try:
            work_requirement = _work_requirement_named(client, first, namespace)
        except AmbiguousNameError as e:
            work_requirement, ambiguous = None, e
        if work_requirement is not None:
            task_group = _task_group_named(client, work_requirement, second)
            if task_group is not None:
                return NamedTarget(work_requirement, task_group)
        namespaced = _work_requirement_named(client, second, first)
        if namespaced is not None:
            return NamedTarget(namespaced)
        if ambiguous is not None:
            raise ambiguous
        if work_requirement is not None:
            raise TargetNotFound(
                f"Task Group '{second}' in Work Requirement '{first}'", ET_TASK_GROUPS
            )
        raise TargetNotFound(
            f"Work Requirement '{first}' (or '{second}' in namespace '{first}')",
            ET_WORK_REQUIREMENTS,
        )

    if len(parts) == 3:
        target_namespace, work_requirement_name, task_group_name = parts
        work_requirement = _work_requirement_named(
            client, work_requirement_name, target_namespace
        )
        if work_requirement is None:
            raise TargetNotFound(
                f"Work Requirement '{work_requirement_name}' in namespace"
                f" '{target_namespace}'",
                ET_TASK_GROUPS,
            )
        task_group = _task_group_named(client, work_requirement, task_group_name)
        if task_group is None:
            raise TargetNotFound(
                f"Task Group '{task_group_name}' in Work Requirement"
                f" '{work_requirement_name}'",
                ET_TASK_GROUPS,
            )
        return NamedTarget(work_requirement, task_group)

    raise MalformedTarget(target)


def _work_requirement_named(
    client: PlatformClient, name: str, namespace: str | None
) -> WorkRequirementSummary | None:
    """
    A Work Requirement by its name, which holds no '/', in a namespace.
    """
    return get_work_requirement_summary_by_name_or_id(client, name, namespace=namespace)


def _task_group_named(
    client: PlatformClient, work_requirement: WorkRequirementSummary, name: str
) -> TaskGroup | None:
    task_groups = get_task_groups_from_wr_by_id(client, work_requirement.id)  # type: ignore[arg-type]
    return next((group for group in task_groups if group.name == name), None)
