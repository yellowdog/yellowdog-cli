#!/usr/bin/env python3

"""
Core functionality for starting and holding Work Requirements: yd-start and
yd-hold.

Work Requirements are selected by the namespace and tag, by glob patterns
matched against their names, or explicitly by name or ID. Explicit targets
are resolved first, in the order given: an ID is fetched directly, whatever
its namespace, and a name is looked up in the configured namespace (or the
one it is prefixed with), preferring the Work Requirement in the state the
action applies to where a name has been reused. Those that cannot be acted
on are recorded as 'failed' (not found, ambiguous) or 'skipped' (in another
state); the rest are confirmed once and acted on. A failure every later call
would repeat (exit_codes.SESSION_FAILURES: authentication, connection) stops
the run, and the targets not yet attempted are recorded as skipped.
"""

from dataclasses import dataclass
from typing import TypeAlias, cast

from yellowdog_client.model import (
    WorkRequirement,
    WorkRequirementStatus,
    WorkRequirementSummary,
)

from yellowdog_cli.utils.entity_utils import (
    describe_glob_scope,
    expand_name_globs,
    get_filtered_work_requirement_summaries,
    resolve_name_glob,
)
from yellowdog_cli.utils.exit_codes import SESSION_FAILURES, classify
from yellowdog_cli.utils.follow_utils import follow_ids
from yellowdog_cli.utils.glob_utils import contains_glob_chars
from yellowdog_cli.utils.interactive import confirmed, select
from yellowdog_cli.utils.misc_utils import is_http_not_found, link_entity
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.settings import ET_WORK_REQUIREMENTS
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

# A Work Requirement to act on: fetched by its ID, or found by its name
_Target: TypeAlias = WorkRequirement | WorkRequirementSummary


@dataclass(frozen=True)
class WorkRequirementAction:
    name: str  # E.g.: "Start"
    gerund: str  # E.g.: "Starting"
    past_tense: str  # E.g.: "Started"
    method_name: str  # WorkClient method, taking a Work Requirement ID
    required_status: WorkRequirementStatus

    def record(
        self, entity: object, outcome: str | None = None, error: str | None = None
    ) -> None:
        """
        Record the action's outcome for '--json': by default, that it was
        applied ('started'); otherwise 'skipped' or 'failed'.
        """
        record_action(
            entity,
            ET_WORK_REQUIREMENTS,
            self.name.lower(),
            outcome or self.past_tense.lower(),
            error,
        )


START = WorkRequirementAction(
    name="Start",
    gerund="Starting",
    past_tense="Started",
    method_name="start_work_requirement_by_id",
    required_status=WorkRequirementStatus.HELD,
)

HOLD = WorkRequirementAction(
    name="Hold",
    gerund="Holding",
    past_tense="Held",
    method_name="hold_work_requirement_by_id",
    required_status=WorkRequirementStatus.RUNNING,
)


def start_work_requirements():
    apply_work_requirement_action(START)


def hold_work_requirements():
    apply_work_requirement_action(HOLD)


def apply_work_requirement_action(action: WorkRequirementAction):
    """
    Entry point for yd-start and yd-hold. The command registry ensures that
    glob patterns are not mixed with explicit names or IDs.
    """
    names_or_ids: list[str] = ARGS_PARSER.work_requirement_names or []
    globs = [name for name in names_or_ids if contains_glob_chars(name)]

    if names_or_ids and not globs:
        _apply_by_name_or_id(action, names_or_ids)
        return

    if globs:
        print_info(
            f"{action.gerund} Work Requirements "
            f"{describe_glob_scope(globs, CONFIG_COMMON.namespace)}"
        )
        summaries: list[WorkRequirementSummary] = expand_name_globs(
            globs,
            CONFIG_COMMON.namespace,
            fetch=lambda namespace, prefix: get_filtered_work_requirement_summaries(
                CLIENT,
                name=prefix or None,
                namespace=namespace,
                include_filter=[action.required_status],
            ),
        )
    else:
        print_info(
            f"{action.gerund} Work Requirements in namespace "
            f"'{CONFIG_COMMON.namespace}' with "
            f"'{CONFIG_COMMON.name_tag}' in tag"
        )
        summaries = get_filtered_work_requirement_summaries(
            client=CLIENT,
            namespace=CONFIG_COMMON.namespace,
            tag=CONFIG_COMMON.name_tag,
            include_filter=[action.required_status],
        )

    selected: list[WorkRequirementSummary] = (
        select(CLIENT, summaries) if summaries else []
    )
    if selected and not confirmed(
        f"{action.name} {len(selected)} Work Requirement(s)?"
    ):
        for summary in selected:
            action.record(summary, "skipped")
        selected = []

    _carry_out(action, list(selected))


class _Unresolved(Exception):
    """
    A target that cannot be acted on, for a reason the user should see:
    'failed' unless it exists but is in another state ('skipped'), in which
    case 'entity' is what was found, to be recorded by its ID and name.
    """

    def __init__(
        self, message: str, outcome: str = "failed", entity: object | None = None
    ):
        super().__init__(message)
        self.outcome = outcome
        self.entity = entity


def _apply_by_name_or_id(action: WorkRequirementAction, names_or_ids: list[str]):
    targets = list(dict.fromkeys(names_or_ids))  # In order, without duplicates
    resolved: list[_Target] = []

    for index, target in enumerate(targets):
        try:
            work_requirement = _resolve(action, target)
        except _Unresolved as e:
            (print_warning if e.outcome == "skipped" else print_error)(str(e))
            action.record(e.entity or target, e.outcome, str(e))
            continue
        except Exception as e:
            print_error(f"Unable to {action.name.lower()} '{target}': {e}")
            action.record(target, "failed", str(e))
            if classify(e) in SESSION_FAILURES:
                _warn_not_attempted(len(targets) - index - 1 + len(resolved))
                for work_requirement in resolved:
                    action.record(work_requirement, "skipped", f"not attempted: {e}")
                for remaining in targets[index + 1 :]:
                    action.record(remaining, "skipped", f"not attempted: {e}")
                return
            continue
        if all(wr.id != work_requirement.id for wr in resolved):  # name and ID
            resolved.append(work_requirement)

    if not resolved:
        print_info(f"No Work Requirements {action.past_tense.lower()}")
        return

    if not confirmed(
        f"{action.name} {len(resolved)} Work Requirement(s) ("
        + ", ".join(_label(wr) for wr in resolved)
        + ")?"
    ):
        for work_requirement in resolved:
            action.record(work_requirement, "skipped")
        print_info(f"No Work Requirements {action.past_tense.lower()}")
        return

    _carry_out(action, resolved)


def _label(work_requirement: _Target) -> str:
    return f"'{work_requirement.namespace}/{work_requirement.name}'"


def _resolve(action: WorkRequirementAction, target: str) -> _Target:
    """
    The Work Requirement a target names, raising _Unresolved if it cannot be
    acted on. Anything else raised is a failure of the lookup itself.
    """
    ydid_type = get_ydid_type(target)
    if ydid_type == YDIDType.WORK_REQUIREMENT:
        try:
            work_requirement: _Target = CLIENT.work_client.get_work_requirement_by_id(
                target
            )
        except Exception as e:
            if is_http_not_found(e):
                raise _Unresolved(f"Cannot find Work Requirement {target}") from e
            raise
    elif ydid_type is not None:
        raise _Unresolved(f"'{target}' is not a Work Requirement ID")
    else:
        work_requirement = _resolve_name(action, target)

    if work_requirement.status != action.required_status:
        raise _Unresolved(
            f"Work Requirement {_label(work_requirement)} is"
            f" {work_requirement.status}, not {action.required_status}",
            "skipped",
            work_requirement,
        )
    return work_requirement


def _resolve_name(
    action: WorkRequirementAction, name_or_namespaced_name: str
) -> WorkRequirementSummary:
    """
    The Work Requirement with a name, in the configured namespace unless the
    name has a 'namespace/' prefix. A name can be reused, so the one in the
    state the action applies to is preferred; with none in that state, one
    in another state is returned (to be skipped), and with two or more, the
    name is ambiguous.
    """
    namespace, name = resolve_name_glob(
        name_or_namespaced_name, CONFIG_COMMON.namespace
    )
    candidates = [
        summary
        for summary in get_filtered_work_requirement_summaries(
            CLIENT, name=name, namespace=namespace
        )
        if summary.name == name  # The search matches partial names
    ]
    if not candidates:
        raise _Unresolved(
            f"Cannot find Work Requirement '{name}' in namespace '{namespace}'"
        )
    in_state = [s for s in candidates if s.status == action.required_status]
    if len(in_state) > 1:
        raise _Unresolved(
            f"{len(in_state)} {action.required_status} Work Requirements are named"
            f" '{namespace}/{name}'; please supply its ID"
        )
    return (in_state or candidates)[0]


def _warn_not_attempted(count: int):
    if count:
        print_warning(
            f"Not attempting the remaining {count} item(s),"
            " which would fail in the same way"
        )


def _carry_out(action: WorkRequirementAction, work_requirements: list[_Target]):
    """
    Apply the action to confirmed Work Requirements; report, and follow those
    actioned.
    """
    actioned_ids: list[str] = []
    for index, work_requirement in enumerate(work_requirements):
        try:
            result = getattr(CLIENT.work_client, action.method_name)(
                work_requirement.id
            )
        except Exception as e:
            print_error(
                f"Failed to {action.name.lower()} Work Requirement"
                f" {_label(work_requirement)}: {e}"
            )
            action.record(work_requirement, "failed", str(e))
            if classify(e) in SESSION_FAILURES:
                not_attempted = work_requirements[index + 1 :]
                _warn_not_attempted(len(not_attempted))
                for remaining in not_attempted:
                    action.record(remaining, "skipped", f"not attempted: {e}")
                break
            continue
        actioned_ids.append(cast(str, work_requirement.id))
        action.record(work_requirement)
        if isinstance(result, WorkRequirement):
            print_info(
                f"{action.past_tense} {link_entity(CONFIG_COMMON.url, result)}"
                f" ({_label(work_requirement)})"
            )
        else:
            print_info(
                f"{action.past_tense} Work Requirement {_label(work_requirement)}"
            )

    if actioned_ids:
        print_info(f"{action.past_tense} {len(actioned_ids)} Work Requirement(s)")
        if ARGS_PARSER.follow:
            follow_ids(actioned_ids)
    else:
        print_info(f"No Work Requirements {action.past_tense.lower()}")
