#!/usr/bin/env python3

"""
Command to show the JSON details of YellowDog entities via their IDs.
"""

from sys import exit as sys_exit
from typing import Any

from yellowdog_client.model import ConfiguredWorkerPool

from yellowdog_cli.list import get_keyring
from yellowdog_cli.utils.entity_utils import (
    get_application_group_summaries,
    get_instance_by_id,
    substitute_id_for_name_in_allowance,
    substitute_ids_for_names_in_crt,
    substitute_image_family_id_for_name_in_cst,
)
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.printing import (
    print_error,
    print_info,
    print_to_file,
    print_yd_object,
)
from yellowdog_cli.utils.settings import (
    PROP_GROUPS,
    RESOURCE_PROPERTY_NAME,
    RN_ALLOWANCE,
    RN_APPLICATION,
    RN_CONFIGURED_POOL,
    RN_GROUP,
    RN_IMAGE_FAMILY,
    RN_KEYRING,
    RN_REQUIREMENT_TEMPLATE,
    RN_ROLE,
    RN_SOURCE_TEMPLATE,
)
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, main_wrapper
from yellowdog_cli.utils.ydid_utils import (
    TYPE_COMPREQ,
    TYPE_COMPSRC,
    TYPE_NODE,
    TYPE_TASKGRP,
    TYPE_WORKREQ,
    TYPE_WRKR,
    YDIDType,
    get_ydid_type,
    split_instance_specification,
)

# An object to be shown, paired with any additional fields to add to its JSON
# representation. A single YellowDog ID can yield more than one: a Configured
# Worker Pool shown with '--show-token' yields the pool and its token.
ShowItem = tuple[Any, dict | None]


@main_wrapper
def main():
    if show_ydids(ARGS_PARSER.yellowdog_ids) > 0:
        sys_exit(1)


def show_ydids(ydids: list[str]) -> int:
    """
    Resolve and print the details of each of the supplied YellowDog IDs.
    Returns the number of IDs that could not be resolved.
    """
    if ARGS_PARSER.strip_ids:
        print_info("Stripping YellowDog IDs (etc.) from detailed JSON objects")

    items: list[ShowItem] = []
    failures = 0
    for ydid in ydids:
        resolved = resolve_details(ydid)
        if resolved is None:  # The reason has already been reported
            failures += 1
            continue
        items += resolved

    # Whenever more than one object is to be printed, it's printed as a JSON
    # array. More than one ID asked for is enough on its own, so that the shape
    # of the output follows the request rather than how much of it succeeded;
    # a single ID can also yield more than one object, a Configured Worker Pool
    # shown with '--show-token' being the only case.
    _print_items(items, as_json_array=len(ydids) > 1 or len(items) > 1)

    return failures


def _print_items(items: list[ShowItem], as_json_array: bool):
    """
    Print the resolved objects, framing them as a JSON array if required.
    This is the only place the array's indentation and its separating commas
    are applied.
    """
    if as_json_array:
        print("[")
        if ARGS_PARSER.output_file is not None:
            print_to_file("[", ARGS_PARSER.output_file)

    for index, (yd_object, add_fields) in enumerate(items):
        print_yd_object(
            yd_object,
            initial_indent=2 if as_json_array else 0,
            with_final_comma=as_json_array and index < len(items) - 1,
            add_fields=add_fields,
        )

    if as_json_array:
        print("]")
        if ARGS_PARSER.output_file is not None:
            print_to_file("]", ARGS_PARSER.output_file)


def resolve_details(ydid: str) -> list[ShowItem] | None:
    """
    Resolve a YellowDog ID to the object(s) to be shown. Returns None if the ID
    could not be resolved, having already reported why.

    Resolution is deliberately separated from printing: the JSON array's
    indentation and commas were previously threaded through each branch below,
    applied to some of them and forgotten on the rest, which left the array
    unparseable for most entity types.
    """
    # Instances have no YDID of their own: they're identified by their Compute
    # Requirement plus an instance ID, in 'cr_id.instance_id' form
    if (cr_id_instance_id := split_instance_specification(ydid)) is not None:
        return _resolve_instance_details(cr_id_instance_id[0], cr_id_instance_id[1])

    try:
        if (ydid_type := get_ydid_type(ydid)) is None:
            print_error(f"Invalid YellowDog ID '{ydid}'")
            return None

        if ydid_type == YDIDType.COMPUTE_SOURCE_TEMPLATE:
            print_info(f"Showing details of Compute Source Template ID '{ydid}'")
            if ARGS_PARSER.substitute_ids:
                print_info("Substituting Image Family ID with name")
            return [
                (
                    substitute_image_family_id_for_name_in_cst(
                        CLIENT, CLIENT.compute_client.get_compute_source_template(ydid)
                    ),
                    {RESOURCE_PROPERTY_NAME: RN_SOURCE_TEMPLATE},
                )
            ]

        elif ydid_type == YDIDType.COMPUTE_REQUIREMENT_TEMPLATE:
            print_info(f"Showing details of Compute Requirement Template ID '{ydid}'")
            if ARGS_PARSER.substitute_ids:
                print_info(
                    "Substituting Compute Source Template IDs and Image Family IDs with names"
                )
            return [
                (
                    substitute_ids_for_names_in_crt(
                        CLIENT,
                        CLIENT.compute_client.get_compute_requirement_template(ydid),
                    ),
                    {RESOURCE_PROPERTY_NAME: RN_REQUIREMENT_TEMPLATE},
                )
            ]

        elif ydid_type == YDIDType.COMPUTE_REQUIREMENT:
            print_info(f"Showing details of Compute Requirement ID '{ydid}'")
            return [(CLIENT.compute_client.get_compute_requirement_by_id(ydid), None)]

        elif ydid_type == YDIDType.COMPUTE_SOURCE:
            print_info(f"Showing details of Compute Source ID '{ydid}'")
            compute_requirement = CLIENT.compute_client.get_compute_requirement_by_id(
                ydid.rsplit(":", 1)[0].replace(TYPE_COMPSRC, TYPE_COMPREQ)
            )
            for source in compute_requirement.provisionStrategy.sources or []:
                if source.id == ydid:
                    return [(source, None)]
            print_error(f"Compute Source ID '{ydid}' not found")
            return None

        elif ydid_type == YDIDType.WORKER_POOL:
            print_info(f"Showing details of Worker Pool ID '{ydid}'")
            worker_pool = CLIENT.worker_pool_client.get_worker_pool_by_id(ydid)
            items: list[ShowItem] = [
                (
                    worker_pool,
                    (
                        {RESOURCE_PROPERTY_NAME: RN_CONFIGURED_POOL}
                        if isinstance(worker_pool, ConfiguredWorkerPool)
                        else {}
                    ),
                )
            ]
            if ARGS_PARSER.show_token and isinstance(worker_pool, ConfiguredWorkerPool):
                print_info("Showing Configured Worker Pool token data")
                items.append(
                    (
                        CLIENT.worker_pool_client.get_configured_worker_pool_token_by_id(
                            ydid
                        ),
                        None,
                    )
                )
            return items

        elif ydid_type == YDIDType.NODE:
            print_info(f"Showing details of Node ID '{ydid}'")
            return [(CLIENT.worker_pool_client.get_node_by_id(ydid), None)]

        elif ydid_type == YDIDType.WORKER:
            print_info(f"Showing details of Worker ID '{ydid}'")
            node = CLIENT.worker_pool_client.get_node_by_id(
                ydid.rsplit(":", 1)[0].replace(TYPE_WRKR, TYPE_NODE)
            )
            for worker in node.workers or []:
                if worker.id == ydid:
                    return [(worker, None)]
            print_error(f"Worker ID '{ydid}' not found")
            return None

        elif ydid_type == YDIDType.WORK_REQUIREMENT:
            print_info(f"Showing details of Work Requirement ID '{ydid}'")
            return [(CLIENT.work_client.get_work_requirement_by_id(ydid), None)]

        elif ydid_type == YDIDType.TASK_GROUP:
            print_info(f"Showing details of Task Group ID '{ydid}'")
            work_requirement = CLIENT.work_client.get_work_requirement_by_id(
                ydid.rsplit(":", 1)[0].replace(TYPE_TASKGRP, TYPE_WORKREQ)
            )
            for task_group in work_requirement.taskGroups or []:
                if task_group.id == ydid:
                    return [(task_group, None)]
            print_error(f"Task Group ID '{ydid}' not found")
            return None

        elif ydid_type == YDIDType.TASK:
            print_info(f"Showing details of Task ID '{ydid}'")
            return [(CLIENT.work_client.get_task_by_id(ydid), None)]

        elif ydid_type == YDIDType.IMAGE_FAMILY:
            print_info(f"Showing details of Image Family ID '{ydid}'")
            return [
                (
                    CLIENT.images_client.get_image_family_by_id(ydid),
                    {RESOURCE_PROPERTY_NAME: RN_IMAGE_FAMILY},
                )
            ]

        elif ydid_type == YDIDType.IMAGE_GROUP:
            print_info(f"Showing details of Image Group ID '{ydid}'")
            return [(CLIENT.images_client.get_image_group_by_id(ydid), None)]

        elif ydid_type == YDIDType.IMAGE:
            print_info(f"Showing details of Image ID '{ydid}'")
            return [(CLIENT.images_client.get_image(ydid), None)]

        elif ydid_type == YDIDType.KEYRING:
            print_info(f"Showing details of Keyring ID '{ydid}'")
            keyrings = CLIENT.keyring_client.find_all_keyrings()
            for keyring in keyrings:
                if keyring.id == ydid:
                    # This fetches additional Keyring data: credentials and accessors
                    return [
                        (
                            get_keyring(keyring.name),  # type: ignore[arg-type]
                            {RESOURCE_PROPERTY_NAME: RN_KEYRING},
                        )
                    ]
            print_error(f"Keyring ID '{ydid}' not found")
            return None

        elif ydid_type == YDIDType.ALLOWANCE:
            print_info(f"Showing details of Allowance ID '{ydid}'")
            allowance = CLIENT.allowances_client.get_allowance_by_id(ydid)
            if ARGS_PARSER.substitute_ids:
                print_info("Substituting ID with name")
                allowance = substitute_id_for_name_in_allowance(CLIENT, allowance)  # type: ignore[arg-type]
            return [(allowance, {RESOURCE_PROPERTY_NAME: RN_ALLOWANCE})]

        elif ydid_type == YDIDType.APPLICATION:
            print_info(f"Showing details of Application ID '{ydid}'")
            group_names = [
                group.name for group in get_application_group_summaries(CLIENT, ydid)
            ]
            return [
                (
                    CLIENT.account_client.get_application(ydid),
                    {
                        PROP_GROUPS: group_names,
                        RESOURCE_PROPERTY_NAME: RN_APPLICATION,
                    },
                )
            ]

        elif ydid_type == YDIDType.USER:
            print_info(f"Showing details of User ID '{ydid}'")
            user = CLIENT.account_client.get_user(ydid)
            return [(user, {RESOURCE_PROPERTY_NAME: user.__class__.__name__})]

        elif ydid_type == YDIDType.GROUP:
            print_info(f"Showing details of Group ID '{ydid}'")
            return [
                (
                    CLIENT.account_client.get_group(ydid),
                    {RESOURCE_PROPERTY_NAME: RN_GROUP},
                )
            ]

        elif ydid_type == YDIDType.ROLE:
            print_info(f"Showing details of Role ID '{ydid}'")
            return [
                (
                    CLIENT.account_client.get_role(ydid),
                    {RESOURCE_PROPERTY_NAME: RN_ROLE},
                )
            ]

        else:
            print_error(f"Unknown (or unsupported) YellowDog ID type for '{ydid}'")
            return None

    except Exception as e:
        if is_http_not_found(e):
            print_error(f"{ydid_type.value} ID '{ydid}' not found")  # type: ignore[union-attr]
        else:
            print_error(f"Unable to show details for '{ydid}': {e}")
        return None


def _resolve_instance_details(cr_id: str, instance_id: str) -> list[ShowItem] | None:
    """
    Resolve the details of an Instance within a Compute Requirement, supplied
    in 'cr_id.instance_id' form.
    """
    print_info(
        f"Showing details of Instance ID '{instance_id}' in "
        f"Compute Requirement ID '{cr_id}'"
    )

    # Check the Compute Requirement exists first: the Instance search below
    # returns an empty list for a non-existent Compute Requirement, which is
    # indistinguishable from a Compute Requirement without this Instance
    try:
        CLIENT.compute_client.get_compute_requirement_by_id(cr_id)
    except Exception as e:
        if is_http_not_found(e):
            print_error(f"Compute Requirement ID '{cr_id}' not found")
        else:
            print_error(f"Unable to find Compute Requirement ID '{cr_id}': {e}")
        return None

    try:
        instance = get_instance_by_id(CLIENT, cr_id, instance_id)
    except Exception as e:
        print_error(f"Unable to show details for '{cr_id}.{instance_id}': {e}")
        return None

    if instance is None:
        print_error(
            f"Instance ID '{instance_id}' not found in Compute Requirement ID '{cr_id}'"
        )
        return None

    return [(instance, None)]


# Entry point
if __name__ == "__main__":
    main()
