#!/usr/bin/env python3

"""
Command to show the JSON details of YellowDog entities via their IDs.
"""

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
    print_json,
    print_simple,
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
from yellowdog_cli.utils.variables import get_all_user_variables, get_user_variable
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
)


@main_wrapper
def main():

    if ARGS_PARSER.report_variables is not None:  # Report selected variables and return
        _report_variables(ARGS_PARSER.report_variables)
        return

    # Generate a JSON list of resources if there are multiple YDIDs
    # and the 'quiet' option is enabled
    generate_json_list = len(ARGS_PARSER.yellowdog_ids) > 1 and ARGS_PARSER.quiet

    if ARGS_PARSER.strip_ids:
        print_info("Stripping YellowDog IDs (etc.) from detailed JSON objects")

    if generate_json_list:
        print("[")
        if ARGS_PARSER.output_file is not None:
            print_to_file("[", ARGS_PARSER.output_file)

    for index, ydid in enumerate(ARGS_PARSER.yellowdog_ids):
        if generate_json_list:
            if index < len(ARGS_PARSER.yellowdog_ids) - 1:
                show_details(ydid, initial_indent=2, with_final_comma=True)
            else:
                show_details(ydid, initial_indent=2, with_final_comma=False)
        else:
            show_details(ydid)

    if generate_json_list:
        print("]")
        if ARGS_PARSER.output_file is not None:
            print_to_file("]", ARGS_PARSER.output_file)


def show_details(ydid: str, initial_indent: int = 0, with_final_comma: bool = False):
    """
    Show the details for a given YDID.
    """
    # Instances have no YDID of their own: they're identified by their Compute
    # Requirement plus an instance ID, in 'cr_id.instance_id' form
    if (
        len(cr_id_instance_id := ydid.split(".")) == 2
        and get_ydid_type(cr_id_instance_id[0]) == YDIDType.COMPUTE_REQUIREMENT
    ):
        _show_instance_details(
            cr_id_instance_id[0],
            cr_id_instance_id[1],
            initial_indent=initial_indent,
            with_final_comma=with_final_comma,
        )
        return

    try:
        if (ydid_type := get_ydid_type(ydid)) is None:
            print_error(f"Invalid YellowDog ID '{ydid}'")
            return
        if ydid_type == YDIDType.COMPUTE_SOURCE_TEMPLATE:
            print_info(f"Showing details of Compute Source Template ID '{ydid}'")
            if ARGS_PARSER.substitute_ids:
                print_info("Substituting Image Family ID with name")
            print_yd_object(
                substitute_image_family_id_for_name_in_cst(
                    CLIENT, CLIENT.compute_client.get_compute_source_template(ydid)
                ),
                initial_indent=initial_indent,
                with_final_comma=with_final_comma,
                add_fields=({RESOURCE_PROPERTY_NAME: RN_SOURCE_TEMPLATE}),
            )

        elif ydid_type == YDIDType.COMPUTE_REQUIREMENT_TEMPLATE:
            print_info(f"Showing details of Compute Requirement Template ID '{ydid}'")
            if ARGS_PARSER.substitute_ids:
                print_info(
                    "Substituting Compute Source Template IDs and Image Family IDs with names"
                )
            print_yd_object(
                substitute_ids_for_names_in_crt(
                    CLIENT, CLIENT.compute_client.get_compute_requirement_template(ydid)
                ),
                initial_indent=initial_indent,
                with_final_comma=with_final_comma,
                add_fields=({RESOURCE_PROPERTY_NAME: RN_REQUIREMENT_TEMPLATE}),
            )

        elif ydid_type == YDIDType.COMPUTE_REQUIREMENT:
            print_info(f"Showing details of Compute Requirement ID '{ydid}'")
            print_yd_object(CLIENT.compute_client.get_compute_requirement_by_id(ydid))

        elif ydid_type == YDIDType.COMPUTE_SOURCE:
            print_info(f"Showing details of Compute Source ID '{ydid}'")
            compute_requirement = CLIENT.compute_client.get_compute_requirement_by_id(
                ydid.rsplit(":", 1)[0].replace(TYPE_COMPSRC, TYPE_COMPREQ)
            )
            for source in compute_requirement.provisionStrategy.sources or []:
                if source.id == ydid:
                    print_yd_object(source)
                    return
            else:
                print_error(f"Compute Source ID '{ydid}' not found")

        elif ydid_type == YDIDType.WORKER_POOL:
            print_info(f"Showing details of Worker Pool ID '{ydid}'")
            worker_pool = CLIENT.worker_pool_client.get_worker_pool_by_id(ydid)
            print_yd_object(
                worker_pool,
                initial_indent=initial_indent,
                with_final_comma=with_final_comma,
                add_fields=(
                    {RESOURCE_PROPERTY_NAME: RN_CONFIGURED_POOL}
                    if isinstance(worker_pool, ConfiguredWorkerPool)
                    else {}
                ),
            )
            if ARGS_PARSER.show_token and isinstance(worker_pool, ConfiguredWorkerPool):
                print_info("Showing Configured Worker Pool token data")
                print_yd_object(
                    CLIENT.worker_pool_client.get_configured_worker_pool_token_by_id(
                        ydid
                    )
                )

        elif ydid_type == YDIDType.NODE:
            print_info(f"Showing details of Node ID '{ydid}'")
            print_yd_object(CLIENT.worker_pool_client.get_node_by_id(ydid))

        elif ydid_type == YDIDType.WORKER:
            print_info(f"Showing details of Worker ID '{ydid}'")
            node = CLIENT.worker_pool_client.get_node_by_id(
                ydid.rsplit(":", 1)[0].replace(TYPE_WRKR, TYPE_NODE)
            )
            for worker in node.workers or []:
                if worker.id == ydid:
                    print_yd_object(worker)
                    return
            else:
                print_error(f"Worker ID '{ydid}' not found")

        elif ydid_type == YDIDType.WORK_REQUIREMENT:
            print_info(f"Showing details of Work Requirement ID '{ydid}'")
            print_yd_object(CLIENT.work_client.get_work_requirement_by_id(ydid))

        elif ydid_type == YDIDType.TASK_GROUP:
            print_info(f"Showing details of Task Group ID '{ydid}'")
            work_requirement = CLIENT.work_client.get_work_requirement_by_id(
                ydid.rsplit(":", 1)[0].replace(TYPE_TASKGRP, TYPE_WORKREQ)
            )
            for task_group in work_requirement.taskGroups or []:
                if task_group.id == ydid:
                    print_yd_object(task_group)
                    return
            else:
                print_error(f"Task Group ID '{ydid}' not found")

        elif ydid_type == YDIDType.TASK:
            print_info(f"Showing details of Task ID '{ydid}'")
            print_yd_object(CLIENT.work_client.get_task_by_id(ydid))

        elif ydid_type == YDIDType.IMAGE_FAMILY:
            print_info(f"Showing details of Image Family ID '{ydid}'")
            print_yd_object(
                CLIENT.images_client.get_image_family_by_id(ydid),
                initial_indent=initial_indent,
                with_final_comma=with_final_comma,
                add_fields=({RESOURCE_PROPERTY_NAME: RN_IMAGE_FAMILY}),
            )

        elif ydid_type == YDIDType.IMAGE_GROUP:
            print_info(f"Showing details of Image Group ID '{ydid}'")
            print_yd_object(CLIENT.images_client.get_image_group_by_id(ydid))

        elif ydid_type == YDIDType.IMAGE:
            print_info(f"Showing details of Image ID '{ydid}'")
            print_yd_object(CLIENT.images_client.get_image(ydid))

        elif ydid_type == YDIDType.KEYRING:
            print_info(f"Showing details of Keyring ID '{ydid}'")
            keyrings = CLIENT.keyring_client.find_all_keyrings()
            for keyring in keyrings:
                if keyring.id == ydid:
                    # This fetches additional Keyring data: credentials and accessors
                    print_yd_object(
                        get_keyring(keyring.name),  # type: ignore[arg-type]
                        initial_indent=initial_indent,
                        with_final_comma=with_final_comma,
                        add_fields=({RESOURCE_PROPERTY_NAME: RN_KEYRING}),
                    )
                    return
            else:
                print_error(f"Keyring ID '{ydid}' not found")

        elif ydid_type == YDIDType.ALLOWANCE:
            print_info(f"Showing details of Allowance ID '{ydid}'")
            allowance = CLIENT.allowances_client.get_allowance_by_id(ydid)
            if ARGS_PARSER.substitute_ids:
                print_info("Substituting ID with name")
                allowance = substitute_id_for_name_in_allowance(CLIENT, allowance)  # type: ignore[arg-type]
            print_yd_object(
                allowance,
                initial_indent=initial_indent,
                with_final_comma=with_final_comma,
                add_fields=({RESOURCE_PROPERTY_NAME: RN_ALLOWANCE}),
            )

        elif ydid_type == YDIDType.APPLICATION:
            print_info(f"Showing details of Application ID '{ydid}'")
            group_names = [
                group.name for group in get_application_group_summaries(CLIENT, ydid)
            ]
            print_yd_object(
                CLIENT.account_client.get_application(ydid),
                initial_indent=initial_indent,
                with_final_comma=with_final_comma,
                add_fields=(
                    {
                        PROP_GROUPS: group_names,
                        RESOURCE_PROPERTY_NAME: RN_APPLICATION,
                    }
                ),
            )

        elif ydid_type == YDIDType.USER:
            print_info(f"Showing details of User ID '{ydid}'")
            user = CLIENT.account_client.get_user(ydid)
            print_yd_object(
                user,
                initial_indent=initial_indent,
                with_final_comma=with_final_comma,
                add_fields=({RESOURCE_PROPERTY_NAME: user.__class__.__name__}),
            )

        elif ydid_type == YDIDType.GROUP:
            print_info(f"Showing details of Group ID '{ydid}'")
            print_yd_object(
                CLIENT.account_client.get_group(ydid),
                initial_indent=initial_indent,
                with_final_comma=with_final_comma,
                add_fields=({RESOURCE_PROPERTY_NAME: RN_GROUP}),
            )

        elif ydid_type == YDIDType.ROLE:
            print_info(f"Showing details of Role ID '{ydid}'")
            print_yd_object(
                CLIENT.account_client.get_role(ydid),
                initial_indent=initial_indent,
                with_final_comma=with_final_comma,
                add_fields=({RESOURCE_PROPERTY_NAME: RN_ROLE}),
            )

        else:
            print_error(f"Unknown (or unsupported) YellowDog ID type for '{ydid}'")
            return

    except Exception as e:
        if is_http_not_found(e):
            print_error(f"{ydid_type.value} ID '{ydid}' not found")  # type: ignore[union-attr]
        else:
            print_error(f"Unable to show details for '{ydid}': {e}")


def _show_instance_details(
    cr_id: str,
    instance_id: str,
    initial_indent: int = 0,
    with_final_comma: bool = False,
):
    """
    Show the details of an Instance within a Compute Requirement, supplied
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
        return

    try:
        instance = get_instance_by_id(CLIENT, cr_id, instance_id)
    except Exception as e:
        print_error(f"Unable to show details for '{cr_id}.{instance_id}': {e}")
        return

    if instance is None:
        print_error(
            f"Instance ID '{instance_id}' not found in Compute Requirement ID '{cr_id}'"
        )
        return

    print_yd_object(
        instance,
        initial_indent=initial_indent,
        with_final_comma=with_final_comma,
    )


def _report_variables(variable_names: list[str]):
    """
    Convenience function to report the processed values of user variables.
    """
    if "all" in variable_names:
        variables = get_all_user_variables()
    else:
        variables = {
            variable_name: get_user_variable(variable_name)
            for variable_name in ARGS_PARSER.report_variables
        }
    variables_sorted = dict(sorted(variables.items()))

    if ARGS_PARSER.quiet:
        print_json(variables_sorted)
        return

    if not variables_sorted:
        print_info("No variables to report")
        return

    print_info("Reporting selected variable values:")
    max_var_name = max(len(name) for name in variables_sorted)
    for name, value in variables_sorted.items():
        print_simple(
            f"                      {name}{' ' * (max_var_name - len(name))} = {value}"
        )
    return


# Entry point
if __name__ == "__main__":
    main()
