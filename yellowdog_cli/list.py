#!/usr/bin/env python3

"""
Command to list YellowDog entities.
"""

from collections.abc import Callable
from json import loads as json_loads
from os.path import exists
from typing import Any, cast

from requests import HTTPError, get
from yellowdog_client.common import SearchClient
from yellowdog_client.model import (
    Allowance,
    AllowanceSearch,
    ComputeRequirementStatus,
    ComputeRequirementSummary,
    ComputeRequirementTemplateSummary,
    Group,
    Instance,
    InstanceSearch,
    InstanceStatus,
    KeyringSearch,
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

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
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
    search_namespaces,
    substitute_id_for_name_in_allowance,
    substitute_ids_for_names_in_crt,
    substitute_image_family_id_for_name_in_cst,
)
from yellowdog_cli.utils.glob_utils import glob_search_prefix
from yellowdog_cli.utils.interactive import confirmed, select
from yellowdog_cli.utils.limits import RAW_REQUEST_TIMEOUT
from yellowdog_cli.utils.output_settings import configure_output
from yellowdog_cli.utils.printing import (
    print_info,
    print_json,
    print_objects_as_json,
    print_warning,
    print_yd_object,
    print_yd_object_list,
)
from yellowdog_cli.utils.property_names import PROP_GROUPS, PROP_RESOURCE
from yellowdog_cli.utils.tables import print_numbered_object_list, sorted_objects
from yellowdog_cli.utils.wrapper import main_wrapper


def _filter_by_name_glob_with_warning(
    objects: list, pattern: str, entity_label: str
) -> list:
    """
    Filter account-global entities by a name glob (client-side, exact-glob on
    '.name'). Warn when entries without a name are excluded — their name is
    optional, so a name pattern can never match them, and dropping them
    silently would understate the result.
    """
    unnamed = sum(1 for obj in objects if getattr(obj, "name", None) is None)
    if unnamed:
        print_warning(
            f"{unnamed} {entity_label}(s) have no name and are excluded from "
            "'--name' pattern matching"
        )
    return filter_summaries_by_name_glob(objects, pattern)


_KNOWN_STATUSES: dict[str, frozenset[str]] = {
    ET_WORK_REQUIREMENTS: frozenset(e.value for e in WorkRequirementStatus),
    ET_TASK_GROUPS: frozenset(e.value for e in TaskGroupStatus),
    ET_TASKS: frozenset(e.value for e in TaskStatus),
    ET_WORKER_POOLS: frozenset(e.value for e in WorkerPoolStatus),
    ET_NODES: frozenset(e.value for e in NodeStatus),
    ET_WORKERS: frozenset(e.value for e in WorkerStatus),
    ET_COMPUTE_REQUIREMENTS: frozenset(e.value for e in ComputeRequirementStatus),
    ET_INSTANCES: frozenset(e.value for e in InstanceStatus),
}


def _apply_count_option(ctx: RunContext) -> None:
    """
    The '--count' option implies '--quiet' and prints only the number of
    matching items, overriding the '--details', '--json' and '--ids-only'
    output options.
    """
    if not ctx.args.count_only:
        return
    ctx.args.quiet = True
    ctx.args.json_output = False
    ctx.args.details = False
    ctx.args.ids_only = False


def _print_json_or_count(ctx: RunContext, objects: list) -> None:
    """
    Final output for the non-interactive aggregate modes: the item count
    for '--count', otherwise a JSON array for '--json'.
    """
    if ctx.args.count_only:
        print(len(objects))
    else:
        print_objects_as_json(objects)


def _listing_all(ctx: RunContext) -> bool:
    """
    The non-interactive modes, which list every matching entity, the
    children of every matching parent included, without asking which:
    '--json', '--count' and '--ids-only'.
    """
    return bool(ctx.args.json_output or ctx.args.count_only or ctx.args.ids_only)


def _print_all(
    ctx: RunContext, objects: list, id_of: Callable[[Any], object] | None = None
) -> None:
    """
    Final output for the non-interactive modes: the IDs for '--ids-only'
    ('id_of' gives an entity's, its 'id' by default), otherwise as
    _print_json_or_count().
    """
    if ctx.args.ids_only:
        for obj in objects:
            print(obj.id if id_of is None else id_of(obj))
    else:
        _print_json_or_count(ctx, objects)


def _print_empty(ctx: RunContext, message: str) -> None:
    """
    Report an empty result: '0' in count mode, otherwise an info message.
    """
    if ctx.args.count_only:
        print(0)
    else:
        print_info(message)


def _apply_status_filter(ctx: RunContext, objects: list) -> list:
    """
    Filter a list of objects to those whose status matches ctx.args.status_filter.
    """
    sf = ctx.args.status_filter
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
def main(ctx: RunContext):
    _apply_count_option(ctx)

    if not (ctx.args.json_output or ctx.args.count_only):
        ctx.args.interactive = True
    # Output follows the options as adjusted: '--count' is quiet
    configure_output(ctx.args)

    if (
        (
            ctx.args.auto_select_all
            or ctx.args.strip_ids
            or ctx.args.substitute_ids
            or ctx.args.output_file
        )
        and not ctx.args.details
        and not ctx.args.count_only
    ):
        print_info("Automatically setting the '--details' option")
        ctx.args.details = True

    if ctx.args.details and ctx.args.strip_ids:
        print_info("Stripping YellowDog IDs (etc.) from detailed JSON objects")

    # ... and '--details' as set here
    configure_output(ctx.args)

    if ctx.args.output_file and ctx.args.details:
        if exists(ctx.args.output_file):
            if not confirmed(
                f"Overwrite file '{ctx.args.output_file}' with new resource details?"
            ):
                return

    entity_type = ctx.args.entity_type

    if sf := ctx.args.status_filter:
        known = _KNOWN_STATUSES.get(entity_type or "", frozenset())
        if known:
            unknown = [s for s in sf if s.upper() not in known]
            if unknown:
                print_warning(
                    f"Unrecognised status value(s): {', '.join(repr(s) for s in unknown)}. "
                    f"Known values: {', '.join(sorted(known))}"
                )

    # An option that does not apply to the entity type has been refused as
    # the command line was parsed ('check_list_options' in the registry)
    if entity_type in (ET_WORK_REQUIREMENTS, ET_TASK_GROUPS, ET_TASKS):
        list_work_requirements(ctx)
    elif entity_type in (ET_WORKER_POOLS, ET_NODES, ET_WORKERS):
        list_worker_pools(ctx)
    elif entity_type in (ET_COMPUTE_REQUIREMENTS, ET_INSTANCES):
        list_compute_requirements(ctx)
    elif entity_type == ET_COMPUTE_REQUIREMENT_TEMPLATES:
        list_compute_requirement_templates(ctx)
    elif entity_type == ET_COMPUTE_SOURCE_TEMPLATES:
        list_compute_source_templates(ctx)
    elif entity_type == ET_KEYRINGS:
        list_keyrings(ctx)
    elif entity_type == ET_IMAGE_FAMILIES:
        list_image_families(ctx)
    elif entity_type == ET_ALLOWANCES:
        list_allowances(ctx)
    elif entity_type == ET_ATTRIBUTE_DEFINITIONS:
        list_attribute_definitions(ctx)
    elif entity_type == ET_NAMESPACES:
        list_namespaces(ctx)
    elif entity_type == ET_NAMESPACE_POLICIES:
        list_namespace_policies(ctx)
    elif entity_type == ET_USERS:
        list_users(ctx)
    elif entity_type == ET_APPLICATIONS:
        list_applications(ctx)
    elif entity_type == ET_GROUPS:
        list_groups(ctx)
    elif entity_type == ET_ROLES:
        list_roles(ctx)
    elif entity_type == ET_PERMISSIONS:
        list_permissions(ctx)


def list_work_requirements(ctx: RunContext):
    """
    List Work Requirements whenever --work-requirements, --task-groups or
    --tasks are selected.

    This function falls through from WRs to TGs to Tasks, depending on the
    options chosen.
    """
    if ctx.args.active_only:
        print_info("Listing active Work Requirements only")

    exclude_filter = (
        [
            WorkRequirementStatus.COMPLETED,
            WorkRequirementStatus.CANCELLED,
            WorkRequirementStatus.FAILED,
        ]
        if ctx.args.active_only
        else []
    )
    work_requirement_summaries: list[WorkRequirementSummary]
    if ctx.args.name_glob:
        namespace, name = resolve_name_glob(ctx.args.name_glob, ctx.config.namespace)
        print_info(
            f"Listing Work Requirements in namespace '{namespace}' "
            f"matching name pattern '{name}'"
        )
        work_requirement_summaries = filter_summaries_by_name_glob(
            get_filtered_work_requirement_summaries(
                ctx.client,
                name=glob_search_prefix(name) or None,
                namespace=namespace,
                exclude_filter=exclude_filter,
            ),
            name,
        )
    else:
        print_info(
            f"Listing Work Requirements in namespace '{ctx.config.namespace}' "
            f"with '{ctx.config.name_tag}' in tag",
        )
        work_requirement_summaries = get_filtered_work_requirement_summaries(
            ctx.client,
            namespace=ctx.config.namespace,
            tag=ctx.config.name_tag,
            exclude_filter=exclude_filter,
        )
    if not work_requirement_summaries:
        _print_empty(ctx, "No matching Work Requirements")
        return

    work_requirement_summaries = sorted_objects(work_requirement_summaries)
    if ctx.args.entity_type == ET_WORK_REQUIREMENTS:
        work_requirement_summaries = _apply_status_filter(
            ctx, work_requirement_summaries
        )
        if not work_requirement_summaries:
            _print_empty(ctx, "No matching Work Requirements")
            return
        if ctx.args.json_output or ctx.args.count_only:
            if ctx.args.details:
                print_objects_as_json(
                    [
                        ctx.client.work_client.get_work_requirement_by_id(
                            cast(str, wr.id)
                        )
                        for wr in work_requirement_summaries
                    ]
                )
            else:
                _print_json_or_count(ctx, work_requirement_summaries)
        elif ctx.args.details:
            print_yd_object_list(
                [
                    (
                        ctx.client.work_client.get_work_requirement_by_id(
                            cast(str, wr_summary.id)
                        ),
                        None,
                    )  # type: ignore[arg-type]
                    for wr_summary in select(ctx.client, work_requirement_summaries)
                ]
            )
        elif ctx.args.ids_only:
            for wr_summary in work_requirement_summaries:
                print(wr_summary.id)
        else:
            print_numbered_object_list(ctx.client, work_requirement_summaries)
    elif _listing_all(ctx):
        # Collect all task groups / tasks across all work requirements
        all_objects: list = []
        for work_summary in work_requirement_summaries:
            tgs = sorted_objects(
                get_task_groups_from_wr_by_id(ctx.client, cast(str, work_summary.id))
            )
            if ctx.args.entity_type == ET_TASK_GROUPS:
                all_objects.extend(_apply_status_filter(ctx, tgs))
            else:
                for tg in tgs:
                    all_objects.extend(
                        _apply_status_filter(
                            ctx,
                            get_all_tasks_in_task_group(ctx.client, cast(str, tg.id)),
                        )
                    )
        _print_all(ctx, all_objects)
    else:
        selected_work_summaries = select(
            ctx.client, work_requirement_summaries, single_result=True
        )
        for work_summary in selected_work_summaries:
            print_info(f"Work Requirement '{work_summary.name}'")
            list_task_groups(ctx, work_summary)


def list_task_groups(ctx: RunContext, work_summary: WorkRequirementSummary):
    task_groups: list[TaskGroup] = get_task_groups_from_wr_by_id(
        ctx.client, cast(str, work_summary.id)
    )
    task_groups = _apply_status_filter(ctx, sorted_objects(task_groups))
    if ctx.args.entity_type != ET_TASKS:
        if ctx.args.details:
            print_yd_object_list(
                [(task_group, None) for task_group in select(ctx.client, task_groups)]
            )
        elif ctx.args.ids_only:
            for task_group in task_groups:
                print(task_group.id)
        else:
            print_numbered_object_list(ctx.client, task_groups)
    else:
        task_groups = select(ctx.client, task_groups, single_result=True)
        for task_group in task_groups:
            list_tasks(ctx, task_group, work_summary)


def list_tasks(
    ctx: RunContext, task_group: TaskGroup, _work_summary: WorkRequirementSummary
):
    tasks: list[Task] = get_all_tasks_in_task_group(
        ctx.client, cast(str, task_group.id)
    )
    tasks = _apply_status_filter(ctx, sorted_objects(tasks))
    if ctx.args.details:
        print_yd_object_list([(task, None) for task in select(ctx.client, tasks)])
    elif ctx.args.ids_only:
        for task in tasks:
            print(task.id)
    else:
        print_numbered_object_list(ctx.client, tasks)


def list_worker_pools(ctx: RunContext):
    worker_pool_summaries: list[WorkerPoolSummary]
    if ctx.args.name_glob:
        namespace, name = resolve_name_glob(ctx.args.name_glob, ctx.config.namespace)
        print_info(
            f"Displaying Worker Pools in namespace '{namespace}' "
            f"matching name pattern '{name}'"
        )
        searched_namespace = namespace
        worker_pool_summaries = filter_summaries_by_name_glob(
            get_worker_pool_summaries(
                ctx.client,
                namespace,
                glob_search_prefix(name) or None,
                partial_name_matches=True,
            ),
            name,
        )
    else:
        print_info(
            f"Displaying Worker Pools in namespace '{ctx.config.namespace}' "
            f"with '{ctx.config.name_tag}' in name"
        )
        worker_pool_summaries = get_worker_pool_summaries(
            ctx.client,
            ctx.config.namespace,
            ctx.config.name_tag,
            partial_name_matches=True,
        )
        searched_namespace = ctx.config.namespace

    excluded_states = (
        [WorkerPoolStatus.TERMINATED, WorkerPoolStatus.SHUTDOWN]
        if ctx.args.active_only
        else []
    )

    if ctx.args.active_only:
        print_info("Displaying active Worker Pools only")

    # Only the namespace searched, matched exactly: a substring match let
    # 'dev' take in 'dev-team'
    worker_pools = [
        wp_summary
        for wp_summary in worker_pool_summaries
        if wp_summary.status not in excluded_states
        and (not searched_namespace or wp_summary.namespace == searched_namespace)
    ]
    # A Worker Pool's own status filters Worker Pools, not their Nodes or
    # Workers, which are filtered on theirs
    worker_pool_summaries = (
        worker_pools
        if ctx.args.entity_type in (ET_NODES, ET_WORKERS)
        else _apply_status_filter(ctx, worker_pools)
    )

    if not worker_pool_summaries:
        _print_empty(ctx, "No Worker Pools to display")
        return

    if ctx.args.entity_type in (ET_NODES, ET_WORKERS):
        if _listing_all(ctx):
            list_nodes(ctx, worker_pool_summaries)
            return
        print_info(
            "Please select the Worker Pool(s) for which to list "
            f"{'Nodes' if ctx.args.entity_type == ET_NODES else 'Workers'}"
        )
        worker_pool_summaries = cast(
            list[WorkerPoolSummary],
            select(ctx.client, sorted_objects(worker_pool_summaries)),
        )
        list_nodes(ctx, worker_pool_summaries)
        return

    if ctx.args.json_output or ctx.args.count_only:
        if ctx.args.details:
            print_objects_as_json(
                [
                    ctx.client.worker_pool_client.get_worker_pool_by_id(wp.id)  # type: ignore[arg-type]
                    for wp in sorted_objects(worker_pool_summaries)
                ]
            )
        else:
            _print_json_or_count(ctx, sorted_objects(worker_pool_summaries))
    elif ctx.args.details:
        print_yd_object_list(
            [
                (
                    ctx.client.worker_pool_client.get_worker_pool_by_id(
                        worker_pool_summary.id  # type: ignore[arg-type]
                    ),
                    None,
                )
                for worker_pool_summary in select(ctx.client, worker_pool_summaries)
            ]
        )
    elif ctx.args.ids_only:
        for wp_summary in worker_pool_summaries:
            print(wp_summary.id)
    else:
        print_numbered_object_list(ctx.client, sorted_objects(worker_pool_summaries))


def list_compute_requirements(ctx: RunContext):
    if ctx.args.active_only:
        print_info("Listing active Compute Requirements only")
        included_statuses = [
            ComputeRequirementStatus.NEW,
            ComputeRequirementStatus.PROVISIONING,
            ComputeRequirementStatus.STARTING,
            ComputeRequirementStatus.RUNNING,
            ComputeRequirementStatus.STOPPING,
            ComputeRequirementStatus.STOPPED,
            ComputeRequirementStatus.TERMINATING,
        ]
    else:
        included_statuses = None

    compute_requirement_summaries: list[ComputeRequirementSummary]
    if ctx.args.name_glob:
        namespace, name = resolve_name_glob(ctx.args.name_glob, ctx.config.namespace)
        print_info(
            f"Listing Compute Requirements in namespace '{namespace}' "
            f"matching name pattern '{name}'"
        )
        compute_requirement_summaries = filter_summaries_by_name_glob(
            get_compute_requirement_summaries(
                ctx.client,
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
            f"namespace '{ctx.config.namespace}' with "
            f"names containing '{ctx.config.name_tag}'"
        )
        compute_requirement_summaries = get_compute_requirement_summaries(
            ctx.client, ctx.config.namespace, ctx.config.name_tag, included_statuses
        )

    if not compute_requirement_summaries:
        _print_empty(ctx, "No matching Compute Requirements")
        return

    compute_requirement_summaries = sorted_objects(compute_requirement_summaries)
    # A Compute Requirement's own status filters Compute Requirements, not
    # their Instances, which are filtered on theirs
    if ctx.args.entity_type != ET_INSTANCES:
        compute_requirement_summaries = _apply_status_filter(
            ctx, compute_requirement_summaries
        )
    if not compute_requirement_summaries:
        _print_empty(ctx, "No matching Compute Requirements")
        return

    if ctx.args.entity_type == ET_INSTANCES:
        if _listing_all(ctx):
            # Each with its Compute Requirement's ID, for '--ids-only': an
            # Instance is named as 'cr_id.instance_id' by the commands that
            # take one
            all_instances: list[tuple[str, Instance]] = []
            for cr_summary in compute_requirement_summaries:
                sc: SearchClient = ctx.client.compute_client.get_instances(
                    instance_search=InstanceSearch(computeRequirementId=cr_summary.id)
                )
                all_instances.extend(
                    (cast(str, cr_summary.id), instance)
                    for instance in _apply_status_filter(ctx, sc.list_all())
                )
            if ctx.args.ids_only:
                for cr_id, instance in all_instances:
                    print(f"{cr_id}.{instance.id.instanceId}")  # type: ignore[union-attr]
            else:
                _print_json_or_count(ctx, [instance for _, instance in all_instances])
            return
        for compute_requirement_summary in select(
            ctx.client, compute_requirement_summaries, single_result=True
        ):
            list_instances(ctx, compute_requirement_summary.id)  # type: ignore[arg-type]
        return

    if ctx.args.json_output or ctx.args.count_only:
        if ctx.args.details:
            print_objects_as_json(
                [
                    ctx.client.compute_client.get_compute_requirement_by_id(
                        cast(str, cr.id)
                    )
                    for cr in compute_requirement_summaries
                ]
            )
        else:
            _print_json_or_count(ctx, compute_requirement_summaries)
    elif ctx.args.details:
        print_yd_object_list(
            [
                (
                    ctx.client.compute_client.get_compute_requirement_by_id(
                        cast(str, compute_requirement.id)
                    ),
                    None,
                )
                for compute_requirement in select(
                    ctx.client, compute_requirement_summaries
                )
            ]
        )
    elif ctx.args.ids_only:
        for compute_requirement_summary in compute_requirement_summaries:
            print(compute_requirement_summary.id)
    else:
        print_numbered_object_list(ctx.client, compute_requirement_summaries)


def list_instances(ctx: RunContext, compute_requirement_id: str):
    """
    List the instances within a Compute Requirement.
    """
    instance_search = InstanceSearch(computeRequirementId=compute_requirement_id)
    search_client: SearchClient = ctx.client.compute_client.get_instances(
        instance_search=instance_search
    )
    instances: list[Instance] = _apply_status_filter(ctx, search_client.list_all())
    if not instances:
        print_info("No instances to list")
        return

    if ctx.args.public_ips_only:
        print_info("Listing public IP addresses only:")
        for instance in instances:
            if instance.publicIpAddress is not None:
                print(instance.publicIpAddress)
        return

    if ctx.args.details:
        print_yd_object_list(
            [(instance, None) for instance in select(ctx.client, instances)]
        )
    else:
        print_numbered_object_list(ctx.client, instances)


def list_nodes(ctx: RunContext, worker_pool_summaries: list[WorkerPoolSummary]):
    """
    List the Nodes in a list of Worker Pools.
    """
    nodes_all: list[Node] = []
    for worker_pool_summary in worker_pool_summaries:
        nodes_search = NodeSearch(
            worker_pool_summary.id,
            statuses=[NodeStatus.RUNNING] if ctx.args.active_only else None,
        )
        search_client = ctx.client.worker_pool_client.get_nodes(search=nodes_search)
        nodes: list[Node] = search_client.list_all()
        for node in nodes:
            node.workerPoolName = worker_pool_summary.name  # type: ignore[attr-defined]
        nodes_all += nodes

    nodes_all = _apply_status_filter(ctx, nodes_all)
    if not nodes_all:
        _print_empty(ctx, "No Nodes to display")
        return

    if ctx.args.entity_type == ET_WORKERS:
        list_workers(ctx, nodes_all)
        return

    if _listing_all(ctx):
        _print_all(ctx, nodes_all)
    elif ctx.args.details:
        print_yd_object_list([(node, None) for node in select(ctx.client, nodes_all)])
    else:
        print_numbered_object_list(ctx.client, nodes_all)


def list_workers(ctx: RunContext, nodes: list[Node]):
    """
    Display a list of workers across all nodes in a worker pool.
    """
    workers_all: list[Worker] = []
    for node in nodes:
        for worker in node.workers or []:
            if ctx.args.active_only:
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

    workers_all = _apply_status_filter(ctx, workers_all)
    if not workers_all:
        _print_empty(ctx, "No Workers to display")
        return

    if _listing_all(ctx):
        _print_all(ctx, workers_all)
    elif ctx.args.details:
        print_yd_object_list(
            [(worker, None) for worker in select(ctx.client, workers_all)]
        )
    else:
        print_numbered_object_list(ctx.client, workers_all)


def list_compute_requirement_templates(ctx: RunContext):
    """
    Print the list of Compute Requirement Templates, filtered on Namespace
    and Name. Set these both to empty strings to generate an unfiltered list.
    """
    cr_templates: list[ComputeRequirementTemplateSummary]
    if ctx.args.name_glob:
        namespace, name = resolve_name_glob(ctx.args.name_glob, ctx.config.namespace)
        print_info(
            f"Listing Compute Requirement Templates in namespace '{namespace}' "
            f"matching name pattern '{name}'"
        )
        cr_templates = filter_summaries_by_name_glob(
            get_compute_requirement_templates(
                ctx.client,
                namespace,
                glob_search_prefix(name) or None,
                partial_name_matches=True,
            ),
            name,
        )
    else:
        print_info(
            "Listing Compute Requirement Templates in namespace "
            f"'{ctx.config.namespace}' with names including "
            f"'{ctx.config.name_tag}'"
        )
        cr_templates = get_compute_requirement_templates(
            ctx.client,
            ctx.config.namespace,
            ctx.config.name_tag,
            partial_name_matches=True,
        )

    if not cr_templates:
        _print_empty(ctx, "No matching Compute Requirement Templates found")
        return

    if ctx.args.json_output or ctx.args.count_only:
        if ctx.args.details:
            print_objects_as_json(
                [
                    substitute_ids_for_names_in_crt(
                        ctx.client,
                        ctx.client.compute_client.get_compute_requirement_template(
                            cast(str, crt.id)
                        ),
                        substitute=bool(ctx.args.substitute_ids),
                    )
                    for crt in sorted_objects(cr_templates)
                ]
            )
        else:
            _print_json_or_count(ctx, sorted_objects(cr_templates))
        return

    if ctx.args.ids_only:
        for crt in cr_templates:
            print(crt.id)
        return

    if not ctx.args.details:
        print_numbered_object_list(ctx.client, sorted_objects(cr_templates))
        return

    # Show details
    cr_templates = select(ctx.client, cr_templates)
    if cr_templates and ctx.args.substitute_ids:
        print_info(
            "Substituting Compute Source Template IDs and Image Family IDs with names"
        )
    cr_template_details = [
        (
            substitute_ids_for_names_in_crt(
                ctx.client,
                ctx.client.compute_client.get_compute_requirement_template(
                    cast(str, cr_template.id)
                ),
                substitute=bool(ctx.args.substitute_ids),
            ),
            {PROP_RESOURCE: RN_REQUIREMENT_TEMPLATE},
        )
        for cr_template in cr_templates
    ]
    print_yd_object_list(
        cr_template_details,  # type: ignore[arg-type]
    )


def list_compute_source_templates(ctx: RunContext):
    """
    Print the list of Compute Source Templates, filtered on Namespace
    and Name. Set these both to empty strings to generate an unfiltered list.
    """

    if ctx.args.name_glob:
        namespace, name = resolve_name_glob(ctx.args.name_glob, ctx.config.namespace)
        print_info(
            f"Listing Compute Source Templates in namespace '{namespace}' "
            f"matching name pattern '{name}'"
        )
        cs_templates = filter_summaries_by_name_glob(
            get_compute_source_templates(
                ctx.client, namespace=namespace, name=glob_search_prefix(name) or None
            ),
            name,
        )
    else:
        print_info(
            "Listing Compute Source Templates in namespace "
            f"'{ctx.config.namespace}' with names including "
            f"'{ctx.config.name_tag}'"
        )
        cs_templates = get_compute_source_templates(
            ctx.client, namespace=ctx.config.namespace, name=ctx.config.name_tag
        )

    if not cs_templates:
        _print_empty(ctx, "No matching Compute Source Templates found")
        return

    if ctx.args.json_output or ctx.args.count_only:
        if ctx.args.details:
            print_objects_as_json(
                [
                    substitute_image_family_id_for_name_in_cst(
                        ctx.client,
                        ctx.client.compute_client.get_compute_source_template(cst.id),  # type: ignore[arg-type]
                        substitute=bool(ctx.args.substitute_ids),
                    )
                    for cst in sorted_objects(cs_templates)
                ]
            )
        else:
            _print_json_or_count(ctx, sorted_objects(cs_templates))
        return

    if ctx.args.ids_only:
        for cst in cs_templates:
            print(cst.id)
        return

    if not ctx.args.details:
        print_numbered_object_list(ctx.client, sorted_objects(cs_templates))
        return

    # Show details
    cs_templates = select(ctx.client, sorted_objects(cs_templates))
    cs_template_details = [
        (
            substitute_image_family_id_for_name_in_cst(
                ctx.client,
                ctx.client.compute_client.get_compute_source_template(cs_template.id),  # type: ignore[arg-type]
                substitute=bool(ctx.args.substitute_ids),
            ),
            {PROP_RESOURCE: RN_SOURCE_TEMPLATE},
        )
        for cs_template in cs_templates
    ]
    print_yd_object_list(
        cs_template_details,  # type: ignore[arg-type]
    )


def list_keyrings(ctx: RunContext):
    """
    Print the list of Keyrings
    """
    # The server search takes a partial name: the glob's literal prefix
    # narrows it, and the glob itself is applied to what comes back
    search_client: SearchClient = ctx.client.keyring_client.get_keyrings(
        KeyringSearch(
            name=(glob_search_prefix(ctx.args.name_glob) or None)
            if ctx.args.name_glob
            else None
        )
    )
    keyrings: list[KeyringSummary] = search_client.list_all()
    if ctx.args.name_glob:
        keyrings = _filter_by_name_glob_with_warning(
            keyrings, ctx.args.name_glob, "Keyring"
        )
    if not keyrings:
        _print_empty(ctx, "No Keyrings found")
        return

    if ctx.args.json_output or ctx.args.count_only:
        _print_json_or_count(ctx, sorted_objects(keyrings))
        return

    if ctx.args.ids_only:
        for keyring in keyrings:
            print(keyring.id)
        return

    if not ctx.args.details:
        print_numbered_object_list(ctx.client, sorted_objects(keyrings))
        return

    # Show details
    print_yd_object_list(
        [
            (keyring, {PROP_RESOURCE: RN_KEYRING})
            for keyring in select(ctx.client, keyrings)
        ]
    )


def list_image_families(ctx: RunContext):
    """
    List the Machine Image Families.
    """
    image_family_summaries: list[MachineImageFamilySummary]
    if ctx.args.name_glob:
        namespace, name = resolve_name_glob(ctx.args.name_glob, ctx.config.namespace)
        print_info(
            f"Listing Machine Image Families in namespace '{namespace}' "
            f"matching name pattern '{name}'"
        )
        image_search = MachineImageFamilySearch(
            includePublic=True,
            namespaces=search_namespaces(ctx.client, namespace),
            familyName=glob_search_prefix(name) or None,
        )
        search_client: SearchClient = ctx.client.images_client.get_image_families(
            image_search
        )
        image_family_summaries = filter_summaries_by_name_glob(
            search_client.list_all(), name
        )
        if not image_family_summaries:
            _print_empty(
                ctx,
                f"No matching Machine Image Families found in namespace "
                f"'{namespace}' matching name pattern '{name}'",
            )
            return
    else:
        image_search = MachineImageFamilySearch(
            includePublic=True,
            namespaces=search_namespaces(ctx.client, ctx.config.namespace),
            familyName=ctx.config.name_tag,  # Supports partial match
        )
        search_client: SearchClient = ctx.client.images_client.get_image_families(
            image_search
        )
        image_family_summaries = search_client.list_all()
        if not image_family_summaries:
            _print_empty(
                ctx,
                f"No matching Machine Image Families found in namespace "
                f"'{ctx.config.namespace}' with tag including "
                f"'{ctx.config.name_tag}'",
            )
            return

    if ctx.args.json_output or ctx.args.count_only:
        if ctx.args.details:
            print_objects_as_json(
                [
                    ctx.client.images_client.get_image_family_by_id(ifs.id)  # type: ignore[arg-type]
                    for ifs in sorted_objects(image_family_summaries)
                ]
            )
        else:
            _print_json_or_count(ctx, sorted_objects(image_family_summaries))
        return

    if ctx.args.ids_only:
        for image_family in image_family_summaries:
            print(image_family.id)
        return

    if not ctx.args.details:
        print_numbered_object_list(ctx.client, sorted_objects(image_family_summaries))
        return

    # Show details
    image_family_summaries = select(ctx.client, sorted_objects(image_family_summaries))
    image_families = [
        (
            ctx.client.images_client.get_image_family_by_id(image_family_summary.id),  # type: ignore[arg-type]
            {PROP_RESOURCE: RN_IMAGE_FAMILY},
        )
        for image_family_summary in image_family_summaries
    ]
    print_yd_object_list(
        image_families,  # type: ignore[arg-type]
    )


def list_allowances(ctx: RunContext):
    """
    List allowances.
    """
    allowances_search = AllowanceSearch()
    search_client: SearchClient = ctx.client.allowances_client.get_allowances(
        allowances_search
    )
    allowances: list[Allowance] = sorted_objects(search_client.list_all())
    if not allowances:
        _print_empty(ctx, "No Allowances to display")
        return

    if ctx.args.json_output or ctx.args.count_only:
        if ctx.args.details:
            print_objects_as_json(
                [
                    substitute_id_for_name_in_allowance(
                        ctx.client,
                        a,  # type: ignore[arg-type]
                        substitute=bool(ctx.args.substitute_ids),
                    )
                    for a in allowances
                ]
            )
        else:
            _print_json_or_count(ctx, allowances)
        return

    if ctx.args.ids_only:
        for allowance in allowances:
            print(allowance.id)
        return

    if not ctx.args.details:
        print_numbered_object_list(ctx.client, allowances)
        return

    # Show details
    if allowances and ctx.args.substitute_ids:
        print_info(
            "Substituting Compute Requirement Template IDs with names (if applicable)"
        )
    print_yd_object_list(
        [
            (
                substitute_id_for_name_in_allowance(
                    ctx.client,
                    allowance,  # type: ignore[arg-type]
                    substitute=bool(ctx.args.substitute_ids),
                ),
                {PROP_RESOURCE: RN_ALLOWANCE},
            )
            for allowance in select(ctx.client, allowances)
        ]
    )


def list_attribute_definitions(ctx: RunContext):
    """
    List user compute attribute definitions using the API.
    """
    response = get(
        url=f"{ctx.config.url}/compute/attributes/user",
        headers={"Authorization": f"yd-key {ctx.config.key}:{ctx.config.secret}"},
        timeout=RAW_REQUEST_TIMEOUT,
    )

    if response.status_code != 200:
        # An HTTPError carrying the response, so that the exit code names
        # the kind of failure (a 401 exits 4)
        raise HTTPError(
            "Unable to list user attribute definitions: HTTP "
            f"{response.status_code} ({response.text})",
            response=response,
        )

    attribute_definition_list = json_loads(response.text)
    attribute_definition_list.sort(key=lambda x: x["name"])

    if ctx.args.json_output or ctx.args.count_only:
        _print_json_or_count(ctx, attribute_definition_list)
        return

    if not ctx.args.details:
        print_numbered_object_list(
            ctx.client,
            attribute_definition_list,
            object_type_name="Attribute Definition",
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
            ctx.client,
            attribute_definition_list,
            object_type_name="Attribute Definition",
            sort_objects=False,
        )
    ]
    print_yd_object_list(attribute_definition_list)  # type: ignore[arg-type]


def list_namespaces(ctx: RunContext):
    """
    List namespaces.
    """

    namespaces: list[Namespace] = ctx.client.namespaces_client.get_namespaces(
        NamespaceSearch()
    ).list_all()

    if not namespaces:
        _print_empty(ctx, "No Namespaces found")
        return

    if ctx.args.json_output or ctx.args.count_only:
        _print_json_or_count(ctx, namespaces)
        return

    if ctx.args.ids_only:
        for namespace in namespaces:
            print(namespace.id)
        return

    if not ctx.args.details:
        print_numbered_object_list(ctx.client, namespaces)
        return

    print_yd_object_list(
        [
            (namespace, {PROP_RESOURCE: RN_NAMESPACE})
            for namespace in select(ctx.client, namespaces)
        ]
    )


def list_namespace_policies(ctx: RunContext):
    """
    List namespace policies.
    """

    np_search = NamespacePolicySearch(namespaces=search_namespaces(ctx.client, None))
    search_client: SearchClient = ctx.client.namespaces_client.get_namespace_policies(
        np_search
    )
    namespace_policies: list[NamespacePolicy] = search_client.list_all()
    if not namespace_policies:
        _print_empty(ctx, "No Namespace Policies to display")
        return

    if ctx.args.json_output or ctx.args.count_only:
        _print_json_or_count(ctx, namespace_policies)
        return

    if not ctx.args.details:
        print_numbered_object_list(ctx.client, namespace_policies)
        return

    for selected_namespace_policy in select(
        ctx.client, namespace_policies, object_type_name="Namespace Policy"
    ):
        if selected_namespace_policy.autoscalingMaxNodes is None:
            print_yd_object(selected_namespace_policy)
        else:
            details = get_autoscaling_capacity(ctx, selected_namespace_policy.namespace)
            details["autoscalingMaxNodes"] = (
                selected_namespace_policy.autoscalingMaxNodes
            )
            print_json(details)


def list_users(ctx: RunContext):
    """
    List all users in the account.
    """
    users: list[User] = get_all_users(ctx.client)

    if ctx.args.name_glob:
        users = _filter_by_name_glob_with_warning(users, ctx.args.name_glob, "User")

    if not users:
        _print_empty(ctx, "No Users to display")
        return

    users.sort(key=lambda user: user.name or "")

    if ctx.args.json_output or ctx.args.count_only:
        _print_json_or_count(ctx, users)
        return

    if ctx.args.ids_only:
        for user in users:
            print(user.id)
        return

    if not ctx.args.details:
        print_numbered_object_list(ctx.client, users, object_type_name="User")
        return

    # Add the list of groups to the user details
    print_yd_object_list(
        [
            (
                user,
                {
                    PROP_GROUPS: [
                        group.name
                        for group in get_user_groups(ctx.client, user.id)  # type: ignore[arg-type]
                    ],
                    PROP_RESOURCE: user.__class__.__name__,
                },
            )
            for user in select(ctx.client, users)
        ]
    )


def list_applications(ctx: RunContext):
    """
    List all applications in the account.
    """
    applications = get_all_applications(ctx.client)

    if ctx.args.name_glob:
        applications = _filter_by_name_glob_with_warning(
            applications, ctx.args.name_glob, "Application"
        )

    if not applications:
        _print_empty(ctx, "No Applications to display")
        return

    applications.sort(key=lambda app: app.name or "")

    if ctx.args.json_output or ctx.args.count_only:
        _print_json_or_count(ctx, applications)
        return

    if ctx.args.ids_only:
        for application in applications:
            print(application.id)
        return

    if not ctx.args.details:
        print_numbered_object_list(
            ctx.client, applications, object_type_name="Application"
        )
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
                            ctx.client, application.id
                        )
                    ],
                    PROP_RESOURCE: RN_APPLICATION,
                },
            )
            for application in select(ctx.client, applications)
        ]
    )


def list_groups(ctx: RunContext):
    """
    List all groups in the account.
    """
    group_summaries = get_all_groups(ctx.client)

    if ctx.args.name_glob:
        group_summaries = _filter_by_name_glob_with_warning(
            group_summaries, ctx.args.name_glob, "Group"
        )

    if not group_summaries:
        _print_empty(ctx, "No Groups to display")
        return

    group_summaries.sort(key=lambda group: group.name if group.name is not None else "")  # type: ignore[arg-type]

    # The summaries are enough to count the Groups or give their IDs; the
    # table, '--json' and '--details' show each one's roles, which only the
    # Group itself carries, so it is fetched, one call each, only for those
    if ctx.args.count_only:
        print(len(group_summaries))
        return

    if ctx.args.ids_only:
        for group_summary in group_summaries:
            print(group_summary.id)
        return

    groups: list[Group] = [
        ctx.client.account_client.get_group(cast(str, group.id))
        for group in group_summaries
    ]

    if ctx.args.json_output:
        print_objects_as_json(groups)
        return

    if not ctx.args.details:
        print_numbered_object_list(ctx.client, groups, object_type_name="Group")
        return

    print_yd_object_list(
        [(group, {PROP_RESOURCE: RN_GROUP}) for group in select(ctx.client, groups)]
    )


def list_roles(ctx: RunContext):
    """
    List all roles in the account.
    """
    role_summaries = get_all_roles(ctx.client)

    if ctx.args.name_glob:
        role_summaries = _filter_by_name_glob_with_warning(
            role_summaries, ctx.args.name_glob, "Role"
        )

    if not role_summaries:
        _print_empty(ctx, "No Roles to display")
        return

    role_summaries.sort(key=lambda role_: role_.name if role_.name is not None else "")

    # The summaries are enough to count the Roles or give their IDs; the
    # table, '--json' and '--details' show each one's permissions, which only
    # the Role itself carries, so it is fetched, one call each, only for those
    if ctx.args.count_only:
        print(len(role_summaries))
        return

    if ctx.args.ids_only:
        for role_summary in role_summaries:
            print(role_summary.id)
        return

    print_info("Obtaining permissions for each role ...")
    roles: list[Role] = [
        ctx.client.account_client.get_role(cast(str, role.id))
        for role in role_summaries
    ]
    # Sort permissions alphabetically (contorting the type)
    for role in roles:
        role.permissions = list(role.permissions)
        role.permissions.sort(key=lambda permission: permission.name)

    if ctx.args.json_output:
        print_objects_as_json(roles)
        return

    if not ctx.args.details:
        print_numbered_object_list(ctx.client, roles, object_type_name="Role")
        return

    print_yd_object_list(
        [(role, {PROP_RESOURCE: RN_ROLE}) for role in select(ctx.client, roles)]
    )


def list_permissions(ctx: RunContext):
    """
    List all permissions in the account.
    """
    permissions: list[PermissionDetail] = ctx.client.account_client.list_permissions()
    if ctx.args.name_glob:
        permissions = _filter_by_name_glob_with_warning(
            permissions, ctx.args.name_glob, "Permission"
        )
    permissions.sort(key=lambda permission_: permission_.name)  # type: ignore[arg-type]

    if ctx.args.json_output or ctx.args.count_only:
        _print_json_or_count(ctx, permissions)
        return

    if not ctx.args.details:
        print_numbered_object_list(
            ctx.client, permissions, object_type_name="Permission"
        )
        return

    for permission in select(ctx.client, permissions, object_type_name="Permission"):
        print_yd_object(permission)


def get_autoscaling_capacity(ctx: RunContext, namespace: str) -> dict:
    """
    Get the current autoscaling values for a namespace.
    """
    response = get(
        url=f"{ctx.config.url}/workerPools/namespaces/{namespace}/autoscalingCapacity",
        headers={"Authorization": f"yd-key {ctx.config.key}:{ctx.config.secret}"},
        timeout=RAW_REQUEST_TIMEOUT,
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
