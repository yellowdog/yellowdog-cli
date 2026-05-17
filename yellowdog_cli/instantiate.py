#!/usr/bin/env python3

"""
A script to provision a Compute Requirement.
"""

from dataclasses import dataclass
from json import loads as json_loads
from math import ceil, floor
from typing import cast

import requests
from yellowdog_client.model import (
    ComputeRequirementTemplateTestResult,
    ComputeRequirementTemplateUsage,
)

from yellowdog_cli.utils.config_types import ConfigWorkerPool
from yellowdog_cli.utils.follow_utils import follow_events, follow_ids
from yellowdog_cli.utils.load_config import load_config_worker_pool
from yellowdog_cli.utils.misc_utils import (
    add_batch_number_postfix,
    generate_id,
    link_entity,
)
from yellowdog_cli.utils.printing import (
    print_compute_template_test_result,
    print_error,
    print_info,
    print_yd_object,
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
)
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON, main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType


# Specifies the number of instances in a Compute Requirement batch
@dataclass
class CRBatch:
    target_instances: int


CONFIG_WP: ConfigWorkerPool = load_config_worker_pool()
GENERATED_ID = generate_id("cr" + "_" + CONFIG_COMMON.name_tag)


@main_wrapper
def main():
    global CONFIG_WP

    if ARGS_PARSER.target is not None:
        CONFIG_WP.target_instance_count = ARGS_PARSER.target
        CONFIG_WP.target_instance_count_set = True

    # Direct file > file supplied using '-C' > file supplied in config file
    cr_json_file = (
        (
            ARGS_PARSER.worker_pool_file
            if ARGS_PARSER.compute_requirement is None
            else ARGS_PARSER.compute_requirement
        )
        if ARGS_PARSER.compute_requirement_file_positional is None
        else ARGS_PARSER.compute_requirement_file_positional
    )

    # -C > -P > workerPoolData / computeRequirementData
    cr_json_file = (
        CONFIG_WP.worker_pool_data_file if cr_json_file is None else cr_json_file
    )
    if cr_json_file is None:  # Finally, try 'computeRequirementData'
        cr_json_file = CONFIG_WP.compute_requirement_data_file

    if cr_json_file is not None:
        print_info(f"Loading Compute Requirement data from: '{cr_json_file}'")
        _create_compute_requirement_from_json(
            cr_json_file, WP_VARIABLES_PREFIX, WP_VARIABLES_POSTFIX
        )
        return

    if CONFIG_WP.template_id is None:
        raise ValueError("No 'templateId' supplied")

    # Allow use of CRT name instead of ID
    CONFIG_WP.template_id = get_template_id(
        client=CLIENT, template_id_or_name=CONFIG_WP.template_id
    )

    # Allow use of IF name instead of ID
    if CONFIG_WP.images_id is not None:
        CONFIG_WP.images_id = get_image_id(
            client=CLIENT, image_name_or_id=CONFIG_WP.images_id
        )

    if not ARGS_PARSER.report:
        print_info(
            "Provisioning Compute Requirement with "
            f"{CONFIG_WP.target_instance_count:,d} instance(s)"
        )

    batches: list[CRBatch] = _allocate_nodes_to_batches(
        CONFIG_WP.compute_requirement_batch_size,
        CONFIG_WP.target_instance_count,
    )

    num_batches = len(batches)
    if num_batches > 1 and not ARGS_PARSER.report:
        print_info(f"Batching into {num_batches} Compute Requirements")

    compute_requirement_ids: list[str] = []
    for batch_number in range(num_batches):
        id = add_batch_number_postfix(
            name=CONFIG_WP.name if CONFIG_WP.name is not None else GENERATED_ID,
            batch_number=batch_number,
            num_batches=num_batches,
        )
        if not (ARGS_PARSER.dry_run or ARGS_PARSER.report):
            if num_batches > 1:
                print_info(
                    f"Provisioning Compute Requirement {batch_number + 1} '{CONFIG_COMMON.namespace}/{id}'"
                    f"with {batches[batch_number].target_instances:,d} instance(s)"
                )
            else:
                print_info(
                    f"Provisioning Compute Requirement '{CONFIG_COMMON.namespace}/{id}'"
                )

        try:
            compute_requirement_template_usage = ComputeRequirementTemplateUsage(
                templateId=cast(str, CONFIG_WP.template_id),
                requirementNamespace=CONFIG_COMMON.namespace,
                requirementName=id,
                targetInstanceCount=batches[batch_number].target_instances,
                requirementTag=(
                    CONFIG_COMMON.name_tag
                    if CONFIG_WP.cr_tag is None
                    else CONFIG_WP.cr_tag
                ),
                maintainInstanceCount=CONFIG_WP.maintainInstanceCount,
                instanceTags=CONFIG_WP.instance_tags,
                imagesId=CONFIG_WP.images_id,
                userData=get_user_data_property(CONFIG_WP, ARGS_PARSER.content_path),
            )

            if ARGS_PARSER.report:
                print_info("Generating provisioning report only")
                try:
                    test_result: ComputeRequirementTemplateTestResult = (
                        CLIENT.compute_client.test_compute_requirement_template(
                            compute_requirement_template_usage
                        )
                    )
                    print_compute_template_test_result(test_result)
                except requests.HTTPError as http_error:
                    resp = http_error.response
                    if resp is not None and resp.status_code == 404:
                        raise RuntimeError(
                            json_loads(resp.text).get(
                                "message", "Template ID not found"
                            )
                        )
                    if resp is not None and "No sources" in resp.text:
                        print_info(
                            "No Compute Sources match the Template's constraints"
                        )
                    else:
                        raise http_error
                return

            if not ARGS_PARSER.dry_run:
                compute_requirement = (
                    CLIENT.compute_client.provision_compute_requirement_template(
                        compute_requirement_template_usage
                    )
                )
                compute_requirement_ids.append(compute_requirement.id)  # type: ignore[arg-type]
                if ARGS_PARSER.quiet:
                    print(compute_requirement.id)
                print_info(
                    f"Provisioned {link_entity(CONFIG_COMMON.url, compute_requirement)}"
                )
                print_info(f"YellowDog ID is '{compute_requirement.id}'")

            else:
                print_info("Dry-run: Printing JSON Compute Requirement specification")
                print_yd_object(compute_requirement_template_usage)
                print_info("Dry-run: Complete")

        except Exception as e:
            raise RuntimeError(
                "Unable to"
                f" {'report on' if ARGS_PARSER.report else 'provision'} Compute"
                f" Requirement: {e}"
            )

    if ARGS_PARSER.follow:
        follow_ids(compute_requirement_ids)


def _allocate_nodes_to_batches(
    max_batch_size: int, initial_nodes: int
) -> list[CRBatch]:
    """
    Helper function to distribute the number of requested instances
    as evenly as possible over Compute Requirements when batches are required.
    """
    try:
        num_batches = ceil(initial_nodes / max_batch_size)
        nodes_per_batch = floor(initial_nodes / num_batches)
    except ZeroDivisionError:
        return [CRBatch(target_instances=0)]

    # First pass population of batches with equal number of instances
    batches = [
        CRBatch(
            target_instances=nodes_per_batch,
        )
        for _ in range(num_batches)
    ]

    # Allocate remainder across batches
    remainder_nodes = initial_nodes - (nodes_per_batch * num_batches)
    for batch in batches:
        if remainder_nodes > 0:
            batch.target_instances += 1
            remainder_nodes -= 1
        else:
            break

    return batches


def _create_compute_requirement_from_json(
    cr_json_file: str, prefix: str = "", postfix: str = ""
) -> None:
    """
    Directly create the Compute Requirement using the YellowDog REST API.
    """

    if ARGS_PARSER.report:
        raise ValueError(
            "Compute Template reports aren't available when using JSON "
            "Compute Requirement / Worker Pool specifications"
        )

    if cr_json_file.lower().endswith(".jsonnet"):
        cr_data = load_jsonnet_file_with_variable_substitutions(
            cr_json_file, prefix=prefix, postfix=postfix
        )
    else:
        if ARGS_PARSER.jsonnet_dry_run:
            raise ValueError(
                "Option '--jsonnet-dry-run' can only be used with files "
                "ending in '.jsonnet'"
            )
        cr_data = load_json_file_with_variable_substitutions(
            cr_json_file, prefix=prefix, postfix=postfix
        )

    # Use only the 'requirementTemplateUsage' value (if present);
    # strips out Worker Pool stuff
    cr_data = cr_data.get("requirementTemplateUsage", cr_data)

    # Some values are configurable via the TOML configuration file;
    # values in the JSON file override values in the TOML file
    try:
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
            ("templateId", CONFIG_WP.template_id),
            ("userData", get_user_data_property(CONFIG_WP, ARGS_PARSER.content_path)),
            ("imagesId", CONFIG_WP.images_id),
            ("instanceTags", CONFIG_WP.instance_tags),
            ("targetInstanceCount", CONFIG_WP.target_instance_count),
            ("maintainInstanceCount", CONFIG_WP.maintainInstanceCount),
        ]:
            if cr_data.get(key) is None and value is not None:
                print_info(f"Setting '{key}' to '{value}'")
                cr_data[key] = value

    except KeyError as e:
        raise KeyError(f"Missing key error in JSON Compute Requirement definition: {e}")

    # Allow use of CRT name instead of ID
    cr_data["templateId"] = get_template_id(
        client=CLIENT, template_id_or_name=cr_data["templateId"]
    )

    # Allow use of IF name instead of ID
    if cr_data.get("imagesId") is not None:
        cr_data["imagesId"] = get_image_id(
            client=CLIENT, image_name_or_id=cr_data["imagesId"]
        )

    if ARGS_PARSER.dry_run:
        print_info("Dry-run: Printing JSON Compute Requirement specification")
        print_yd_object(cr_data)
        print_info("Dry-run: Complete")
        return

    response = requests.post(
        url=f"{CONFIG_COMMON.url}/compute/templates/provision",
        headers={"Authorization": f"yd-key {CONFIG_COMMON.key}:{CONFIG_COMMON.secret}"},
        json=cr_data,
    )
    name = cr_data["requirementName"]
    if response.status_code == 200:
        id = response.json()["id"]
        print_info(
            f"Provisioned Compute Requirement '{cr_data['requirementNamespace']}/{name}' ({id})"
        )
        if ARGS_PARSER.quiet:
            print(id)
        if ARGS_PARSER.follow:
            print_info("Following Compute Requirement event stream")
            follow_events(id, YDIDType.COMPUTE_REQUIREMENT)
    else:
        print_error(f"Failed to provision Compute Requirement '{name}'")
        raise RuntimeError(f"{response.text}")


# Standalone entry point
if __name__ == "__main__":
    main()
