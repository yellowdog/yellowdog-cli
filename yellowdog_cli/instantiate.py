#!/usr/bin/env python3

"""
A script to provision a Compute Requirement.
"""

from dataclasses import dataclass
from json import loads as json_loads
from math import ceil, floor
from typing import cast

import requests
from yellowdog_client.common.json import Json
from yellowdog_client.model import (
    ComputeRequirementTemplateTestResult,
    ComputeRequirementTemplateUsage,
)

from yellowdog_cli.utils.config_types import ConfigWorkerPool
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import ET_COMPUTE_REQUIREMENTS
from yellowdog_cli.utils.exit_codes import NotFoundError
from yellowdog_cli.utils.follow_utils import follow_events, follow_ids
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
    print_yd_object,
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
from yellowdog_cli.utils.spec_loading import load_specification
from yellowdog_cli.utils.spec_schema import Family
from yellowdog_cli.utils.tables import print_compute_template_test_result
from yellowdog_cli.utils.variable_syntax import (
    WP_VARIABLES_POSTFIX,
    WP_VARIABLES_PREFIX,
)
from yellowdog_cli.utils.wrapper import main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType


# Specifies the number of instances in a Compute Requirement batch
@dataclass
class CRBatch:
    target_instances: int


CONFIG_WP: ConfigWorkerPool = lazy(load_config_worker_pool)
# Generated in main() rather than at import, so that a name tag too long for
# it is reported as an error by main_wrapper rather than as a traceback
GENERATED_ID: str = ""


@main_wrapper
def main(ctx: RunContext):
    global GENERATED_ID

    warn_of_undefined_worker_pool_variables()
    GENERATED_ID = generate_id(ctx.config.name_tag)

    if ctx.args.target is not None:
        CONFIG_WP.target_instance_count = ctx.args.target
        CONFIG_WP.target_instance_count_set = True

    # Direct file > file supplied using '-C' > file supplied in config file
    cr_json_file = (
        (
            ctx.args.worker_pool_file
            if ctx.args.compute_requirement is None
            else ctx.args.compute_requirement
        )
        if ctx.args.compute_requirement_file_positional is None
        else ctx.args.compute_requirement_file_positional
    )

    # -C > -P > workerPoolData / computeRequirementData
    cr_json_file = (
        CONFIG_WP.worker_pool_data_file if cr_json_file is None else cr_json_file
    )
    if cr_json_file is None:  # Finally, try 'computeRequirementData'
        cr_json_file = CONFIG_WP.compute_requirement_data_file

    if cr_json_file is not None:
        _create_compute_requirement_from_json(
            ctx, cr_json_file, WP_VARIABLES_PREFIX, WP_VARIABLES_POSTFIX
        )
        return

    if ctx.args.validate:
        raise ValueError(
            "Option '--validate' needs a Compute Requirement specification file"
        )

    if CONFIG_WP.template_id is None:
        raise ValueError("No 'templateId' supplied")

    # Allow use of CRT name instead of ID
    CONFIG_WP.template_id = get_template_id(
        client=ctx.client, template_id_or_name=CONFIG_WP.template_id
    )

    # Allow use of IF name instead of ID
    if CONFIG_WP.images_id is not None:
        CONFIG_WP.images_id = get_image_id(
            client=ctx.client, image_name_or_id=CONFIG_WP.images_id
        )

    if not ctx.args.report:
        print_info(
            "Provisioning Compute Requirement with "
            f"{CONFIG_WP.target_instance_count:,d} instance(s)"
        )

    batches: list[CRBatch] = _allocate_nodes_to_batches(
        CONFIG_WP.compute_requirement_batch_size,
        CONFIG_WP.target_instance_count,
    )

    num_batches = len(batches)
    if num_batches > 1 and not ctx.args.report:
        print_info(f"Batching into {num_batches} Compute Requirements")

    # Read once: every batch has the same user data
    user_data = get_user_data_property(CONFIG_WP, ctx.args.content_path)

    compute_requirement_ids: list[str] = []
    for batch_number in range(num_batches):
        id = add_batch_number_postfix(
            name=CONFIG_WP.name if CONFIG_WP.name is not None else GENERATED_ID,
            batch_number=batch_number,
            num_batches=num_batches,
        )
        if not (ctx.args.dry_run or ctx.args.report):
            if num_batches > 1:
                print_info(
                    f"Provisioning Compute Requirement {batch_number + 1} '{ctx.config.namespace}/{id}'"
                    f" with {batches[batch_number].target_instances:,d} instance(s)"
                )
            else:
                print_info(
                    f"Provisioning Compute Requirement '{ctx.config.namespace}/{id}'"
                )

        try:
            compute_requirement_template_usage = ComputeRequirementTemplateUsage(
                templateId=cast(str, CONFIG_WP.template_id),
                requirementNamespace=ctx.config.namespace,
                requirementName=id,
                targetInstanceCount=batches[batch_number].target_instances,
                requirementTag=(
                    ctx.config.name_tag
                    if CONFIG_WP.cr_tag is None
                    else CONFIG_WP.cr_tag
                ),
                maintainInstanceCount=CONFIG_WP.maintain_instance_count,
                instanceTags=CONFIG_WP.instance_tags,
                imagesId=CONFIG_WP.images_id,
                userData=user_data,
            )

            if ctx.args.report:
                print_info("Generating provisioning report only")
                if num_batches > 1:
                    # The Platform tests one Compute Requirement at a time
                    print_warning(
                        f"The report is for the first of {num_batches} Compute"
                        f" Requirements, of {batches[0].target_instances:,d}"
                        " instance(s): 'computeRequirementBatchSize' divides the"
                        f" {CONFIG_WP.target_instance_count:,d} requested"
                    )
                try:
                    test_result: ComputeRequirementTemplateTestResult = (
                        ctx.client.compute_client.test_compute_requirement_template(
                            compute_requirement_template_usage
                        )
                    )
                    print_compute_template_test_result(test_result)
                except requests.HTTPError as http_error:
                    resp = http_error.response
                    if resp is not None and resp.status_code == 404:
                        raise NotFoundError(_message_of(resp.text)) from http_error
                    if resp is not None and "No sources" in resp.text:
                        print_info(
                            "No Compute Sources match the Template's constraints"
                        )
                    else:
                        raise http_error
                return

            if not ctx.args.dry_run:
                compute_requirement = (
                    ctx.client.compute_client.provision_compute_requirement_template(
                        compute_requirement_template_usage
                    )
                )
                compute_requirement_ids.append(compute_requirement.id)  # type: ignore[arg-type]
                # One per batch: the document is an array if batched
                record_entity(
                    compute_requirement.id,
                    compute_requirement.name,
                    ctx.config.namespace,
                    ET_COMPUTE_REQUIREMENTS,
                )
                print_quiet_result(compute_requirement.id)
                print_info(
                    f"Provisioned {link_entity(ctx.config.url, compute_requirement)}"
                )
                print_info(f"YellowDog ID is '{compute_requirement.id}'")

            elif ctx.args.json_output:
                # One per batch, as above
                record_document_part(Json.dump(compute_requirement_template_usage))
            else:
                print_dry_run("Printing JSON Compute Requirement specification")
                print_yd_object(compute_requirement_template_usage)
                print_dry_run("Complete")

        except Exception:
            # Re-raised as it is, so that the wrapper's exit code reflects it
            print_error(
                "Unable to"
                f" {'report on' if ctx.args.report else 'provision'} Compute"
                f" Requirement '{ctx.config.namespace}/{id}'"
            )
            if compute_requirement_ids:
                print_warning(
                    f"{len(compute_requirement_ids)} of {num_batches} Compute"
                    " Requirements were provisioned before the failure, and are"
                    f" still running: {', '.join(compute_requirement_ids)}"
                )
            raise

    if ctx.args.follow:
        follow_ids(ctx, compute_requirement_ids)


def _message_of(response_text: str) -> str:
    """
    A Platform error response's 'message', or a default if it has none or
    is not JSON.
    """
    try:
        message = json_loads(response_text).get("message")
    except (ValueError, AttributeError):
        message = None
    return message or "Compute Requirement Template not found"


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
    ctx: RunContext, cr_json_file: str, prefix: str = "", postfix: str = ""
) -> None:
    """
    Directly create the Compute Requirement using the YellowDog REST API.
    """

    if ctx.args.report:
        raise ValueError(
            "Compute Template reports aren't available when using JSON "
            "Compute Requirement / Worker Pool specifications"
        )

    # Validated before 'requirementTemplateUsage' is unwrapped
    cr_data = load_specification(
        cr_json_file,
        "Compute Requirement",
        family=Family.COMPUTE_REQUIREMENT,
        jsonnet_dry_run=bool(ctx.args.jsonnet_dry_run),
        validate=bool(ctx.args.validate),
        prefix=prefix,
        postfix=postfix,
        other_extensions_as_json=True,
    )

    # Use only the 'requirementTemplateUsage' value (if present);
    # strips out Worker Pool stuff
    cr_data = cr_data.get("requirementTemplateUsage", cr_data)

    # Some values are configurable via the TOML configuration file;
    # values in the JSON file override values in the TOML file, and
    # '--target' overrides both
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
        ("templateId", CONFIG_WP.template_id),
        ("imagesId", CONFIG_WP.images_id),
        ("instanceTags", CONFIG_WP.instance_tags),
        # Only a count the configuration actually gives: its default, 0, is
        # no count at all, and would provision an empty Compute Requirement
        (
            "targetInstanceCount",
            (
                CONFIG_WP.target_instance_count
                if CONFIG_WP.target_instance_count_set
                else None
            ),
        ),
        ("maintainInstanceCount", CONFIG_WP.maintain_instance_count),
    ]:
        if cr_data.get(key) is None and value is not None:
            print_info(f"Setting '{key}' to '{shown_value(value)}'")
            cr_data[key] = value

    # The TOML user data is read only if the specification has none
    if cr_data.get("userData") is None:
        user_data = get_user_data_property(CONFIG_WP, ctx.args.content_path)
        if user_data is not None:
            # Its source and size, never the script itself
            print_info(
                f"Setting 'userData' from {user_data_source(CONFIG_WP)}"
                f" ({len(user_data):,d} characters)"
            )
            cr_data["userData"] = user_data

    if (
        ctx.args.target is not None
        and cr_data.get("targetInstanceCount") != ctx.args.target
    ):
        print_info(
            f"Setting 'targetInstanceCount' to '{ctx.args.target}' (from '--target')"
        )
        cr_data["targetInstanceCount"] = ctx.args.target

    # Neither the specification nor the configuration names a template
    if cr_data.get("templateId") is None:
        raise ValueError("No 'templateId' supplied")

    # Allow use of CRT name instead of ID
    cr_data["templateId"] = get_template_id(
        client=ctx.client, template_id_or_name=cr_data["templateId"]
    )

    # Allow use of IF name instead of ID
    if cr_data.get("imagesId") is not None:
        cr_data["imagesId"] = get_image_id(
            client=ctx.client, image_name_or_id=cr_data["imagesId"]
        )

    if ctx.args.dry_run:
        if ctx.args.json_output:
            record_document(cr_data)
            return
        print_dry_run("Printing JSON Compute Requirement specification")
        print_yd_object(cr_data)
        print_dry_run("Complete")
        return

    response = requests.post(
        url=f"{ctx.config.url}/compute/templates/provision",
        headers={"Authorization": f"yd-key {ctx.config.key}:{ctx.config.secret}"},
        json=cr_data,
        timeout=RAW_REQUEST_TIMEOUT,
    )
    name = cr_data["requirementName"]
    if response.status_code == 200:
        id = response.json()["id"]
        print_info(
            f"Provisioned Compute Requirement '{cr_data['requirementNamespace']}/{name}' ({id})"
        )
        record_entity(
            id, name, cr_data["requirementNamespace"], ET_COMPUTE_REQUIREMENTS
        )
        print_quiet_result(id)
        if ctx.args.follow:
            print_info("Following Compute Requirement event stream")
            follow_events(ctx, id, YDIDType.COMPUTE_REQUIREMENT)
    else:
        print_error(f"Failed to provision Compute Requirement '{name}'")
        # An HTTPError, so that the wrapper's exit code reflects the status
        raise requests.HTTPError(response.text, response=response)


# Entry point
if __name__ == "__main__":
    main()
