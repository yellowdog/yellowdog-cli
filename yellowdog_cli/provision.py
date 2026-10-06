#!/usr/bin/env python3

"""
A script to Provision a Worker Pool.
"""

from dataclasses import dataclass
from datetime import timedelta
from math import ceil, floor
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
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import ET_WORKER_POOLS
from yellowdog_cli.utils.file_substitution import (
    load_json_file_with_variable_substitutions,
    load_jsonnet_file_with_variable_substitutions,
)
from yellowdog_cli.utils.follow_utils import follow_ids
from yellowdog_cli.utils.lazy import lazy
from yellowdog_cli.utils.limits import RAW_REQUEST_TIMEOUT
from yellowdog_cli.utils.load_config import (
    load_config_worker_pool,
    warn_of_undefined_worker_pool_variables,
)
from yellowdog_cli.utils.misc_utils import (
    add_batch_number_postfix,
    generate_id,
    link_entity,
)
from yellowdog_cli.utils.printing import (
    print_dry_run,
    print_error,
    print_info,
    print_quiet_result,
    print_warning,
    print_worker_pool,
    print_yd_object,
    worker_pool_specification,
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
    shown_value,
    user_data_source,
)
from yellowdog_cli.utils.results import (
    record_document,
    record_document_part,
    record_entity,
)
from yellowdog_cli.utils.spec_schema import Family
from yellowdog_cli.utils.spec_validation import check_specification
from yellowdog_cli.utils.variable_syntax import (
    WP_VARIABLES_POSTFIX,
    WP_VARIABLES_PREFIX,
)
from yellowdog_cli.utils.wrapper import main_wrapper


# Specifies the cardinality for a Worker Pool batch
@dataclass
class WPBatch:
    initial_nodes: int
    min_nodes: int
    max_nodes: int


CONFIG_WP: ConfigWorkerPool = lazy(load_config_worker_pool)
# Generated in main() rather than at import, so that a name tag too long for
# it is reported as an error by main_wrapper rather than as a traceback
GENERATED_ID: str = ""


@main_wrapper
def main(ctx: RunContext) -> None:
    global GENERATED_ID

    warn_of_undefined_worker_pool_variables()
    GENERATED_ID = generate_id(ctx.config.name_tag)

    if ctx.args.target is not None:
        CONFIG_WP.target_instance_count = ctx.args.target
        CONFIG_WP.target_instance_count_set = True

    # Direct file > file supplied using '-p' > file supplied in config file
    wp_json_file = (
        (
            CONFIG_WP.worker_pool_data_file
            if ctx.args.worker_pool_file is None
            else ctx.args.worker_pool_file
        )
        if ctx.args.worker_pool_file_positional is None
        else ctx.args.worker_pool_file_positional
    )

    if wp_json_file is not None:
        print_info(f"Loading Worker Pool data from: '{wp_json_file}'")
        create_worker_pool_from_json(ctx, wp_json_file)
    elif ctx.args.validate:
        raise ValueError("Option '--validate' needs a Worker Pool specification file")
    elif CONFIG_WP.template_id is None:
        raise ValueError("No 'templateId' supplied")
    else:
        create_worker_pool_from_toml(ctx)


def create_worker_pool_from_json(ctx: RunContext, wp_json_file: str) -> None:
    """
    Directly create the Worker Pool using the YellowDog REST API.
    """
    if wp_json_file.lower().endswith(".jsonnet"):
        wp_data = load_jsonnet_file_with_variable_substitutions(
            wp_json_file,
            prefix=WP_VARIABLES_PREFIX,
            postfix=WP_VARIABLES_POSTFIX,
            dry_run=bool(ctx.args.jsonnet_dry_run),
        )
    else:
        if ctx.args.jsonnet_dry_run:
            raise ValueError(
                "Option '--jsonnet-dry-run' can only be used with files ending in '.jsonnet'"
            )
        wp_data = load_json_file_with_variable_substitutions(
            wp_json_file, prefix=WP_VARIABLES_PREFIX, postfix=WP_VARIABLES_POSTFIX
        )

    # Both branches above, JSON and Jsonnet, arrive here with the loaded document
    wp_data = check_specification(
        Family.WORKER_POOL, wp_data, wp_json_file, bool(ctx.args.validate)
    )

    # Some values are configurable via the TOML configuration file;
    # values in the JSON file override values in the TOML file, and
    # '--target' overrides both
    try:
        # requirementTemplateUsage insertions
        reqt_template_usage: dict = wp_data["requirementTemplateUsage"]
        for key, value in [
            # Generate a default name
            (
                "requirementName",
                (CONFIG_WP.name if CONFIG_WP.name is not None else GENERATED_ID),
            ),
            ("requirementNamespace", ctx.config.namespace),
            (
                "requirementTag",
                (ctx.config.name_tag if CONFIG_WP.cr_tag is None else CONFIG_WP.cr_tag),
            ),
            (TEMPLATE_ID, CONFIG_WP.template_id),
            (IMAGES_ID, CONFIG_WP.images_id),
            (INSTANCE_TAGS, CONFIG_WP.instance_tags),
        ]:
            if reqt_template_usage.get(key) is None and value is not None:
                print_info(
                    f"Setting 'requirementTemplateUsage.{key}': '{shown_value(value)}'"
                )
                reqt_template_usage[key] = value

        # The TOML user data is read only if the specification has none
        if reqt_template_usage.get(USERDATA) is None:
            user_data = get_user_data_property(CONFIG_WP, ctx.args.content_path)
            if user_data is not None:
                # Its source and size, never the script itself
                print_info(
                    f"Setting 'requirementTemplateUsage.{USERDATA}' from"
                    f" {user_data_source(CONFIG_WP)} ({len(user_data):,d} characters)"
                )
                reqt_template_usage[USERDATA] = user_data

        if ctx.args.target is not None:
            if reqt_template_usage.get(TARGET_INSTANCE_COUNT) != ctx.args.target:
                print_info(
                    f"Setting 'requirementTemplateUsage.{TARGET_INSTANCE_COUNT}':"
                    f" '{ctx.args.target}' (from '--target')"
                )
                reqt_template_usage[TARGET_INSTANCE_COUNT] = ctx.args.target
        elif (
            reqt_template_usage.get(TARGET_INSTANCE_COUNT) is None
            and CONFIG_WP.target_instance_count is not None
            and CONFIG_WP.target_instance_count_set is True
        ):
            print_info(
                f"Setting 'requirementTemplateUsage.{TARGET_INSTANCE_COUNT}':"
                f" '{CONFIG_WP.target_instance_count}'"
            )
            reqt_template_usage[TARGET_INSTANCE_COUNT] = CONFIG_WP.target_instance_count

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
                print_info(
                    f"Setting 'provisionedProperties.{key}': '{shown_value(value)}'"
                )
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
        raise ValueError(
            f"The Worker Pool specification '{wp_json_file}' has no"
            f" '{e.args[0]}' property"
        ) from e

    # The name lookups are outside the 'try' above: a name that is not found
    # raises a KeyError too, and is no error in the specification's keys
    if reqt_template_usage.get(TEMPLATE_ID) is None:
        raise ValueError(f"No '{TEMPLATE_ID}' supplied")

    # Allow a Compute Requirement Template name to be used instead of ID
    reqt_template_usage[TEMPLATE_ID] = get_template_id(
        ctx.client, reqt_template_usage[TEMPLATE_ID]
    )

    # Allow Image Family name to be used instead of ID
    if reqt_template_usage.get(IMAGES_ID) is not None:
        reqt_template_usage[IMAGES_ID] = get_image_id(
            ctx.client, reqt_template_usage[IMAGES_ID]
        )

    _rationalise_specification_node_counts(reqt_template_usage, provisioned_properties)

    # As for a TOML Worker Pool: a Worker Pool's Compute Requirement must not
    # maintain its instance count
    if reqt_template_usage.get(MAINTAIN_INSTANCE_COUNT) is True:
        print_warning(
            f"Property '{MAINTAIN_INSTANCE_COUNT}' will be set to "
            "'false' when creating a Worker Pool"
        )
        reqt_template_usage[MAINTAIN_INSTANCE_COUNT] = False

    # Batching is the TOML path's alone: a specification is one Worker Pool
    max_nodes = _integer_or_none(provisioned_properties.get(MAX_NODES))
    if max_nodes is not None and max_nodes > CONFIG_WP.compute_requirement_batch_size:
        print_warning(
            f"'maxNodes' ({max_nodes:,d}) is more than"
            f" 'computeRequirementBatchSize' ({CONFIG_WP.compute_requirement_batch_size:,d}),"
            " which applies only to a Worker Pool defined in the configuration: this"
            " specification is provisioned as a single Worker Pool"
        )

    if ctx.args.dry_run:
        if ctx.args.json_output:
            record_document(wp_data)
            return
        print_dry_run("Printing JSON Worker Pool specification")
        print_yd_object(wp_data)
        print_dry_run("Complete")
        return

    response = requests.post(
        url=f"{ctx.config.url}/workerPools/provisioned/template",
        headers={"Authorization": f"yd-key {ctx.config.key}:{ctx.config.secret}"},
        json=wp_data,
        timeout=RAW_REQUEST_TIMEOUT,
    )
    name = wp_data["requirementTemplateUsage"]["requirementName"]
    if response.status_code == 200:
        id = response.json()["id"]
        print_info(
            f"Provisioned Worker Pool '{reqt_template_usage['requirementNamespace']}/{name}' ({id})"
        )
        record_entity(
            id, name, reqt_template_usage["requirementNamespace"], ET_WORKER_POOLS
        )
        print_quiet_result(id)
        if ctx.args.follow:
            print_info("Following Worker Pool event stream")
            follow_ids(ctx, [id], auto_cr=ctx.args.auto_cr)
    else:
        print_error(f"Failed to provision Worker Pool '{name}'")
        # An HTTPError, so that the wrapper's exit code reflects the status
        raise requests.HTTPError(response.text, response=response)


def create_worker_pool_from_toml(ctx: RunContext) -> None:
    """
    Create the Worker Pool.
    """

    _update_node_counts()

    # Allow the Compute Requirement Template name to be used instead of ID
    CONFIG_WP.template_id = get_template_id(
        client=ctx.client, template_id_or_name=cast(str, CONFIG_WP.template_id)
    )

    # Allow the Image Family name to be used instead of ID
    if CONFIG_WP.images_id is not None:
        CONFIG_WP.images_id = get_image_id(
            client=ctx.client, image_name_or_id=CONFIG_WP.images_id
        )

    node_boot_timeout = timedelta(minutes=CONFIG_WP.node_boot_timeout)

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

    if CONFIG_WP.maintain_instance_count:
        print_warning(
            f"Property '{MAINTAIN_INSTANCE_COUNT}' will be set to "
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

    # Read once: every batch has the same user data
    user_data = get_user_data_property(CONFIG_WP, ctx.args.content_path)

    for batch_number in range(num_batches):
        id = add_batch_number_postfix(
            name=(CONFIG_WP.name if CONFIG_WP.name is not None else GENERATED_ID),
            batch_number=batch_number,
            num_batches=num_batches,
        )
        if num_batches > 1:
            print_info(
                f"Provisioning Worker Pool {batch_number + 1} '{ctx.config.namespace}/{id}' "
                f"with {batches[batch_number].initial_nodes:,d} nodes(s) "
                f"(minNodes: {batches[batch_number].min_nodes:,d}, "
                f"maxNodes: {batches[batch_number].max_nodes:,d})"
            )
        else:
            print_info(f"Provisioning Worker Pool '{ctx.config.namespace}/{id}'")
        try:
            compute_requirement_template_usage = ComputeRequirementTemplateUsage(
                templateId=cast(str, CONFIG_WP.template_id),
                requirementNamespace=ctx.config.namespace,
                requirementName=id,
                targetInstanceCount=batches[batch_number].initial_nodes,
                requirementTag=(
                    ctx.config.name_tag
                    if CONFIG_WP.cr_tag is None
                    else CONFIG_WP.cr_tag
                ),
                userData=user_data,
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
            if not ctx.args.dry_run:
                worker_pool = ctx.client.worker_pool_client.provision_worker_pool(
                    compute_requirement_template_usage,
                    provisioned_worker_pool_properties,
                )
                print_info(f"Created {link_entity(ctx.config.url, worker_pool)}")
                print_info(f"YellowDog ID is '{worker_pool.id}'")
                worker_pool_ids.append(worker_pool.id)  # type: ignore[arg-type]
                # One per batch: the document is an array if batched
                record_entity(
                    worker_pool.id,
                    worker_pool.name,
                    ctx.config.namespace,
                    ET_WORKER_POOLS,
                )
                print_quiet_result(worker_pool.id)
            elif ctx.args.json_output:
                # One per batch, as above
                record_document_part(
                    worker_pool_specification(
                        compute_requirement_template_usage,
                        provisioned_worker_pool_properties,
                    )
                )
            else:
                print_worker_pool(
                    compute_requirement_template_usage,
                    provisioned_worker_pool_properties,
                )

        except Exception:
            # Re-raised as it is, so that the wrapper's exit code reflects it
            print_error(
                f"Unable to provision Worker Pool '{ctx.config.namespace}/{id}'"
            )
            if worker_pool_ids:
                print_warning(
                    f"{len(worker_pool_ids)} of {num_batches} Worker Pools were"
                    " provisioned before the failure, and are still running:"
                    f" {', '.join(worker_pool_ids)}"
                )
            raise

    idle_node_shutdown_string = (
        f"time limit is {_minutes(CONFIG_WP.idle_node_timeout)} minute(s)"
        if CONFIG_WP.idle_node_timeout != 0
        else "is disabled"
    )

    print_info(
        "Node boot time limit is "
        f"{_minutes(CONFIG_WP.node_boot_timeout)} minute(s) | "
        "Node idle shutdown "
        f"{idle_node_shutdown_string}"
    )

    idle_pool_shutdown = "enabled" if CONFIG_WP.idle_pool_timeout != 0 else "disabled"
    idle_pool_shutdown_msg = f"Worker Pool auto-shutdown is {idle_pool_shutdown}"
    idle_pool_shutdown_msg = (
        idle_pool_shutdown_msg
        + f" with a delay of {_minutes(CONFIG_WP.idle_pool_timeout)} minute(s)"
        if CONFIG_WP.idle_pool_timeout != 0
        else idle_pool_shutdown_msg
    )
    print_info(idle_pool_shutdown_msg)

    if CONFIG_WP.metrics_enabled:
        print_info("Node metrics are enabled")

    if ctx.args.dry_run:
        print_dry_run("Complete")
        return

    if ctx.args.follow:
        print_info("Following Worker Pool event stream(s)")
        follow_ids(ctx, worker_pool_ids, auto_cr=ctx.args.auto_cr)


def _minutes(minutes: float) -> str:
    """
    A number of minutes as a message shows it: '10', not '10.0'.
    """
    return f"{minutes:,.0f}" if float(minutes).is_integer() else f"{minutes:,}"


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


def _update_node_counts() -> None:
    """
    Rationalise the node counts in the TOML configuration.
    """
    (
        CONFIG_WP.min_nodes,
        CONFIG_WP.target_instance_count,
        CONFIG_WP.max_nodes,
    ) = cast(
        tuple[int, int, int],
        _rationalised_node_counts(
            CONFIG_WP.min_nodes, CONFIG_WP.target_instance_count, CONFIG_WP.max_nodes
        ),
    )


def _rationalise_specification_node_counts(
    requirement_template_usage: dict, provisioned_properties: dict
) -> None:
    """
    Rationalise the node counts in a JSON Worker Pool specification, once the
    TOML values and '--target' have been merged into it, so that the counts
    adjusted are the ones that will be sent. A count the specification does
    not give as an integer is left alone: absent, it is the platform's to
    default, and otherwise the platform's to reject.
    """
    counts = (
        (provisioned_properties, MIN_NODES),
        (requirement_template_usage, TARGET_INSTANCE_COUNT),
        (provisioned_properties, MAX_NODES),
    )
    current = [_integer_or_none(section.get(key)) for section, key in counts]
    rationalised = _rationalised_node_counts(*current)
    for (section, key), before, after in zip(counts, current, rationalised):
        if after != before:
            section[key] = after


def _integer_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _rationalised_node_counts(
    min_nodes: int | None, target_instance_count: int | None, max_nodes: int | None
) -> tuple[int | None, int | None, int | None]:
    """
    The node counts adjusted to be consistent, reporting each adjustment.
    A count that is None is not known, and is neither adjusted nor compared.
    """
    # Automatically set minNodes to 0 if required
    if min_nodes is not None and min_nodes < 0:
        print_info(
            f"Increasing 'minNodes' from {min_nodes} to 0 to satisfy minimum constraint"
        )
        min_nodes = 0

    # Automatically increase targetInstanceCount if required
    if (
        target_instance_count is not None
        and min_nodes is not None
        and target_instance_count < min_nodes
    ):
        print_info(
            f"Increasing 'targetInstanceCount' from {target_instance_count} "
            f"to {min_nodes} to match 'minNodes'"
        )
        target_instance_count = min_nodes

    # Automatically set maxNodes to 1 if required
    if (
        max_nodes is not None
        and max_nodes < 1
        and (target_instance_count is None or target_instance_count <= 1)
    ):
        print_info(
            f"Increasing 'maxNodes' from {max_nodes} to 1 to satisfy minimum constraint"
        )
        max_nodes = 1

    # Automatically increase maxNodes if required
    if (
        target_instance_count is not None
        and max_nodes is not None
        and target_instance_count > max_nodes
    ):
        print_info(
            f"Increasing 'maxNodes' from {max_nodes} to "
            f"{target_instance_count} to match 'targetInstanceCount'"
        )
        max_nodes = target_instance_count

    return min_nodes, target_instance_count, max_nodes


# Entry point
if __name__ == "__main__":
    main()
