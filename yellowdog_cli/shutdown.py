#!/usr/bin/env python3

"""
A script to shut down Worker Pools and/or Nodes.

Explicit targets are handled in two passes, as the compute commands handle
theirs (utils/compute_action_common.py). Each argument is first resolved, in
the order given, to a Worker Pool or a Node, recording any that cannot be
shut down as 'failed' (not found) or 'skipped' (already finished). What
remains is confirmed once and shut down; with '--terminate', each
Provisioned Worker Pool's Compute Requirement is terminated straight after
its pool is shut down. The rules for what cannot be shut down, confirming
and stopping on a session failure are action_runner.py's.
"""

from typing import TypeAlias, cast

from yellowdog_client.model import (
    Node,
    NodeStatus,
    ProvisionedWorkerPool,
    WorkerPool,
    WorkerPoolSummary,
)

from yellowdog_cli.utils.action_runner import (
    SKIPPED,
    Item,
    SessionStop,
    Unit,
    Unresolved,
    by_type,
    carry_out,
    confirm_items,
    resolve_targets,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.dryrun_utils import report_dry_run
from yellowdog_cli.utils.entity_names import (
    ET_COMPUTE_REQUIREMENTS,
    ET_NODES,
    ET_WORKER_POOLS,
)
from yellowdog_cli.utils.entity_utils import (
    describe_glob_scope,
    expand_name_globs,
    get_worker_pool_by_id,
    get_worker_pool_id_by_name,
    get_worker_pool_summaries,
)
from yellowdog_cli.utils.exit_codes import SESSION_FAILURES, classify
from yellowdog_cli.utils.follow_utils import follow_ids
from yellowdog_cli.utils.glob_utils import contains_glob_chars
from yellowdog_cli.utils.interactive import select
from yellowdog_cli.utils.misc_utils import is_http_not_found, link_entity
from yellowdog_cli.utils.printing import (
    print_dry_run,
    print_error,
    print_info,
    print_warning,
)
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.wrapper import main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

# The '--json' records' actions and outcomes
_SHUTDOWN = "shutdown"
_SHUT_DOWN = "shut down"
_TERMINATE = "terminate"
_TERMINATED = "terminated"

# A Worker Pool to shut down: fetched, or listed
_Pool: TypeAlias = WorkerPool | WorkerPoolSummary


def _record(
    entity: object,
    outcome: str,
    error: str | None = None,
    entity_type: str = ET_WORKER_POOLS,
) -> None:
    record_action(entity, entity_type, _SHUTDOWN, outcome, error)


def _record_termination(
    compute_requirement: object,
    worker_pool_id: str | None,
    outcome: str,
    error: str | None = None,
) -> None:
    """
    Record '--terminate''s outcome for a Compute Requirement, with the ID of
    the Worker Pool it belongs to.
    """
    record_action(
        compute_requirement,
        ET_COMPUTE_REQUIREMENTS,
        _TERMINATE,
        outcome,
        error,
        workerPoolId=worker_pool_id,
    )


def _recorder(entity: object, entity_type: str, outcome: str, error: str | None):
    """_record, as action_runner calls it."""
    _record(entity, outcome, error, entity_type)


@main_wrapper
def main(ctx: RunContext):
    shut_down(ctx, ctx.args.worker_pool_nodes_list or [])


def shut_down(ctx: RunContext, names: list[str]):
    """
    Shut down the Worker Pools and Nodes named, or those matching the glob
    patterns given, or, given nothing, the Worker Pools whose names include
    the tag.
    """
    globs = [n for n in names if contains_glob_chars(n)]

    if names and not globs:
        shutdown_by_names_or_ids(ctx, names)
        return

    if globs:
        print_info(
            f"Shutting down Worker Pools "
            f"{describe_glob_scope(globs, ctx.config.namespace)}"
        )
        worker_pool_summaries: list[WorkerPoolSummary] = expand_name_globs(
            globs,
            ctx.config.namespace,
            fetch=lambda namespace, prefix: get_worker_pool_summaries(
                ctx.client, namespace, prefix or None, partial_name_matches=True
            ),
        )
    else:
        print_info(
            "Shutting down Worker Pools in "
            f"namespace '{ctx.config.namespace}' with "
            f"names including '{ctx.config.name_tag}'"
        )
        worker_pool_summaries = [
            worker_pool_summary
            for worker_pool_summary in get_worker_pool_summaries(
                ctx.client,
                ctx.config.namespace,
                ctx.config.name_tag,
                partial_name_matches=True,
            )
            if worker_pool_summary.name is not None
            and worker_pool_summary.namespace == ctx.config.namespace
            and ctx.config.name_tag in worker_pool_summary.name
        ]

    worker_pool_summaries = [
        worker_pool_summary
        for worker_pool_summary in worker_pool_summaries
        if not _is_finished(worker_pool_summary)
    ]

    if ctx.args.dry_run:
        report_dry_run(
            ctx.client,
            worker_pool_summaries,
            "Worker Pool",
            "shut down",
            ET_WORKER_POOLS,
            _SHUTDOWN,
            bool(ctx.args.json_output),
        )
        if ctx.args.terminate:
            _report_terminations_dry_run(ctx, worker_pool_summaries)
        return

    selected: list[WorkerPoolSummary] = (
        select(ctx.client, worker_pool_summaries) if worker_pool_summaries else []
    )
    items = [_pool_item(summary) for summary in selected]

    if items and not confirm_items(_confirmation(ctx, items), items, _recorder):
        items = []

    _carry_out(ctx, items)


def _is_finished(worker_pool: _Pool) -> bool:
    return worker_pool.status is not None and worker_pool.status.finished


def _report_terminations_dry_run(
    ctx: RunContext, worker_pool_summaries: list[WorkerPoolSummary]
):
    """
    Under '--dry-run --terminate', report the Compute Requirements that would
    be terminated with the Worker Pools: those of the Provisioned ones.
    """
    for worker_pool_summary in worker_pool_summaries:
        worker_pool = get_worker_pool_by_id(
            ctx.client, cast(str, worker_pool_summary.id)
        )
        if not isinstance(worker_pool, ProvisionedWorkerPool):
            continue
        cr_id = worker_pool.computeRequirementId
        print_dry_run(
            f"Compute Requirement {cr_id} of Worker Pool"
            f" '{worker_pool_summary.name}' would be terminated"
        )
        _record_termination(
            {"id": cr_id, "name": None},
            worker_pool_summary.id,
            f"would {_TERMINATE}",
        )


def _pool_item(pool: _Pool) -> Item:
    return Item(pool, ET_WORKER_POOLS, ("pool", pool.id), pool)


def _node_item(node: Node) -> Item:
    return Item(node, ET_NODES, ("node", node.id), node)


def _describe(target: str) -> tuple[object, str]:
    return target, ET_NODES if _is_node(target) else ET_WORKER_POOLS


def shutdown_by_names_or_ids(ctx: RunContext, names_or_ids: list[str]):
    """
    Shut down Worker Pools and/or Nodes by their names or IDs.
    """
    items = resolve_targets(
        names_or_ids,
        resolve=lambda target: _resolve(ctx, target),
        describe=_describe,
        record=_recorder,
        verb="shut down",
        order=by_type(ET_WORKER_POOLS, ET_NODES),
    )

    if not items:
        print_info("No Worker Pools or Nodes shut down")
        return

    if not confirm_items(_confirmation(ctx, items), items, _recorder):
        print_info("No Worker Pools or Nodes shut down")
        return

    _carry_out(ctx, items)


def _is_node(target: str) -> bool:
    return get_ydid_type(target) == YDIDType.NODE


def _resolve(ctx: RunContext, target: str) -> Item:
    """
    The Worker Pool or Node a target names, raising Unresolved if it cannot
    be shut down. Anything else raised is a failure of the lookup itself.
    """
    if _is_node(target):
        try:
            node: Node = ctx.client.worker_pool_client.get_node_by_id(target)
        except Exception as e:
            if is_http_not_found(e):
                raise Unresolved(f"Cannot find Node {target}") from e
            raise
        if node.status == NodeStatus.TERMINATED:
            raise Unresolved(f"Node {target} is already TERMINATED", SKIPPED, node)
        return _node_item(node)

    if get_ydid_type(target) == YDIDType.WORKER_POOL:
        worker_pool_id: str | None = target
    else:
        worker_pool_id = get_worker_pool_id_by_name(
            ctx.client, target, ctx.config.namespace
        )
        if worker_pool_id is None:
            raise Unresolved(f"Cannot find Worker Pool '{target}'")
    try:
        worker_pool = get_worker_pool_by_id(ctx.client, cast(str, worker_pool_id))
    except Exception as e:
        if is_http_not_found(e):
            raise Unresolved(f"Cannot find Worker Pool {worker_pool_id}") from e
        raise
    if _is_finished(worker_pool):
        raise Unresolved(
            f"Worker Pool '{worker_pool.name}' is already {worker_pool.status}",
            SKIPPED,
            worker_pool,
        )
    return _pool_item(worker_pool)


def _confirmation(ctx: RunContext, items: list[Item]) -> str:
    pools = [item.value for item in items if item.entity_type == ET_WORKER_POOLS]
    nodes = [item.value for item in items if item.entity_type == ET_NODES]
    parts = []
    if pools:
        parts.append(
            f"{len(pools)} Worker Pool(s) ("
            + ", ".join(f"'{pool.name}'" if pool.name else pool.id for pool in pools)
            + ")"
        )
    if nodes:
        parts.append(
            f"{len(nodes)} Node(s) ({', '.join(cast(str, n.id) for n in nodes)})"
        )
    terminating = (
        ", immediately terminating their Compute Requirements"
        if ctx.args.terminate and pools
        else ""
    )
    return f"Shut down {' and '.join(parts)}{terminating}?"


def _carry_out(ctx: RunContext, items: list[Item]):
    """
    Shut down confirmed Worker Pools (terminating their Compute Requirements,
    with '--terminate'), then Nodes; report, and follow the pools shut down.
    Each unit reports and records its own failures.
    """
    shut_down_pool_ids: list[str] = []
    shut_down_node_ids: list[str] = []
    carry_out(
        [
            Unit(
                [item],
                act=(
                    (
                        lambda pool=item.value: _shut_down_pool(
                            ctx, pool, shut_down_pool_ids
                        )
                    )
                    if item.entity_type == ET_WORKER_POOLS
                    else (
                        lambda node=item.value: _shut_down_node(
                            ctx, node, shut_down_node_ids
                        )
                    )
                ),
                failure=lambda e, item=item: (
                    f"Failed to shut down '{_label(item.value)}': {e}"
                ),
            )
            for item in items
        ],
        _recorder,
    )

    if shut_down_pool_ids or shut_down_node_ids:
        if shut_down_pool_ids:
            print_info(f"Shut down {len(shut_down_pool_ids)} Worker Pool(s)")
        if shut_down_node_ids:
            print_info(f"Shut down {len(shut_down_node_ids)} Node(s)")
        if ctx.args.follow and shut_down_pool_ids:
            follow_ids(shut_down_pool_ids, auto_cr=ctx.args.auto_cr)
    else:
        print_info("No Worker Pools or Nodes shut down")


def _label(target: object) -> str:
    return str(getattr(target, "name", None) or getattr(target, "id", target))


def _failed(target: object, entity_type: str, message: str, e: Exception):
    """
    Report and record a failure, raising SessionStop if nothing further can
    succeed.
    """
    print_error(f"{message}: {e}")
    _record(target, "failed", str(e), entity_type)
    if classify(e) in SESSION_FAILURES:
        raise SessionStop(e) from e


def _shut_down_node(ctx: RunContext, node: Node, shut_down_node_ids: list[str]):
    try:
        ctx.client.worker_pool_client.shutdown_node_by_id(cast(str, node.id))
    except Exception as e:
        _failed(node, ET_NODES, f"Failed to shut down Node {node.id}", e)
        return
    print_info(f"Shut down Node {node.id}")
    _record(node, _SHUT_DOWN, entity_type=ET_NODES)
    shut_down_node_ids.append(cast(str, node.id))


def _shut_down_pool(ctx: RunContext, pool: _Pool, shut_down_pool_ids: list[str]):
    """
    Shut down a Worker Pool and, with '--terminate', terminate its Compute
    Requirement, adding its ID to 'shut_down_pool_ids' if it was shut down.
    """
    pool_id = cast(str, pool.id)
    try:
        ctx.client.worker_pool_client.shutdown_worker_pool_by_id(pool_id)
    except Exception as e:
        _failed(pool, ET_WORKER_POOLS, f"Failed to shut down '{pool.name}'", e)
        return
    shut_down_pool_ids.append(pool_id)
    _record(pool, _SHUT_DOWN)

    # A listed pool is a summary: the pool itself names its type, for the
    # link, and its Compute Requirement, for '--terminate'
    try:
        worker_pool = (
            pool
            if isinstance(pool, WorkerPool)
            else get_worker_pool_by_id(ctx.client, pool_id)
        )
    except Exception as e:
        print_info(f"Shut down Worker Pool '{pool.name}'")
        if ctx.args.terminate:
            print_error(
                "Unable to find the Compute Requirement of Worker Pool"
                f" '{pool.name}': {e}"
            )
            _record_termination({"id": None, "name": None}, pool_id, "failed", str(e))
            if classify(e) in SESSION_FAILURES:
                raise SessionStop(e) from e
        return
    print_info(f"Shut down {link_entity(ctx.config.url, worker_pool)}")  # type: ignore[arg-type]

    if ctx.args.terminate:
        _terminate_compute_requirement(ctx, worker_pool)


def _terminate_compute_requirement(ctx: RunContext, worker_pool: WorkerPool):
    """
    Terminate a Provisioned Worker Pool's Compute Requirement. A Configured
    Worker Pool has none, which is noted rather than recorded.
    """
    if not isinstance(worker_pool, ProvisionedWorkerPool):
        print_warning(
            f"Worker Pool '{worker_pool.name}' is a Configured Worker Pool, with"
            " no Compute Requirement to terminate"
        )
        return
    cr_id = worker_pool.computeRequirementId
    try:
        compute_requirement = (
            ctx.client.compute_client.terminate_compute_requirement_by_id(
                cast(str, cr_id)
            )
        )
    except Exception as e:
        print_error(
            f"Failed to terminate Compute Requirement {cr_id} of Worker Pool"
            f" '{worker_pool.name}': {e}"
        )
        _record_termination(
            {"id": cr_id, "name": None}, worker_pool.id, "failed", str(e)
        )
        if classify(e) in SESSION_FAILURES:
            raise SessionStop(e) from e
        return
    name = getattr(compute_requirement, "name", None)
    print_info(
        f"Terminated Compute Requirement {cr_id}"
        + ("" if name is None else f" ('{name}')")
        + f" of Worker Pool '{worker_pool.name}'"
    )
    _record_termination({"id": cr_id, "name": name}, worker_pool.id, _TERMINATED)


# Entry point
if __name__ == "__main__":
    main()
