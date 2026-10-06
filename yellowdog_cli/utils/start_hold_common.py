#!/usr/bin/env python3

"""
Core functionality for starting, holding and finishing Work Requirements:
yd-start, yd-hold and yd-finish.

Work Requirements are selected by the namespace and tag, by glob patterns
matched against their names, or explicitly by name or ID. Explicit targets
are resolved first, in the order given: an ID is fetched directly, whatever
its namespace, and a name is looked up in the configured namespace (or the
one it is prefixed with), preferring the Work Requirement in the state the
action applies to where a name has been reused. The rules for what cannot
be acted on, confirming and stopping on a session failure are
action_runner.py's.
"""

from dataclasses import dataclass
from typing import TypeAlias, cast

from yellowdog_client.model import (
    WorkRequirement,
    WorkRequirementStatus,
    WorkRequirementSummary,
)

from yellowdog_cli.utils.action_runner import (
    SKIPPED,
    Item,
    Record,
    Unit,
    Unresolved,
    by_type,
    carry_out,
    confirm_items,
    resolve_targets,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import ET_WORK_REQUIREMENTS
from yellowdog_cli.utils.entity_utils import (
    AmbiguousNameError,
    describe_glob_scope,
    expand_name_globs,
    find_work_requirement_by_name,
    get_filtered_work_requirement_summaries,
)
from yellowdog_cli.utils.exit_codes import NotFoundError
from yellowdog_cli.utils.follow_utils import follow_ids
from yellowdog_cli.utils.glob_utils import contains_glob_chars
from yellowdog_cli.utils.interactive import select
from yellowdog_cli.utils.misc_utils import is_http_not_found, link_entity
from yellowdog_cli.utils.printing import print_info
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

# A Work Requirement to act on: fetched by its ID, or found by its name
_Target: TypeAlias = WorkRequirement | WorkRequirementSummary


@dataclass(frozen=True)
class WorkRequirementAction:
    name: str  # E.g.: "Start"
    gerund: str  # E.g.: "Starting"
    past_tense: str  # E.g.: "Started"
    method_name: str  # WorkClient method, taking a Work Requirement ID
    statuses: tuple[WorkRequirementStatus, ...]  # Those it applies to

    @property
    def statuses_phrase(self) -> str:
        return " or ".join(str(status) for status in self.statuses)

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

    def recorder(self) -> Record:
        """The action's record, as action_runner calls it."""
        return lambda entity, _entity_type, outcome, error: self.record(
            entity, outcome, error
        )


START = WorkRequirementAction(
    name="Start",
    gerund="Starting",
    past_tense="Started",
    method_name="start_work_requirement_by_id",
    statuses=(WorkRequirementStatus.HELD,),
)

FINISH = WorkRequirementAction(
    name="Finish",
    gerund="Finishing",
    past_tense="Finished",
    method_name="finish_work_requirement_by_id",
    # A FINISHING one is in neither, so it is left out or skipped
    statuses=(WorkRequirementStatus.RUNNING, WorkRequirementStatus.HELD),
)

HOLD = WorkRequirementAction(
    name="Hold",
    gerund="Holding",
    past_tense="Held",
    method_name="hold_work_requirement_by_id",
    statuses=(WorkRequirementStatus.RUNNING,),
)


def start_work_requirements(ctx: RunContext):
    apply_work_requirement_action(ctx, START)


def hold_work_requirements(ctx: RunContext):
    apply_work_requirement_action(ctx, HOLD)


def finish_work_requirements(ctx: RunContext):
    apply_work_requirement_action(ctx, FINISH)


def apply_work_requirement_action(ctx: RunContext, action: WorkRequirementAction):
    """
    Entry point for yd-start, yd-hold and yd-finish. The command registry
    ensures that glob patterns are not mixed with explicit names or IDs.
    """
    names_or_ids: list[str] = ctx.args.work_requirement_names or []
    globs = [name for name in names_or_ids if contains_glob_chars(name)]

    if names_or_ids and not globs:
        _apply_by_name_or_id(ctx, action, names_or_ids)
        return

    if globs:
        print_info(
            f"{action.gerund} Work Requirements "
            f"{describe_glob_scope(globs, ctx.config.namespace)}"
        )
        summaries: list[WorkRequirementSummary] = expand_name_globs(
            globs,
            ctx.config.namespace,
            fetch=lambda namespace, prefix: get_filtered_work_requirement_summaries(
                ctx.client,
                name=prefix or None,
                namespace=namespace,
                include_filter=list(action.statuses),
            ),
        )
    else:
        print_info(
            f"{action.gerund} Work Requirements in namespace "
            f"'{ctx.config.namespace}' with "
            f"'{ctx.config.name_tag}' in tag"
        )
        summaries = get_filtered_work_requirement_summaries(
            client=ctx.client,
            namespace=ctx.config.namespace,
            tag=ctx.config.name_tag,
            include_filter=list(action.statuses),
        )

    selected: list[WorkRequirementSummary] = (
        select(ctx.client, summaries) if summaries else []
    )
    items = [_item(summary) for summary in selected]
    if items and not confirm_items(
        f"{action.name} {len(items)} Work Requirement(s)?", items, action.recorder()
    ):
        items = []

    _carry_out(ctx, action, items)


def _item(work_requirement: _Target) -> Item:
    return Item(
        work_requirement, ET_WORK_REQUIREMENTS, work_requirement.id, work_requirement
    )


def _apply_by_name_or_id(
    ctx: RunContext, action: WorkRequirementAction, names_or_ids: list[str]
):
    items = resolve_targets(
        names_or_ids,
        resolve=lambda target: _item(_resolve(ctx, action, target)),
        describe=lambda target: (target, ET_WORK_REQUIREMENTS),
        record=action.recorder(),
        verb=action.name.lower(),
        order=by_type(ET_WORK_REQUIREMENTS),
    )

    if not items:
        print_info(f"No Work Requirements {action.past_tense.lower()}")
        return

    question = (
        f"{action.name} {len(items)} Work Requirement(s) ("
        + ", ".join(_label(item.value) for item in items)
        + ")?"
    )
    if not confirm_items(question, items, action.recorder()):
        print_info(f"No Work Requirements {action.past_tense.lower()}")
        return

    _carry_out(ctx, action, items)


def _label(work_requirement: _Target) -> str:
    return f"'{work_requirement.namespace}/{work_requirement.name}'"


def _resolve(ctx: RunContext, action: WorkRequirementAction, target: str) -> _Target:
    """
    The Work Requirement a target names, raising Unresolved if it cannot be
    acted on. Anything else raised is a failure of the lookup itself.
    """
    ydid_type = get_ydid_type(target)
    if ydid_type == YDIDType.WORK_REQUIREMENT:
        try:
            work_requirement: _Target = (
                ctx.client.work_client.get_work_requirement_by_id(target)
            )
        except Exception as e:
            if is_http_not_found(e):
                raise Unresolved(f"Cannot find Work Requirement {target}") from e
            raise
    elif ydid_type is not None:
        raise Unresolved(f"'{target}' is not a Work Requirement ID")
    else:
        work_requirement = _resolve_name(ctx, action, target)

    if work_requirement.status not in action.statuses:
        raise Unresolved(
            f"Work Requirement {_label(work_requirement)} is"
            f" {work_requirement.status}, not {action.statuses_phrase}",
            SKIPPED,
            work_requirement,
        )
    return work_requirement


def _resolve_name(
    ctx: RunContext, action: WorkRequirementAction, name_or_namespaced_name: str
) -> WorkRequirementSummary:
    """
    The Work Requirement with a name, preferring the one in the state the
    action applies to (entity_utils.find_work_requirement_by_name()).
    """
    try:
        return find_work_requirement_by_name(
            ctx.client,
            name_or_namespaced_name,
            ctx.config.namespace,
            action.statuses,
        )
    except (NotFoundError, AmbiguousNameError) as e:
        raise Unresolved(str(e)) from e


def _carry_out(ctx: RunContext, action: WorkRequirementAction, items: list[Item]):
    """
    Apply the action to confirmed Work Requirements; report, and follow those
    actioned.
    """
    done = carry_out(
        [
            Unit(
                [item],
                act=lambda wr=item.value: _act(ctx, action, wr),
                failure=lambda e, wr=item.value: (
                    f"Failed to {action.name.lower()} Work Requirement"
                    f" {_label(wr)}: {e}"
                ),
            )
            for item in items
        ],
        action.recorder(),
    )
    actioned_ids = [cast(str, unit.items[0].key) for unit in done]

    if actioned_ids:
        print_info(f"{action.past_tense} {len(actioned_ids)} Work Requirement(s)")
        if ctx.args.follow:
            follow_ids(actioned_ids)
    else:
        print_info(f"No Work Requirements {action.past_tense.lower()}")


def _act(ctx: RunContext, action: WorkRequirementAction, work_requirement: _Target):
    result = getattr(ctx.client.work_client, action.method_name)(work_requirement.id)
    action.record(work_requirement)
    if isinstance(result, WorkRequirement):
        print_info(
            f"{action.past_tense} {link_entity(ctx.config.url, result)}"
            f" ({_label(work_requirement)})"
        )
    else:
        print_info(f"{action.past_tense} Work Requirement {_label(work_requirement)}")
