"""
A Work Requirement or one of its Task Groups named on the command line, as
yd-abort and yd-priority read one: 'wr', 'wr/tg', 'namespace/wr' or
'namespace/wr/tg'. Of the two readings of 'a/b', the Task Group is tried
first; an ambiguous Work Requirement name rules out only that reading.

A name pattern (a wildcard in the last part: 'wr-*', 'wr/tg-*',
'namespace/wr-*', 'namespace/wr/tg-*') is read the same way, and stands for
the unfinished Work Requirements or Task Groups it matches
(matching_work_ids()).
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from yellowdog_cli.utils.entity_names import ET_TASK_GROUPS, ET_WORK_REQUIREMENTS
from yellowdog_cli.utils.entity_utils import (
    AmbiguousNameError,
    expand_name_globs,
    get_filtered_work_requirement_summaries,
    get_task_groups_from_wr_by_id,
    get_work_requirement_summary_by_name_or_id,
)
from yellowdog_cli.utils.exit_codes import NotFoundError
from yellowdog_cli.utils.glob_utils import contains_glob_chars

if TYPE_CHECKING:
    from yellowdog_client import PlatformClient
    from yellowdog_client.model import TaskGroup, WorkRequirementSummary


_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class NamedTarget:
    """
    What a named target resolved to: a Work Requirement, and the Task Group
    in it when the target named one.
    """

    work_requirement: WorkRequirementSummary
    task_group: TaskGroup | None = None


class TargetNotFound(NotFoundError):
    """
    A named target that names nothing: 'what' says what was looked for
    ("Task Group 'tg' in Work Requirement 'wr'"), and 'entity_type' the type
    it is recorded as. A NotFoundError, so it exits NOT_FOUND.
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
                _LOG.debug(
                    "'%s' read as Task Group '%s' in Work Requirement '%s'",
                    target,
                    second,
                    first,
                )
                return NamedTarget(work_requirement, task_group)
        namespaced = _work_requirement_named(client, second, first)
        if namespaced is not None:
            _LOG.debug(
                "'%s' read as Work Requirement '%s' in namespace '%s'%s",
                target,
                second,
                first,
                (
                    f", Work Requirement '{first}' having no Task Group '{second}'"
                    if work_requirement is not None
                    else ""
                ),
            )
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


def matching_work_ids(
    client: PlatformClient, pattern: str, namespace: str | None
) -> list[str]:
    """
    The IDs of the unfinished Work Requirements, or Task Groups, a name
    pattern matches, read as a name is: 'wr-*' and 'namespace/wr-*' Work
    Requirements; 'wr/tg-*' the Task Groups of Work Requirement 'wr' if it
    has any that match, else the Work Requirements 'tg-*' in namespace 'wr';
    'namespace/wr/tg-*' Task Groups. Raises MalformedTarget for a wildcard
    anywhere but the last part.
    """
    parts = pattern.split("/")
    if parts[0] == "" and len(parts) > 1:  # a leading '/' names no namespace
        parts = parts[1:]
    if not 1 <= len(parts) <= 3 or not all(parts):
        raise MalformedTarget(pattern)
    if any(contains_glob_chars(part) for part in parts[:-1]):
        raise ValueError(
            f"'{pattern}': a wildcard may be given in the last part of the name alone"
        )
    match parts:
        case [name]:
            return _matching_work_requirements(client, name, namespace)
        case [first, second]:
            work_requirement = _unambiguous(client, first, namespace)
            if work_requirement is not None and (
                ids := _matching_task_groups(client, work_requirement, second)
            ):
                return ids
            return _matching_work_requirements(client, second, first)
        case [target_namespace, work_requirement_name, task_group_pattern]:
            work_requirement = _work_requirement_named(
                client, work_requirement_name, target_namespace
            )
            if work_requirement is None:
                raise TargetNotFound(
                    f"Work Requirement '{work_requirement_name}' in namespace"
                    f" '{target_namespace}'",
                    ET_TASK_GROUPS,
                )
            return _matching_task_groups(client, work_requirement, task_group_pattern)
    raise MalformedTarget(pattern)


def _unambiguous(
    client: PlatformClient, name: str, namespace: str | None
) -> WorkRequirementSummary | None:
    """
    The Work Requirement of the name, or None if there is none, or more than
    one: an ambiguous name rules out only the Task Group reading.
    """
    try:
        return _work_requirement_named(client, name, namespace)
    except AmbiguousNameError:
        return None


def _matching_work_requirements(
    client: PlatformClient, pattern: str, namespace: str | None
) -> list[str]:
    from yellowdog_client.model import WorkRequirementStatus

    from yellowdog_cli.utils.entity_utils import FINISHED_WORK_REQUIREMENT_STATUSES

    unfinished = [
        status
        for status in WorkRequirementStatus
        if status not in FINISHED_WORK_REQUIREMENT_STATUSES
    ]
    return [
        cast(str, summary.id)
        for summary in expand_name_globs(
            [pattern],
            namespace,
            fetch=lambda ns, prefix: get_filtered_work_requirement_summaries(
                client, name=prefix or None, namespace=ns, include_filter=unfinished
            ),
        )
    ]


def _matching_task_groups(
    client: PlatformClient, work_requirement: WorkRequirementSummary, pattern: str
) -> list[str]:
    from yellowdog_client.model import TaskGroupStatus

    finished = {
        TaskGroupStatus.COMPLETED,
        TaskGroupStatus.FAILED,
        TaskGroupStatus.CANCELLED,
    }
    return [
        cast(str, group.id)
        for group in get_task_groups_from_wr_by_id(client, work_requirement.id)  # type: ignore[arg-type]
        if group.name is not None
        and fnmatch.fnmatchcase(group.name, pattern)
        and group.status not in finished
    ]
