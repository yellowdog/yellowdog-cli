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
and classifies it. With '--wait', a resized Compute Requirement is waited for
until it has its new target of Instances running (capacity_wait.py).
"""

from collections.abc import Callable
from typing import TypeVar, cast

from yellowdog_client.model import (
    ComputeRequirement,
    ComputeRequirementStatus,
    ComputeRequirementSummary,
    ProvisionedWorkerPool,
    WorkerPool,
)

from yellowdog_cli.utils.capacity_wait import (
    capacity_reached,
    until_settled,
    until_settled_again,
    wait_for_capacity,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import ET_COMPUTE_REQUIREMENTS, ET_WORKER_POOLS
from yellowdog_cli.utils.entity_utils import (
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
from yellowdog_cli.utils.wrapper import main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

# The only state a Compute Requirement is resized in
_RESIZABLE_CR_STATUSES = [ComputeRequirementStatus.RUNNING]


def _record(
    ctx: RunContext,
    entity: object,
    entity_type: str,
    outcome: str,
    error: str | None = None,
) -> None:
    record_action(
        entity,
        entity_type,
        "resize",
        outcome,
        error,
        targetInstanceCount=ctx.args.worker_pool_size,
    )


def _count(count: int | None) -> str:
    return "unknown" if count is None else f"{count:,d}"


_T = TypeVar("_T")


def _found(
    ctx: RunContext, target: str, entity_type: str, find: Callable[[], _T]
) -> _T:
    """
    What 'find' finds, any failure to find it (not found, ambiguous, or the
    lookup's own failure) recorded as the target's, and raised.
    """
    try:
        return find()
    except Exception as e:
        _record(ctx, target, entity_type, "failed", str(e))
        raise


def _cannot(ctx: RunContext, entity: object, entity_type: str, message: str) -> None:
    """
    Report and record a target that cannot be resized as asked.
    """
    print_error(message)
    _record(ctx, entity, entity_type, "failed", message)


def _skip(ctx: RunContext, entity: object, entity_type: str, message: str) -> None:
    """
    Report and record a target that needs no resize.
    """
    print_warning(message)
    _record(ctx, entity, entity_type, "skipped", message)


@main_wrapper
def main(ctx: RunContext):
    if ctx.args.compute_req_resize:
        _resize_compute_requirement(ctx, cast(str, ctx.args.worker_pool_name))
    else:
        _resize_worker_pool(ctx, cast(str, ctx.args.worker_pool_name))


def _resize_worker_pool(ctx: RunContext, target: str):
    size: int = cast(int, ctx.args.worker_pool_size)
    worker_pool = _found(
        ctx, target, ET_WORKER_POOLS, lambda: _find_worker_pool(ctx, target)
    )
    label = f"'{worker_pool.namespace}/{worker_pool.name}'"

    if not isinstance(worker_pool, ProvisionedWorkerPool):
        _cannot(
            ctx,
            worker_pool,
            ET_WORKER_POOLS,
            f"Worker Pool {label} is a Configured Worker Pool, which cannot be resized",
        )
        return
    if worker_pool.status is not None and worker_pool.status.finished:
        _skip(
            ctx,
            worker_pool,
            ET_WORKER_POOLS,
            f"Worker Pool {label} is {worker_pool.status}",
        )
        return
    if worker_pool.awaitingNodes:
        _cannot(
            ctx,
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
            ctx,
            worker_pool,
            ET_WORKER_POOLS,
            f"{size:,d} node(s) is outside Worker Pool {label}'s limits"
            f" ({_count(min_nodes)} to {_count(max_nodes)})",
        )
        return
    current = worker_pool.expectedNodeCount
    if current == size:
        _skip(
            ctx,
            worker_pool,
            ET_WORKER_POOLS,
            f"Worker Pool {label} already expects {size:,d} node(s)",
        )
        return

    change = f"from {_count(current)} to {size:,d} node(s)"
    if ctx.args.dry_run:
        print_dry_run(f"Would resize Worker Pool {label} {change}")
        _record(ctx, worker_pool, ET_WORKER_POOLS, "would resize")
        return
    if not confirmed(f"Resize Worker Pool {label} {change}?"):
        _record(ctx, worker_pool, ET_WORKER_POOLS, "skipped")
        return

    try:
        ctx.client.worker_pool_client.resize_worker_pool(
            worker_pool=worker_pool, size=size
        )
    except Exception as e:
        _record(ctx, worker_pool, ET_WORKER_POOLS, "failed", str(e))
        raise
    _record(ctx, worker_pool, ET_WORKER_POOLS, "resized")
    print_info(f"Resized Worker Pool {label} {change}")

    if ctx.args.follow:
        print_info("Following event stream(s)")
        follow_ids(
            ctx,
            [cast(str, worker_pool.id)],
            auto_cr=ctx.args.auto_cr,
            settled=_resized_pool_settled(ctx, worker_pool),
        )


def _resized_pool_settled(ctx: RunContext, worker_pool: WorkerPool):
    """
    For follow_ids(): each stream (the pool's, and with '-a' its Compute
    Requirement's) ends once the pool's Compute Requirement is at its target
    again, having left it, as a resized pool stays alive and its stream never
    closes. A Configured Worker Pool has no Compute Requirement to tell by,
    so is followed until stopped.
    """
    cr_id = getattr(worker_pool, "computeRequirementId", None)
    if cr_id is None:
        return None
    reached = capacity_reached(ctx, until_settled_again)
    return lambda _ydid: reached(cr_id)


def _find_worker_pool(ctx: RunContext, target: str) -> WorkerPool:
    """
    The Worker Pool a YDID or name names, raising NotFoundError (exit 6) if
    there is none.
    """
    if get_ydid_type(target) == YDIDType.WORKER_POOL:
        worker_pool_id: str | None = target
    else:
        worker_pool_id = get_worker_pool_id_by_name(
            ctx.client, target, namespace=ctx.config.namespace
        )
        if worker_pool_id is None:
            raise NotFoundError(f"Cannot find Worker Pool '{target}'")
    try:
        return ctx.client.worker_pool_client.get_worker_pool_by_id(
            worker_pool_id=cast(str, worker_pool_id)
        )
    except Exception as e:
        if is_http_not_found(e):
            raise NotFoundError(f"Cannot find Worker Pool {target}") from e
        raise


def _resize_compute_requirement(ctx: RunContext, target: str):
    size: int = cast(int, ctx.args.worker_pool_size)
    compute_requirement = _found(
        ctx,
        target,
        ET_COMPUTE_REQUIREMENTS,
        lambda: _find_compute_requirement(ctx, target),
    )
    label = f"'{compute_requirement.namespace}/{compute_requirement.name}'"

    if compute_requirement.status not in _RESIZABLE_CR_STATUSES:
        _skip(
            ctx,
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
            ctx,
            compute_requirement,
            ET_COMPUTE_REQUIREMENTS,
            f"Compute Requirement {label} already has a target of"
            f" {size:,d} instance(s)",
        )
        return

    change = f"from {_count(current)} to {size:,d} instance(s)"
    if ctx.args.dry_run:
        print_dry_run(f"Would resize Compute Requirement {label} {change}")
        _record(ctx, compute_requirement, ET_COMPUTE_REQUIREMENTS, "would resize")
        return
    if not confirmed(f"Resize Compute Requirement {label} {change}?"):
        _record(ctx, compute_requirement, ET_COMPUTE_REQUIREMENTS, "skipped")
        return

    try:
        # The full Compute Requirement, as it is now, is what is updated
        cr: ComputeRequirement = (
            ctx.client.compute_client.get_compute_requirement_by_id(
                cast(str, compute_requirement.id)
            )
        )
        cr.targetInstanceCount = size  # type: ignore[misc]
        ctx.client.compute_client.update_compute_requirement(cr, reprovision=False)
    except Exception as e:
        _record(ctx, compute_requirement, ET_COMPUTE_REQUIREMENTS, "failed", str(e))
        raise
    _record(ctx, compute_requirement, ET_COMPUTE_REQUIREMENTS, "resized")
    print_info(f"Resized Compute Requirement {label} {change}")

    if ctx.args.wait:
        wait_for_capacity(ctx, [cast(str, compute_requirement.id)], ctx.args.timeout)

    if ctx.args.follow:
        if ctx.args.auto_cr:
            print_warning(
                "Option '--auto-follow-compute-requirements/-a' is"
                " ignored when resizing Compute Requirements"
            )
        print_info("Following event stream")
        cr_id = cast(str, compute_requirement.id)
        # Its target changed by the resize itself, so at it is done
        follow_events(
            ctx,
            cr_id,
            YDIDType.COMPUTE_REQUIREMENT,
            settled=capacity_reached(ctx, until_settled)(cr_id),
        )


def _find_compute_requirement(
    ctx: RunContext,
    target: str,
) -> ComputeRequirement | ComputeRequirementSummary:
    """
    The Compute Requirement a YDID or name names, raising NotFoundError
    (exit 6) if there is none. Of two RUNNING ones of the same name, neither
    is guessed at: AmbiguousNameError is raised.
    """
    if get_ydid_type(target) == YDIDType.COMPUTE_REQUIREMENT:
        try:
            return ctx.client.compute_client.get_compute_requirement_by_id(target)
        except Exception as e:
            if is_http_not_found(e):
                raise NotFoundError(f"Cannot find Compute Requirement {target}") from e
            raise
    return find_compute_requirement_by_name(
        ctx.client, target, ctx.config.namespace, _RESIZABLE_CR_STATUSES
    )


# Entry point
if __name__ == "__main__":
    main()
