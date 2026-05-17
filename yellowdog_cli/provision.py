#!/usr/bin/env python3

"""
A script to Provision a Worker Pool.
"""

from dataclasses import dataclass
from datetime import timedelta
from math import ceil, floor
from os.path import dirname
from typing import cast

import requests
from yellowdog_client.common.iso_datetime import iso_timedelta_format
from yellowdog_client.model import (
    AutoShutdown,
    ComputeRequirementTemplateUsage,
    NodeWorkerTarget,
    NodeWorkerTargetType,
    ProvisionedWorkerPoolProperties,
)

from yellowdog_cli.utils.config_types import ConfigWorkerPool
from yellowdog_cli.utils.follow_utils import follow_ids
from yellowdog_cli.utils.load_config import CONFIG_FILE_DIR, load_config_worker_pool
from yellowdog_cli.utils.misc_utils import (
    add_batch_number_postfix,
    generate_id,
    link_entity,
)
from yellowdog_cli.utils.printing import (
    print_error,
    print_info,
    print_worker_pool,
    print_yd_object,
)
from yellowdog_cli.utils.property_names import (
    IMAGES_ID,
    INSTANCE_TAGS,
    MAINTAIN_INSTANCE_COUNT,
    MAX_NODES,
    MIN_NODES,
    NODE_BOOT_TIMEOUT,
    TARGET_INSTANCE_COUNT,
    TEMPLATE_ID,
    USERDATA,
    WORKER_TAG,
)
from yellowdog_cli.utils.provision_utils import (
    get_image_id,
    get_template_id,
    get_user_data_property,
)
from yellowdog_cli.utils.settings import WP_VARIABLES_POSTFIX, WP_VARIABLES_PREFIX
from yellowdog_cli.utils.variables import (
    load_json_file_with_variable_substitutions,
    load_jsonnet_file_with_variable_substitutions,
    resolve_filename,
)
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON, main_wrapper


# Specifies the cardinality for a Worker Pool batch
@dataclass
class WPBatch:
    initial_nodes: int
    min_nodes: int
    max_nodes: int


CONFIG_WP: ConfigWorkerPool = load_config_worker_pool()
GENERATED_ID = generate_id("wp" + "_" + CONFIG_COMMON.name_tag)


@main_wrapper
def main():

    if ARGS_PARSER.target is not None:
        CONFIG_WP.target_instance_count = ARGS_PARSER.target
        CONFIG_WP.target_instance_count_set = True

    # Direct file > file supplied using '-p' > file supplied in config file
    wp_json_file = (
        (
            CONFIG_WP.worker_pool_data_file
            if ARGS_PARSER.worker_pool_file is None
            else ARGS_PARSER.worker_pool_file
        )
        if ARGS_PARSER.worker_pool_file_positional is None
        else ARGS_PARSER.worker_pool_file_positional
    )

    # Where do we find the data files?
    # content-path > wp_json_file location > config file location
    files_directory = (
        (CONFIG_FILE_DIR if wp_json_file is None else dirname(wp_json_file))
        if ARGS_PARSER.content_path is None
        else ARGS_PARSER.content_path
    )

    if wp_json_file is not None:
        wp_json_file = resolve_filename(files_directory, wp_json_file)
        print_info(f"Loading Worker Pool data from: '{wp_json_file}'")
        create_worker_pool_from_json(wp_json_file)
    elif CONFIG_WP.template_id is None:
        print_error("No template ID supplied")
    else:
        create_worker_pool_from_toml()


def create_worker_pool_from_json(wp_json_file: str) -> None:
    """
    Directly create the Worker Pool using the YellowDog REST API.
    """
    if wp_json_file.lower().endswith(".jsonnet"):
        wp_data = load_jsonnet_file_with_variable_substitutions(
            wp_json_file, prefix=WP_VARIABLES_PREFIX, postfix=WP_VARIABLES_POSTFIX
        )
    else:
        if ARGS_PARSER.jsonnet_dry_run:
            raise ValueError(
                "Option '--jsonnet-dry-run' can only be used with files ending in '.jsonnet'"
            )
        wp_data = load_json_file_with_variable_substitutions(
            wp_json_file, prefix=WP_VARIABLES_PREFIX, postfix=WP_VARIABLES_POSTFIX
        )

    _update_node_counts()

    # Some values are configurable via the TOML configuration file;
    # values in the JSON file override values in the TOML file
    try:
        # requirementTemplateUsage insertions
        reqt_template_usage: dict = wp_data["requirementTemplateUsage"]
        for key, value in [
            # Generate a default name
            (
                "requirementName",
                (CONFIG_WP.name if CONFIG_WP.name is not None else GENERATED_ID),
            ),
            ("requirementNamespace", CONFIG_COMMON.namespace),
            (
                "requirementTag",
                (
                    CONFIG_COMMON.name_tag
                    if CONFIG_WP.cr_tag is None
                    else CONFIG_WP.cr_tag
                ),
            ),
            (TEMPLATE_ID, CONFIG_WP.template_id),
            (USERDATA, get_user_data_property(CONFIG_WP, ARGS_PARSER.content_path)),
            (IMAGES_ID, CONFIG_WP.images_id),
            (INSTANCE_TAGS, CONFIG_WP.instance_tags),
        ]:
            if reqt_template_usage.get(key) is None and value is not None:
                print_info(f"Setting 'requirementTemplateUsage.{key}': '{value}'")
                reqt_template_usage[key] = value

        if (
            reqt_template_usage.get(TARGET_INSTANCE_COUNT) is None
            and CONFIG_WP.target_instance_count is not None
            and CONFIG_WP.target_instance_count_set is True
        ):
            print_info(
                f"Setting 'requirementTemplateUsage.{TARGET_INSTANCE_COUNT}':"
                f" '{CONFIG_WP.target_instance_count}'"
            )
            reqt_template_usage[TARGET_INSTANCE_COUNT] = CONFIG_WP.target_instance_count

        # Allow a Compute Requirement Template name to be used instead of ID
        reqt_template_usage[TEMPLATE_ID] = get_template_id(
            CLIENT, reqt_template_usage[TEMPLATE_ID]
        )

        # Allow Image Family name to be used instead of ID
        if reqt_template_usage.get(IMAGES_ID) is not None:
            reqt_template_usage[IMAGES_ID] = get_image_id(
                CLIENT, reqt_template_usage[IMAGES_ID]
            )

        # provisionedProperties insertions
        provisioned_properties = wp_data["provisionedProperties"]

        # Three options for the number of workers per node
        if CONFIG_WP.workers_custom_command is not None:
            create_node_workers = {
                "customTargetCommand": CONFIG_WP.workers_custom_command,
                "targetType": "CUSTOM",
            }
        elif CONFIG_WP.workers_per_vcpu is not None:
            create_node_workers = {
                "targetCount": CONFIG_WP.workers_per_vcpu,
                "targetType": "PER_VCPU",
            }
        else:  # Default option
            create_node_workers = {
                "targetCount": CONFIG_WP.workers_per_node,
                "targetType": "PER_NODE",
            }

        for key, value in [
            (WORKER_TAG, CONFIG_WP.worker_tag),
            (
                NODE_BOOT_TIMEOUT,
                iso_timedelta_format(timedelta(minutes=CONFIG_WP.node_boot_timeout)),
            ),
            (
                "idleNodeShutdown",
                (
                    {
                        "enabled": True,
                        "timeout": iso_timedelta_format(
                            timedelta(minutes=CONFIG_WP.idle_node_timeout)
                        ),
                    }
                    if CONFIG_WP.idle_node_timeout != 0
                    else {"enabled": False}
                ),
            ),
            (
                "idlePoolShutdown",
                (
                    {
                        "enabled": True,
                        "timeout": iso_timedelta_format(
                            timedelta(minutes=CONFIG_WP.idle_pool_timeout)
                        ),
                    }
                    if CONFIG_WP.idle_pool_timeout != 0
                    else {"enabled": False}
                ),
            ),
            ("createNodeWorkers", create_node_workers),
            ("metricsEnabled", CONFIG_WP.metrics_enabled),
        ]:
            if provisioned_properties.get(key) is None and value is not None:
                print_info(f"Setting 'provisionedProperties.{key}': '{value}'")
                provisioned_properties[key] = value

        for key, value, is_set in [
            (MIN_NODES, CONFIG_WP.min_nodes, CONFIG_WP.min_nodes_set),
            (MAX_NODES, CONFIG_WP.max_nodes, CONFIG_WP.max_nodes_set),
        ]:
            if (
                provisioned_properties.get(key) is None
                and value is not None
                and is_set is True
            ):
                print_info(f"Setting 'provisionedProperties.{key}': '{value}'")
                provisioned_properties[key] = value

    except KeyError as e:
        raise KeyError(f"Key error in JSON Worker Pool definition: {e}")

    if ARGS_PARSER.dry_run:
        print_info("Dry-run: Printing JSON Worker Pool specification")
        print_yd_object(wp_data)
        print_info("Dry-run: Complete")
        return

    response = requests.post(
        url=f"{CONFIG_COMMON.url}/workerPools/provisioned/template",
        headers={"Authorization": f"yd-key {CONFIG_COMMON.key}:{CONFIG_COMMON.secret}"},
        json=wp_data,
    )
    name = wp_data["requirementTemplateUsage"]["requirementName"]
    if response.status_code == 200:
        id = response.json()["id"]
        print_info(
            f"Provisioned Worker Pool '{reqt_template_usage['requirementNamespace']}/{name}' ({id})"
        )
        if ARGS_PARSER.quiet:
            print(id)
        if ARGS_PARSER.follow:
            print_info("Following Worker Pool event stream")
            follow_ids([id], auto_cr=ARGS_PARSER.auto_cr)
    else:
        print_error(f"Failed to provision Worker Pool '{name}'")
        raise RuntimeError(f"{response.text}")


def create_worker_pool_from_toml():
    """
    Create the Worker Pool.
    """

    _update_node_counts()

    # Allow the Compute Requirement Template name to be used instead of ID
    CONFIG_WP.template_id = get_template_id(
        client=CLIENT, template_id_or_name=cast(str, CONFIG_WP.template_id)
    )

    # Allow the Image Family name to be used instead of ID
    if CONFIG_WP.images_id is not None:
        CONFIG_WP.images_id = get_image_id(
            client=CLIENT, image_name_or_id=CONFIG_WP.images_id
        )

    node_boot_timeout = (
        None
        if CONFIG_WP.node_boot_timeout is None
        else timedelta(minutes=CONFIG_WP.node_boot_timeout)
    )

    idle_node_auto_shutdown = (
        AutoShutdown(
            enabled=True,
            timeout=timedelta(minutes=CONFIG_WP.idle_node_timeout),
        )
        if CONFIG_WP.idle_node_timeout != 0
        else AutoShutdown(enabled=False)
    )

    idle_pool_auto_shutdown = (
        AutoShutdown(
            enabled=True,
            timeout=timedelta(minutes=CONFIG_WP.idle_pool_timeout),
        )
        if CONFIG_WP.idle_pool_timeout != 0
        else AutoShutdown(enabled=False)
    )

    # Establish the number of Workers to create
    if CONFIG_WP.workers_custom_command is not None:
        node_workers = NodeWorkerTarget.per_custom_command(
            CONFIG_WP.workers_custom_command
        )
    elif CONFIG_WP.workers_per_vcpu is not None:
        node_workers = NodeWorkerTarget.per_vcpus(CONFIG_WP.workers_per_vcpu)
    else:
        node_workers = NodeWorkerTarget.per_node(CONFIG_WP.workers_per_node)

    if CONFIG_WP.maintainInstanceCount:
        print_info(
            f"Warning: Property '{MAINTAIN_INSTANCE_COUNT}' will be set to "
            "'false' when creating a Worker Pool"
        )

    # Create the Worker Pool
    if node_workers.targetType == NodeWorkerTargetType.CUSTOM:
        print_info(
            f"Provisioning {CONFIG_WP.target_instance_count:,d} node(s) "
            f"with a custom number of workers per node "
            f"(minNodes: {CONFIG_WP.min_nodes:,d}, "
            f"maxNodes: {CONFIG_WP.max_nodes:,d})"
        )
    else:
        print_info(
            f"Provisioning {CONFIG_WP.target_instance_count:,d} node(s) "
            f"with {node_workers.targetCount} worker(s) "
            f"{node_workers.targetType} "
            f"(minNodes: {CONFIG_WP.min_nodes:,d}, "
            f"maxNodes: {CONFIG_WP.max_nodes:,d})"
        )
    batches: list[WPBatch] = _allocate_nodes_to_batches(
        CONFIG_WP.compute_requirement_batch_size,
        CONFIG_WP.target_instance_count,
        CONFIG_WP.min_nodes,
        CONFIG_WP.max_nodes,
    )
    num_batches = len(batches)

    worker_pool_ids: list[str] = []
    if num_batches > 1:
        print_info(f"Batching into {num_batches} Compute Requirements")

    for batch_number in range(num_batches):
        id = add_batch_number_postfix(
            name=(CONFIG_WP.name if CONFIG_WP.name is not None else GENERATED_ID),
            batch_number=batch_number,
            num_batches=num_batches,
        )
        if num_batches > 1:
            print_info(
                f"Provisioning Worker Pool {batch_number + 1} '{CONFIG_COMMON.namespace}/{id}' "
                f"with {batches[batch_number].initial_nodes:,d} nodes(s) "
                f"(minNodes: {batches[batch_number].min_nodes:,d}, "
                f"maxNodes: {batches[batch_number].max_nodes:,d})"
            )
        else:
            print_info(f"Provisioning Worker Pool '{CONFIG_COMMON.namespace}/{id}'")
        try:
            compute_requirement_template_usage = ComputeRequirementTemplateUsage(
                templateId=cast(str, CONFIG_WP.template_id),
                requirementNamespace=CONFIG_COMMON.namespace,
                requirementName=id,
                targetInstanceCount=batches[batch_number].initial_nodes,
                requirementTag=(
                    CONFIG_COMMON.name_tag
                    if CONFIG_WP.cr_tag is None
                    else CONFIG_WP.cr_tag
                ),
                userData=get_user_data_property(CONFIG_WP, ARGS_PARSER.content_path),
                imagesId=CONFIG_WP.images_id,
                instanceTags=CONFIG_WP.instance_tags,
                maintainInstanceCount=False,  # Must be false for Worker Pools
            )
            provisioned_worker_pool_properties = ProvisionedWorkerPoolProperties(
                createNodeWorkers=node_workers,
                minNodes=batches[batch_number].min_nodes,
                maxNodes=batches[batch_number].max_nodes,
                workerTag=CONFIG_WP.worker_tag,
                idleNodeShutdown=idle_node_auto_shutdown,
                idlePoolShutdown=idle_pool_auto_shutdown,
                nodeBootTimeout=node_boot_timeout,
                metricsEnabled=CONFIG_WP.metrics_enabled,
            )
            if not ARGS_PARSER.dry_run:
                worker_pool = CLIENT.worker_pool_client.provision_worker_pool(
                    compute_requirement_template_usage,
                    provisioned_worker_pool_properties,
                )
                print_info(f"Created {link_entity(CONFIG_COMMON.url, worker_pool)}")
                print_info(f"YellowDog ID is '{worker_pool.id}'")
                worker_pool_ids.append(worker_pool.id)  # type: ignore[arg-type]
                if ARGS_PARSER.quiet:
                    print(worker_pool.id)
            else:
                print_worker_pool(
                    compute_requirement_template_usage,
                    provisioned_worker_pool_properties,
                )

        except Exception as e:
            raise RuntimeError(f"Unable to provision worker pool: {e}")

    idle_node_shutdown_string = (
        f"time limit is {CONFIG_WP.idle_node_timeout} minute(s)"
        if CONFIG_WP.idle_node_timeout != 0
        else "is **disabled**"
    )

    print_info(
        "Node boot time limit is "
        f"{CONFIG_WP.node_boot_timeout} minute(s) | "
        "Node idle shutdown "
        f"{idle_node_shutdown_string}"
    )

    idle_pool_shutdown = "enabled" if CONFIG_WP.idle_pool_timeout != 0 else "disabled"
    idle_pool_shutdown_msg = f"Worker Pool auto-shutdown is {idle_pool_shutdown}"
    idle_pool_shutdown_msg = (
        idle_pool_shutdown_msg
        + f" with a delay of {CONFIG_WP.idle_pool_timeout} minute(s)"
        if CONFIG_WP.idle_pool_timeout != 0
        else idle_pool_shutdown_msg
    )
    print_info(idle_pool_shutdown_msg)

    if CONFIG_WP.metrics_enabled:
        print_info("Node metrics are enabled")

    if ARGS_PARSER.dry_run:
        print_info("Dry-run: Complete")
        return

    if ARGS_PARSER.follow:
        print_info("Following Worker Pool event stream(s)")
        follow_ids(worker_pool_ids, auto_cr=ARGS_PARSER.auto_cr)


def _allocate_nodes_to_batches(
    max_batch_size: int, initial_nodes: int, min_nodes: int, max_nodes: int
) -> list[WPBatch]:
    """
    Helper function to distribute the number of requested instances
    as evenly as possible over Compute Requirements when batches are required.
    """
    num_batches = ceil(max_nodes / max_batch_size)
    nodes_per_batch = floor(initial_nodes / num_batches)
    min_nodes_per_batch = floor(min_nodes / num_batches)
    max_nodes_per_batch = floor(max_nodes / num_batches)
    # First pass population of batches with equal numbers
    batches = [
        WPBatch(
            initial_nodes=nodes_per_batch,
            min_nodes=min_nodes_per_batch,
            max_nodes=max_nodes_per_batch,
        )
        for _ in range(num_batches)
    ]
    # Allocate remainders across batches
    remainder_nodes = initial_nodes - (nodes_per_batch * num_batches)
    remainder_min_nodes = min_nodes - (min_nodes_per_batch * num_batches)
    remainder_max_nodes = max_nodes - (max_nodes_per_batch * num_batches)
    for batch in batches:
        if remainder_nodes > 0:
            batch.initial_nodes += 1
            remainder_nodes -= 1
        if remainder_min_nodes > 0:
            batch.min_nodes += 1
            remainder_min_nodes -= 1
        if remainder_max_nodes > 0:
            batch.max_nodes += 1
            remainder_max_nodes -= 1
        if (
            remainder_nodes == 0
            and remainder_min_nodes == 0
            and remainder_max_nodes == 0
        ):
            break
    return batches


def _update_node_counts():
    """
    Rationalise the node counts.
    """
    global CONFIG_WP

    # Automatically set minNodes to 0 if required
    if CONFIG_WP.min_nodes < 0:
        print_info(
            f"Increasing 'minNodes' from {CONFIG_WP.min_nodes} to 0 to satisfy "
            "minimum constraint"
        )
        CONFIG_WP.min_nodes = 0

    # Automatically increase targetInstanceCount if required
    if CONFIG_WP.target_instance_count < CONFIG_WP.min_nodes:
        print_info(
            f"Increasing 'targetInstanceCount' from {CONFIG_WP.target_instance_count} "
            f"to {CONFIG_WP.min_nodes} to match 'minNodes'"
        )
        CONFIG_WP.target_instance_count = CONFIG_WP.min_nodes

    # Automatically set maxNodes to 1 if required
    if CONFIG_WP.max_nodes < 1 and CONFIG_WP.target_instance_count <= 1:
        print_info(
            f"Increasing 'maxNodes' from {CONFIG_WP.max_nodes} to 1 to satisfy "
            "minimum constraint"
        )
        CONFIG_WP.max_nodes = 1

    # Automatically increase maxNodes if required
    if CONFIG_WP.target_instance_count > CONFIG_WP.max_nodes:
        print_info(
            f"Increasing 'maxNodes' from {CONFIG_WP.max_nodes} to "
            f"{CONFIG_WP.target_instance_count} to match 'targetInstanceCount'"
        )
        CONFIG_WP.max_nodes = CONFIG_WP.target_instance_count


# Entry point
if __name__ == "__main__":
    main()
