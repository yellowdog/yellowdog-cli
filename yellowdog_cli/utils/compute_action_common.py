#!/usr/bin/env python3

"""
Core functionality for stopping, starting, restarting, terminating and
deprovisioning Compute Requirements and Instances: yd-compute-stop,
yd-compute-start, yd-compute-restart, yd-terminate and yd-compute-deprovision.

Explicit targets are handled in two passes. Each argument is first resolved,
in the order given, to a Compute Requirement or to an Instance (a Node
standing for the Instance it runs on), recording any that cannot be acted on
as 'failed' or 'skipped'. What remains is then confirmed once and acted on:
one call per Compute Requirement, and one per Compute Requirement for its
Instances, which the SDK takes as a list. The rules for what cannot be acted
on, confirming and stopping on a session failure are action_runner.py's.
"""

from dataclasses import dataclass
from typing import TypeAlias, cast

from yellowdog_client.model import (
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
    resolve_targets,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.dryrun_utils import report_dry_run
from yellowdog_cli.utils.entity_names import (
    ET_COMPUTE_REQUIREMENTS,
    ET_INSTANCES,
    ET_NODES,
)
from yellowdog_cli.utils.entity_utils import (
    AmbiguousNameError,
    describe_glob_scope,
    expand_name_globs,
    find_compute_requirement_by_name,
    get_compute_requirement_summaries,
    get_instance_by_id,
)
from yellowdog_cli.utils.exit_codes import NotFoundError
from yellowdog_cli.utils.follow_utils import follow_ids
from yellowdog_cli.utils.glob_utils import contains_glob_chars
from yellowdog_cli.utils.interactive import select
from yellowdog_cli.utils.misc_utils import is_http_not_found, link_entity
from yellowdog_cli.utils.printing import print_info
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.ydid_utils import (
    YDIDType,
    get_ydid_type,
    split_instance_specification,
)


@dataclass(frozen=True)
class ComputeAction:
    name: str  # E.g.: "Stop"
    gerund: str  # E.g.: "Stopping"
    past_tense: str  # E.g.: "Stopped"
    cr_method_name: str | None  # ComputeClient method for CRs (None if N/A)
    instance_method_name: str  # ComputeClient method for instances
    valid_cr_statuses: list[ComputeRequirementStatus]
    valid_instance_statuses: list[InstanceStatus]
    # How a confirmation names the action, where its name alone undersells it
    confirmation_verb: str | None = None

    @property
    def prompt(self) -> str:
        return self.confirmation_verb or self.name

    def record(
        self,
        entity: object,
        outcome: str | None = None,
        error: str | None = None,
        entity_type: str = ET_COMPUTE_REQUIREMENTS,
    ) -> None:
        """
        Record the action's outcome for '--json': by default, that it was
        applied ('stopped'); otherwise 'skipped' or 'failed'.
        """
        record_action(
            entity,
            entity_type,
            self.name.lower(),
            outcome or self.past_tense.lower(),
            error,
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
)

COMPUTE_START = ComputeAction(
    name="Start",
    gerund="Starting",
    past_tense="Started",
    cr_method_name="start_compute_requirement_by_id",
    instance_method_name="start_instances",
    valid_cr_statuses=[ComputeRequirementStatus.STOPPED],
    valid_instance_statuses=[InstanceStatus.STOPPED],
)

COMPUTE_RESTART = ComputeAction(
    name="Restart",
    gerund="Restarting",
    past_tense="Restarted",
    cr_method_name=None,  # The platform has no CR-level restart
    instance_method_name="restart_instances",
    valid_cr_statuses=[],
    valid_instance_statuses=[InstanceStatus.RUNNING],
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
)


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
    Entry point for the yd-compute-stop/start/restart/deprovision commands
    and yd-terminate. The command registry ensures that yd-compute-restart
    and yd-compute-deprovision have explicit targets, and that glob patterns
    are not mixed with explicit names or IDs.
    """
    names_or_ids: list[str] = ctx.args.compute_requirements_instances_or_nodes or []
    globs = [name for name in names_or_ids if contains_glob_chars(name)]

    if names_or_ids and not globs:
        _apply_action_by_name_or_id(ctx, action, names_or_ids)
        return

    if globs:
        print_info(
            f"{action.gerund} Compute Requirements "
            f"{describe_glob_scope(globs, ctx.config.namespace)}"
        )
        compute_requirement_summaries: list[ComputeRequirementSummary] = (
            expand_name_globs(
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
        )
    else:
        print_info(
            f"{action.gerund} Compute Requirements in "
            f"namespace '{ctx.config.namespace}' with tags "
            f"including '{ctx.config.name_tag}'"
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
        f"{action.prompt} {len(items)} Compute Requirement(s)?",
        items,
        action.recorder(),
    ):
        items = []

    done = carry_out(
        [
            Unit(
                [item],
                act=lambda cr=item.value: _act_on_compute_requirement(ctx, action, cr),
                failure=lambda e, cr=item.value: (
                    f"Failed to {action.name.lower()} '{cr.name}': {e}"
                ),
            )
            for item in items
        ],
        action.recorder(),
    )
    actioned_ids = [cast(str, unit.items[0].value.id) for unit in done]

    if actioned_ids:
        print_info(f"{action.past_tense} {len(actioned_ids)} Compute Requirement(s)")
        if ctx.args.follow:
            follow_ids(ctx, actioned_ids)
    else:
        print_info(f"No Compute Requirements {action.past_tense.lower()}")


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
        compute_requirement.id
    )
    action.record(compute_requirement)
    if isinstance(result, ComputeRequirement):
        print_info(f"{action.past_tense} {link_entity(ctx.config.url, result)}")
    else:
        print_info(f"{action.past_tense} '{compute_requirement.name}'")


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
    items = resolve_targets(
        names_or_ids,
        resolve=lambda target: _resolve_target(ctx, action, target),
        describe=_target_entity,
        record=action.recorder(),
        verb=action.name.lower(),
        order=_plan,
    )

    if not items:
        print_info(f"No Compute Requirements {action.past_tense.lower()}")
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
            f"{len(crs)} Compute Requirement(s) ("
            + ", ".join(f"'{cr.name}'" if cr.name else cast(str, cr.id) for cr in crs)
            + ")"
        )
    if instances:
        parts.append(
            f"{len(instances)} Instance(s) ("
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
        Unit(
            [item],
            act=lambda cr=item.value: _act_on_compute_requirement(ctx, action, cr),
            failure=lambda e, cr=item.value: (
                f"Failed to {action.name.lower()} Compute Requirement '{cr.name}': {e}"
            ),
        )
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
    for unit in carry_out(units, action.recorder()):
        value = unit.items[0].value
        cr_id = value.cr_id if isinstance(value, _Instance) else cast(str, value.id)
        if cr_id not in actioned_ids:
            actioned_ids.append(cr_id)

    if actioned_ids and ctx.args.follow:
        follow_ids(ctx, actioned_ids)


def _instances_failure(action: ComputeAction, group: list[_Instance], e: Exception):
    labels = ", ".join(instance.label() for instance in group)
    if "InvalidComputeRequirementStatusException" in str(e):
        return (
            f"Unable to {action.name.lower()} Instance(s) {labels}: Compute"
            f" Requirement {group[0].cr_id} is in invalid status"
            f" '{group[0].compute_requirement.status}'"
        )
    return f"Failed to {action.name.lower()} Instance(s) {labels}: {e}"


def _act_on_instances(ctx: RunContext, action: ComputeAction, group: list[_Instance]):
    """
    Apply the action to a Compute Requirement's Instances in one call,
    recording and reporting each. Raises on failure, for the caller to record.
    """
    getattr(ctx.client.compute_client, action.instance_method_name)(
        group[0].compute_requirement, [instance.instance for instance in group]
    )
    for instance in group:
        print_info(f"{action.past_tense} Instance {instance.label()}")
        action.record(
            _instance_record(instance.cr_id, instance.instance_id),
            entity_type=ET_INSTANCES,
        )


def _resolve_target(ctx: RunContext, action: ComputeAction, target: str) -> Item:
    """
    What a target names, raising Unresolved if it cannot be acted on.
    Anything else raised is a failure of the lookup itself.
    """
    if (spec := split_instance_specification(target)) is not None:
        compute_requirement, instance = _resolve_instance(ctx, action, spec[0], spec[1])
        return _instance_item(
            _Instance(spec[0], compute_requirement, instance, spec[1], None)
        )

    if (ydid_type := get_ydid_type(target)) == YDIDType.NODE:
        cr_id, compute_requirement, instance, instance_id = _resolve_node(
            ctx, action, target
        )
        return _instance_item(
            _Instance(cr_id, compute_requirement, instance, instance_id, target)
        )

    if action.cr_method_name is None:
        raise Unresolved(
            f"Compute Requirements cannot be {action.past_tense.lower()}; "
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
            f" not a valid state for action '{action.name}'",
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
    print_info(f"Found Compute Requirement ID: {summary.id}")
    return summary


def _resolve_instance(
    ctx: RunContext, action: ComputeAction, cr_id: str, instance_id: str
) -> tuple[ComputeRequirement, Instance]:
    compute_requirement = _get_compute_requirement(ctx, cr_id)
    instance: Instance | None = get_instance_by_id(ctx.client, cr_id, instance_id)
    if instance is None:
        raise Unresolved(
            f"Cannot find Instance ID '{instance_id}' in Compute Requirement {cr_id}"
        )
    if instance.status not in action.valid_instance_statuses:
        raise Unresolved(
            f"Instance '{cr_id}.{instance_id}' is {instance.status},"
            f" not a valid state for action '{action.name}'",
            SKIPPED,
        )
    return compute_requirement, instance


def _resolve_node(
    ctx: RunContext, action: ComputeAction, node_id: str
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
    compute_requirement, instance = _resolve_instance(ctx, action, cr_id, instance_id)
    return cr_id, compute_requirement, instance, instance_id
