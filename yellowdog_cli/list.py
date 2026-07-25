#!/usr/bin/env python3

"""
Command to list YellowDog entities.
"""

from json import loads as json_loads
from os.path import exists
from typing import cast

from requests import get
from yellowdog_client.common import SearchClient
from yellowdog_client.common.json import Json
from yellowdog_client.model import (
    Allowance,
    AllowanceSearch,
    ComputeRequirementStatus,
    ComputeRequirementSummary,
    ComputeRequirementTemplateSummary,
    Group,
    Instance,
    InstanceSearch,
    Keyring,
    KeyringSummary,
    MachineImageFamilySearch,
    MachineImageFamilySummary,
    Namespace,
    NamespacePolicy,
    NamespacePolicySearch,
    NamespaceSearch,
    Node,
    NodeSearch,
    NodeStatus,
    PermissionDetail,
    Role,
    Task,
    TaskGroup,
    TaskGroupStatus,
    TaskStatus,
    User,
    Worker,
    WorkerPoolStatus,
    WorkerPoolSummary,
    WorkerStatus,
    WorkRequirementStatus,
    WorkRequirementSummary,
)

from yellowdog_cli.utils.entity_utils import (
    filter_summaries_by_name_glob,
    get_all_applications,
    get_all_groups,
    get_all_roles,
    get_all_tasks_in_task_group,
    get_all_users,
    get_application_group_summaries,
    get_compute_requirement_summaries,
    get_compute_requirement_templates,
    get_compute_source_templates,
    get_filtered_work_requirement_summaries,
    get_task_groups_from_wr_by_id,
    get_user_groups,
    get_worker_pool_summaries,
    resolve_name_glob,
    substitute_id_for_name_in_allowance,
    substitute_ids_for_names_in_crt,
    substitute_image_family_id_for_name_in_cst,
)
from yellowdog_cli.utils.glob_utils import glob_search_prefix
from yellowdog_cli.utils.interactive import confirmed, select
from yellowdog_cli.utils.printing import (
    print_info,
    print_json,
    print_numbered_object_list,
    print_objects_as_json,
    print_warning,
    print_yd_object,
    print_yd_object_list,
    sorted_objects,
)
from yellowdog_cli.utils.settings import (
    ET_ALLOWANCES,
    ET_APPLICATIONS,
    ET_ATTRIBUTE_DEFINITIONS,
    ET_COMPUTE_REQUIREMENT_TEMPLATES,
    ET_COMPUTE_REQUIREMENTS,
    ET_COMPUTE_SOURCE_TEMPLATES,
    ET_GROUPS,
    ET_IMAGE_FAMILIES,
    ET_INSTANCES,
    ET_KEYRINGS,
    ET_NAMESPACE_POLICIES,
    ET_NAMESPACES,
    ET_NODES,
    ET_PERMISSIONS,
    ET_ROLES,
    ET_TASK_GROUPS,
    ET_TASKS,
    ET_USERS,
    ET_WORK_REQUIREMENTS,
    ET_WORKER_POOLS,
    ET_WORKERS,
    PROP_GROUPS,
    PROP_RESOURCE,
    RN_ALLOWANCE,
    RN_APPLICATION,
    RN_GROUP,
    RN_IMAGE_FAMILY,
    RN_KEYRING,
    RN_NAMESPACE,
    RN_NUMERIC_ATTRIBUTE_DEFINITION,
    RN_REQUIREMENT_TEMPLATE,
    RN_ROLE,
    RN_SOURCE_TEMPLATE,
    RN_STRING_ATTRIBUTE_DEFINITION,
)
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON, main_wrapper

_KNOWN_STATUSES: dict[str, frozenset[str]] = {
    ET_WORK_REQUIREMENTS: frozenset(e.value for e in WorkRequirementStatus),
    ET_TASK_GROUPS: frozenset(e.value for e in TaskGroupStatus),
    ET_TASKS: frozenset(e.value for e in TaskStatus),
    ET_WORKER_POOLS: frozenset(e.value for e in WorkerPoolStatus),
    ET_NODES: frozenset(e.value for e in NodeStatus),
    ET_WORKERS: frozenset(e.value for e in WorkerStatus),
    ET_COMPUTE_REQUIREMENTS: frozenset(e.value for e in ComputeRequirementStatus),
}


def _apply_count_option() -> None:
    """
    The '--count' option implies '--quiet' and prints only the number of
    matching items, overriding the '--details', '--json' and '--ids-only'
    output options.
    """
    if not ARGS_PARSER.count_only:
        return
    ARGS_PARSER.quiet = True
    ARGS_PARSER.json_output = False
    ARGS_PARSER.details = False
    ARGS_PARSER.ids_only = False


def _print_json_or_count(objects: list) -> None:
    """
    Final output for the non-interactive aggregate modes: the item count
    for '--count', otherwise a JSON array for '--json'.
    """
    if ARGS_PARSER.count_only:
        print(len(objects))
    else:
        print_objects_as_json(objects)


def _print_empty(message: str) -> None:
    """
    Report an empty result: '0' in count mode, otherwise an info message.
    """
    if ARGS_PARSER.count_only:
        print(0)
    else:
        print_info(message)


def _apply_status_filter(objects: list) -> list:
    """Filter a list of objects to those whose status matches ARGS_PARSER.status_filter."""
    sf = ARGS_PARSER.status_filter
    if not sf:
        return objects
    upper = {s.upper() for s in sf}
    result = []
    for obj in objects:
        status = getattr(obj, "status", None)
        if status is None:
            result.append(obj)
            continue
        try:
            status_str = status.value.upper()
        except AttributeError:
            status_str = str(status).upper()
        if status_str in upper:
            result.append(obj)
    return result


@main_wrapper
def main():
    _apply_count_option()

    if not (ARGS_PARSER.json_output or ARGS_PARSER.count_only):
        ARGS_PARSER.interactive = True

    if (
        (
            ARGS_PARSER.auto_select_all
            or ARGS_PARSER.strip_ids
            or ARGS_PARSER.substitute_ids
            or ARGS_PARSER.output_file
        )
        and not ARGS_PARSER.details
        and not ARGS_PARSER.count_only
    ):
        print_info("Automatically setting the '--details' option")
        ARGS_PARSER.details = True

    if ARGS_PARSER.details and ARGS_PARSER.strip_ids:
        print_info("Stripping YellowDog IDs (etc.) from detailed JSON objects")

    if ARGS_PARSER.output_file and ARGS_PARSER.details:
        if exists(ARGS_PARSER.output_file):
            if not confirmed(
                f"Overwrite file '{ARGS_PARSER.output_file}' with new resource details?"
            ):
                return

    entity_type = ARGS_PARSER.entity_type

    if sf := ARGS_PARSER.status_filter:
        known = _KNOWN_STATUSES.get(entity_type or "", frozenset())
        if known:
            unknown = [s for s in sf if s.upper() not in known]
            if unknown:
                print_warning(
                    f"Unrecognised status value(s): {', '.join(repr(s) for s in unknown)}. "
                    f"Known values: {', '.join(sorted(known))}"
                )

    if entity_type in (ET_WORK_REQUIREMENTS, ET_TASK_GROUPS, ET_TASKS):
        list_work_requirements()
    elif entity_type in (ET_WORKER_POOLS, ET_NODES, ET_WORKERS):
        list_worker_pools()
    elif entity_type in (ET_COMPUTE_REQUIREMENTS, ET_INSTANCES):
        list_compute_requirements()
    elif entity_type == ET_COMPUTE_REQUIREMENT_TEMPLATES:
        list_compute_requirement_templates()
    elif entity_type == ET_COMPUTE_SOURCE_TEMPLATES:
        list_compute_source_templates()
    elif entity_type == ET_KEYRINGS:
        list_keyrings()
    elif entity_type == ET_IMAGE_FAMILIES:
        list_image_families()
    elif entity_type == ET_ALLOWANCES:
        list_allowances()
    elif entity_type == ET_ATTRIBUTE_DEFINITIONS:
        list_attribute_definitions()
    elif entity_type == ET_NAMESPACES:
        list_namespaces()
    elif entity_type == ET_NAMESPACE_POLICIES:
        list_namespace_policies()
    elif entity_type == ET_USERS:
        list_users()
    elif entity_type == ET_APPLICATIONS:
        list_applications()
    elif entity_type == ET_GROUPS:
        list_groups()
    elif entity_type == ET_ROLES:
        list_roles()
    elif entity_type == ET_PERMISSIONS:
        list_permissions()


def list_work_requirements():
    """
    List Work Requirements whenever --work-requirements, --task-groups or
    --tasks are selected.

    This function falls through from WRs to TGs to Tasks, depending on the
    options chosen.
    """
    if ARGS_PARSER.active_only:
        print_info("Listing active Work Requirements only")

    exclude_filter = (
        [
            WorkRequirementStatus.COMPLETED,
            WorkRequirementStatus.CANCELLED,
            WorkRequirementStatus.FAILED,
        ]
        if ARGS_PARSER.active_only
        else []
    )
    work_requirement_summaries: list[WorkRequirementSummary]
    if ARGS_PARSER.name_glob:
        namespace, name = resolve_name_glob(
            ARGS_PARSER.name_glob, CONFIG_COMMON.namespace
        )
        print_info(
            f"Listing Work Requirements in namespace '{namespace}' "
            f"matching name pattern '{name}'"
        )
        work_requirement_summaries = filter_summaries_by_name_glob(
            get_filtered_work_requirement_summaries(
                CLIENT,
                name=glob_search_prefix(name) or None,
                namespace=namespace,
                exclude_filter=exclude_filter,
            ),
            name,
        )
    else:
        print_info(
            f"Listing Work Requirements in namespace  '{CONFIG_COMMON.namespace}' "
            f"with '{CONFIG_COMMON.name_tag}' in tag",
        )
        work_requirement_summaries = get_filtered_work_requirement_summaries(
            CLIENT,
            namespace=CONFIG_COMMON.namespace,
            tag=CONFIG_COMMON.name_tag,
            exclude_filter=exclude_filter,
        )
    if not work_requirement_summaries:
        _print_empty("No matching Work Requirements")
        return

    work_requirement_summaries = sorted_objects(work_requirement_summaries)
    if ARGS_PARSER.entity_type == ET_WORK_REQUIREMENTS:
        work_requirement_summaries = _apply_status_filter(work_requirement_summaries)
        if not work_requirement_summaries:
            _print_empty("No matching Work Requirements")
            return
        if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
            if ARGS_PARSER.details:
                print_objects_as_json(
                    [
                        CLIENT.work_client.get_work_requirement_by_id(cast(str, wr.id))
                        for wr in work_requirement_summaries
                    ]
                )
            else:
                _print_json_or_count(work_requirement_summaries)
        elif ARGS_PARSER.details:
            print_yd_object_list(
                [
                    (CLIENT.work_client.get_work_requirement_by_id(wr_summary.id), None)  # type: ignore[arg-type]
                    for wr_summary in select(CLIENT, work_requirement_summaries)
                ]
            )
        elif ARGS_PARSER.ids_only:
            for wr_summary in work_requirement_summaries:
                print(wr_summary.id)
        else:
            print_numbered_object_list(CLIENT, work_requirement_summaries)
    elif ARGS_PARSER.json_output or ARGS_PARSER.count_only:
        # Collect all task groups / tasks across all work requirements
        all_objects: list = []
        for work_summary in work_requirement_summaries:
            tgs = sorted_objects(
                get_task_groups_from_wr_by_id(CLIENT, cast(str, work_summary.id))
            )
            if ARGS_PARSER.entity_type == ET_TASK_GROUPS:
                all_objects.extend(_apply_status_filter(tgs))
            else:
                for tg in tgs:
                    all_objects.extend(
                        _apply_status_filter(
                            get_all_tasks_in_task_group(CLIENT, cast(str, tg.id))
                        )
                    )
        _print_json_or_count(all_objects)
    else:
        selected_work_summaries = select(
            CLIENT, work_requirement_summaries, single_result=True
        )
        for work_summary in selected_work_summaries:
            print_info(f"Work Requirement '{work_summary.name}'")
            list_task_groups(work_summary)


def list_task_groups(work_summary: WorkRequirementSummary):
    task_groups: list[TaskGroup] = get_task_groups_from_wr_by_id(
        CLIENT, cast(str, work_summary.id)
    )
    task_groups = _apply_status_filter(sorted_objects(task_groups))
    if ARGS_PARSER.entity_type != ET_TASKS:
        if ARGS_PARSER.details:
            print_yd_object_list(
                [(task_group, None) for task_group in select(CLIENT, task_groups)]
            )
        elif ARGS_PARSER.ids_only:
            for task_group in task_groups:
                print(task_group.id)
        else:
            print_numbered_object_list(CLIENT, task_groups)
    else:
        task_groups = select(CLIENT, task_groups, single_result=True)
        for task_group in task_groups:
            list_tasks(task_group, work_summary)


def list_tasks(task_group: TaskGroup, _work_summary: WorkRequirementSummary):
    tasks: list[Task] = get_all_tasks_in_task_group(CLIENT, cast(str, task_group.id))
    tasks = _apply_status_filter(sorted_objects(tasks))
    if ARGS_PARSER.details:
        print_yd_object_list([(task, None) for task in select(CLIENT, tasks)])
    elif ARGS_PARSER.ids_only:
        for task in tasks:
            print(task.id)
    else:
        print_numbered_object_list(CLIENT, tasks)


def list_worker_pools():
    worker_pool_summaries: list[WorkerPoolSummary]
    if ARGS_PARSER.name_glob:
        namespace, name = resolve_name_glob(
            ARGS_PARSER.name_glob, CONFIG_COMMON.namespace
        )
        print_info(
            f"Displaying Worker Pools in namespace '{namespace}' "
            f"matching name pattern '{name}'"
        )
        worker_pool_summaries = filter_summaries_by_name_glob(
            get_worker_pool_summaries(
                CLIENT,
                namespace,
                glob_search_prefix(name) or None,
                partial_name_matches=True,
            ),
            name,
        )
    else:
        print_info(
            f"Displaying Worker Pools in namespace '{CONFIG_COMMON.namespace}' "
            f"with '{CONFIG_COMMON.name_tag}' in name"
        )
        worker_pool_summaries = get_worker_pool_summaries(
            CLIENT,
            CONFIG_COMMON.namespace,
            CONFIG_COMMON.name_tag,
            partial_name_matches=True,
        )

    excluded_states = (
        [WorkerPoolStatus.TERMINATED, WorkerPoolStatus.SHUTDOWN]
        if ARGS_PARSER.active_only
        else []
    )

    if ARGS_PARSER.active_only:
        print_info("Displaying active Worker Pools only")

    worker_pool_summaries = _apply_status_filter(
        [
            wp_summary
            for wp_summary in worker_pool_summaries
            if wp_summary.status not in excluded_states
            and (
                bool(ARGS_PARSER.name_glob)
                or CONFIG_COMMON.namespace in cast(str, wp_summary.namespace)
            )
        ]
    )

    if not worker_pool_summaries:
        _print_empty("No Worker Pools to display")
        return

    if ARGS_PARSER.entity_type in (ET_NODES, ET_WORKERS):
        if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
            list_nodes(worker_pool_summaries)
            return
        print_info(
            "Please select the Worker Pool(s) for which to list "
            f"{'Nodes' if ARGS_PARSER.entity_type == ET_NODES else 'Workers'}"
        )
        worker_pool_summaries = cast(
            list[WorkerPoolSummary],
            select(CLIENT, sorted_objects(worker_pool_summaries)),
        )
        list_nodes(worker_pool_summaries)
        return

    if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
        if ARGS_PARSER.details:
            print_objects_as_json(
                [
                    CLIENT.worker_pool_client.get_worker_pool_by_id(wp.id)  # type: ignore[arg-type]
                    for wp in sorted_objects(worker_pool_summaries)
                ]
            )
        else:
            _print_json_or_count(sorted_objects(worker_pool_summaries))
    elif ARGS_PARSER.details:
        print_yd_object_list(
            [
                (
                    CLIENT.worker_pool_client.get_worker_pool_by_id(
                        worker_pool_summary.id  # type: ignore[arg-type]
                    ),
                    None,
                )
                for worker_pool_summary in select(CLIENT, worker_pool_summaries)
            ]
        )
    elif ARGS_PARSER.ids_only:
        for wp_summary in worker_pool_summaries:
            print(wp_summary.id)
    else:
        print_numbered_object_list(CLIENT, sorted_objects(worker_pool_summaries))


def list_compute_requirements():
    if ARGS_PARSER.active_only:
        print_info("Listing active Compute Requirements only")
        included_statuses = [
            ComputeRequirementStatus.NEW,
            ComputeRequirementStatus.STARTING,
            ComputeRequirementStatus.RUNNING,
            ComputeRequirementStatus.STOPPING,
            ComputeRequirementStatus.STOPPED,
            ComputeRequirementStatus.TERMINATING,
        ]
    else:
        included_statuses = None

    compute_requirement_summaries: list[ComputeRequirementSummary]
    if ARGS_PARSER.name_glob:
        namespace, name = resolve_name_glob(
            ARGS_PARSER.name_glob, CONFIG_COMMON.namespace
        )
        print_info(
            f"Listing Compute Requirements in namespace '{namespace}' "
            f"matching name pattern '{name}'"
        )
        compute_requirement_summaries = filter_summaries_by_name_glob(
            get_compute_requirement_summaries(
                CLIENT,
                namespace,
                None,
                included_statuses,
                name=glob_search_prefix(name) or None,
            ),
            name,
        )
    else:
        print_info(
            "Listing Compute Requirements in "
            f"namespace '{CONFIG_COMMON.namespace}' with "
            f" names containing '{CONFIG_COMMON.name_tag}'"
        )
        compute_requirement_summaries = get_compute_requirement_summaries(
            CLIENT, CONFIG_COMMON.namespace, CONFIG_COMMON.name_tag, included_statuses
        )

    if not compute_requirement_summaries:
        _print_empty("No matching Compute Requirements")
        return

    compute_requirement_summaries = _apply_status_filter(
        sorted_objects(compute_requirement_summaries)
    )
    if not compute_requirement_summaries:
        _print_empty("No matching Compute Requirements")
        return

    if ARGS_PARSER.entity_type == ET_INSTANCES:
        if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
            all_instances: list = []
            for cr_summary in compute_requirement_summaries:
                sc: SearchClient = CLIENT.compute_client.get_instances(
                    instance_search=InstanceSearch(computeRequirementId=cr_summary.id)
                )
                all_instances.extend(sc.list_all())
            _print_json_or_count(all_instances)
            return
        for compute_requirement_summary in select(
            CLIENT, compute_requirement_summaries, single_result=True
        ):
            list_instances(compute_requirement_summary.id)  # type: ignore[arg-type]
        return

    if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
        _print_json_or_count(compute_requirement_summaries)
    elif ARGS_PARSER.details:
        print_yd_object_list(
            [
                (compute_requirement, None)
                for compute_requirement in select(CLIENT, compute_requirement_summaries)
            ]
        )
    elif ARGS_PARSER.ids_only:
        for compute_requirement_summary in compute_requirement_summaries:
            print(compute_requirement_summary.id)
    else:
        print_numbered_object_list(CLIENT, compute_requirement_summaries)


def list_instances(compute_requirement_id: str):
    """
    List the instances within a Compute Requirement.
    """
    instance_search = InstanceSearch(computeRequirementId=compute_requirement_id)
    search_client: SearchClient = CLIENT.compute_client.get_instances(
        instance_search=instance_search
    )
    instances: list[Instance] = search_client.list_all()
    if not instances:
        print_info("No instances to list")
        return

    if ARGS_PARSER.public_ips_only:
        print_info("Listing public IP addresses only:")
        for instance in instances:
            try:
                if instance.publicIpAddress is not None:
                    print(instance.publicIpAddress)
            except Exception:
                pass
        return

    if ARGS_PARSER.details:
        print_yd_object_list(
            [(instance, None) for instance in select(CLIENT, instances)]
        )
    elif ARGS_PARSER.ids_only:
        for instance in instances:
            print(instance.id.instanceId)  # type: ignore[union-attr]
    else:
        print_numbered_object_list(CLIENT, instances)


def list_nodes(worker_pool_summaries: list[WorkerPoolSummary]):
    """
    List the Nodes in a list of Worker Pools.
    """
    nodes_all: list[Node] = []
    for worker_pool_summary in worker_pool_summaries:
        nodes_search = NodeSearch(
            worker_pool_summary.id,
            statuses=[NodeStatus.RUNNING] if ARGS_PARSER.active_only else None,
        )
        search_client = CLIENT.worker_pool_client.get_nodes(search=nodes_search)
        nodes: list[Node] = search_client.list_all()
        for node in nodes:
            node.workerPoolName = worker_pool_summary.name  # type: ignore[attr-defined]
        nodes_all += nodes

    nodes_all = _apply_status_filter(nodes_all)
    if not nodes_all:
        _print_empty("No Nodes to display")
        return

    if ARGS_PARSER.entity_type == ET_WORKERS:
        list_workers(nodes_all)
        return

    if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
        _print_json_or_count(nodes_all)
    elif ARGS_PARSER.details:
        print_yd_object_list([(node, None) for node in select(CLIENT, nodes_all)])
    elif ARGS_PARSER.ids_only:
        for node in nodes_all:
            print(node.id)
    else:
        print_numbered_object_list(CLIENT, nodes_all)


def list_workers(nodes: list[Node]):
    """
    Display a list of workers across all nodes in a worker pool.
    """
    workers_all: list[Worker] = []
    for node in nodes:
        for worker in node.workers or []:
            if ARGS_PARSER.active_only:
                if worker.status not in [
                    WorkerStatus.SLEEPING,
                    WorkerStatus.DOING_TASK,
                    WorkerStatus.STOPPED,
                    WorkerStatus.STARTING,
                ]:
                    continue
            # Add extra info to the Worker object
            if node.details is not None:
                worker.workerTag = node.details.workerTag  # type: ignore[attr-defined]
                worker.taskTypes = node.details.supportedTaskTypes  # type: ignore[attr-defined]
                worker.workerPoolName = (  # type: ignore[attr-defined]
                    node.workerPoolName  # type: ignore[attr-defined]
                )  # This property is added by the caller
                workers_all.append(worker)

    workers_all = _apply_status_filter(workers_all)
    if not workers_all:
        _print_empty("No Workers to display")
        return

    if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
        _print_json_or_count(workers_all)
    elif ARGS_PARSER.details:
        print_yd_object_list([(worker, None) for worker in select(CLIENT, workers_all)])
    elif ARGS_PARSER.ids_only:
        for worker in workers_all:
            print(worker.id)
    else:
        print_numbered_object_list(CLIENT, workers_all)


def list_compute_requirement_templates():
    """
    Print the list of Compute Requirement Templates, filtered on Namespace
    and Name. Set these both to empty strings to generate an unfiltered list.
    """
    print_info(
        "Listing Compute Requirement Templates in namespace "
        f"'{CONFIG_COMMON.namespace}' with names including "
        f"'{CONFIG_COMMON.name_tag}'"
    )

    cr_templates: list[ComputeRequirementTemplateSummary] = (
        get_compute_requirement_templates(
            CLIENT,
            CONFIG_COMMON.namespace,
            CONFIG_COMMON.name_tag,
            partial_name_matches=True,
        )
    )

    if not cr_templates:
        _print_empty("No matching Compute Requirement Templates found")
        return

    if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
        if ARGS_PARSER.details:
            print_objects_as_json(
                [
                    substitute_ids_for_names_in_crt(
                        CLIENT,
                        CLIENT.compute_client.get_compute_requirement_template(crt.id),  # type: ignore[arg-type]
                    )
                    for crt in sorted_objects(cr_templates)
                ]
            )
        else:
            _print_json_or_count(sorted_objects(cr_templates))
        return

    if ARGS_PARSER.ids_only:
        for crt in cr_templates:
            print(crt.id)
        return

    if not ARGS_PARSER.details:
        print_numbered_object_list(CLIENT, sorted_objects(cr_templates))
        return

    # Show details
    cr_templates = select(CLIENT, cr_templates)
    if cr_templates and ARGS_PARSER.substitute_ids:
        print_info(
            "Substituting Compute Source Template IDs and Image Family IDs with names"
        )
    cr_template_details = [
        (
            substitute_ids_for_names_in_crt(
                CLIENT,
                CLIENT.compute_client.get_compute_requirement_template(cr_template.id),  # type: ignore[arg-type]
            ),
            {PROP_RESOURCE: RN_REQUIREMENT_TEMPLATE},
        )
        for cr_template in cr_templates
    ]
    print_yd_object_list(
        cr_template_details,  # type: ignore[arg-type]
    )


def list_compute_source_templates():
    """
    Print the list of Compute Source Templates, filtered on Namespace
    and Name. Set these both to empty strings to generate an unfiltered list.
    """

    print_info(
        "Listing Compute Source Templates in namespace "
        f"'{CONFIG_COMMON.namespace}' with names including "
        f"'{CONFIG_COMMON.name_tag}'"
    )

    cs_templates = get_compute_source_templates(
        CLIENT, namespace=CONFIG_COMMON.namespace, name=CONFIG_COMMON.name_tag
    )

    if not cs_templates:
        _print_empty("No matching Compute Source Templates found")
        return

    if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
        if ARGS_PARSER.details:
            print_objects_as_json(
                [
                    substitute_image_family_id_for_name_in_cst(
                        CLIENT,
                        CLIENT.compute_client.get_compute_source_template(cst.id),  # type: ignore[arg-type]
                    )
                    for cst in sorted_objects(cs_templates)
                ]
            )
        else:
            _print_json_or_count(sorted_objects(cs_templates))
        return

    if ARGS_PARSER.ids_only:
        for cst in cs_templates:
            print(cst.id)
        return

    if not ARGS_PARSER.details:
        print_numbered_object_list(CLIENT, sorted_objects(cs_templates))
        return

    # Show details
    cs_templates = select(CLIENT, sorted_objects(cs_templates))
    cs_template_details = [
        (
            substitute_image_family_id_for_name_in_cst(
                CLIENT,
                CLIENT.compute_client.get_compute_source_template(cs_template.id),  # type: ignore[arg-type]
            ),
            {PROP_RESOURCE: RN_SOURCE_TEMPLATE},
        )
        for cs_template in cs_templates
    ]
    print_yd_object_list(
        cs_template_details,  # type: ignore[arg-type]
    )


def list_keyrings():
    """
    Print the list of Keyrings
    """
    keyrings: list[KeyringSummary] = CLIENT.keyring_client.find_all_keyrings()
    if not keyrings:
        _print_empty("No Keyrings found")
        return

    if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
        _print_json_or_count(sorted_objects(keyrings))
        return

    if ARGS_PARSER.ids_only:
        for keyring in keyrings:
            print(keyring.id)
        return

    if not ARGS_PARSER.details:
        print_numbered_object_list(CLIENT, sorted_objects(keyrings))
        return

    # Show details
    print_yd_object_list(
        [(keyring, {PROP_RESOURCE: RN_KEYRING}) for keyring in select(CLIENT, keyrings)]
    )


def get_keyring(name: str) -> Keyring:
    """
    Temporary function in place of a missing KeyringClient SDK call.
    """
    response = get(
        url=f"{CONFIG_COMMON.url}/keyrings/{name}",
        headers={"Authorization": f"yd-key {CONFIG_COMMON.key}:{CONFIG_COMMON.secret}"},
    )
    if response.status_code == 200:
        return Json.load(response.json(), Keyring)
    else:
        raise RuntimeError(f"Failed to get Keyring '{name}' ({response.text})")


def list_image_families():
    """
    List the Machine Image Families.
    """
    image_search = MachineImageFamilySearch(
        includePublic=True,
        namespaces=(
            None if CONFIG_COMMON.namespace == "" else [CONFIG_COMMON.namespace]
        ),
        familyName=CONFIG_COMMON.name_tag,  # Supports partial match
    )
    search_client: SearchClient = CLIENT.images_client.get_image_families(image_search)
    image_family_summaries: list[MachineImageFamilySummary] = search_client.list_all()
    if not image_family_summaries:
        _print_empty(
            f"No matching Machine Image Families found in namespace "
            f"'{CONFIG_COMMON.namespace}' with tag including '{CONFIG_COMMON.name_tag}'"
        )
        return

    if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
        if ARGS_PARSER.details:
            print_objects_as_json(
                [
                    CLIENT.images_client.get_image_family_by_id(ifs.id)  # type: ignore[arg-type]
                    for ifs in sorted_objects(image_family_summaries)
                ]
            )
        else:
            _print_json_or_count(sorted_objects(image_family_summaries))
        return

    if ARGS_PARSER.ids_only:
        for image_family in image_family_summaries:
            print(image_family.id)
        return

    if not ARGS_PARSER.details:
        print_numbered_object_list(CLIENT, sorted_objects(image_family_summaries))
        return

    # Show details
    image_family_summaries = select(CLIENT, sorted_objects(image_family_summaries))
    image_families = [
        (
            CLIENT.images_client.get_image_family_by_id(image_family_summary.id),  # type: ignore[arg-type]
            {PROP_RESOURCE: RN_IMAGE_FAMILY},
        )
        for image_family_summary in image_family_summaries
    ]
    print_yd_object_list(
        image_families,  # type: ignore[arg-type]
    )


def list_allowances():
    """
    List allowances.
    """
    allowances_search = AllowanceSearch()
    search_client: SearchClient = CLIENT.allowances_client.get_allowances(
        allowances_search
    )
    allowances: list[Allowance] = search_client.list_all()
    if not allowances:
        _print_empty("No Allowances to display")
        return

    if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
        if ARGS_PARSER.details:
            print_objects_as_json(
                [
                    substitute_id_for_name_in_allowance(CLIENT, a)  # type: ignore[arg-type]
                    for a in allowances
                ]
            )
        else:
            _print_json_or_count(allowances)
        return

    if ARGS_PARSER.ids_only:
        for allowance in allowances:
            print(allowance.id)
        return

    if not ARGS_PARSER.details:
        print_numbered_object_list(CLIENT, allowances)
        return

    # Show details
    if allowances and ARGS_PARSER.substitute_ids:
        print_info(
            "Substituting Compute Requirement Template IDs with names (if applicable)"
        )
    print_yd_object_list(
        [
            (
                substitute_id_for_name_in_allowance(CLIENT, allowance),  # type: ignore[arg-type]
                {PROP_RESOURCE: RN_ALLOWANCE},
            )
            for allowance in select(CLIENT, allowances)
        ]
    )


def list_attribute_definitions():
    """
    List user compute attribute definitions using the API.
    """
    response = get(
        url=f"{CONFIG_COMMON.url}/compute/attributes/user",
        headers={"Authorization": f"yd-key {CONFIG_COMMON.key}:{CONFIG_COMMON.secret}"},
    )

    if response.status_code != 200:
        raise RuntimeError(
            "Unable to list user attribute definitions: HTTP "
            f"{response.status_code} ({response.text})"
        )

    attribute_definition_list = json_loads(response.text)
    attribute_definition_list.sort(key=lambda x: x["name"])

    if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
        _print_json_or_count(attribute_definition_list)
        return

    if ARGS_PARSER.ids_only:
        print_warning(
            "'--ids-only' is not supported for Attribute Definitions"
            " (they have no YellowDog IDs)"
        )
        return

    if not ARGS_PARSER.details:
        print_numbered_object_list(
            CLIENT, attribute_definition_list, object_type_name="Attribute Definition"
        )
        return

    # Show details
    attribute_definition_list = [
        (
            attribute,
            {
                PROP_RESOURCE: (
                    RN_NUMERIC_ATTRIBUTE_DEFINITION
                    if "Numeric" in attribute["type"]
                    else RN_STRING_ATTRIBUTE_DEFINITION
                )
            },
        )
        for attribute in select(
            CLIENT,
            attribute_definition_list,
            object_type_name="Attribute Definition",
            sort_objects=False,
        )
    ]
    print_yd_object_list(attribute_definition_list)  # type: ignore[arg-type]


def list_namespaces():
    """
    List namespaces.
    """

    namespaces: list[Namespace] = CLIENT.namespaces_client.get_namespaces(
        NamespaceSearch()
    ).list_all()

    if not namespaces:
        _print_empty("No Namespaces found")
        return

    if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
        _print_json_or_count(namespaces)
        return

    if ARGS_PARSER.ids_only:
        for namespace in namespaces:
            print(namespace.id)
        return

    if not ARGS_PARSER.details:
        print_numbered_object_list(CLIENT, namespaces)
        return

    print_yd_object_list(
        [
            (namespace, {PROP_RESOURCE: RN_NAMESPACE})
            for namespace in select(CLIENT, namespaces)
        ]
    )


def list_namespace_policies():
    """
    List namespace policies.
    """

    np_search = NamespacePolicySearch()
    search_client: SearchClient = CLIENT.namespaces_client.get_namespace_policies(
        np_search
    )
    namespace_policies: list[NamespacePolicy] = search_client.list_all()
    if not namespace_policies:
        _print_empty("No Namespace Policies to display")
        return

    if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
        _print_json_or_count(namespace_policies)
        return

    if ARGS_PARSER.ids_only:
        print_warning(
            "'--ids-only' is not supported for Namespace Policies"
            " (they have no YellowDog IDs)"
        )
        return

    if not ARGS_PARSER.details:
        print_numbered_object_list(CLIENT, namespace_policies)
        return

    for selected_namespace_policy in select(
        CLIENT, namespace_policies, object_type_name="Namespace Policy"
    ):
        if selected_namespace_policy.autoscalingMaxNodes is None:
            print_yd_object(selected_namespace_policy)
        else:
            details = get_autoscaling_capacity(selected_namespace_policy.namespace)
            details["autoscalingMaxNodes"] = (
                selected_namespace_policy.autoscalingMaxNodes
            )
            print_json(details)


def list_users():
    """
    List all users in the account.
    """
    users: list[User] = get_all_users(CLIENT)

    if not users:
        _print_empty("No Users to display")
        return

    users.sort(key=lambda user: user.name)

    if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
        _print_json_or_count(users)
        return

    if ARGS_PARSER.ids_only:
        for user in users:
            print(user.id)
        return

    if not ARGS_PARSER.details:
        print_numbered_object_list(CLIENT, users, object_type_name="User")
        return

    # Add the list of groups to the user details
    print_yd_object_list(
        [
            (
                user,
                {
                    PROP_GROUPS: [
                        group.name
                        for group in get_user_groups(CLIENT, user.id)  # type: ignore[arg-type]
                    ],
                    PROP_RESOURCE: user.__class__.__name__,
                },
            )
            for user in select(CLIENT, users)
        ]
    )


def list_applications():
    """
    List all applications in the account.
    """
    applications = get_all_applications(CLIENT)

    if not applications:
        _print_empty("No Applications to display")
        return

    applications.sort(key=lambda app: app.name)

    if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
        _print_json_or_count(applications)
        return

    if ARGS_PARSER.ids_only:
        for application in applications:
            print(application.id)
        return

    if not ARGS_PARSER.details:
        print_numbered_object_list(CLIENT, applications, object_type_name="Application")
        return

    # Add the list of group names for each application
    print_yd_object_list(
        [
            (
                application,
                {
                    PROP_GROUPS: [
                        group.name
                        for group in get_application_group_summaries(
                            CLIENT, application.id
                        )
                    ],
                    PROP_RESOURCE: RN_APPLICATION,
                },
            )
            for application in select(CLIENT, applications)
        ]
    )


def list_groups():
    """
    List all groups in the account.
    """
    group_summaries = get_all_groups(CLIENT)

    if not group_summaries:
        _print_empty("No Groups to display")
        return

    group_summaries.sort(key=lambda group: group.name if group.name is not None else "")  # type: ignore[arg-type]

    if ARGS_PARSER.count_only:
        # Avoid the per-group detail fetches below just to count them
        print(len(group_summaries))
        return

    groups: list[Group] = [
        CLIENT.account_client.get_group(group.id)  # type: ignore[arg-type]
        for group in group_summaries
    ]

    if ARGS_PARSER.json_output:
        print_objects_as_json(groups)
        return

    if ARGS_PARSER.ids_only:
        for group in groups:
            print(group.id)
        return

    if not ARGS_PARSER.details:
        print_numbered_object_list(CLIENT, groups, object_type_name="Group")
        return

    selected_groups = select(CLIENT, groups)

    print_yd_object_list(
        [(group, {PROP_RESOURCE: RN_GROUP}) for group in selected_groups]
    )


def list_roles():
    """
    List all roles in the account.
    """
    role_summaries = get_all_roles(CLIENT)

    if not role_summaries:
        _print_empty("No Roles to display")
        return

    role_summaries.sort(key=lambda role_: role_.name if role_.name is not None else "")

    if ARGS_PARSER.count_only:
        # Avoid the per-role permission fetches below just to count them
        print(len(role_summaries))
        return

    print_info("Obtaining permissions for each role ...")
    roles: list[Role] = [CLIENT.account_client.get_role(x.id) for x in role_summaries]  # type: ignore[arg-type]

    # Sort permissions alphabetically (contorting the type)
    for role in roles:
        role.permissions = list(role.permissions)
        role.permissions.sort(key=lambda permission: permission.name)

    if ARGS_PARSER.json_output:
        print_objects_as_json(roles)
        return

    if ARGS_PARSER.ids_only:
        for role in roles:
            print(role.id)
        return

    if not ARGS_PARSER.details:
        print_numbered_object_list(CLIENT, roles, object_type_name="Role")
        return

    print_yd_object_list(
        [(role, {PROP_RESOURCE: RN_ROLE}) for role in select(CLIENT, roles)]
    )


def list_permissions():
    """
    List all permissions in the account.
    """
    permissions: list[PermissionDetail] = CLIENT.account_client.list_permissions()
    permissions.sort(key=lambda permission_: permission_.name)  # type: ignore[arg-type]

    if ARGS_PARSER.json_output or ARGS_PARSER.count_only:
        _print_json_or_count(permissions)
        return

    if ARGS_PARSER.ids_only:
        print_warning(
            "'--ids-only' is not supported for Permissions (they have no YellowDog IDs)"
        )
        return

    if not ARGS_PARSER.details:
        print_numbered_object_list(CLIENT, permissions, object_type_name="Permission")
        return

    for permission in select(CLIENT, permissions, object_type_name="Permission"):
        print_yd_object(permission)


def get_autoscaling_capacity(namespace: str) -> dict:
    """
    Get the current autoscaling values for a namespace.
    """
    response = get(
        url=f"{CONFIG_COMMON.url}/workerPools/namespaces/{namespace}/autoscalingCapacity",
        headers={"Authorization": f"yd-key {CONFIG_COMMON.key}:{CONFIG_COMMON.secret}"},
    )
    if response.status_code == 200:
        return response.json()
    else:
        print_warning(
            f"Failed to get autoscaling details for namespace '{namespace}' ({response.text})"
        )
        return {"namespace": namespace}


# Entry point
if __name__ == "__main__":
    main()
