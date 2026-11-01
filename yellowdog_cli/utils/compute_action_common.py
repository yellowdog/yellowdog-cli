#!/usr/bin/env python3

"""
Core functionality for stopping, starting, restarting, terminating,
deprovisioning and reprovisioning Compute Requirements and Instances, and
setting when Compute Requirements are terminated: yd-compute-stop,
yd-compute-start, yd-compute-restart, yd-terminate, yd-compute-deprovision,
yd-compute-reprovision and yd-auto-shutdown.

Explicit targets are handled in two passes. Each argument is first resolved,
in the order given, to a Compute Requirement or to an Instance (a Node
standing for the Instance it runs on), recording any that cannot be acted on
as 'failed' or 'skipped'. What remains is then confirmed once and acted on:
one call per Compute Requirement, and one per Compute Requirement for its
Instances, which the SDK takes as a list. The rules for what cannot be acted
on, confirming and stopping on a session failure are action_runner.py's.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeAlias, cast

from yellowdog_client.model import (
    AutoShutdown,
    ComputeRequirement,
    ComputeRequirementStatus,
    ComputeRequirementSummary,
    Instance,
    InstanceStatus,
    NodeStatus,
    ProvisionedWorkerPool,
)

from yellowdog_cli.utils.action_runner import (
    SKIPPED,
    Item,
    Record,
    Unit,
    Unresolved,
    carry_out,
    confirm_items,
    expand_patterns,
    resolve_targets,
)
from yellowdog_cli.utils.capacity_wait import (
    DoneWhen,
    capacity_reached,
    until_quiet,
    until_settled,
    until_settled_again,
    until_stopped,
    wait_for_capacity,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.dryrun_utils import report_dry_run, report_dry_run_items
from yellowdog_cli.utils.entity_names import (
    ET_COMPUTE_REQUIREMENTS,
    ET_INSTANCES,
    ET_NODES,
)
from yellowdog_cli.utils.entity_utils import (
    AmbiguousNameError,
    describe_glob_scope,
    expand_name_globs,
    filter_phrase,
    find_compute_requirement_by_name,
    get_compute_requirement_summaries,
    get_instance_by_id,
    namespace_scope,
)
from yellowdog_cli.utils.exit_codes import ExitCode, NotFoundError
from yellowdog_cli.utils.follow_utils import follow_ids
from yellowdog_cli.utils.glob_utils import contains_glob_chars
from yellowdog_cli.utils.interactive import select
from yellowdog_cli.utils.misc_utils import (
    is_http_not_found,
    link_entity,
    shown_expiry,
)
from yellowdog_cli.utils.printing import counted, plural, print_info
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.ydid_utils import (
    YDIDType,
    get_ydid_type,
    split_instance_specification,
)

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComputeAction:
    name: str  # E.g.: "Stop"
    gerund: str  # E.g.: "Stopping"
    past_tense: str  # E.g.: "Stopped"
    cr_method_name: str | None  # ComputeClient method for CRs (None if N/A)
    instance_method_name: str | None  # ComputeClient method for instances (None if N/A)
    valid_cr_statuses: list[ComputeRequirementStatus]
    valid_instance_statuses: list[InstanceStatus]
    # How a confirmation names the action, where its name alone undersells it
    confirmation_verb: str | None = None
    # When '--follow' is done, the Compute Requirement being left alive (its
    # stream never closes); None to follow it to its end, as a terminate does
    done_when: DoneWhen | None = None
    # When '--follow' is done after acting on Instances, where that differs:
    # a terminate of some of them leaves their Compute Requirement alive
    instances_done_when: DoneWhen | None = None
    # The '--json' record's 'action', where the name is a phrase
    record_name: str | None = None
    # Passed to the Compute Requirement method after the ID
    cr_arguments: tuple[Any, ...] = ()
    # What the Compute Requirement the method returns adds to the line
    # printed for it, and the fields it adds to its record
    reported: Callable[[ComputeRequirement], tuple[str, dict[str, Any]]] | None = None

    @property
    def prompt(self) -> str:
        return self.confirmation_verb or self.name

    @property
    def verb(self) -> str:
        """
        How a message names the action: its '--json' record's 'action'
        ('stop', 'autoshutdown'), the verb the command is typed as.
        """
        return self.record_name or self.name.lower()

    def record(
        self,
        entity: object,
        outcome: str | None = None,
        error: str | None = None,
        entity_type: str = ET_COMPUTE_REQUIREMENTS,
        **extra: Any,
    ) -> None:
        """
        Record the action's outcome for '--json': by default, that it was
        applied ('stopped'); otherwise 'skipped' or 'failed'.
        """
        record_action(
            entity,
            entity_type,
            self.verb,
            outcome or self.past_tense.lower(),
            error,
            **extra,
        )

    def recorder(self) -> Record:
        """
        The action's record, as action_runner calls it.
        """
        return lambda entity, entity_type, outcome, error: self.record(
            entity, outcome, error, entity_type
        )


COMPUTE_STOP = ComputeAction(
    name="Stop",
    gerund="Stopping",
    past_tense="Stopped",
    cr_method_name="stop_compute_requirement_by_id",
    instance_method_name="stop_instances",
    valid_cr_statuses=[ComputeRequirementStatus.RUNNING],
    valid_instance_statuses=[InstanceStatus.RUNNING],
    done_when=until_stopped,
)

COMPUTE_START = ComputeAction(
    name="Start",
    gerund="Starting",
    past_tense="Started",
    cr_method_name="start_compute_requirement_by_id",
    instance_method_name="start_instances",
    valid_cr_statuses=[ComputeRequirementStatus.STOPPED],
    valid_instance_statuses=[InstanceStatus.STOPPED],
    done_when=until_settled,
)

COMPUTE_RESTART = ComputeAction(
    name="Restart",
    gerund="Restarting",
    past_tense="Restarted",
    cr_method_name=None,  # The platform has no CR-level restart
    instance_method_name="restart_instances",
    valid_cr_statuses=[],
    valid_instance_statuses=[InstanceStatus.RUNNING],
    done_when=until_settled_again,
)


COMPUTE_TERMINATE = ComputeAction(
    name="Terminate",
    gerund="Terminating",
    past_tense="Terminated",
    cr_method_name="terminate_compute_requirement_by_id",
    instance_method_name="terminate_instances",
    # Every state but TERMINATING and TERMINATED
    valid_cr_statuses=[
        ComputeRequirementStatus.NEW,
        ComputeRequirementStatus.PROVISIONING,
        ComputeRequirementStatus.STARTING,
        ComputeRequirementStatus.RUNNING,
        ComputeRequirementStatus.STOPPING,
        ComputeRequirementStatus.STOPPED,
    ],
    valid_instance_statuses=[
        InstanceStatus.PENDING,
        InstanceStatus.RUNNING,
        InstanceStatus.STOPPING,
        InstanceStatus.STOPPED,
        InstanceStatus.UNAVAILABLE,
        InstanceStatus.UNKNOWN,
    ],
    confirmation_verb="Immediately terminate",
    instances_done_when=until_quiet,
)

COMPUTE_DEPROVISION = ComputeAction(
    name="Deprovision",
    gerund="Deprovisioning",
    past_tense="Deprovisioned",
    # Instance-level only: deprovisioning terminates the Instances and
    # reduces their Compute Requirement's target count to match, so that
    # they are not replaced
    cr_method_name=None,
    instance_method_name="deprovision_instances",
    valid_cr_statuses=[],
    valid_instance_statuses=COMPUTE_TERMINATE.valid_instance_statuses,
    confirmation_verb="Deprovision (terminate, reducing the target count of)",
    done_when=until_settled,
)

COMPUTE_REPROVISION = ComputeAction(
    name="Reprovision",
    gerund="Reprovisioning",
    past_tense="Reprovisioned",
    # Compute Requirement-level only: reprovisioning provisions Instances
    # until as many are running as the target count asks for
    cr_method_name="reprovision_compute_requirement_by_id",
    instance_method_name=None,
    valid_cr_statuses=[ComputeRequirementStatus.RUNNING],
    valid_instance_statuses=[],
    confirmation_verb="Reprovision (restore to their target instance counts)",
    done_when=until_settled,
)


def compute_auto_shutdown(shutdown: AutoShutdown) -> ComputeAction:
    """
    Setting when Compute Requirements are terminated (yd-auto-shutdown), or
    with the shutdown disabled that they never are: an action built for the
    run, since its confirmation and the call it makes carry the shutdown.
    Each record adds the 'autoShutdownTime' the Platform set, null for none.
    """
    minutes = (
        None
        if not shutdown.enabled or shutdown.timeout is None
        else shutdown.timeout.total_seconds() / 60
    )
    return ComputeAction(
        name="Set the auto shutdown of",
        gerund="Setting the auto shutdown of",
        past_tense="Updated",
        cr_method_name="update_compute_requirement_auto_shutdown",
        instance_method_name=None,
        valid_cr_statuses=COMPUTE_TERMINATE.valid_cr_statuses,
        valid_instance_statuses=[],
        confirmation_verb=(
            "Disable the auto shutdown of"
            if minutes is None
            else f"Terminate, {counted(minutes, 'minute')} from now,"
        ),
        record_name="autoshutdown",
        cr_arguments=(shutdown,),
        reported=_auto_shutdown_reported,
    )


def _auto_shutdown_reported(
    compute_requirement: ComputeRequirement,
) -> tuple[str, dict[str, Any]]:
    # Enabled or not by the shutdown itself, the time added where the
    # Platform gives one, so that a reply without it is not reported as never
    shutdown = compute_requirement.autoShutdown
    when = compute_requirement.autoShutdownTime
    fields = {"autoShutdownTime": None if when is None else when.isoformat()}
    if shutdown is None or not shutdown.enabled:
        return ": it will not be terminated automatically", fields
    if when is not None:
        return f": it will be terminated at {shown_expiry(when)}", fields
    if shutdown.timeout is not None:
        minutes = shutdown.timeout.total_seconds() / 60
        return f": it will be terminated in {counted(minutes, 'minute')}", fields
    return ": it will be terminated automatically", fields


# A Compute Requirement to act on: fetched by its ID, or found by its name
_ComputeRequirementTarget: TypeAlias = ComputeRequirement | ComputeRequirementSummary


def _instance_record(cr_id: str, instance_id: str) -> dict:
    """
    An Instance as the '--json' record names it: by the 'cr_id.instance_id'
    form the commands accept, and by the Instance ID they print.
    """
    return {"id": f"{cr_id}.{instance_id}", "name": instance_id}


@dataclass(frozen=True)
class _Instance:
    """
    An Instance to act on, and the Node ID it was named by, if any.
    """

    cr_id: str
    compute_requirement: ComputeRequirement
    instance: Instance
    instance_id: str
    node_id: str | None

    def label(self) -> str:
        return f"{self.cr_id}.{self.instance_id}" + (
            "" if self.node_id is None else f" (Node {self.node_id})"
        )


def _cr_item(compute_requirement: _ComputeRequirementTarget) -> Item:
    return Item(
        compute_requirement,
        ET_COMPUTE_REQUIREMENTS,
        ("cr", compute_requirement.id),
        compute_requirement,
    )


def _instance_item(instance: _Instance) -> Item:
    return Item(
        _instance_record(instance.cr_id, instance.instance_id),
        ET_INSTANCES,
        ("instance", instance.cr_id, instance.instance_id),
        instance,
    )


def _plan(items: list[Item]) -> list[Item]:
    """
    The order a plan is acted on and recorded in: the Compute Requirements,
    then the Instances grouped by Compute Requirement, each in the order
    first given.
    """
    crs = [item for item in items if item.entity_type == ET_COMPUTE_REQUIREMENTS]
    groups: dict[str, list[Item]] = {}
    for item in items:
        if item.entity_type == ET_INSTANCES:
            groups.setdefault(item.value.cr_id, []).append(item)
    return crs + [item for group in groups.values() for item in group]


def _groups(items: list[Item]) -> list[list[_Instance]]:
    """
    The Instances among the items, grouped by Compute Requirement.
    """
    groups: dict[str, list[_Instance]] = {}
    for item in items:
        if item.entity_type == ET_INSTANCES:
            groups.setdefault(item.value.cr_id, []).append(item.value)
    return list(groups.values())


def apply_compute_action(ctx: RunContext, action: ComputeAction):
    """
    Entry point for the yd-compute-stop/start/restart/deprovision/reprovision
    commands and yd-terminate. The command registry ensures that yd-compute-restart
    and yd-compute-deprovision have explicit targets, and no glob patterns.
    Glob patterns alone are a listing; mixed with names or IDs, each pattern
    is replaced by the IDs it matches, and they are resolved with the rest.
    """
    names_or_ids: list[str] = ctx.args.compute_requirements_instances_or_nodes or []
    globs = [name for name in names_or_ids if contains_glob_chars(name)]

    if names_or_ids and len(globs) < len(names_or_ids):
        _apply_action_by_name_or_id(
            ctx,
            action,
            expand_patterns(
                names_or_ids,
                expand=lambda pattern: [
                    cast(str, summary.id)
                    for summary in _matching(ctx, action, [pattern])
                ],
                describe=_target_entity,
                record=action.recorder(),
                none_match=lambda pattern: (
                    f"No Compute Requirements to {action.name.lower()}"
                    f" match '{pattern}'"
                ),
            ),
        )
        return

    if globs:
        print_info(
            f"{action.gerund} Compute Requirements "
            f"{describe_glob_scope(ctx.client, globs, ctx.config.namespace)}"
        )
        compute_requirement_summaries: list[ComputeRequirementSummary] = _matching(
            ctx, action, globs
        )
    else:
        print_info(
            f"{action.gerund} Compute Requirements "
            f"{namespace_scope(ctx.client, ctx.config.namespace)}"
            + filter_phrase("with tags including '{}'", ctx.config.name_tag)
        )
        compute_requirement_summaries = get_compute_requirement_summaries(
            ctx.client,
            ctx.config.namespace,
            ctx.config.name_tag,
            action.valid_cr_statuses,
        )

    if ctx.args.dry_run:  # yd-terminate's, the only one to take --dry-run
        report_dry_run(
            ctx.client,
            compute_requirement_summaries,
            "Compute Requirement",
            action.past_tense.lower(),
            ET_COMPUTE_REQUIREMENTS,
            action.name.lower(),
            bool(ctx.args.json_output),
        )
        return

    _apply_action_to_summaries(ctx, action, compute_requirement_summaries)


def _matching(
    ctx: RunContext, action: ComputeAction, globs: list[str]
) -> list[ComputeRequirementSummary]:
    """
    The Compute Requirements the action applies to whose names match the glob
    patterns.
    """
    return expand_name_globs(
        globs,
        ctx.config.namespace,
        fetch=lambda namespace, prefix: get_compute_requirement_summaries(
            ctx.client,
            namespace,
            tag=None,
            statuses=action.valid_cr_statuses,
            name=prefix or None,
        ),
    )


def _apply_action_to_summaries(
    ctx: RunContext, action: ComputeAction, summaries: list[ComputeRequirementSummary]
):
    """
    Select (with --interactive), confirm, and apply the action to listed
    Compute Requirements.
    """
    selected: list[ComputeRequirementSummary] = select(ctx.client, summaries)
    items = [_cr_item(summary) for summary in selected]

    if items and not confirm_items(
        f"{action.prompt} {counted(len(items), 'Compute Requirement')}?",
        items,
        action.recorder(),
    ):
        items = []

    done = carry_out([_cr_unit(ctx, action, item) for item in items], action.recorder())
    actioned_ids = [cast(str, unit.items[0].value.id) for unit in done]

    if actioned_ids:
        print_info(
            f"{action.past_tense} {counted(len(actioned_ids), 'Compute Requirement')}"
        )
        _after(ctx, action, actioned_ids)
    else:
        print_info(f"No Compute Requirements {action.past_tense.lower()}")


def _cr_unit(ctx: RunContext, action: ComputeAction, item: Item) -> Unit:
    """
    The action on one Compute Requirement, as carry_out() takes it.
    """
    compute_requirement: _ComputeRequirementTarget = item.value
    return Unit(
        [item],
        act=lambda: _act_on_compute_requirement(ctx, action, compute_requirement),
        failure=lambda e: (
            f"Failed to {action.name.lower()} Compute Requirement"
            f" '{compute_requirement.name}': {e}"
        ),
    )


def _act_on_compute_requirement(
    ctx: RunContext,
    action: ComputeAction,
    compute_requirement: _ComputeRequirementTarget,
):
    """
    Apply the action to a Compute Requirement, recording and reporting it.
    Raises on failure, for the caller to record.
    """
    result = getattr(ctx.client.compute_client, cast(str, action.cr_method_name))(
        compute_requirement.id, *action.cr_arguments
    )
    added, fields = (
        action.reported(result)
        if action.reported is not None and isinstance(result, ComputeRequirement)
        else ("", {})
    )
    action.record(compute_requirement, **fields)
    if isinstance(result, ComputeRequirement):
        print_info(f"{action.past_tense} {link_entity(ctx.config.url, result)}{added}")
    else:
        print_info(f"{action.past_tense} '{compute_requirement.name}'{added}")


def _target_entity(target: str) -> tuple[object, str]:
    """
    A target as its '--json' record names it, before it has been resolved.
    """
    if (spec := split_instance_specification(target)) is not None:
        return _instance_record(spec[0], spec[1]), ET_INSTANCES
    if get_ydid_type(target) == YDIDType.NODE:
        return target, ET_NODES
    return target, ET_COMPUTE_REQUIREMENTS


def _apply_action_by_name_or_id(
    ctx: RunContext, action: ComputeAction, names_or_ids: list[str]
):
    """
    Apply the action to Compute Requirements by their names or IDs, to
    nodes' instances by node ID, or to instances by 'cr_id.instance_id'.
    """
    # The Compute Requirements of the Instances named, each fetched once
    fetched: dict[str, ComputeRequirement] = {}
    items = resolve_targets(
        names_or_ids,
        resolve=lambda target: _resolve_target(ctx, action, target, fetched),
        describe=_target_entity,
        record=action.recorder(),
        verb=action.name.lower(),
        order=_plan,
    )

    if not items:
        print_info(f"No Compute Requirements {action.past_tense.lower()}")
        return

    if ctx.args.dry_run:  # yd-terminate's, the only one to take --dry-run
        verb = action.name.lower()
        report_dry_run_items(
            items,
            verb,
            lambda item, status: record_action(
                item.entity, item.entity_type, verb, f"would {verb}", status=status
            ),
        )
        return

    if not confirm_items(_confirmation(action, items), items, action.recorder()):
        print_info(f"No Compute Requirements {action.past_tense.lower()}")
        return

    _carry_out(ctx, action, items)


def _confirmation(action: ComputeAction, items: list[Item]) -> str:
    crs = [item.value for item in items if item.entity_type == ET_COMPUTE_REQUIREMENTS]
    instances = [instance for group in _groups(items) for instance in group]
    parts = []
    if crs:
        parts.append(
            f"{counted(len(crs), 'Compute Requirement')} ("
            + ", ".join(f"'{cr.name}'" if cr.name else cast(str, cr.id) for cr in crs)
            + ")"
        )
    if instances:
        parts.append(
            f"{counted(len(instances), 'Instance')} ("
            + ", ".join(instance.label() for instance in instances)
            + ")"
        )
    return f"{action.prompt} {' and '.join(parts)}?"


def _carry_out(ctx: RunContext, action: ComputeAction, items: list[Item]):
    """
    Act on a confirmed plan: each Compute Requirement, then each Compute
    Requirement's Instances in one call.
    """
    units = [
        _cr_unit(ctx, action, item)
        for item in items
        if item.entity_type == ET_COMPUTE_REQUIREMENTS
    ] + [
        Unit(
            [_instance_item(instance) for instance in group],
            act=lambda group=group: _act_on_instances(ctx, action, group),
            failure=lambda e, group=group: _instances_failure(action, group, e),
        )
        for group in _groups(items)
    ]

    actioned_ids: list[str] = []
    acted_on_instances = False
    for unit in carry_out(units, action.recorder()):
        value = unit.items[0].value
        acted_on_instances = acted_on_instances or isinstance(value, _Instance)
        cr_id = value.cr_id if isinstance(value, _Instance) else cast(str, value.id)
        if cr_id not in actioned_ids:
            actioned_ids.append(cr_id)

    if actioned_ids:
        _after(
            ctx,
            action,
            actioned_ids,
            action.instances_done_when if acted_on_instances else None,
        )


def _after(
    ctx: RunContext,
    action: ComputeAction,
    actioned_ids: list[str],
    done_when: DoneWhen | None = None,
):
    """
    Follow (--follow) or wait for (--wait, yd-compute-reprovision's) the
    Compute Requirements acted on, '--follow' ending by 'done_when' (by
    default the action's own); the registry refuses the two together.
    """
    done_when = action.done_when if done_when is None else done_when
    if ctx.args.follow:
        follow_ids(
            ctx,
            actioned_ids,
            settled=None if done_when is None else capacity_reached(ctx, done_when),
        )
    elif ctx.args.wait:
        wait_for_capacity(ctx, actioned_ids, ctx.args.timeout)


def _instances_failure(action: ComputeAction, group: list[_Instance], e: Exception):
    labels = ", ".join(instance.label() for instance in group)
    if "InvalidComputeRequirementStatusException" in str(e):
        return (
            f"Unable to {action.name.lower()} {plural('Instance', len(group))} {labels}: Compute"
            f" Requirement {group[0].cr_id} is in invalid status"
            f" '{group[0].compute_requirement.status}'"
        )
    return f"Failed to {action.name.lower()} {plural('Instance', len(group))} {labels}: {e}"


def _act_on_instances(ctx: RunContext, action: ComputeAction, group: list[_Instance]):
    """
    Apply the action to a Compute Requirement's Instances in one call,
    recording and reporting each. Raises on failure, for the caller to record.
    """
    getattr(ctx.client.compute_client, cast(str, action.instance_method_name))(
        group[0].compute_requirement, [instance.instance for instance in group]
    )
    for instance in group:
        print_info(f"{action.past_tense} Instance {instance.label()}")
        action.record(
            _instance_record(instance.cr_id, instance.instance_id),
            entity_type=ET_INSTANCES,
        )


def _resolve_target(
    ctx: RunContext,
    action: ComputeAction,
    target: str,
    fetched: dict[str, ComputeRequirement],
) -> Item:
    """
    What a target names, raising Unresolved if it cannot be acted on.
    Anything else raised is a failure of the lookup itself. 'fetched' holds
    the Compute Requirements an Instance's resolution has fetched, by ID.
    """
    ydid_type = get_ydid_type(target)
    spec = split_instance_specification(target)
    if action.instance_method_name is None and (
        spec is not None or ydid_type == YDIDType.NODE
    ):
        raise Unresolved(
            f"'{action.verb}' does not apply to Instances; "
            "please supply Compute Requirement names or IDs"
        )

    if spec is not None:
        compute_requirement, instance = _resolve_instance(
            ctx, action, spec[0], spec[1], fetched
        )
        return _instance_item(
            _Instance(spec[0], compute_requirement, instance, spec[1], None)
        )

    if ydid_type == YDIDType.NODE:
        cr_id, compute_requirement, instance, instance_id = _resolve_node(
            ctx, action, target, fetched
        )
        return _instance_item(
            _Instance(cr_id, compute_requirement, instance, instance_id, target)
        )

    if action.cr_method_name is None:
        raise Unresolved(
            f"'{action.verb}' does not apply to Compute Requirements; "
            "please supply Instance or Node IDs"
        )
    compute_requirement: _ComputeRequirementTarget = (
        _get_compute_requirement(ctx, target)
        if ydid_type == YDIDType.COMPUTE_REQUIREMENT
        else _resolve_compute_requirement_name(ctx, action, target)
    )
    if compute_requirement.status not in action.valid_cr_statuses:
        raise Unresolved(
            f"Compute Requirement '{target}' is {compute_requirement.status},"
            f" not a valid state for '{action.verb}'",
            SKIPPED,
            compute_requirement,
        )
    return _cr_item(compute_requirement)


def _get_compute_requirement(ctx: RunContext, cr_id: str) -> ComputeRequirement:
    try:
        return ctx.client.compute_client.get_compute_requirement_by_id(cr_id)
    except Exception as e:
        if is_http_not_found(e):
            raise Unresolved(f"Cannot find Compute Requirement {cr_id}") from e
        raise


def _resolve_compute_requirement_name(
    ctx: RunContext, action: ComputeAction, name_or_namespaced_name: str
) -> ComputeRequirementSummary:
    """
    The Compute Requirement with a name, preferring one in a state the action
    applies to (entity_utils.find_compute_requirement_by_name()).
    """
    try:
        summary = find_compute_requirement_by_name(
            ctx.client,
            name_or_namespaced_name,
            ctx.config.namespace,
            action.valid_cr_statuses,
        )
    except (NotFoundError, AmbiguousNameError) as e:
        raise Unresolved(str(e)) from e
    _LOG.debug("Found Compute Requirement ID: %s", summary.id)
    return summary


def _resolve_instance(
    ctx: RunContext,
    action: ComputeAction,
    cr_id: str,
    instance_id: str,
    fetched: dict[str, ComputeRequirement],
) -> tuple[ComputeRequirement, Instance]:
    if (compute_requirement := fetched.get(cr_id)) is None:
        compute_requirement = fetched[cr_id] = _get_compute_requirement(ctx, cr_id)
    instance: Instance | None = get_instance_by_id(ctx.client, cr_id, instance_id)
    if instance is None:
        raise Unresolved(
            f"Cannot find Instance ID '{instance_id}' in Compute Requirement {cr_id}",
            code=ExitCode.NOT_FOUND,
        )
    if instance.status not in action.valid_instance_statuses:
        raise Unresolved(
            f"Instance '{cr_id}.{instance_id}' is {instance.status},"
            f" not a valid state for '{action.verb}'",
            SKIPPED,
        )
    return compute_requirement, instance


def _resolve_node(
    ctx: RunContext,
    action: ComputeAction,
    node_id: str,
    fetched: dict[str, ComputeRequirement],
) -> tuple[str, ComputeRequirement, Instance, str]:
    """
    The Compute Requirement (its ID, and itself), Instance and Instance ID a
    Node runs on.
    """
    try:
        node = ctx.client.worker_pool_client.get_node_by_id(node_id)
    except Exception as e:
        if is_http_not_found(e):
            raise Unresolved(f"Cannot find Node {node_id}") from e
        raise
    if node.status == NodeStatus.TERMINATED:
        raise Unresolved(f"Node {node_id} is already TERMINATED", SKIPPED)

    try:
        worker_pool = ctx.client.worker_pool_client.get_worker_pool_by_id(
            cast(str, node.workerPoolId)
        )
    except Exception as e:
        if is_http_not_found(e):
            raise Unresolved(f"Cannot find the Worker Pool of Node {node_id}") from e
        raise
    if not isinstance(worker_pool, ProvisionedWorkerPool):
        raise Unresolved(
            f"Node {node_id} is in a Configured Worker Pool, whose Instances"
            " YellowDog does not manage"
        )
    if not worker_pool.computeRequirementId:
        raise Unresolved(f"Node {node_id}'s Worker Pool has no Compute Requirement")
    if node.details is None or not node.details.instanceId:
        raise Unresolved(f"Node {node_id} has not yet reported its Instance")

    cr_id = worker_pool.computeRequirementId
    instance_id = node.details.instanceId
    compute_requirement, instance = _resolve_instance(
        ctx, action, cr_id, instance_id, fetched
    )
    return cr_id, compute_requirement, instance, instance_id
