"""
What counts as active for the three kinds of thing a run is made of,
which 'yd list' and 'yd status' share so that their '--active-only' keeps
the same things: a Work Requirement not yet finished, a Worker Pool not
shut down or terminated, a Compute Requirement from new to terminating;
and 'yd status's searches for them.
"""

from yellowdog_client import PlatformClient
from yellowdog_client.model import (
    ComputeRequirementStatus,
    ComputeRequirementSummary,
    WorkerPoolStatus,
    WorkerPoolSummary,
    WorkRequirementStatus,
    WorkRequirementSummary,
)

from yellowdog_cli.utils.entity_utils import (
    get_compute_requirement_summaries,
    get_filtered_work_requirement_summaries,
    get_worker_pool_summaries,
    in_namespace_scope,
)

INACTIVE_WORK_REQUIREMENT_STATUSES: tuple[WorkRequirementStatus, ...] = (
    WorkRequirementStatus.COMPLETED,
    WorkRequirementStatus.CANCELLED,
    WorkRequirementStatus.FAILED,
)

INACTIVE_WORKER_POOL_STATUSES: tuple[WorkerPoolStatus, ...] = (
    WorkerPoolStatus.TERMINATED,
    WorkerPoolStatus.SHUTDOWN,
)

# A Compute Requirement still provisioning counts as active
ACTIVE_COMPUTE_REQUIREMENT_STATUSES: tuple[ComputeRequirementStatus, ...] = (
    ComputeRequirementStatus.NEW,
    ComputeRequirementStatus.PROVISIONING,
    ComputeRequirementStatus.STARTING,
    ComputeRequirementStatus.RUNNING,
    ComputeRequirementStatus.STOPPING,
    ComputeRequirementStatus.STOPPED,
    ComputeRequirementStatus.TERMINATING,
)


def work_requirements(
    client: PlatformClient, namespace: str | None, tag: str | None, active_only: bool
) -> list[WorkRequirementSummary]:
    """
    The Work Requirements in a namespace with the tag, the active alone if
    'active_only'.
    """
    return get_filtered_work_requirement_summaries(
        client,
        namespace=namespace,
        tag=tag,
        exclude_filter=list(INACTIVE_WORK_REQUIREMENT_STATUSES) if active_only else [],
    )


def worker_pools(
    client: PlatformClient, namespace: str | None, tag: str | None, active_only: bool
) -> list[WorkerPoolSummary]:
    """
    The Worker Pools in a namespace whose names hold the tag, a Worker Pool
    having no tag of its own, the active alone if 'active_only'; the
    namespace matched exactly, since the search matches it as a substring.
    """
    excluded = INACTIVE_WORKER_POOL_STATUSES if active_only else ()
    return [
        worker_pool
        for worker_pool in get_worker_pool_summaries(
            client, namespace, tag, partial_name_matches=True
        )
        if worker_pool.status not in excluded
        and in_namespace_scope(client, namespace, worker_pool.namespace)
    ]


def compute_requirements(
    client: PlatformClient, namespace: str | None, tag: str | None, active_only: bool
) -> list[ComputeRequirementSummary]:
    """
    The Compute Requirements in a namespace with the tag, the active alone
    if 'active_only'.
    """
    return get_compute_requirement_summaries(
        client,
        namespace,
        tag,
        list(ACTIVE_COMPUTE_REQUIREMENT_STATUSES) if active_only else None,
    )
