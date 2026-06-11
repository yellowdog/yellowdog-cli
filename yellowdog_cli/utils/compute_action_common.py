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
    get_instance_id_by_id,
)
from yellowdog_cli.utils.follow_utils import follow_ids
from yellowdog_cli.utils.interactive import confirmed, select
from yellowdog_cli.utils.misc_utils import is_http_not_found, link_entity
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type


@dataclass(frozen=True)
class ComputeAction:
    name: str  # E.g.: "Stop"
    gerund: str  # E.g.: "Stopping"
    past_tense: str  # E.g.: "Stopped"
    cr_method_name: str | None  # ComputeClient method for CRs (None if N/A)
    instance_method_name: str  # ComputeClient method for instances
    valid_cr_statuses: list[ComputeRequirementStatus]
    valid_instance_statuses: list[InstanceStatus]


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

    if selected_compute_requirement_summaries and confirmed(
        f"{action.name} {len(selected_compute_requirement_summaries)} "
        "Compute Requirement(s)?"
    ):
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
                continue  # Don't follow Compute Requirements that weren't actioned
            actioned_ids.append(cast(str, compute_requirement_summary.id))
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
        # Is this a cr_id.instance_id specification? The prefix must be a CR
        # YDID, otherwise a CR *name* containing a '.' would be misclassified
        if (
            len(cr_id_instance_id := name_or_id.split(".")) == 2
            and get_ydid_type(cr_id_instance_id[0]) == YDIDType.COMPUTE_REQUIREMENT
        ):
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
                continue
            try:
                compute_requirement = (
                    CLIENT.compute_client.get_compute_requirement_by_id(name_or_id)
                )
            except Exception as e:
                if is_http_not_found(e):
                    print_error(f"Cannot find Compute Requirement ID {name_or_id}")
                else:
                    print_error(f"Cannot find Compute Requirement ID {name_or_id}: {e}")
                continue
            if compute_requirement.status not in action.valid_cr_statuses:
                print_error(
                    f"Compute Requirement status {compute_requirement.status} "
                    f"is not a valid state for action '{action.name}'"
                )
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
                continue
            compute_requirement_id = get_compute_requirement_id_by_name(
                CLIENT, name_or_id, CONFIG_COMMON.namespace, action.valid_cr_statuses
            )
            if compute_requirement_id is None:
                print_warning(
                    f"Compute Requirement in valid state not found for '{name_or_id}'"
                )
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
            return
        for compute_requirement_id in compute_requirement_ids:
            try:
                getattr(CLIENT.compute_client, cast(str, action.cr_method_name))(
                    compute_requirement_id
                )
                print_info(f"{action.past_tense} '{compute_requirement_id}'")
            except Exception as e:
                print_error(
                    f"Failed to {action.name.lower()} '{compute_requirement_id}': ({e})"
                )

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
            return None
        else:
            print_error(f"Error for Node ID {node_id}: {e}")
            return None

    if (
        cr_id := get_compute_requirement_id_by_worker_pool_id(
            CLIENT, cast(str, node.workerPoolId)
        )
    ) is None:
        return None

    instance: Instance | None = get_instance_id_by_id(
        CLIENT,
        cr_id,
        node.details.instanceId,  # type: ignore[union-attr]
    )

    if instance is None:
        print_error(
            f"Cannot find Instance ID for Node ID {node_id} "
            f"in Compute Requirement {cr_id}"
        )
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

    if get_ydid_type(cr_id) != YDIDType.COMPUTE_REQUIREMENT:
        print_error(f"Invalid Compute Requirement ID {cr_id}")
        return None

    try:
        compute_requirement = CLIENT.compute_client.get_compute_requirement_by_id(cr_id)
    except Exception:
        print_error(f"Cannot find Compute Requirement {cr_id}")
        return None

    instance: Instance | None = get_instance_id_by_id(CLIENT, cr_id, instance_id)
    if instance is None:
        print_error(
            f"Cannot find Instance ID '{instance_id}' in Compute Requirement {cr_id}"
        )
        return None

    if instance.status not in action.valid_instance_statuses:
        print_error(
            f"Instance ID '{cr_id}.{instance_id}' status {instance.status} "
            f"is not a valid state for action '{action.name}'"
        )
        return None

    node_id_msg = "" if node_id is None else f" (Node ID {node_id})"
    if not confirmed(
        f"{action.name} {instance.status} Instance ID '{instance_id}' "
        f"in Compute Requirement {cr_id}{node_id_msg}?"
    ):
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
        return None

    print_info(
        f"{action.past_tense} Instance '{instance_id}' in Compute Requirement {cr_id}"
    )
    return cr_id
