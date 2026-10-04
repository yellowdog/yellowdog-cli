#!/usr/bin/env python3

"""
Core functionality for stopping, starting, restarting and terminating
Compute Requirements and Instances: yd-compute-stop, yd-compute-start,
yd-compute-restart and yd-terminate.

Explicit targets are handled in two passes. Each argument is first resolved,
in the order given, to a Compute Requirement or to an Instance (a Node
standing for the Instance it runs on), recording any that cannot be acted on
as 'failed' or 'skipped'. What remains is then confirmed once and acted on:
one call per Compute Requirement, and one per Compute Requirement for its
Instances, which the SDK takes as a list. A failure every later call would
repeat (exit_codes.SESSION_FAILURES: authentication, connection) stops the
run, and the targets not yet attempted are recorded as skipped.
"""

from dataclasses import dataclass, field
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

from yellowdog_cli.utils.dryrun_utils import report_dry_run
from yellowdog_cli.utils.entity_utils import (
    AmbiguousNameError,
    describe_glob_scope,
    expand_name_globs,
    find_compute_requirement_by_name,
    get_compute_requirement_summaries,
    get_instance_by_id,
)
from yellowdog_cli.utils.exit_codes import (
    SESSION_FAILURES,
    NotFoundError,
    ReportedFailure,
    classify,
)
from yellowdog_cli.utils.follow_utils import follow_ids
from yellowdog_cli.utils.glob_utils import contains_glob_chars
from yellowdog_cli.utils.interactive import confirmed, select
from yellowdog_cli.utils.misc_utils import is_http_not_found, link_entity
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.settings import (
    ET_COMPUTE_REQUIREMENTS,
    ET_INSTANCES,
    ET_NODES,
)
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON
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


# A Compute Requirement to act on: fetched by its ID, or found by its name
_ComputeRequirementTarget: TypeAlias = ComputeRequirement | ComputeRequirementSummary


def _instance_record(cr_id: str, instance_id: str) -> dict:
    """
    An Instance as the '--json' record names it: by the 'cr_id.instance_id'
    form the commands accept, and by the Instance ID they print.
    """
    return {"id": f"{cr_id}.{instance_id}", "name": instance_id}


@dataclass
class _InstanceGroup:
    """
    The Instances to act on in one Compute Requirement, in the order given,
    with the Node ID each was named by, if any.
    """

    cr_id: str
    compute_requirement: ComputeRequirement
    instances: list[Instance] = field(default_factory=list)
    instance_ids: list[str] = field(default_factory=list)
    node_ids: list[str | None] = field(default_factory=list)

    def records(self) -> list[dict]:
        return [
            _instance_record(self.cr_id, instance_id)
            for instance_id in self.instance_ids
        ]

    def labels(self) -> list[str]:
        return [
            f"{record['id']}" + ("" if node_id is None else f" (Node {node_id})")
            for record, node_id in zip(self.records(), self.node_ids)
        ]


@dataclass
class _Plan:
    """
    What the resolved targets come to: Compute Requirements, and Instances
    grouped by Compute Requirement, each in the order first given.
    """

    compute_requirements: list[_ComputeRequirementTarget] = field(default_factory=list)
    instance_groups: dict[str, _InstanceGroup] = field(default_factory=dict)

    def add_compute_requirement(self, compute_requirement: _ComputeRequirementTarget):
        if all(cr.id != compute_requirement.id for cr in self.compute_requirements):
            self.compute_requirements.append(compute_requirement)

    def add_instance(
        self,
        cr_id: str,
        compute_requirement: ComputeRequirement,
        instance: Instance,
        instance_id: str,
        node_id: str | None,
    ):
        group = self.instance_groups.setdefault(
            cr_id, _InstanceGroup(cr_id, compute_requirement)
        )
        # An Instance named twice, by its ID and by its Node's, is one target
        if instance_id not in group.instance_ids:
            group.instances.append(instance)
            group.instance_ids.append(instance_id)
            group.node_ids.append(node_id)

    def is_empty(self) -> bool:
        return not self.compute_requirements and not self.instance_groups

    def instance_count(self) -> int:
        return sum(len(group.instances) for group in self.instance_groups.values())

    def record_all(self, action: ComputeAction, outcome: str, error: str | None):
        for compute_requirement in self.compute_requirements:
            action.record(compute_requirement, outcome, error)
        for group in self.instance_groups.values():
            for record in group.records():
                action.record(record, outcome, error, ET_INSTANCES)


def apply_compute_action(action: ComputeAction):
    """
    Entry point for the yd-compute-stop/start/restart commands. The command
    registry ensures that yd-compute-restart has explicit targets, and that
    glob patterns are not mixed with explicit names or IDs.
    """
    names_or_ids: list[str] = ARGS_PARSER.compute_requirements_instances_or_nodes or []
    globs = [name for name in names_or_ids if contains_glob_chars(name)]

    if names_or_ids and not globs:
        _apply_action_by_name_or_id(action, names_or_ids)
        return

    if globs:
        print_info(
            f"{action.gerund} Compute Requirements "
            f"{describe_glob_scope(globs, CONFIG_COMMON.namespace)}"
        )
        compute_requirement_summaries: list[ComputeRequirementSummary] = (
            expand_name_globs(
                globs,
                CONFIG_COMMON.namespace,
                fetch=lambda namespace, prefix: get_compute_requirement_summaries(
                    CLIENT,
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
            f"namespace '{CONFIG_COMMON.namespace}' with tags "
            f"including '{CONFIG_COMMON.name_tag}'"
        )
        compute_requirement_summaries = get_compute_requirement_summaries(
            CLIENT,
            CONFIG_COMMON.namespace,
            CONFIG_COMMON.name_tag,
            action.valid_cr_statuses,
        )

    if ARGS_PARSER.dry_run:  # yd-terminate's, the only one to take --dry-run
        report_dry_run(
            CLIENT,
            compute_requirement_summaries,
            "Compute Requirement",
            action.past_tense.lower(),
            ET_COMPUTE_REQUIREMENTS,
            action.name.lower(),
            bool(ARGS_PARSER.json_output),
        )
        return

    _apply_action_to_summaries(action, compute_requirement_summaries)


def _apply_action_to_summaries(
    action: ComputeAction, summaries: list[ComputeRequirementSummary]
):
    """
    Select (with --interactive), confirm, and apply the action to listed
    Compute Requirements.
    """
    selected: list[ComputeRequirementSummary] = select(CLIENT, summaries)

    if selected and not confirmed(
        f"{action.prompt} {len(selected)} Compute Requirement(s)?"
    ):
        for compute_requirement_summary in selected:
            action.record(compute_requirement_summary, "skipped")
        selected = []

    actioned_ids: list[str] = []
    for index, compute_requirement_summary in enumerate(selected):
        try:
            _act_on_compute_requirement(action, compute_requirement_summary)
        except Exception as e:
            print_error(
                f"Failed to {action.name.lower()} "
                f"'{compute_requirement_summary.name}': {e}"
            )
            action.record(compute_requirement_summary, "failed", str(e))
            if classify(e) in SESSION_FAILURES:
                not_attempted = selected[index + 1 :]
                _warn_not_attempted(len(not_attempted))
                for remaining in not_attempted:
                    action.record(remaining, "skipped", f"not attempted: {e}")
                raise ReportedFailure(e)
            continue  # Don't follow Compute Requirements that weren't actioned
        actioned_ids.append(cast(str, compute_requirement_summary.id))

    if actioned_ids:
        print_info(f"{action.past_tense} {len(actioned_ids)} Compute Requirement(s)")
        if ARGS_PARSER.follow:
            follow_ids(actioned_ids)
    else:
        print_info(f"No Compute Requirements {action.past_tense.lower()}")


def _act_on_compute_requirement(
    action: ComputeAction, compute_requirement: _ComputeRequirementTarget
):
    """
    Apply the action to a Compute Requirement, recording and reporting it.
    Raises on failure, for the caller to record.
    """
    result = getattr(CLIENT.compute_client, cast(str, action.cr_method_name))(
        compute_requirement.id
    )
    action.record(compute_requirement)
    if isinstance(result, ComputeRequirement):
        print_info(f"{action.past_tense} {link_entity(CONFIG_COMMON.url, result)}")
    else:
        print_info(f"{action.past_tense} '{compute_requirement.name}'")


def _warn_not_attempted(count: int):
    if count:
        print_warning(
            f"Not attempting the remaining {count} item(s),"
            " which would fail in the same way"
        )


class _Unresolved(Exception):
    """
    A target that cannot be acted on, for a reason the user should see: the
    message is printed and recorded. 'outcome' is 'failed' unless the target
    exists but is not in a state the action applies to ('skipped'), in
    which case 'entity' is what was found, to be recorded by its ID and name.
    """

    def __init__(
        self, message: str, outcome: str = "failed", entity: object | None = None
    ):
        super().__init__(message)
        self.outcome = outcome
        self.entity = entity  # what to record, when better than the target


def _target_entity(target: str) -> tuple[object, str]:
    """
    A target as its '--json' record names it, before it has been resolved.
    """
    if (spec := split_instance_specification(target)) is not None:
        return _instance_record(spec[0], spec[1]), ET_INSTANCES
    if get_ydid_type(target) == YDIDType.NODE:
        return target, ET_NODES
    return target, ET_COMPUTE_REQUIREMENTS


def _apply_action_by_name_or_id(action: ComputeAction, names_or_ids: list[str]):
    """
    Apply the action to Compute Requirements by their names or IDs, to
    nodes' instances by node ID, or to instances by 'cr_id.instance_id'.
    """
    targets = list(dict.fromkeys(names_or_ids))  # In order, without duplicates
    plan = _Plan()

    for index, target in enumerate(targets):
        entity, entity_type = _target_entity(target)
        try:
            _resolve_target(action, target, plan)
        except _Unresolved as e:
            if e.outcome == "skipped":
                print_warning(str(e))
            else:
                print_error(str(e))
            action.record(e.entity or entity, e.outcome, str(e), entity_type)
        except Exception as e:
            print_error(f"Unable to {action.name.lower()} '{target}': {e}")
            action.record(entity, "failed", str(e), entity_type)
            if classify(e) in SESSION_FAILURES:
                not_attempted = targets[index + 1 :]
                _warn_not_attempted(
                    len(not_attempted)
                    + len(plan.compute_requirements)
                    + plan.instance_count()
                )
                plan.record_all(action, "skipped", f"not attempted: {e}")
                for remaining in not_attempted:
                    remaining_entity, remaining_type = _target_entity(remaining)
                    action.record(
                        remaining_entity,
                        "skipped",
                        f"not attempted: {e}",
                        remaining_type,
                    )
                raise ReportedFailure(e)

    if plan.is_empty():
        print_info(f"No Compute Requirements {action.past_tense.lower()}")
        return

    if not confirmed(_confirmation(action, plan)):
        plan.record_all(action, "skipped", None)
        print_info(f"No Compute Requirements {action.past_tense.lower()}")
        return

    _carry_out(action, plan)


def _confirmation(action: ComputeAction, plan: _Plan) -> str:
    parts = []
    if plan.compute_requirements:
        parts.append(
            f"{len(plan.compute_requirements)} Compute Requirement(s) ("
            + ", ".join(
                f"'{cr.name}'" if cr.name else cast(str, cr.id)
                for cr in plan.compute_requirements
            )
            + ")"
        )
    if plan.instance_groups:
        parts.append(
            f"{plan.instance_count()} Instance(s) ("
            + ", ".join(
                label
                for group in plan.instance_groups.values()
                for label in group.labels()
            )
            + ")"
        )
    return f"{action.prompt} {' and '.join(parts)}?"


def _carry_out(action: ComputeAction, plan: _Plan):
    """
    Act on a confirmed plan: each Compute Requirement, then each Compute
    Requirement's Instances in one call. A session failure records everything
    not yet attempted as skipped and stops.
    """
    # Each unit is (records if it fails, the entity type, the work)
    units: list[tuple[list[object], str, object]] = []
    for cr in plan.compute_requirements:
        units.append(([cr], ET_COMPUTE_REQUIREMENTS, cr))
    for group in plan.instance_groups.values():
        units.append((list(group.records()), ET_INSTANCES, group))

    actioned_ids: list[str] = []
    for index, (entities, entity_type, work) in enumerate(units):
        try:
            if isinstance(work, _InstanceGroup):
                _act_on_instances(action, work)
                cr_id = work.cr_id
            else:
                compute_requirement = cast(_ComputeRequirementTarget, work)
                _act_on_compute_requirement(action, compute_requirement)
                cr_id = cast(str, compute_requirement.id)
        except Exception as e:
            _report_failure(action, work, e)
            for entity in entities:
                action.record(entity, "failed", str(e), entity_type)
            if classify(e) in SESSION_FAILURES:
                not_attempted = units[index + 1 :]
                _warn_not_attempted(sum(len(u[0]) for u in not_attempted))
                for remaining, remaining_type, _ in not_attempted:
                    for entity in remaining:
                        action.record(
                            entity, "skipped", f"not attempted: {e}", remaining_type
                        )
                raise ReportedFailure(e)
            continue
        if cr_id not in actioned_ids:
            actioned_ids.append(cr_id)

    if actioned_ids and ARGS_PARSER.follow:
        follow_ids(actioned_ids)


def _report_failure(action: ComputeAction, work: object, e: Exception):
    if not isinstance(work, _InstanceGroup):
        print_error(
            f"Failed to {action.name.lower()} Compute Requirement "
            f"'{cast(_ComputeRequirementTarget, work).name}': {e}"
        )
    elif "InvalidComputeRequirementStatusException" in str(e):
        print_error(
            f"Unable to {action.name.lower()} Instance(s) "
            f"{', '.join(work.labels())}: Compute Requirement {work.cr_id} is in"
            f" invalid status '{work.compute_requirement.status}'"
        )
    else:
        print_error(
            f"Failed to {action.name.lower()} Instance(s) "
            f"{', '.join(work.labels())}: {e}"
        )


def _act_on_instances(action: ComputeAction, group: _InstanceGroup):
    """
    Apply the action to a Compute Requirement's Instances in one call,
    recording and reporting each. Raises on failure, for the caller to record.
    """
    getattr(CLIENT.compute_client, action.instance_method_name)(
        group.compute_requirement, group.instances
    )
    for record, label in zip(group.records(), group.labels()):
        print_info(f"{action.past_tense} Instance {label}")
        action.record(record, entity_type=ET_INSTANCES)


def _resolve_target(action: ComputeAction, target: str, plan: _Plan):
    """
    Add what a target names to the plan, raising _Unresolved if it cannot be
    acted on. Anything else raised is a failure of the lookup itself.
    """
    if (spec := split_instance_specification(target)) is not None:
        compute_requirement, instance = _resolve_instance(action, spec[0], spec[1])
        plan.add_instance(spec[0], compute_requirement, instance, spec[1], None)

    elif (ydid_type := get_ydid_type(target)) == YDIDType.NODE:
        cr_id, compute_requirement, instance, instance_id = _resolve_node(
            action, target
        )
        plan.add_instance(cr_id, compute_requirement, instance, instance_id, target)

    else:
        if action.cr_method_name is None:
            raise _Unresolved(
                f"Compute Requirements cannot be {action.past_tense.lower()}; "
                "please supply Instance or Node IDs"
            )
        compute_requirement: _ComputeRequirementTarget = (
            _get_compute_requirement(target)
            if ydid_type == YDIDType.COMPUTE_REQUIREMENT
            else _resolve_compute_requirement_name(action, target)
        )
        if compute_requirement.status not in action.valid_cr_statuses:
            raise _Unresolved(
                f"Compute Requirement '{target}' is {compute_requirement.status},"
                f" not a valid state for action '{action.name}'",
                "skipped",
                compute_requirement,
            )
        plan.add_compute_requirement(compute_requirement)


def _get_compute_requirement(cr_id: str) -> ComputeRequirement:
    try:
        return CLIENT.compute_client.get_compute_requirement_by_id(cr_id)
    except Exception as e:
        if is_http_not_found(e):
            raise _Unresolved(f"Cannot find Compute Requirement {cr_id}") from e
        raise


def _resolve_compute_requirement_name(
    action: ComputeAction, name_or_namespaced_name: str
) -> ComputeRequirementSummary:
    """
    The Compute Requirement with a name, preferring one in a state the action
    applies to (entity_utils.find_compute_requirement_by_name()).
    """
    try:
        summary = find_compute_requirement_by_name(
            CLIENT,
            name_or_namespaced_name,
            CONFIG_COMMON.namespace,
            action.valid_cr_statuses,
        )
    except (NotFoundError, AmbiguousNameError) as e:
        raise _Unresolved(str(e)) from e
    print_info(f"Found Compute Requirement ID: {summary.id}")
    return summary


def _resolve_instance(
    action: ComputeAction, cr_id: str, instance_id: str
) -> tuple[ComputeRequirement, Instance]:
    compute_requirement = _get_compute_requirement(cr_id)
    instance: Instance | None = get_instance_by_id(CLIENT, cr_id, instance_id)
    if instance is None:
        raise _Unresolved(
            f"Cannot find Instance ID '{instance_id}' in Compute Requirement {cr_id}"
        )
    if instance.status not in action.valid_instance_statuses:
        raise _Unresolved(
            f"Instance '{cr_id}.{instance_id}' is {instance.status},"
            f" not a valid state for action '{action.name}'",
            "skipped",
        )
    return compute_requirement, instance


def _resolve_node(
    action: ComputeAction, node_id: str
) -> tuple[str, ComputeRequirement, Instance, str]:
    """
    The Compute Requirement (its ID, and itself), Instance and Instance ID a
    Node runs on.
    """
    try:
        node = CLIENT.worker_pool_client.get_node_by_id(node_id)
    except Exception as e:
        if is_http_not_found(e):
            raise _Unresolved(f"Cannot find Node {node_id}") from e
        raise
    if node.status == NodeStatus.TERMINATED:
        raise _Unresolved(f"Node {node_id} is already TERMINATED", "skipped")

    try:
        worker_pool = CLIENT.worker_pool_client.get_worker_pool_by_id(
            cast(str, node.workerPoolId)
        )
    except Exception as e:
        if is_http_not_found(e):
            raise _Unresolved(f"Cannot find the Worker Pool of Node {node_id}") from e
        raise
    if not isinstance(worker_pool, ProvisionedWorkerPool):
        raise _Unresolved(
            f"Node {node_id} is in a Configured Worker Pool, whose Instances"
            " YellowDog does not manage"
        )
    if not worker_pool.computeRequirementId:
        raise _Unresolved(f"Node {node_id}'s Worker Pool has no Compute Requirement")
    if node.details is None or not node.details.instanceId:
        raise _Unresolved(f"Node {node_id} has not yet reported its Instance")

    cr_id = worker_pool.computeRequirementId
    instance_id = node.details.instanceId
    compute_requirement, instance = _resolve_instance(action, cr_id, instance_id)
    return cr_id, compute_requirement, instance, instance_id
