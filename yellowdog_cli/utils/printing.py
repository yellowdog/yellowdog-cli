"""
Functions focused on print outputs.
"""

import re
from collections.abc import Sequence
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime
from json import dumps as json_dumps
from json import loads as json_loads
from os import get_terminal_size, getpid
from sys import stderr
from textwrap import fill
from textwrap import indent as text_indent
from typing import Any, TypeVar

from rich.console import Console
from rich.highlighter import JSONHighlighter, RegexHighlighter
from rich.markup import escape
from rich.theme import Theme
from tabulate import tabulate
from yellowdog_client import PlatformClient
from yellowdog_client.common.json import Json
from yellowdog_client.model import (
    Allowance,
    Application,
    ComputeRequirementDynamicTemplateTestResult,
    ComputeRequirementStatus,
    ComputeRequirementSummary,
    ComputeRequirementTemplateSummary,
    ComputeRequirementTemplateTestResult,
    ComputeRequirementTemplateUsage,
    ComputeSourceTemplateSummary,
    ExternalUser,
    Group,
    Instance,
    InstanceStatus,
    InternalUser,
    KeyringSummary,
    MachineImageFamilySummary,
    Namespace,
    NamespacePolicy,
    Node,
    NodeAction,
    NodeActionQueueSnapshot,
    NodeActionQueueStatus,
    NodeStatus,
    PermissionDetail,
    ProvisionedWorkerPoolProperties,
    Role,
    Task,
    TaskGroup,
    TaskStatus,
    User,
    Worker,
    WorkerPoolSummary,
    WorkerStatus,
    WorkRequirement,
    WorkRequirementSummary,
)

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.cloudwizard_aws_types import AWSAvailabilityZone
from yellowdog_cli.utils.compact_json import CompactJSONEncoder
from yellowdog_cli.utils.items import Item
from yellowdog_cli.utils.property_names import NAME, TASK_GROUPS, TASKS
from yellowdog_cli.utils.rich_console_input_fixed import ConsoleWithInputBackspaceFixed
from yellowdog_cli.utils.settings import (
    DEBUG_STYLE,
    DEFAULT_LOG_WIDTH,
    DEFAULT_THEME,
    ERROR_STYLE,
    HIGHLIGHTED_STATES,
    JSON_INDENT,
    MAX_LINES_COLOURED_FORMATTING,
    MAX_TABLE_DESCRIPTION,
    PROP_ACCESS_DELEGATES,
    PROP_ADMIN_GROUP,
    PROP_CREATED_BY_ID,
    PROP_CREATED_BY_USER_ID,
    PROP_CREATED_TIME,
    PROP_DELETABLE,
    PROP_ID,
    PROP_INSTANCE_PRICING,
    PROP_PROVIDER,
    PROP_REMAINING_HOURS,
    PROP_SOURCE,
    PROP_SUPPORTING_RESOURCE_CREATED,
    PROP_TRAITS,
    WARNING_STYLE,
)
from yellowdog_cli.utils.ydid_utils import YDID_HIGHLIGHT_RE, YDIDType

_T = TypeVar("_T")

try:
    LOG_WIDTH = get_terminal_size().columns
except OSError:
    LOG_WIDTH = DEFAULT_LOG_WIDTH  # Default log line width


# Set up Rich formatting for coloured output
class PrintLogHighlighter(RegexHighlighter):
    """
    Apply styles for print_info() lines.
    """

    base_style = "pyexamples."
    highlights = [  # type: ignore[assignment]  # noqa: RUF012
        re.compile(
            r"(?P<date_time>[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"
            r" [0-9][0-9]:[0-9][0-9]:[0-9][0-9])"
        ),
        re.compile(r"(?P<quoted>'[a-zA-Z0-9-._=;,:/\\\[\]{}+#@$£%^&*()~`<>?]*')"),
        YDID_HIGHLIGHT_RE,
        re.compile(r"(?P<url>(https?):((//)|(\\\\))+[\w:#@%/;$~_?+=\\.&]*)"),
        *HIGHLIGHTED_STATES,
    ]


class PrintTableHighlighter(RegexHighlighter):
    """
    Apply styles for table printing.
    """

    base_style = "pyexamples."
    table_outline_chars = "┌─┬│┼┐┤└┴┘├"
    highlights = [  # type: ignore[assignment]  # noqa: RUF012
        re.compile(rf"(?P<table_outline>[{table_outline_chars}]*)"),
        re.compile(rf"(?P<table_content>[^{table_outline_chars}]*)"),
        YDID_HIGHLIGHT_RE,
        *HIGHLIGHTED_STATES,
    ]


pyexamples_theme = Theme(DEFAULT_THEME)


CONSOLE = ConsoleWithInputBackspaceFixed(
    highlighter=PrintLogHighlighter(), theme=pyexamples_theme
)
CONSOLE_TABLE = Console(highlighter=PrintTableHighlighter(), theme=pyexamples_theme)
CONSOLE_ERR = Console(stderr=True, highlighter=PrintLogHighlighter())
CONSOLE_JSON = Console(highlighter=JSONHighlighter())

PREFIX_LEN = 0
SUBSEQUENT_INDENT = ""


def print_string(msg: str = "", no_fill: bool = False) -> str:
    """
    Message output format, with tidy line-wrapping calibrated
    for the terminal width.
    """
    global PREFIX_LEN, SUBSEQUENT_INDENT

    prefix = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Optionally add the PID to the prefix to disambiguate interleaved
    # log messages
    if ARGS_PARSER.print_pid:
        prefix += f" ({getpid():06d}) : "
    else:
        prefix += " : "

    if PREFIX_LEN == 0:
        PREFIX_LEN = len(prefix)
        SUBSEQUENT_INDENT = " " * PREFIX_LEN

    if no_fill or msg == "" or msg.isspace() or ARGS_PARSER.no_format:
        return prefix + msg

    return fill(
        msg,
        width=LOG_WIDTH,
        initial_indent=prefix,
        subsequent_indent=SUBSEQUENT_INDENT,
        drop_whitespace=True,
        break_long_words=False,  # Preserve URLs
        break_on_hyphens=False,  # Preserve names
    )


def print_simple(
    log_message: str = "",
    override_quiet: bool = False,
):
    """
    Simple print function without timestamp.
    Set 'override_quiet' to print when '-q' is set.
    """
    if ARGS_PARSER.quiet and override_quiet is False:
        return

    if ARGS_PARSER.no_format:
        print(log_message)
    else:
        CONSOLE.print(escape(log_message))


def print_info(
    log_message: str = "",
    override_quiet: bool = False,
    no_fill: bool = False,
):
    """
    Placeholder for logging.
    Set 'override_quiet' to print when '-q' is set.
    """
    if (
        ARGS_PARSER.quiet or ARGS_PARSER.json_output or ARGS_PARSER.count_only
    ) and override_quiet is False:
        return

    if ARGS_PARSER.no_format:
        print(print_string(log_message, no_fill=no_fill), flush=True)
        return

    CONSOLE.print(escape(print_string(log_message, no_fill=no_fill)))


def print_debug(
    log_message: str = "",
    _override_quiet: bool = False,
    no_fill: bool = False,
):
    """
    Placeholder for debugging.
    """
    if not ARGS_PARSER.debug:
        return

    log_message = f"DEBUG: {log_message}"

    if ARGS_PARSER.no_format:
        print(print_string(log_message, no_fill=no_fill), flush=True)
        return

    CONSOLE.print(escape(print_string(log_message, no_fill=no_fill)), style=DEBUG_STYLE)


def print_error(error_obj: Exception | str):
    """
    Print an error message to stderr.
    """
    if ARGS_PARSER.no_format:
        print(print_string(f"Error: {error_obj}"), flush=True, file=stderr)
        return

    CONSOLE_ERR.print(escape(print_string(f"Error: {error_obj}")), style=ERROR_STYLE)


def print_warning(
    warning: str,
    override_quiet: bool = False,
    no_fill: bool = False,
):
    """
    Print a warning.
    """
    if (
        ARGS_PARSER.quiet or ARGS_PARSER.json_output or ARGS_PARSER.count_only
    ) and override_quiet is False:
        return

    if ARGS_PARSER.no_format:
        print(print_string(f"Warning: {warning}", no_fill=no_fill), flush=True)
        return

    CONSOLE.print(
        escape(print_string(f"Warning: {warning}", no_fill=no_fill)),
        style=WARNING_STYLE,
    )


# Maps SDK class names (type(obj).__name__) to their human-readable display names.
# Used by get_type_name() below. Instance and Allowance subtypes are handled
# separately via endswith() special cases in that function, as their class names
# vary (e.g. AWSInstance, AccountAllowance).
TYPE_MAP: dict[str, str] = {
    "AWSAvailabilityZone": "AWS Availability Zones",
    "Allowance": "Allowance",
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
    if ARGS_PARSER.no_format or table.count("\n") > MAX_LINES_COLOURED_FORMATTING:
        print(table, flush=True)
    else:
        CONSOLE_TABLE.print(escape(table))


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
    _client: PlatformClient, worker_pool_summaries: list[WorkerPoolSummary]
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
        try:
            type_str = (
                (crt_summary.type or "")
                .split(".")[-1]
                .replace("ComputeRequirement", "")
            )
        except Exception:
            type_str = None
        try:
            strategy_type = (
                (crt_summary.strategyType or "")
                .split(".")[-1]
                .replace("ProvisionStrategy", "")
            )
        except Exception:
            strategy_type = None
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
        try:
            type_str = (cst_summary.sourceType or "").split(".")[-1]
        except Exception:
            type_str = None
        try:
            provider = cst_summary.provider
        except Exception:
            provider = None
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
        if node.details is None:
            continue
        row = [index + 1]
        if show_pool_name:
            row.append(getattr(node, "workerPoolName", None))  # type: ignore[union-attr]
        row += [
            node.details.provider,
            node.details.region,
            node.details.ram,
            node.details.vcpus,
            ", ".join(node.details.supportedTaskTypes or []),
            node.details.workerTag,
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
    if not objects:
        return

    if ARGS_PARSER.auto_select_all and ARGS_PARSER.details and ARGS_PARSER.quiet:
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
        headers, table = worker_pool_table(client, objects)  # type: ignore
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


def print_numbered_strings(objects: list[str], override_quiet: bool = False):
    """
    Print a simple list of strings with numbering.
    """
    if ARGS_PARSER.quiet and override_quiet is False:
        return

    table = []
    for index, obj in enumerate(objects):
        table.append([index + 1, ":", obj])

    print_table_core(indent(tabulate(table, tablefmt="plain"), indent_width=4))
    print(flush=True)


def sorted_objects(objects: list[_T], reverse: bool = False) -> list[_T]:
    """
    Sort objects by their 'name' property, or 'instanceType' in the case of
    Instances, etc.
    """
    if not objects:
        return objects

    if ARGS_PARSER.reverse is not None:
        reverse = ARGS_PARSER.reverse

    # '--sort created' orders any entity exposing a 'createdTime' (e.g. Work
    # Requirement / Compute Requirement / Worker Pool summaries) by creation
    # time, earliest first (latest first with --reverse). Entities without a
    # 'createdTime', or a None value that breaks comparison, fall through to
    # the name-based sorting below.
    if ARGS_PARSER.sort == "created" and hasattr(objects[0], "createdTime"):
        try:
            return sorted(objects, key=lambda x: x.createdTime, reverse=reverse)  # type: ignore[union-attr]
        except TypeError:
            pass

    # '--sort status' orders any entity exposing a 'status' by its status name
    # (statuses are enums, so sort on their string form), with the entity name
    # as a secondary key so same-status entities stay name-ordered.
    if ARGS_PARSER.sort == "status" and hasattr(objects[0], "status"):
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
    if ARGS_PARSER.sort == "namespace" and hasattr(objects[0], "namespace"):
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
        return sorted(objects)  # type: ignore[type-var]

    if isinstance(objects[0], Allowance):
        try:
            return sorted(objects, key=lambda x: x.description, reverse=reverse)  # type: ignore[union-attr]
        except TypeError:
            return objects

    if isinstance(objects[0], Task):  # Sort tasks by their task number
        return sorted(objects, key=lambda x: int(x.id.split(":")[-1]), reverse=reverse)  # type: ignore[union-attr]

    try:
        return sorted(objects, key=lambda x: x.name, reverse=reverse)  # type: ignore[union-attr]
    except Exception:
        return sorted(objects, key=lambda x: x.namespace, reverse=reverse)  # type: ignore[union-attr]


def indent(txt: str, indent_width: int = 4) -> str:
    """
    Indent lines of text.
    """
    return text_indent(txt, prefix=" " * indent_width)


def _strip_id_props(d):
    """
    Remove ID and read-only metadata fields from a deserialized dict, recursively.
    Shared by print_yd_object (--strip-ids path) and print_objects_as_json.
    """
    if isinstance(d, dict):
        return {
            k: _strip_id_props(v)
            for k, v in d.items()
            if k
            not in [
                PROP_ID,
                PROP_ACCESS_DELEGATES,
                PROP_ADMIN_GROUP,
                PROP_CREATED_BY_ID,
                PROP_CREATED_BY_USER_ID,
                PROP_CREATED_TIME,
                PROP_DELETABLE,
                PROP_INSTANCE_PRICING,
                PROP_REMAINING_HOURS,
                PROP_SUPPORTING_RESOURCE_CREATED,
                PROP_TRAITS,
            ]
        }
    elif isinstance(d, list):
        return [_strip_id_props(item) for item in d]
    return d


def print_objects_as_json(objects: list) -> None:
    """
    Serialise a list of SDK model objects (or plain dicts) as a JSON array
    and print to stdout with no Rich formatting.  Used by --json mode.
    """
    data = [Json.dump(obj) if not isinstance(obj, dict) else obj for obj in objects]
    if ARGS_PARSER.strip_ids:
        stripped = []
        for item in data:
            item = _strip_id_props(item)
            try:
                item.get(PROP_SOURCE).pop(PROP_PROVIDER)  # type: ignore[union-attr]
            except (AttributeError, KeyError):
                pass
            stripped.append(item)
        data = stripped
    print_json(data)


def print_json(
    data: Any,
    initial_indent: int = 0,
    drop_first_line: bool = False,
    with_final_comma: bool = False,
):
    """
    Print a dictionary as a JSON data structure, using the compact JSON
    encoder.
    """
    json_string = indent(
        json_dumps(data, indent=JSON_INDENT, cls=CompactJSONEncoder), initial_indent
    )
    if drop_first_line:
        json_string = "\n".join(json_string.splitlines()[1:])

    # Coloured formatting of JSON console output is expensive
    if json_string.count("\n") > MAX_LINES_COLOURED_FORMATTING or ARGS_PARSER.no_format:
        if with_final_comma:
            print(json_string, end=",\n", flush=True)
        else:
            print(json_string, flush=True)

    else:
        if with_final_comma:
            CONSOLE_JSON.print(escape(json_string), end=",\n", soft_wrap=True)
        else:
            CONSOLE_JSON.print(escape(json_string), soft_wrap=True)

    if ARGS_PARSER.output_file is not None:  # Also output to a nominated file
        print_to_file(
            json_string=json_string,
            output_file=ARGS_PARSER.output_file,
            with_final_comma=with_final_comma,
        )


def print_yd_object(
    yd_object: object,
    initial_indent: int = 0,
    drop_first_line: bool = False,
    with_final_comma: bool = False,
    add_fields: dict | None = None,
):
    """
    Print a YellowDog object as a JSON data structure,
    using the compact JSON encoder.
    """
    object_data: Any = Json.dump(yd_object)

    if ARGS_PARSER.strip_ids:
        object_data = _strip_id_props(object_data)
        # Remove the 'provider' property from CST/source data only
        # 'object_data' is always a dict in practice
        try:
            object_data.get(PROP_SOURCE).pop(PROP_PROVIDER)
        except (AttributeError, KeyError):
            pass

    if add_fields is not None:
        # Requires a copy of the 'object' datatype to be made,
        # in order to insert additional fields
        object_data_new = {}
        for key, value in object_data.items():
            object_data_new[key] = value
        for key, value in add_fields.items():
            object_data_new[key] = value
        object_data = object_data_new

    print_json(object_data, initial_indent, drop_first_line, with_final_comma)


def print_yd_object_list(
    objects: list[tuple[Any, dict | None]],
):
    """
    Print a JSON list of objects.
    """

    if ARGS_PARSER.output_file is not None:
        print_info(f"Copying detailed resource list to '{ARGS_PARSER.output_file}'")

    if len(objects) > 1:
        print("[")
        if ARGS_PARSER.output_file is not None:
            print_to_file("[", ARGS_PARSER.output_file)

    for index, (object_, add_fields) in enumerate(objects):
        print_yd_object(
            object_,
            initial_indent=2 if len(objects) > 1 else 0,
            with_final_comma=(True if index < len(objects) - 1 else False),
            add_fields=add_fields,
        )

    if len(objects) > 1:
        print("]")
        if ARGS_PARSER.output_file is not None:
            print_to_file("]", ARGS_PARSER.output_file)


def print_worker_pool(
    crtu: ComputeRequirementTemplateUsage, pwpp: ProvisionedWorkerPoolProperties
):
    """
    Reconstruct and print the JSON-formatted Worker Pool specification.
    """
    print_info("Dry-run: Printing JSON Worker Pool specification")
    wp_data = {
        "provisionedProperties": Json.dump(pwpp),
        "requirementTemplateUsage": Json.dump(crtu),
    }
    print_json(wp_data)


class WorkRequirementSnapshot:
    """
    Represent a complete Work Requirement, with Tasks included within
    Task Group definitions. Note, this is not an 'official' representation
    of a Work Requirement.
    """

    def __init__(self):
        self.wr_data: dict = {}

    def set_work_requirement(self, wr: WorkRequirement):
        """
        Set the Work Requirement to be represented, processed to
        comply with the API.
        """
        self.wr_data = Json.dump(wr)  # type: ignore[assignment]  # Dictionary holding the complete WR

    def add_tasks(self, task_group_name: str, tasks: list[Task]):
        """
        Add the list of Tasks to a named Task Group within the
        Work Requirement. Cumulative.
        """
        for task_group in self.wr_data[TASK_GROUPS]:
            if task_group[NAME] == task_group_name:
                task_group[TASKS] = task_group.get(TASKS, [])
                task_group[TASKS] += [Json.dump(task) for task in tasks]
                return

    def print(self):
        """
        Print the JSON representation.
        """
        print_info("Dry-run: Printing JSON Work Requirement specification:")
        print_json(self.wr_data)
        print_info("Dry-run: Complete")


def print_compute_template_test_result(result: ComputeRequirementTemplateTestResult):
    """
    Print the results of a test submission of a Dynamic Compute Template.
    """
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


@dataclass
class StatusCount:
    name: str
    include_if_zero: bool = False


STATUS_COUNTS_TASKS = [
    StatusCount(TaskStatus.PENDING.value),
    StatusCount(TaskStatus.READY.value, True),
    StatusCount(TaskStatus.ALLOCATED.value),
    StatusCount(TaskStatus.EXECUTING.value, True),
    StatusCount(TaskStatus.UPLOADING.value),
    StatusCount(TaskStatus.DOWNLOADING.value),
    StatusCount(TaskStatus.COMPLETED.value, True),
    StatusCount(TaskStatus.CANCELLED.value),
    StatusCount(TaskStatus.ABORTED.value),
    StatusCount(TaskStatus.FAILED.value),
    StatusCount(TaskStatus.RESUBMITTED.value),
]

STATUS_COUNTS_INSTANCES = [
    StatusCount(InstanceStatus.PENDING.value, True),
    StatusCount(InstanceStatus.RUNNING.value, True),
    StatusCount(InstanceStatus.STOPPING.value),
    StatusCount(InstanceStatus.STOPPED.value),
    StatusCount(InstanceStatus.TERMINATING.value),
    StatusCount(InstanceStatus.TERMINATED.value, True),
    StatusCount(InstanceStatus.UNAVAILABLE.value),
    StatusCount(InstanceStatus.UNKNOWN.value),
]

STATUS_COUNTS_WORKERS = [
    StatusCount(WorkerStatus.BATCH_ALLOCATION.value),  # Deprecated
    StatusCount(WorkerStatus.DOING_TASK.value, True),  # Deprecated
    StatusCount(WorkerStatus.STOPPED.value, True),
    StatusCount(WorkerStatus.RUNNING.value, True),
    StatusCount(WorkerStatus.SLEEPING.value),  # Deprecated
    StatusCount(WorkerStatus.STARTING.value),
    StatusCount(WorkerStatus.LATE.value),
    StatusCount(WorkerStatus.LOST.value),
    StatusCount(WorkerStatus.SHUTDOWN.value),
]

STATUS_COUNTS_NODES = [
    StatusCount(NodeStatus.RUNNING.value, True),
    StatusCount(NodeStatus.TERMINATED.value, True),
    StatusCount(NodeStatus.DEREGISTERED.value),
    StatusCount(NodeStatus.LATE.value),
    StatusCount(NodeStatus.LOST.value),
]

STATUS_COUNTS_NODE_ACTIONS = [
    # StatusCount(NodeActionQueueStatus.EMPTY.value, True),
    StatusCount(NodeActionQueueStatus.WAITING.value, True),
    StatusCount(NodeActionQueueStatus.EXECUTING.value, True),
    StatusCount(NodeActionQueueStatus.FAILED.value),
]

STATUS_COUNTS_COMPUTE_REQ = [
    StatusCount(ComputeRequirementStatus.PROVISIONING.value, True),
    StatusCount(ComputeRequirementStatus.RUNNING.value, True),
    StatusCount(ComputeRequirementStatus.STOPPING.value),
    StatusCount(ComputeRequirementStatus.STOPPED.value),
    StatusCount(ComputeRequirementStatus.TERMINATING.value),
    StatusCount(ComputeRequirementStatus.TERMINATED.value),
]


def status_counts_msg(
    status_counts: list[StatusCount],
    counts_data: dict,
    empty_msg_if_zero_total: bool = False,
) -> str:
    """
    Generate the count of items in specific statuses.
    """
    msg = ""
    first = True
    total_count = 0
    for status_count in status_counts:
        try:
            count = counts_data[status_count.name]
            if count > 0 or status_count.include_if_zero:
                msg += f"{'' if first else ', '}{count:,d} {status_count.name}"
                first = False
                total_count += count
        except (KeyError, TypeError):
            continue  # Do nothing if a status is not present in the event data
    if total_count > 0 or empty_msg_if_zero_total is False:
        return msg
    else:
        return ""


def print_event(event: str, id_type: YDIDType):
    """
    Print a YellowDog event.
    """
    data_prefix = "data:"

    # Ignore events that don't have a 'data:' payload
    if not event.startswith(data_prefix):
        return

    # Strip only the leading prefix: the payload itself may contain 'data:'
    event_data: dict = json_loads(event[len(data_prefix) :])

    if ARGS_PARSER.raw_events:
        print_json(event_data)
        return

    event_indent = "\n" + (" " * PREFIX_LEN) + "--> "
    event_indent_2 = "\n" + (" " * (PREFIX_LEN + 4))

    if id_type == YDIDType.WORK_REQUIREMENT:
        msg = f"{id_type.value} '{event_data['name']}' is {event_data['status']}"
        for task_group in event_data["taskGroups"]:
            status = task_group["status"]
            if task_group["waitingOnDependency"] is True:
                status += "/WAITING"
            elif task_group["starved"] is True:
                status += "/STARVED"
            msg += (
                f"{event_indent}[{status}] Task Group '{task_group['name']}':"
                f" {task_group['taskSummary']['taskCount']:,d} Task(s){event_indent_2}"
            )
            msg += status_counts_msg(
                STATUS_COUNTS_TASKS, task_group["taskSummary"]["statusCounts"]
            )

    elif id_type == YDIDType.WORKER_POOL:
        msg = f"{id_type.value} '{event_data['name']}' is {event_data['status']}"
        msg += f"{event_indent}Node(s):        " + status_counts_msg(
            STATUS_COUNTS_NODES, event_data["nodeSummary"]["statusCounts"]
        )
        node_actions_msg = status_counts_msg(
            STATUS_COUNTS_NODE_ACTIONS,
            event_data["nodeSummary"]["actionQueueStatuses"],
            empty_msg_if_zero_total=True,
        )
        if node_actions_msg:
            msg += f"{event_indent}Node Action(s): " + node_actions_msg
        workers_msg = status_counts_msg(
            STATUS_COUNTS_WORKERS,
            event_data["workerSummary"]["statusCounts"],
            empty_msg_if_zero_total=True,
        )
        if workers_msg:
            msg += f"{event_indent}Worker(s):      " + workers_msg

    elif id_type == YDIDType.COMPUTE_REQUIREMENT:
        msg = f"{id_type.value} '{event_data['name']}' is {event_data['status']}"
        alive_count = sum(
            [
                int(source["instanceSummary"]["aliveCount"])
                for source in event_data["provisionStrategy"]["sources"]
            ]
        )
        msg += (
            f"{event_indent}Instance(s): "
            f"{event_data['targetInstanceCount']:,d} TARGET,"
            f" {event_data['expectedInstanceCount']:,d} EXPECTED,"
            f" {alive_count:,d} ALIVE"
        )
        for source in event_data["provisionStrategy"]["sources"]:
            source_msg = status_counts_msg(
                STATUS_COUNTS_INSTANCES,
                source["instanceSummary"]["statusCounts"],
                empty_msg_if_zero_total=True,
            )
            if source_msg:
                msg += f"{event_indent}Source: '{source['name']}': " + source_msg

    else:
        return

    print_info(msg, no_fill=True)


FIRST_OUTPUT_TO_FILE = True  # Determine whether to 'write' or 'append'


def print_to_file(json_string: str, output_file: str, with_final_comma: bool = False):
    """
    Dump details output to a file.
    """
    global FIRST_OUTPUT_TO_FILE

    try:
        with open(output_file, "w" if FIRST_OUTPUT_TO_FILE else "a") as f:
            with redirect_stdout(f):
                if with_final_comma:
                    print(json_string, end=",\n", flush=True)
                else:
                    print(json_string, flush=True)
    except Exception as e:
        raise RuntimeError(f"Cannot open output file for writing: {e}")

    FIRST_OUTPUT_TO_FILE = False


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


def print_node_action_queue_table(
    rows: list[tuple[str, NodeActionQueueSnapshot]],
):
    """
    Print a consolidated table of NodeActionQueueSnapshot rows, one per node.
    """
    headers = ["Node ID", "Status", "Waiting", "Executing", "Failed"]
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
    print_table_core(
        indent(tabulate(table, headers=headers, tablefmt="simple_outline"))
    )
    print(flush=True)
