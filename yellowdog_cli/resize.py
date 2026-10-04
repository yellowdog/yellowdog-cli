#!/usr/bin/env python3

"""
A script to resize Worker Pools and Compute Requirements.

The target is resolved first: a YDID is fetched directly, whatever its
namespace, and a name is looked up in the configured namespace unless it has
a 'namespace/' prefix. What cannot be resized is reported before anything is
asked: a target that does not exist fails (exit 6), as does a Worker Pool
that is Configured, awaiting nodes, or would go outside its node limits; a
target that has finished, or is already the size asked for, is skipped. A
lookup that fails for any other reason reaches the wrapper, which reports
and classifies it.
"""

from typing import cast

from yellowdog_client.model import (
    ComputeRequirement,
    ComputeRequirementStatus,
    ComputeRequirementSummary,
    ProvisionedWorkerPool,
    WorkerPool,
)

from yellowdog_cli.utils.entity_utils import (
    AmbiguousNameError,
    find_compute_requirement_by_name,
    get_worker_pool_id_by_name,
)
from yellowdog_cli.utils.exit_codes import NotFoundError
from yellowdog_cli.utils.follow_utils import follow_events, follow_ids
from yellowdog_cli.utils.interactive import confirmed
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.printing import (
    print_dry_run,
    print_error,
    print_info,
    print_warning,
)
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.settings import ET_COMPUTE_REQUIREMENTS, ET_WORKER_POOLS
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON, main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

# The only state a Compute Requirement is resized in
_RESIZABLE_CR_STATUSES = [ComputeRequirementStatus.RUNNING]


def _record(
    entity: object, entity_type: str, outcome: str, error: str | None = None
) -> None:
    record_action(
        entity,
        entity_type,
        "resize",
        outcome,
        error,
        targetInstanceCount=ARGS_PARSER.worker_pool_size,
    )


def _count(count: int | None) -> str:
    return "unknown" if count is None else f"{count:,d}"


def _not_found(message: str, target: str, entity_type: str) -> None:
    """Record the target as not found, and raise NotFoundError (exit 6)."""
    _record(target, entity_type, "failed", message)
    raise NotFoundError(message)


def _cannot(entity: object, entity_type: str, message: str) -> None:
    """Report and record a target that cannot be resized as asked."""
    print_error(message)
    _record(entity, entity_type, "failed", message)


def _skip(entity: object, entity_type: str, message: str) -> None:
    """Report and record a target that needs no resize."""
    print_warning(message)
    _record(entity, entity_type, "skipped", message)


@main_wrapper
def main():
    if ARGS_PARSER.compute_req_resize:
        _resize_compute_requirement(cast(str, ARGS_PARSER.worker_pool_name))
    else:
        _resize_worker_pool(cast(str, ARGS_PARSER.worker_pool_name))


def _resize_worker_pool(target: str):
    size: int = cast(int, ARGS_PARSER.worker_pool_size)
    worker_pool = _find_worker_pool(target)
    label = f"'{worker_pool.namespace}/{worker_pool.name}'"

    if not isinstance(worker_pool, ProvisionedWorkerPool):
        _cannot(
            worker_pool,
            ET_WORKER_POOLS,
            f"Worker Pool {label} is a Configured Worker Pool, which cannot be resized",
        )
        return
    if worker_pool.status is not None and worker_pool.status.finished:
        _skip(
            worker_pool, ET_WORKER_POOLS, f"Worker Pool {label} is {worker_pool.status}"
        )
        return
    if worker_pool.awaitingNodes:
        _cannot(
            worker_pool,
            ET_WORKER_POOLS,
            f"Worker Pool {label} is awaiting nodes, and cannot be resized until"
            " they have registered",
        )
        return
    properties = worker_pool.properties
    min_nodes = None if properties is None else properties.minNodes
    max_nodes = None if properties is None else properties.maxNodes
    if (min_nodes is not None and size < min_nodes) or (
        max_nodes is not None and size > max_nodes
    ):
        _cannot(
            worker_pool,
            ET_WORKER_POOLS,
            f"{size:,d} node(s) is outside Worker Pool {label}'s limits"
            f" ({_count(min_nodes)} to {_count(max_nodes)})",
        )
        return
    current = worker_pool.expectedNodeCount
    if current == size:
        _skip(
            worker_pool,
            ET_WORKER_POOLS,
            f"Worker Pool {label} already expects {size:,d} node(s)",
        )
        return

    change = f"from {_count(current)} to {size:,d} node(s)"
    if ARGS_PARSER.dry_run:
        print_dry_run(f"Would resize Worker Pool {label} {change}")
        _record(worker_pool, ET_WORKER_POOLS, "would resize")
        return
    if not confirmed(f"Resize Worker Pool {label} {change}?"):
        _record(worker_pool, ET_WORKER_POOLS, "skipped")
        return

    try:
        CLIENT.worker_pool_client.resize_worker_pool(worker_pool=worker_pool, size=size)
    except Exception as e:
        _record(worker_pool, ET_WORKER_POOLS, "failed", str(e))
        raise
    _record(worker_pool, ET_WORKER_POOLS, "resized")
    print_info(f"Resized Worker Pool {label} {change}")

    if ARGS_PARSER.follow:
        print_info("Following event stream(s)")
        follow_ids([cast(str, worker_pool.id)], auto_cr=ARGS_PARSER.auto_cr)


def _find_worker_pool(target: str) -> WorkerPool:
    """
    The Worker Pool a YDID or name names, recording and raising NotFoundError
    if there is none.
    """
    if get_ydid_type(target) == YDIDType.WORKER_POOL:
        worker_pool_id: str | None = target
    else:
        worker_pool_id = get_worker_pool_id_by_name(
            CLIENT, target, namespace=CONFIG_COMMON.namespace
        )
        if worker_pool_id is None:
            _not_found(f"Cannot find Worker Pool '{target}'", target, ET_WORKER_POOLS)
    try:
        return CLIENT.worker_pool_client.get_worker_pool_by_id(
            worker_pool_id=cast(str, worker_pool_id)
        )
    except Exception as e:
        if is_http_not_found(e):
            _not_found(f"Cannot find Worker Pool {target}", target, ET_WORKER_POOLS)
        raise


def _resize_compute_requirement(target: str):
    size: int = cast(int, ARGS_PARSER.worker_pool_size)
    compute_requirement = _find_compute_requirement(target)
    label = f"'{compute_requirement.namespace}/{compute_requirement.name}'"

    if compute_requirement.status not in _RESIZABLE_CR_STATUSES:
        _skip(
            compute_requirement,
            ET_COMPUTE_REQUIREMENTS,
            f"Compute Requirement {label} is {compute_requirement.status}, and only"
            f" a {ComputeRequirementStatus.RUNNING} one can be resized",
        )
        return
    current = compute_requirement.targetInstanceCount
    print_info(
        f"Current target/expected instance counts = {_count(current)}/"
        f"{_count(compute_requirement.expectedInstanceCount)}"
    )
    if current == size:
        _skip(
            compute_requirement,
            ET_COMPUTE_REQUIREMENTS,
            f"Compute Requirement {label} already has a target of"
            f" {size:,d} instance(s)",
        )
        return

    change = f"from {_count(current)} to {size:,d} instance(s)"
    if ARGS_PARSER.dry_run:
        print_dry_run(f"Would resize Compute Requirement {label} {change}")
        _record(compute_requirement, ET_COMPUTE_REQUIREMENTS, "would resize")
        return
    if not confirmed(f"Resize Compute Requirement {label} {change}?"):
        _record(compute_requirement, ET_COMPUTE_REQUIREMENTS, "skipped")
        return

    try:
        # The full Compute Requirement, as it is now, is what is updated
        cr: ComputeRequirement = CLIENT.compute_client.get_compute_requirement_by_id(
            cast(str, compute_requirement.id)
        )
        cr.targetInstanceCount = size  # type: ignore[misc]
        CLIENT.compute_client.update_compute_requirement(cr, reprovision=False)
    except Exception as e:
        _record(compute_requirement, ET_COMPUTE_REQUIREMENTS, "failed", str(e))
        raise
    _record(compute_requirement, ET_COMPUTE_REQUIREMENTS, "resized")
    print_info(f"Resized Compute Requirement {label} {change}")

    if ARGS_PARSER.follow:
        if ARGS_PARSER.auto_cr:
            print_warning(
                "Option '--auto-follow-compute-requirements/-a' is"
                " ignored when resizing Compute Requirements"
            )
        print_info("Following event stream")
        follow_events(cast(str, compute_requirement.id), YDIDType.COMPUTE_REQUIREMENT)


def _find_compute_requirement(
    target: str,
) -> ComputeRequirement | ComputeRequirementSummary:
    """
    The Compute Requirement a YDID or name names, recording and raising
    NotFoundError if there is none. Of two RUNNING ones of the same name,
    neither is guessed at: the failure is recorded and raised.
    """
    if get_ydid_type(target) == YDIDType.COMPUTE_REQUIREMENT:
        try:
            return CLIENT.compute_client.get_compute_requirement_by_id(target)
        except Exception as e:
            if is_http_not_found(e):
                _not_found(
                    f"Cannot find Compute Requirement {target}",
                    target,
                    ET_COMPUTE_REQUIREMENTS,
                )
            raise
    try:
        return find_compute_requirement_by_name(
            CLIENT, target, CONFIG_COMMON.namespace, _RESIZABLE_CR_STATUSES
        )
    except NotFoundError as e:
        _not_found(str(e), target, ET_COMPUTE_REQUIREMENTS)
        raise  # Not reached: _not_found() raises
    except AmbiguousNameError as e:
        _record(target, ET_COMPUTE_REQUIREMENTS, "failed", str(e))
        raise


# Entry point
if __name__ == "__main__":
    main()
