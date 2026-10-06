"""
Event formatting: a Work Requirement's, Worker Pool's or Compute
Requirement's server-sent event as yd-follow and '--follow' print it
(print_event(), or each event as a JSON document under yd-follow's
'--json'), and the status counts it summarises (status_counts_msg() over the
status_counts_*() lists, built on first use so that importing this module
loads no SDK).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from json import loads as json_loads
from typing import Any

from yellowdog_cli.utils.output_settings import OUTPUT
from yellowdog_cli.utils.printing import prefix_width, print_info, print_json
from yellowdog_cli.utils.ydid_utils import YDIDType


@dataclass
class StatusCount:
    name: str
    include_if_zero: bool = False


@cache
def status_counts_tasks() -> list[StatusCount]:
    from yellowdog_client.model import TaskStatus

    return [
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


@cache
def status_counts_instances() -> list[StatusCount]:
    from yellowdog_client.model import InstanceStatus

    return [
        StatusCount(InstanceStatus.PENDING.value, True),
        StatusCount(InstanceStatus.RUNNING.value, True),
        StatusCount(InstanceStatus.STOPPING.value),
        StatusCount(InstanceStatus.STOPPED.value),
        StatusCount(InstanceStatus.TERMINATING.value),
        StatusCount(InstanceStatus.TERMINATED.value, True),
        StatusCount(InstanceStatus.UNAVAILABLE.value),
        StatusCount(InstanceStatus.UNKNOWN.value),
    ]


@cache
def status_counts_workers() -> list[StatusCount]:
    from yellowdog_client.model import WorkerStatus

    return [
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


@cache
def status_counts_nodes() -> list[StatusCount]:
    from yellowdog_client.model import NodeStatus

    return [
        StatusCount(NodeStatus.RUNNING.value, True),
        StatusCount(NodeStatus.TERMINATED.value, True),
        StatusCount(NodeStatus.DEREGISTERED.value),
        StatusCount(NodeStatus.LATE.value),
        StatusCount(NodeStatus.LOST.value),
    ]


@cache
def status_counts_node_actions() -> list[StatusCount]:
    from yellowdog_client.model import NodeActionQueueStatus

    return [
        # StatusCount(NodeActionQueueStatus.EMPTY.value, True),
        StatusCount(NodeActionQueueStatus.WAITING.value, True),
        StatusCount(NodeActionQueueStatus.EXECUTING.value, True),
        StatusCount(NodeActionQueueStatus.FAILED.value),
    ]


@cache
def status_counts_compute_req() -> list[StatusCount]:
    from yellowdog_client.model import ComputeRequirementStatus

    return [
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


def _field(data: Any, *keys: str) -> Any:
    """
    A field of an event's JSON, or None where it, or any object on the way
    to it, is absent or null: the Platform leaves a summary null until there
    is something to summarise.
    """
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _counts(data: Any, *keys: str) -> dict:
    """
    A status count table from an event, empty where there is none.
    """
    counts = _field(data, *keys)
    return counts if isinstance(counts, dict) else {}


def _count(value: Any) -> int:
    """
    A count from an event, 0 where there is none.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def print_event(event: str, id_type: YDIDType):
    """
    Print a YellowDog event. A field the event leaves null is shown as
    nothing, or a zero count, rather than ending the stream being followed.
    """
    data_prefix = "data:"

    # Ignore events that don't have a 'data:' payload
    if not event.startswith(data_prefix):
        return

    # Strip only the leading prefix: the payload itself may contain 'data:'
    event_data: dict = json_loads(event[len(data_prefix) :])

    if OUTPUT.events_as_json:
        print_json(event_data)
        return

    event_indent = "\n" + (" " * prefix_width()) + "--> "
    event_indent_2 = "\n" + (" " * (prefix_width() + 4))

    if id_type not in (
        YDIDType.WORK_REQUIREMENT,
        YDIDType.WORKER_POOL,
        YDIDType.COMPUTE_REQUIREMENT,
    ):
        return

    msg = f"{id_type.value} '{event_data.get('name')}' is {event_data.get('status')}"

    if id_type == YDIDType.WORK_REQUIREMENT:
        for task_group in event_data.get("taskGroups") or []:
            status = str(task_group.get("status"))
            if task_group.get("waitingOnDependency") is True:
                status += "/WAITING"
            elif task_group.get("starved") is True:
                status += "/STARVED"
            msg += (
                f"{event_indent}[{status}] Task Group '{task_group.get('name')}':"
                f" {_count(_field(task_group, 'taskSummary', 'taskCount')):,d}"
                f" Task(s){event_indent_2}"
            )
            msg += status_counts_msg(
                status_counts_tasks(),
                _counts(task_group, "taskSummary", "statusCounts"),
            )

    elif id_type == YDIDType.WORKER_POOL:
        msg += f"{event_indent}Node(s):        " + status_counts_msg(
            status_counts_nodes(), _counts(event_data, "nodeSummary", "statusCounts")
        )
        node_actions_msg = status_counts_msg(
            status_counts_node_actions(),
            _counts(event_data, "nodeSummary", "actionQueueStatuses"),
            empty_msg_if_zero_total=True,
        )
        if node_actions_msg:
            msg += f"{event_indent}Node Action(s): " + node_actions_msg
        workers_msg = status_counts_msg(
            status_counts_workers(),
            _counts(event_data, "workerSummary", "statusCounts"),
            empty_msg_if_zero_total=True,
        )
        if workers_msg:
            msg += f"{event_indent}Worker(s):      " + workers_msg

    else:
        sources = _field(event_data, "provisionStrategy", "sources") or []
        alive_count = sum(
            _count(_field(source, "instanceSummary", "aliveCount"))
            for source in sources
        )
        msg += (
            f"{event_indent}Instance(s): "
            f"{_count(event_data.get('targetInstanceCount')):,d} TARGET,"
            f" {_count(event_data.get('expectedInstanceCount')):,d} EXPECTED,"
            f" {alive_count:,d} ALIVE"
        )
        for source in sources:
            source_msg = status_counts_msg(
                status_counts_instances(),
                _counts(source, "instanceSummary", "statusCounts"),
                empty_msg_if_zero_total=True,
            )
            if source_msg:
                msg += (
                    f"{event_indent}Source: '{_field(source, 'name')}': " + source_msg
                )

    print_info(msg, no_fill=True)
