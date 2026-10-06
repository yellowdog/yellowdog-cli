"""
Tables: one builder per entity type (headers and rows for tabulate), the
numbered listing and sort order interactive selection and yd-list use, and
printing a table (print_table_core(), plain under '--no-format' or for a
very long table). printing.py holds the message, JSON and object printing
these build on.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, TypeVar

from rich.markup import escape
from tabulate import tabulate

from yellowdog_cli.utils.cloudwizard.aws_types import AWSAvailabilityZone
from yellowdog_cli.utils.output_settings import OUTPUT
from yellowdog_cli.utils.output_style import (
    MAX_LINES_COLOURED_FORMATTING,
    MAX_TABLE_DESCRIPTION,
)
from yellowdog_cli.utils.printing import CONSOLE_TABLE, indent, print_info

if TYPE_CHECKING:
    from yellowdog_client import PlatformClient
    from yellowdog_client.model import (
        Allowance,
        Application,
        ComputeRequirementSummary,
        ComputeRequirementTemplateSummary,
        ComputeRequirementTemplateTestResult,
        ComputeSourceTemplateSummary,
        Group,
        Instance,
        KeyringSummary,
        MachineImageFamilySummary,
        Namespace,
        NamespacePolicy,
        Node,
        NodeAction,
        NodeActionQueueSnapshot,
        PermissionDetail,
        Role,
        Task,
        TaskGroup,
        User,
        Worker,
        WorkerPoolSummary,
        WorkRequirementSummary,
    )

    from yellowdog_cli.utils.items import Item

_T = TypeVar("_T")


# Maps SDK class names (type(obj).__name__) to their human-readable display names.
# Used by get_type_name() below. Instance and Allowance subtypes are handled
# separately via endswith() special cases in that function, as their class names
# vary (e.g. AWSInstance, AccountAllowance).
TYPE_MAP: dict[str, str] = {
    "AWSAvailabilityZone": "AWS Availability Zones",
    "Application": "Application",
    "ComputeRequirement": "Compute Requirement",
    "ComputeRequirementSummary": "Compute Requirement",
    "ComputeRequirementTemplateSummary": "Compute Requirement Template",
    "ComputeSourceTemplateSummary": "Compute Source Template",
    "ConfiguredWorkerPool": "Configured Worker Pool",
    "Group": "Group",
    "KeyringSummary": "Keyring",
    "MachineImageFamilySummary": "Machine Image Family",
    "Namespace": "Namespace",
    "NamespacePolicy": "Namespace Policy",
    "Node": "Node",
    "PermissionDetail": "Permission",
    "ProvisionedWorkerPool": "Provisioned Worker Pool",
    "Role": "Role",
    "Task": "Task",
    "TaskGroup": "Task Group",
    "User": "User",
    "WorkRequirementSummary": "Work Requirement",
    "Worker": "Worker",
    "WorkerPoolSummary": "Worker Pool",
}


def print_table_core(table: str):
    """
    Core function for printing a table.
    """
    if OUTPUT.no_format or table.count("\n") > MAX_LINES_COLOURED_FORMATTING:
        print(table, flush=True)
    else:
        CONSOLE_TABLE.print(escape(table), soft_wrap=True)


def get_type_name(obj: Item) -> str:
    """
    Get the display name of an object's type.
    """
    if type(obj).__name__.endswith("Instance"):
        # Special case
        return "Instance"

    if type(obj).__name__.endswith("Allowance"):
        # Special case
        return "Allowance"

    return TYPE_MAP.get(type(obj).__name__, "")


def compute_requirement_table(
    cr_list: list[ComputeRequirementSummary],
) -> tuple[list[str], list[list]]:
    headers = [
        "#",
        "Compute Requirement Name",
        "Namespace",
        "Tag",
        "Status (Tgt/Exp/Alive)",
        "Compute Requirement ID",
    ]
    table = []
    for index, cr in enumerate(cr_list):
        table.append(
            [
                index + 1,
                cr.name,
                cr.namespace,
                cr.tag,
                str(cr.status)
                + f" ({cr.targetInstanceCount:,d}/{cr.expectedInstanceCount:,d}/{cr.aliveInstanceCount:,d})",
                cr.id,
            ]
        )
    return headers, table


def work_requirement_table(
    wr_summary_list: list[WorkRequirementSummary],
) -> tuple[list[str], list[list]]:
    headers = [
        "#",
        "Work Requirement Name",
        "Namespace",
        "Tag",
        "Status",
        "Tasks",
        "Healthy",
        "Work Requirement ID",
    ]
    table = []
    for index, wr_summary in enumerate(wr_summary_list):
        namespace = "" if wr_summary.namespace is None else wr_summary.namespace
        tag = "" if wr_summary.tag is None else wr_summary.tag
        table.append(
            [
                index + 1,
                wr_summary.name,
                namespace,
                tag,
                str(wr_summary.status),
                f"{wr_summary.completedTaskCount}/{wr_summary.totalTaskCount}",
                _yes_or_no(wr_summary.healthy),
                wr_summary.id,
            ]
        )
    return headers, table


def task_group_table(
    task_group_list: list[TaskGroup],
) -> tuple[list[str], list[list]]:
    headers = ["#", "Task Group Name", "Status", "Task Group ID"]
    table = []
    for index, task_group in enumerate(task_group_list):
        status_msg = str(task_group.status)
        if task_group.starved:
            status_msg += "/STARVED"
        if task_group.waitingOnDependency:
            status_msg += "/WAITING"
        table.append(
            [
                index + 1,
                task_group.name,
                status_msg,
                task_group.id,
            ]
        )
    return headers, table


def task_table(task_list: list[Task]) -> tuple[list[str], list[list]]:
    headers = ["#", "Task Name", "Status", "Task ID"]
    table = []
    for index, task in enumerate(task_list):
        table.append(
            [
                index + 1,
                task.name,
                str(task.status),
                task.id,
            ]
        )
    return headers, table


def worker_pool_table(
    worker_pool_summaries: list[WorkerPoolSummary],
) -> tuple[list[str], list[list]]:
    headers = [
        "#",
        "Worker Pool Name",
        "Namespace",
        "Type",
        "Status",
        "Worker Pool ID",
    ]
    table = []
    for index, worker_pool_summary in enumerate(worker_pool_summaries):
        table.append(
            [
                index + 1,
                worker_pool_summary.name,
                worker_pool_summary.namespace,
                f"{(worker_pool_summary.type or '').split('.')[-1:][0].replace('WorkerPool', '')}",
                f"{worker_pool_summary.status}",
                worker_pool_summary.id,
            ]
        )
    return headers, table


def compute_requirement_template_table(
    crt_summaries: list[ComputeRequirementTemplateSummary],
) -> tuple[list[str], list[list]]:
    headers = [
        "#",
        "Name",
        "Namespace",
        "Type",
        "Description",
        "Strategy Type",
        "Compute Requirement Template ID",
    ]
    table = []
    for index, crt_summary in enumerate(crt_summaries):
        type_str = (
            (crt_summary.type or "").split(".")[-1].replace("ComputeRequirement", "")
        )
        strategy_type = (
            (crt_summary.strategyType or "")
            .split(".")[-1]
            .replace("ProvisionStrategy", "")
        )
        table.append(
            [
                index + 1,
                crt_summary.name,
                crt_summary.namespace,
                type_str,
                _truncate_text(crt_summary.description),
                strategy_type,
                crt_summary.id,
            ]
        )
    return headers, table


def compute_source_template_table(
    cst_summaries: list[ComputeSourceTemplateSummary],
) -> tuple[list[str], list[list]]:
    headers = [
        "#",
        "Name",
        "Namespace",
        "Description",
        "Provider",
        "Type",
        "Compute Source Template ID",
    ]
    table = []
    for index, cst_summary in enumerate(cst_summaries):
        type_str = (cst_summary.sourceType or "").split(".")[-1]
        provider = cst_summary.provider
        table.append(
            [
                index + 1,
                cst_summary.name,
                cst_summary.namespace,
                _truncate_text(cst_summary.description),
                provider,
                type_str,
                cst_summary.id,
            ]
        )
    return headers, table


def keyring_table(
    keyring_summaries: list[KeyringSummary],
) -> tuple[list[str], list[list]]:
    headers = [
        "#",
        "Name",
        "Description",
        "Keyring ID",
    ]
    table = []
    for index, keyring in enumerate(keyring_summaries):
        table.append(
            [
                index + 1,
                keyring.name,
                _truncate_text(keyring.description),
                keyring.id,
            ]
        )
    return headers, table


def image_family_table(
    image_family_summaries: list[MachineImageFamilySummary],
) -> tuple[list[str], list[str]]:
    headers = [
        "#",
        "Name",
        "Access",
        "Namespace",
        "OS Type",
        "Image Family ID",
    ]
    table = []
    for index, image_family in enumerate(image_family_summaries):
        table.append(
            [
                index + 1,
                image_family.name,
                image_family.access,
                image_family.namespace,
                image_family.osType,
                image_family.id,
            ]
        )
    return headers, table


def instances_table(
    instances: list[Instance],
) -> tuple[list[str], list[str]]:
    headers = [
        "#",
        "Provider",
        "Instance Type",
        "Spot",
        "Hostname",
        "Status",
        "Private IP",
        "Public IP",
        "Source ID",
        "Instance ID",
    ]
    table = []
    for index, instance in enumerate(instances):
        table.append(
            [
                index + 1,
                instance.provider,
                instance.instanceType,
                _yes_or_no(instance.spot),
                instance.hostname,
                instance.status,
                instance.privateIpAddress,
                instance.publicIpAddress,
                instance.id.sourceId if instance.id else None,
                instance.id.instanceId if instance.id else None,
            ]
        )
    return headers, table


def nodes_table(
    nodes: list[Node],
) -> tuple[list[str], list[str]]:
    show_pool_name = any(getattr(n, "workerPoolName", None) is not None for n in nodes)
    headers = ["#"]
    if show_pool_name:
        headers.append("Worker Pool Name")
    headers += [
        "Provider",
        "Region",
        "RAM",
        "vCPUs",
        "Task Types",
        "Worker Tag",
        "Workers",
        "Status",
        "Node ID",
    ]
    table = []
    for index, node in enumerate(nodes):
        # A Node without details is still listed, so that the numbers a
        # selection is made by are the rows shown
        details = node.details
        row = [index + 1]
        if show_pool_name:
            row.append(getattr(node, "workerPoolName", None))  # type: ignore[union-attr]
        row += [
            None if details is None else details.provider,
            None if details is None else details.region,
            None if details is None else details.ram,
            None if details is None else details.vcpus,
            "" if details is None else ", ".join(details.supportedTaskTypes or []),
            None if details is None else details.workerTag,
            len(node.workers or []),
            node.status,
            node.id,
        ]
        table.append(row)
    return headers, table


def workers_table(
    workers: list[Worker],
) -> tuple[list[str], list[str]]:
    headers = [
        "#",
        "Worker Pool Name",
        "Task Types",
        "Worker Tag",
        "Status",
        "Claims",
        "Exclusive",
        "Worker ID",
    ]
    table = []
    for index, worker in enumerate(workers):
        table.append(
            [
                index + 1,
                getattr(worker, "workerPoolName", None),
                ", ".join(getattr(worker, "taskTypes", None) or []),
                getattr(worker, "workerTag", None),
                worker.status,
                getattr(worker, "claimCount", None),
                _yes_or_no(getattr(worker, "exclusive", False)),
                worker.id,
            ]
        )
    return headers, table


def allowances_table(
    allowances: list[Allowance],
) -> tuple[list[str], list[str]]:
    headers = [
        "#",
        "Type",
        "Description",
        "Allowed Hrs",
        "Remaining Hrs",
        "Limit",
        "Reset",
        "Allowances ID",
    ]
    table = []
    for index, allowance in enumerate(allowances):
        table.append(
            [
                index + 1,
                allowance.type.split(".")[-1],
                _truncate_text(allowance.description),
                allowance.allowedHours,
                allowance.remainingHours,
                allowance.limitEnforcement,
                (
                    f"{allowance.resetInterval} {allowance.resetType}"
                    if allowance.resetInterval is not None
                    else ""
                ),
                allowance.id,
            ]
        )
    return headers, table


def attribute_definitions_table(
    attribute_definitions: list[dict],
) -> tuple[list[str], list[str]]:
    headers = [
        "#",
        "Name",
        "Type",
        "Title",
        "Description",
    ]
    table = []
    for index, attribute_definition in enumerate(attribute_definitions):
        table.append(
            [
                index + 1,
                attribute_definition["name"],
                attribute_definition["type"].split(".")[-1],
                attribute_definition["title"],
                _truncate_text(attribute_definition.get("description", "")),
            ]
        )
    return headers, table


def aws_availability_zone_table(
    aws_azs: list[AWSAvailabilityZone],
) -> tuple[list[str], list[str]]:
    headers = [
        "#",
        "Availability Zone",
        "Default Subnet ID",
        "Default Security Group ID",
    ]
    table = []
    for index, az in enumerate(aws_azs):
        table.append(
            [
                index + 1,
                az.az,
                az.default_subnet_id,
                az.default_sec_grp.id if az.default_sec_grp else None,
            ]
        )
    return headers, table


def namespaces_table(
    ns_policies: list[Namespace],
) -> tuple[list[str], list[list]]:
    headers = [
        "#",
        "Namespace Name",
        "ID",
        "Deletable",
    ]
    table = []
    for index, namespace in enumerate(ns_policies):
        table.append(
            [
                index + 1,
                namespace.namespace,
                namespace.id,
                _yes_or_no(namespace.deletable),
            ]
        )
    return headers, table


def namespace_policies_table(
    ns_policies: list[NamespacePolicy],
) -> tuple[list[str], list[list]]:
    headers = [
        "#",
        "Namespace",
        "AutoscalingMaxNodes",
    ]
    table = []
    for index, ns_policy in enumerate(ns_policies):
        table.append(
            [
                index + 1,
                ns_policy.namespace,
                ns_policy.autoscalingMaxNodes,
            ]
        )
    return headers, table


def users_table(
    users: list[User],
) -> tuple[list[str], list[list]]:
    from yellowdog_client.model import ExternalUser, InternalUser

    headers = [
        "#",
        "Name",
        "User Type",
        "Username",
        "Email",
        "ID",
    ]
    table = []
    for index, user in enumerate(users):
        if isinstance(user, InternalUser):
            table.append(
                [
                    index + 1,
                    user.name,
                    "Internal",
                    user.username,
                    user.email,
                    user.id,
                ]
            )
        elif isinstance(user, ExternalUser):  # External user
            table.append(
                [
                    index + 1,
                    user.name,
                    "External",
                    "",
                    user.email,
                    user.id,
                ]
            )
    return headers, table


def applications_table(
    applications: list[Application],
) -> tuple[list[str], list[list]]:
    headers = [
        "#",
        "Name",
        "Description",
        "ID",
    ]
    table = []
    for index, application in enumerate(applications):
        table.append(
            [
                index + 1,
                application.name,
                _truncate_text(application.description),
                application.id,
            ]
        )
    return headers, table


def groups_table(
    groups: list[Group],
) -> tuple[list[str], list[list]]:
    headers = [
        "#",
        "Name",
        "Admin Group",
        "Description",
        "Roles",
        "ID",
    ]
    table = []
    for index, group in enumerate(groups):
        table.append(
            [
                index + 1,
                group.name,
                _yes_or_no(group.adminGroup),
                _truncate_text(group.description),
                ", ".join([x.role.name or "" for x in group.roles or []]),
                group.id,
            ]
        )
    return headers, table


def roles_table(
    roles: list[Role],
) -> tuple[list[str], list[list]]:
    headers = [
        "#",
        "Name",
        "Permissions",
        "ID",
    ]
    table = []
    for index, role in enumerate(roles):
        permissions = ", ".join(sorted([x.value for x in role.permissions]))
        table.append(
            [
                index + 1,
                role.name,
                _truncate_text(permissions),
                role.id,
            ]
        )
    return headers, table


def permissions_table(
    permissions: list[PermissionDetail],
) -> tuple[list[str], list[list]]:
    headers = [
        "#",
        "Name",
        "Scope",
        "Description",
        "Includes",
    ]
    table = []
    for index, permission in enumerate(permissions):
        includes = ", ".join(sorted(permission.includes or []))
        table.append(
            [
                index + 1,
                permission.name,
                permission.scope,
                permission.title,
                includes,
            ]
        )
    return headers, table


def print_numbered_object_list(
    client: PlatformClient,
    objects: Sequence[Item | str | dict],
    object_type_name: str | None = None,
    override_quiet: bool = False,
    showing_all: bool = False,
) -> None:
    """
    Print a numbered list of objects.
    Assume that the list supplied is already sorted.
    """
    from yellowdog_client.model import (
        Allowance,
        Application,
        ComputeRequirementSummary,
        ComputeRequirementTemplateSummary,
        ComputeSourceTemplateSummary,
        Group,
        Instance,
        KeyringSummary,
        MachineImageFamilySummary,
        Namespace,
        NamespacePolicy,
        Node,
        PermissionDetail,
        Role,
        Task,
        TaskGroup,
        User,
        Worker,
        WorkerPoolSummary,
        WorkRequirementSummary,
    )

    if not objects:
        return

    if OUTPUT.auto_select_all and OUTPUT.details and OUTPUT.quiet:
        return

    print_info(
        "Displaying"
        f" {'all' if showing_all else 'matching'}"
        f" {(object_type_name if object_type_name is not None else get_type_name(objects[0]))}(s):",  # type: ignore
        override_quiet=override_quiet,
    )
    print()

    headers = None
    if isinstance(objects[0], str):
        headers = ["#", "Name"]
        table = [[index + 1, name] for index, name in enumerate(objects)]
    elif isinstance(objects[0], ComputeRequirementSummary):
        headers, table = compute_requirement_table(objects)  # type: ignore
    elif isinstance(objects[0], WorkRequirementSummary):
        headers, table = work_requirement_table(objects)  # type: ignore
    elif isinstance(objects[0], TaskGroup):
        headers, table = task_group_table(objects)  # type: ignore
    elif isinstance(objects[0], Task):
        headers, table = task_table(objects)  # type: ignore
    elif isinstance(objects[0], WorkerPoolSummary):
        headers, table = worker_pool_table(objects)  # type: ignore
    elif isinstance(objects[0], ComputeRequirementTemplateSummary):
        headers, table = compute_requirement_template_table(objects)  # type: ignore
    elif isinstance(objects[0], ComputeSourceTemplateSummary):
        headers, table = compute_source_template_table(objects)  # type: ignore
    elif isinstance(objects[0], KeyringSummary):
        headers, table = keyring_table(objects)  # type: ignore
    elif isinstance(objects[0], MachineImageFamilySummary):
        headers, table = image_family_table(objects)  # type: ignore
    elif isinstance(objects[0], Instance):
        headers, table = instances_table(objects)  # type: ignore
    elif isinstance(objects[0], Allowance):
        headers, table = allowances_table(objects)  # type: ignore
    elif isinstance(objects[0], AWSAvailabilityZone):
        headers, table = aws_availability_zone_table(objects)  # type: ignore
    elif object_type_name == "Attribute Definition":
        headers, table = attribute_definitions_table(objects)  # type: ignore
    elif isinstance(objects[0], NamespacePolicy):
        headers, table = namespace_policies_table(objects)  # type: ignore
    elif isinstance(objects[0], Node):
        headers, table = nodes_table(objects)  # type: ignore
    elif isinstance(objects[0], Worker):
        headers, table = workers_table(objects)  # type: ignore
    elif isinstance(objects[0], User):
        headers, table = users_table(objects)  # type: ignore
    elif isinstance(objects[0], Application):
        headers, table = applications_table(objects)  # type: ignore
    elif isinstance(objects[0], Group):
        headers, table = groups_table(objects)  # type: ignore
    elif isinstance(objects[0], Role):
        headers, table = roles_table(objects)  # type: ignore
    elif isinstance(objects[0], PermissionDetail):
        headers, table = permissions_table(objects)  # type: ignore
    elif isinstance(objects[0], Namespace):
        headers, table = namespaces_table(objects)  # type: ignore
    else:
        table = []
        for index, obj in enumerate(objects):
            table.append([index + 1, ":", obj.name])  # type: ignore[union-attr]
    if headers is None:
        print_table_core(indent(tabulate(table, tablefmt="plain"), indent_width=4))
    else:
        print_table_core(
            indent(
                tabulate(table, headers=headers, tablefmt="simple_outline"),
                indent_width=4,
            )
        )
    print(flush=True)


def sorted_objects(objects: list[_T], reverse: bool = False) -> list[_T]:
    """
    Sort objects by their 'name' property, or 'instanceType' in the case of
    Instances, etc.
    """
    from yellowdog_client.model import Allowance, Instance, Node, Task, Worker

    if not objects:
        return objects

    if OUTPUT.reverse is not None:
        reverse = OUTPUT.reverse

    # '--sort created' orders any entity exposing a 'createdTime' (e.g. Work
    # Requirement / Compute Requirement / Worker Pool summaries) by creation
    # time, earliest first (latest first with --reverse). Entities without a
    # 'createdTime', or a None value that breaks comparison, fall through to
    # the name-based sorting below.
    if OUTPUT.sort == "created" and hasattr(objects[0], "createdTime"):
        try:
            return sorted(objects, key=lambda x: x.createdTime, reverse=reverse)  # type: ignore[union-attr]
        except TypeError:
            pass

    # '--sort status' orders any entity exposing a 'status' by its status name
    # (statuses are enums, so sort on their string form), with the entity name
    # as a secondary key so same-status entities stay name-ordered.
    if OUTPUT.sort == "status" and hasattr(objects[0], "status"):
        try:
            return sorted(
                objects,
                key=lambda x: (str(x.status), str(getattr(x, "name", "") or "")),  # type: ignore[union-attr]
                reverse=reverse,
            )
        except TypeError:
            pass

    # '--sort namespace' groups entities by namespace, with the entity name as
    # a secondary key so same-namespace entities stay name-ordered.
    if OUTPUT.sort == "namespace" and hasattr(objects[0], "namespace"):
        try:
            return sorted(
                objects,
                key=lambda x: (str(x.namespace), str(getattr(x, "name", "") or "")),  # type: ignore[union-attr]
                reverse=reverse,
            )
        except TypeError:
            pass

    if isinstance(objects[0], str):
        return sorted(objects, reverse=reverse)  # type: ignore[type-var]

    if isinstance(objects[0], Instance):
        return sorted(objects, key=lambda x: x.instanceType, reverse=reverse)  # type: ignore[union-attr]

    if isinstance(objects[0], Node):
        # Note: worker_pool_name property is added dynamically in yd_list
        return sorted(objects, key=lambda x: str(x.workerPoolName), reverse=reverse)  # type: ignore[attr-defined]

    if isinstance(objects[0], Worker):
        # Note: worker_pool_name property is added dynamically in yd_list
        return sorted(objects, key=lambda x: str(x.workerPoolName), reverse=reverse)  # type: ignore[attr-defined]

    if isinstance(objects[0], AWSAvailabilityZone):
        return sorted(objects, reverse=reverse)  # type: ignore[type-var]

    if isinstance(objects[0], Allowance):
        return sorted(objects, key=lambda x: _text(x.description), reverse=reverse)  # type: ignore[union-attr]

    if isinstance(objects[0], Task):  # Sort tasks by their task number
        return sorted(objects, key=lambda x: int(x.id.split(":")[-1]), reverse=reverse)  # type: ignore[union-attr]

    if hasattr(objects[0], "name"):
        return sorted(objects, key=lambda x: _text(x.name), reverse=reverse)  # type: ignore[union-attr]
    return sorted(
        objects,
        key=lambda x: _text(getattr(x, "namespace", None)),
        reverse=reverse,
    )


def _text(value: object) -> str:
    """
    A sort key for a value that may be None, which sorts first.
    """
    return "" if value is None else str(value)


def print_compute_template_test_result(result: ComputeRequirementTemplateTestResult):
    """
    Print the results of a test submission of a Dynamic Compute Template.
    """
    from yellowdog_client.model import ComputeRequirementDynamicTemplateTestResult

    if not isinstance(result, ComputeRequirementDynamicTemplateTestResult):
        print_info("Reports are only available for Dynamic Templates")
        return

    report = result.report
    if report is None:
        return
    sources = report.sources or []
    source_table = [
        [
            "#",
            "Rank",
            "Provider",
            "Type",
            "Region",
            "Instance Type",
            "Source Name",
        ]
    ]
    for index, source in enumerate(sources):
        source_table.append(
            [  # type: ignore[list-item]
                index + 1,
                source.rank,
                source.provider,
                source.type,
                source.region,
                source.instanceType,
                source.name,
            ]
        )
    print(flush=True)
    print_table_core(
        indent(tabulate(source_table, headers="firstrow", tablefmt="simple_outline"))
    )
    print(flush=True)


def _truncate_text(description: str | None):
    """
    Truncate a description to fit within MAX_TABLE_DESCRIPTION.
    """
    if description is None:
        return ""

    return f"{description[: MAX_TABLE_DESCRIPTION - 3] + '...' if len(description) > MAX_TABLE_DESCRIPTION else description}"


def _yes_or_no(true_: bool) -> str:
    """
    Swap bools into strings.
    """
    return "Yes" if true_ else "No"


def node_action_type_label(action: NodeAction | None) -> str:
    """
    Return a short human-readable label for a node action.
    """
    if action is None:
        return "-"
    path = getattr(action, "path", None)
    match type(action).__name__:
        case "NodeRunCommandAction":
            return f"runCommand({path})"
        case "NodeWriteFileAction":
            return f"writeFile({path})"
        case "NodeCreateWorkersAction":
            return "createWorkers"
        case _:
            return type(action).__name__


NODE_ACTION_QUEUE_HEADINGS = ["Node ID", "Status", "Waiting", "Executing", "Failed"]


def node_action_queue_table(
    rows: list[tuple[str, NodeActionQueueSnapshot]],
) -> list[list]:
    """
    The node action queue table's rows, one per node, under
    NODE_ACTION_QUEUE_HEADINGS.
    """
    table = []
    for node_id, snapshot in rows:
        waiting_count = len(snapshot.waiting) if snapshot.waiting else 0
        executing_label = node_action_type_label(
            snapshot.executing[0] if snapshot.executing else None
        )
        failed_label = node_action_type_label(snapshot.failed)
        table.append(
            [
                node_id,
                snapshot.status.value if snapshot.status else "-",
                waiting_count,
                executing_label,
                failed_label,
            ]
        )
    return table


def print_node_action_queue_table(
    rows: list[tuple[str, NodeActionQueueSnapshot]],
):
    """
    Print a consolidated table of NodeActionQueueSnapshot rows, one per node.
    """
    print_table_core(
        indent(
            tabulate(
                node_action_queue_table(rows),
                headers=NODE_ACTION_QUEUE_HEADINGS,
                tablefmt="simple_outline",
            )
        )
    )
    print(flush=True)
