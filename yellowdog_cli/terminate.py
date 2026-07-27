#!/usr/bin/env python3

"""
A script to terminate Compute Requirements and Nodes.
"""

from typing import cast

from yellowdog_client.model import (
    ComputeRequirement,
    ComputeRequirementStatus,
    ComputeRequirementSummary,
    Instance,
    InstanceStatus,
    Node,
    NodeStatus,
)

from yellowdog_cli.utils.dryrun_utils import report_dry_run
from yellowdog_cli.utils.entity_utils import (
    describe_glob_scope,
    expand_name_globs,
    get_compute_requirement_id_by_name,
    get_compute_requirement_id_by_worker_pool_id,
    get_compute_requirement_summaries,
    get_instance_by_id,
)
from yellowdog_cli.utils.follow_utils import follow_ids
from yellowdog_cli.utils.glob_utils import contains_glob_chars
from yellowdog_cli.utils.interactive import confirmed, select
from yellowdog_cli.utils.misc_utils import is_http_not_found, link_entity
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON, main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

VALID_TERMINATION_STATUSES = [
    ComputeRequirementStatus.NEW,
    ComputeRequirementStatus.PROVISIONING,
    ComputeRequirementStatus.STARTING,
    ComputeRequirementStatus.RUNNING,
    ComputeRequirementStatus.STOPPING,
    ComputeRequirementStatus.STOPPED,
]  # Excludes TERMINATED, TERMINATING


@main_wrapper
def main():
    names = ARGS_PARSER.compute_requirements_instances_or_nodes or []
    globs = [n for n in names if contains_glob_chars(n)]

    if names and not globs:
        terminate_by_name_or_id(names)
        return

    if globs:
        print_info(
            f"Terminating Compute Requirements "
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
                    statuses=VALID_TERMINATION_STATUSES,
                    name=prefix or None,
                ),
            )
        )
    else:
        print_info(
            "Terminating Compute Requirements in "
            f"namespace '{CONFIG_COMMON.namespace}' with tags "
            f"including '{CONFIG_COMMON.name_tag}'"
        )
        compute_requirement_summaries = get_compute_requirement_summaries(
            CLIENT,
            CONFIG_COMMON.namespace,
            CONFIG_COMMON.name_tag,
            VALID_TERMINATION_STATUSES,
        )

    if ARGS_PARSER.dry_run:
        report_dry_run(
            CLIENT,
            compute_requirement_summaries,
            "Compute Requirement",
            "terminated",
            bool(ARGS_PARSER.json_output),
        )
        return

    terminated_ids: list[str] = []
    selected_compute_requirement_summaries: list[ComputeRequirementSummary] = select(
        CLIENT, compute_requirement_summaries
    )

    if selected_compute_requirement_summaries and confirmed(
        f"Terminate {len(selected_compute_requirement_summaries)} Compute Requirement(s)?"
    ):
        for compute_requirement_summary in selected_compute_requirement_summaries:
            try:
                CLIENT.compute_client.terminate_compute_requirement_by_id(
                    compute_requirement_summary.id  # type: ignore[arg-type]
                )
            except Exception as e:
                print_error(
                    f"Failed to terminate '{compute_requirement_summary.name}': {e}"
                )
                continue  # Don't follow Compute Requirements that weren't terminated
            terminated_ids.append(cast(str, compute_requirement_summary.id))
            # The refetch is only needed to generate the link; the
            # termination has already succeeded
            try:
                compute_requirement: ComputeRequirement = (
                    CLIENT.compute_client.get_compute_requirement_by_id(
                        compute_requirement_summary.id  # type: ignore[arg-type]
                    )
                )
                print_info(
                    f"Terminated {link_entity(CONFIG_COMMON.url, compute_requirement)}"
                )
            except Exception:
                print_info(f"Terminated '{compute_requirement_summary.name}'")

    if terminated_ids:
        print_info(f"Terminated {len(terminated_ids)} Compute Requirement(s)")
        if ARGS_PARSER.follow:
            follow_ids(terminated_ids)
    else:
        print_info("No Compute Requirements terminated")


def terminate_by_name_or_id(names_or_ids: list[str]):
    """
    Terminate Compute Requirements by their names or IDs, or
    node IDs by their ID, or instances by 'cr_id.instance_id'.
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
                cr_id := _terminate_instance(cr_id_instance_id[0], cr_id_instance_id[1])
            ) is not None:
                node_or_instance_cr_ids.append(cr_id)

        # Compute requirement ID?
        elif (ydid_type := get_ydid_type(name_or_id)) == YDIDType.COMPUTE_REQUIREMENT:
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
            if compute_requirement.status not in VALID_TERMINATION_STATUSES:
                print_error(
                    f"Compute Requirement status {compute_requirement.status} "
                    "is not a valid state for termination"
                )
                continue
            compute_requirement_ids.append(name_or_id)

        # Node ID?
        elif ydid_type == YDIDType.NODE:
            if (cr_id := _terminate_node_instance_by_id(name_or_id)) is not None:
                node_or_instance_cr_ids.append(cr_id)

        # Compute requirement name?
        else:
            compute_requirement_id = get_compute_requirement_id_by_name(
                CLIENT, name_or_id, CONFIG_COMMON.namespace, VALID_TERMINATION_STATUSES
            )
            if compute_requirement_id is None:
                print_warning(
                    f"Compute Requirement in valid state not found for '{name_or_id}'"
                )
                continue
            else:
                print_info(f"Found Compute Requirement ID: {compute_requirement_id}")
                compute_requirement_ids.append(compute_requirement_id)

    # Handle termination of accumulated compute requirement IDs
    if compute_requirement_ids:
        if not confirmed(
            f"Terminate {len(compute_requirement_ids)} Compute Requirement(s)?"
            f": ({', '.join(compute_requirement_ids)})"
        ):
            return
        for compute_requirement_id in compute_requirement_ids:
            try:
                CLIENT.compute_client.terminate_compute_requirement_by_id(
                    compute_requirement_id
                )
                print_info(f"Terminated '{compute_requirement_id}'")
            except Exception as e:
                print_error(f"Failed to terminate '{compute_requirement_id}': ({e})")

    # Follow all the CR IDs from CR terminations and node, instance terminations
    if ARGS_PARSER.follow:
        follow_ids(compute_requirement_ids + node_or_instance_cr_ids)


def _terminate_node_instance_by_id(node_id: str) -> str | None:
    """
    Terminate a node's instance by its ID.
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

    if node.status == NodeStatus.TERMINATED:
        print_info(f"Node {node_id} is already {node.status}")
        return None

    if (
        cr_id := get_compute_requirement_id_by_worker_pool_id(
            CLIENT, cast(str, node.workerPoolId)
        )
    ) is None:
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
        return None

    return _terminate_instance(cr_id, instance.id.instanceId, node_id)  # type: ignore[union-attr]


def _terminate_instance(
    cr_id: str, instance_id: str, node_id: str | None = None
) -> str | None:
    """
    Terminate instance_id within cr_id.
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

    instance: Instance | None = get_instance_by_id(CLIENT, cr_id, instance_id)
    if instance is None:
        print_error(
            f"Cannot find Instance ID '{instance_id}' in Compute Requirement {cr_id}"
        )
        return None

    if instance.status in [InstanceStatus.TERMINATING, InstanceStatus.TERMINATED]:
        print_info(f"Instance ID '{cr_id}.{instance_id}' is already {instance.status}")
        return None

    node_id_msg = "" if node_id is None else f" (Node ID {node_id})"
    if not confirmed(
        f"Immediately terminate {instance.status} Instance ID '{instance_id}' "
        f"in Compute Requirement {cr_id}{node_id_msg}?"
    ):
        return None

    try:
        CLIENT.compute_client.terminate_instances(compute_requirement, [instance])
    except Exception as e:
        if "InvalidComputeRequirementStatusException" in str(e):
            print_error(
                f"Unable to terminate Instance ID '{instance_id}': "
                f"Compute Requirement {cr_id} is in invalid status"
                f" '{compute_requirement.status}'"
            )
        else:
            print_error(
                f"Failed to terminate Instance '{instance_id}' in "
                f"Compute Requirement {cr_id}: {e}"
            )
        return None

    print_info(f"Terminated Instance '{instance_id}' in Compute Requirement {cr_id}")
    return cr_id


# Entry point
if __name__ == "__main__":
    main()
