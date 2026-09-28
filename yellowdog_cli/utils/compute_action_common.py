#!/usr/bin/env python3

"""
Core functionality for stopping, starting and restarting Compute
Requirements and Instances.
"""

from dataclasses import dataclass
from typing import cast

from yellowdog_client.model import (
    ComputeRequirementStatus,
    ComputeRequirementSummary,
    Instance,
    InstanceStatus,
    Node,
)

from yellowdog_cli.utils.entity_utils import (
    get_compute_requirement_id_by_name,
    get_compute_requirement_id_by_worker_pool_id,
    get_compute_requirement_summaries,
    get_instance_by_id,
)
from yellowdog_cli.utils.follow_utils import follow_ids
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


def apply_compute_action(action: ComputeAction):
    """
    Entry point for the yd-compute-stop/start/restart commands.
    """
    if ARGS_PARSER.compute_requirements_instances_or_nodes:
        _apply_action_by_name_or_id(
            action, ARGS_PARSER.compute_requirements_instances_or_nodes
        )
        return

    if action.cr_method_name is None:
        print_error(
            f"Please supply one or more Instances ('cr_id.instance_id') or "
            f"Node IDs to {action.name.lower()}"
        )
        return

    print_info(
        f"{action.gerund} Compute Requirements in "
        f"namespace '{CONFIG_COMMON.namespace}' with tags "
        f"including '{CONFIG_COMMON.name_tag}'"
    )

    compute_requirement_summaries: list[ComputeRequirementSummary] = (
        get_compute_requirement_summaries(
            CLIENT,
            CONFIG_COMMON.namespace,
            CONFIG_COMMON.name_tag,
            action.valid_cr_statuses,
        )
    )

    actioned_ids: list[str] = []
    selected_compute_requirement_summaries: list[ComputeRequirementSummary] = select(
        CLIENT, compute_requirement_summaries
    )

    if selected_compute_requirement_summaries and not confirmed(
        f"{action.name} {len(selected_compute_requirement_summaries)} "
        "Compute Requirement(s)?"
    ):
        for compute_requirement_summary in selected_compute_requirement_summaries:
            action.record(compute_requirement_summary, "skipped")
        selected_compute_requirement_summaries = []

    if selected_compute_requirement_summaries:
        for compute_requirement_summary in selected_compute_requirement_summaries:
            try:
                getattr(CLIENT.compute_client, action.cr_method_name)(
                    compute_requirement_summary.id
                )
            except Exception as e:
                print_error(
                    f"Failed to {action.name.lower()} "
                    f"'{compute_requirement_summary.name}': {e}"
                )
                action.record(compute_requirement_summary, "failed", str(e))
                continue  # Don't follow Compute Requirements that weren't actioned
            actioned_ids.append(cast(str, compute_requirement_summary.id))
            action.record(compute_requirement_summary)
            # The refetch is only needed to generate the link; the
            # action has already succeeded
            try:
                compute_requirement = (
                    CLIENT.compute_client.get_compute_requirement_by_id(
                        compute_requirement_summary.id  # type: ignore[arg-type]
                    )
                )
                print_info(
                    f"{action.past_tense} "
                    f"{link_entity(CONFIG_COMMON.url, compute_requirement)}"
                )
            except Exception:
                print_info(f"{action.past_tense} '{compute_requirement_summary.name}'")

    if actioned_ids:
        print_info(f"{action.past_tense} {len(actioned_ids)} Compute Requirement(s)")
        if ARGS_PARSER.follow:
            follow_ids(actioned_ids)
    else:
        print_info(f"No Compute Requirements {action.past_tense.lower()}")


def _apply_action_by_name_or_id(action: ComputeAction, names_or_ids: list[str]):
    """
    Apply the action to Compute Requirements by their names or IDs, to
    nodes' instances by node ID, or to instances by 'cr_id.instance_id'.
    """
    compute_requirement_ids: list[str] = []
    node_or_instance_cr_ids: list[str] = []

    for name_or_id in set(names_or_ids):  # Remove duplicates
        # Is this a cr_id.instance_id specification?
        if (cr_id_instance_id := split_instance_specification(name_or_id)) is not None:
            if (
                cr_id := _apply_action_to_instance(
                    action, cr_id_instance_id[0], cr_id_instance_id[1]
                )
            ) is not None:
                node_or_instance_cr_ids.append(cr_id)

        # Compute requirement ID?
        elif (ydid_type := get_ydid_type(name_or_id)) == YDIDType.COMPUTE_REQUIREMENT:
            if action.cr_method_name is None:
                print_error(
                    f"Compute Requirements cannot be {action.past_tense.lower()}; "
                    "please supply Instance or Node IDs"
                )
                action.record(
                    name_or_id,
                    "failed",
                    f"Compute Requirements cannot be {action.past_tense.lower()}",
                )
                continue
            try:
                compute_requirement = (
                    CLIENT.compute_client.get_compute_requirement_by_id(name_or_id)
                )
            except Exception as e:
                if is_http_not_found(e):
                    print_error(f"Cannot find Compute Requirement ID {name_or_id}")
                    action.record(name_or_id, "failed", "not found")
                else:
                    print_error(f"Cannot find Compute Requirement ID {name_or_id}: {e}")
                    action.record(name_or_id, "failed", str(e))
                continue
            if compute_requirement.status not in action.valid_cr_statuses:
                print_error(
                    f"Compute Requirement status {compute_requirement.status} "
                    f"is not a valid state for action '{action.name}'"
                )
                action.record(name_or_id, "skipped")
                continue
            compute_requirement_ids.append(name_or_id)

        # Node ID?
        elif ydid_type == YDIDType.NODE:
            if (
                cr_id := _apply_action_to_node_instance_by_id(action, name_or_id)
            ) is not None:
                node_or_instance_cr_ids.append(cr_id)

        # Compute requirement name?
        else:
            if action.cr_method_name is None:
                print_error(
                    f"Compute Requirements cannot be {action.past_tense.lower()}; "
                    "please supply Instance or Node IDs"
                )
                action.record(
                    name_or_id,
                    "failed",
                    f"Compute Requirements cannot be {action.past_tense.lower()}",
                )
                continue
            compute_requirement_id = get_compute_requirement_id_by_name(
                CLIENT, name_or_id, CONFIG_COMMON.namespace, action.valid_cr_statuses
            )
            if compute_requirement_id is None:
                print_warning(
                    f"Compute Requirement in valid state not found for '{name_or_id}'"
                )
                action.record(name_or_id, "failed", "not found in a valid state")
                continue
            else:
                print_info(f"Found Compute Requirement ID: {compute_requirement_id}")
                compute_requirement_ids.append(compute_requirement_id)

    # Handle the action for accumulated compute requirement IDs
    if compute_requirement_ids:
        if not confirmed(
            f"{action.name} {len(compute_requirement_ids)} Compute Requirement(s)?"
            f": ({', '.join(compute_requirement_ids)})"
        ):
            for compute_requirement_id in compute_requirement_ids:
                action.record(compute_requirement_id, "skipped")
            return
        for compute_requirement_id in compute_requirement_ids:
            try:
                getattr(CLIENT.compute_client, cast(str, action.cr_method_name))(
                    compute_requirement_id
                )
                print_info(f"{action.past_tense} '{compute_requirement_id}'")
                action.record(compute_requirement_id)
            except Exception as e:
                print_error(
                    f"Failed to {action.name.lower()} '{compute_requirement_id}': ({e})"
                )
                action.record(compute_requirement_id, "failed", str(e))

    # Follow all the CR IDs from CR actions and node, instance actions
    if ARGS_PARSER.follow:
        follow_ids(compute_requirement_ids + node_or_instance_cr_ids)


def _apply_action_to_node_instance_by_id(
    action: ComputeAction, node_id: str
) -> str | None:
    """
    Apply the action to a node's instance by its node ID.
    Returns the compute requirement ID or None.
    """
    try:
        node: Node = CLIENT.worker_pool_client.get_node_by_id(node_id)
    except Exception as e:
        if is_http_not_found(e):
            print_error(f"Cannot find Node with ID {node_id}")
            action.record(node_id, "failed", "not found", ET_NODES)
            return None
        else:
            print_error(f"Error for Node ID {node_id}: {e}")
            action.record(node_id, "failed", str(e), ET_NODES)
            return None

    if (
        cr_id := get_compute_requirement_id_by_worker_pool_id(
            CLIENT, cast(str, node.workerPoolId)
        )
    ) is None:
        action.record(node_id, "failed", "no Compute Requirement found", ET_NODES)
        return None

    instance: Instance | None = get_instance_by_id(
        CLIENT,
        cr_id,
        node.details.instanceId,  # type: ignore[union-attr]
    )

    if instance is None:
        print_error(
            f"Cannot find Instance ID for Node ID {node_id} "
            f"in Compute Requirement {cr_id}"
        )
        action.record(node_id, "failed", "Instance not found", ET_NODES)
        return None

    return _apply_action_to_instance(
        action,
        cr_id,
        instance.id.instanceId,  # type: ignore[union-attr]
        node_id,
    )


def _apply_action_to_instance(
    action: ComputeAction, cr_id: str, instance_id: str, node_id: str | None = None
) -> str | None:
    """
    Apply the action to instance_id within cr_id.
    Returns the compute requirement ID or None.
    """

    # Named by the 'cr_id.instance_id' form the command accepts, and by the
    # Instance ID it prints
    instance_record = {"id": f"{cr_id}.{instance_id}", "name": instance_id}

    if get_ydid_type(cr_id) != YDIDType.COMPUTE_REQUIREMENT:
        print_error(f"Invalid Compute Requirement ID {cr_id}")
        action.record(
            instance_record, "failed", "invalid Compute Requirement ID", ET_INSTANCES
        )
        return None

    try:
        compute_requirement = CLIENT.compute_client.get_compute_requirement_by_id(cr_id)
    except Exception:
        print_error(f"Cannot find Compute Requirement {cr_id}")
        action.record(
            instance_record, "failed", "Compute Requirement not found", ET_INSTANCES
        )
        return None

    instance: Instance | None = get_instance_by_id(CLIENT, cr_id, instance_id)
    if instance is None:
        print_error(
            f"Cannot find Instance ID '{instance_id}' in Compute Requirement {cr_id}"
        )
        action.record(instance_record, "failed", "not found", ET_INSTANCES)
        return None

    if instance.status not in action.valid_instance_statuses:
        print_error(
            f"Instance ID '{cr_id}.{instance_id}' status {instance.status} "
            f"is not a valid state for action '{action.name}'"
        )
        action.record(instance_record, "skipped", entity_type=ET_INSTANCES)
        return None

    node_id_msg = "" if node_id is None else f" (Node ID {node_id})"
    if not confirmed(
        f"{action.name} {instance.status} Instance ID '{instance_id}' "
        f"in Compute Requirement {cr_id}{node_id_msg}?"
    ):
        action.record(instance_record, "skipped", entity_type=ET_INSTANCES)
        return None

    try:
        getattr(CLIENT.compute_client, action.instance_method_name)(
            compute_requirement, [instance]
        )
    except Exception as e:
        if "InvalidComputeRequirementStatusException" in str(e):
            print_error(
                f"Unable to {action.name.lower()} Instance ID '{instance_id}': "
                f"Compute Requirement {cr_id} is in invalid status"
                f" '{compute_requirement.status}'"
            )
        else:
            print_error(
                f"Failed to {action.name.lower()} Instance '{instance_id}' in "
                f"Compute Requirement {cr_id}: {e}"
            )
        action.record(instance_record, "failed", str(e), ET_INSTANCES)
        return None

    print_info(
        f"{action.past_tense} Instance '{instance_id}' in Compute Requirement {cr_id}"
    )
    action.record(instance_record, entity_type=ET_INSTANCES)
    return cr_id
