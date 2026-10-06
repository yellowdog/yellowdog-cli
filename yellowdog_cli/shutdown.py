#!/usr/bin/env python3

"""
A script to shut down Worker Pools and/or Nodes.

Explicit targets are handled in two passes, as the compute commands handle
theirs (utils/compute_action_common.py). Each argument is first resolved, in
the order given, to a Worker Pool or a Node, recording any that cannot be
shut down as 'failed' (not found) or 'skipped' (already finished). What
remains is confirmed once and shut down; with '--terminate', each
Provisioned Worker Pool's Compute Requirement is terminated straight after
its pool is shut down. A failure every later call would repeat
(exit_codes.SESSION_FAILURES: authentication, connection) stops the run, and
the targets not yet attempted are recorded as skipped.
"""

from typing import TypeAlias, cast

from yellowdog_client.model import (
    Node,
    NodeStatus,
    ProvisionedWorkerPool,
    WorkerPool,
    WorkerPoolSummary,
)

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
from yellowdog_cli.utils.exit_codes import SESSION_FAILURES, ReportedFailure, classify
from yellowdog_cli.utils.follow_utils import follow_ids
from yellowdog_cli.utils.glob_utils import contains_glob_chars
from yellowdog_cli.utils.interactive import confirmed, select
from yellowdog_cli.utils.misc_utils import is_http_not_found, link_entity
from yellowdog_cli.utils.printing import (
    print_dry_run,
    print_error,
    print_info,
    print_warning,
)
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON, main_wrapper
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


class _SessionFailure(Exception):
    """
    A failure every later call would repeat (see SESSION_FAILURES), raised
    once the failing target has been recorded, so that nothing further is
    attempted.
    """

    def __init__(self, cause: Exception):
        super().__init__(str(cause))
        self.cause = cause


class _Unresolved(Exception):
    """
    A target that cannot be shut down, for a reason the user should see:
    'failed' unless it exists but has already finished ('skipped'), in which
    case 'entity' is what was found, to be recorded by its ID and name.
    """

    def __init__(
        self, message: str, outcome: str = "failed", entity: object | None = None
    ):
        super().__init__(message)
        self.outcome = outcome
        self.entity = entity


@main_wrapper
def main():
    shut_down(ARGS_PARSER.worker_pool_nodes_list or [])


def shut_down(names: list[str]):
    """
    Shut down the Worker Pools and Nodes named, or those matching the glob
    patterns given, or, given nothing, the Worker Pools whose names include
    the tag.
    """
    globs = [n for n in names if contains_glob_chars(n)]

    if names and not globs:
        shutdown_by_names_or_ids(names)
        return

    if globs:
        print_info(
            f"Shutting down Worker Pools "
            f"{describe_glob_scope(globs, CONFIG_COMMON.namespace)}"
        )
        worker_pool_summaries: list[WorkerPoolSummary] = expand_name_globs(
            globs,
            CONFIG_COMMON.namespace,
            fetch=lambda namespace, prefix: get_worker_pool_summaries(
                CLIENT, namespace, prefix or None, partial_name_matches=True
            ),
        )
    else:
        print_info(
            "Shutting down Worker Pools in "
            f"namespace '{CONFIG_COMMON.namespace}' with "
            f"names including '{CONFIG_COMMON.name_tag}'"
        )
        worker_pool_summaries = [
            worker_pool_summary
            for worker_pool_summary in get_worker_pool_summaries(
                CLIENT,
                CONFIG_COMMON.namespace,
                CONFIG_COMMON.name_tag,
                partial_name_matches=True,
            )
            if worker_pool_summary.name is not None
            and worker_pool_summary.namespace == CONFIG_COMMON.namespace
            and CONFIG_COMMON.name_tag in worker_pool_summary.name
        ]

    worker_pool_summaries = [
        worker_pool_summary
        for worker_pool_summary in worker_pool_summaries
        if not _is_finished(worker_pool_summary)
    ]

    if ARGS_PARSER.dry_run:
        report_dry_run(
            CLIENT,
            worker_pool_summaries,
            "Worker Pool",
            "shut down",
            ET_WORKER_POOLS,
            _SHUTDOWN,
            bool(ARGS_PARSER.json_output),
        )
        if ARGS_PARSER.terminate:
            _report_terminations_dry_run(worker_pool_summaries)
        return

    selected: list[WorkerPoolSummary] = (
        select(CLIENT, worker_pool_summaries) if worker_pool_summaries else []
    )

    if selected and not confirmed(_confirmation(selected, [])):
        for worker_pool_summary in selected:
            _record(worker_pool_summary, "skipped")
        selected = []

    _carry_out(list(selected), [])


def _is_finished(worker_pool: _Pool) -> bool:
    return worker_pool.status is not None and worker_pool.status.finished


def _report_terminations_dry_run(worker_pool_summaries: list[WorkerPoolSummary]):
    """
    Under '--dry-run --terminate', report the Compute Requirements that would
    be terminated with the Worker Pools: those of the Provisioned ones.
    """
    for worker_pool_summary in worker_pool_summaries:
        worker_pool = get_worker_pool_by_id(CLIENT, cast(str, worker_pool_summary.id))
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


def shutdown_by_names_or_ids(names_or_ids: list[str]):
    """
    Shut down Worker Pools and/or Nodes by their names or IDs.
    """
    targets = list(dict.fromkeys(names_or_ids))  # In order, without duplicates
    pools: list[WorkerPool] = []
    nodes: list[Node] = []

    for index, target in enumerate(targets):
        entity_type = ET_NODES if _is_node(target) else ET_WORKER_POOLS
        try:
            resolved = _resolve(target)
        except _Unresolved as e:
            (print_warning if e.outcome == "skipped" else print_error)(str(e))
            _record(e.entity or target, e.outcome, str(e), entity_type)
            continue
        except Exception as e:
            print_error(f"Unable to shut down '{target}': {e}")
            _record(target, "failed", str(e), entity_type)
            if classify(e) in SESSION_FAILURES:
                not_attempted = targets[index + 1 :]
                _warn_not_attempted(len(not_attempted) + len(pools) + len(nodes))
                for pool in pools:
                    _record(pool, "skipped", f"not attempted: {e}")
                for node in nodes:
                    _record(node, "skipped", f"not attempted: {e}", ET_NODES)
                for remaining in not_attempted:
                    _record(
                        remaining,
                        "skipped",
                        f"not attempted: {e}",
                        ET_NODES if _is_node(remaining) else ET_WORKER_POOLS,
                    )
                raise ReportedFailure(e)
            continue

        if entity_type == ET_NODES:
            if all(node.id != resolved.id for node in nodes):
                nodes.append(cast(Node, resolved))
        elif all(pool.id != resolved.id for pool in pools):  # e.g. name and ID
            pools.append(cast(WorkerPool, resolved))

    if not pools and not nodes:
        print_info("No Worker Pools or Nodes shut down")
        return

    if not confirmed(_confirmation(pools, nodes)):
        for pool in pools:
            _record(pool, "skipped")
        for node in nodes:
            _record(node, "skipped", entity_type=ET_NODES)
        print_info("No Worker Pools or Nodes shut down")
        return

    _carry_out(list(pools), nodes)


def _is_node(target: str) -> bool:
    return get_ydid_type(target) == YDIDType.NODE


def _resolve(target: str) -> WorkerPool | Node:
    """
    The Worker Pool or Node a target names, raising _Unresolved if it cannot
    be shut down. Anything else raised is a failure of the lookup itself.
    """
    if _is_node(target):
        try:
            node: Node = CLIENT.worker_pool_client.get_node_by_id(target)
        except Exception as e:
            if is_http_not_found(e):
                raise _Unresolved(f"Cannot find Node {target}") from e
            raise
        if node.status == NodeStatus.TERMINATED:
            raise _Unresolved(f"Node {target} is already TERMINATED", "skipped", node)
        return node

    if get_ydid_type(target) == YDIDType.WORKER_POOL:
        worker_pool_id: str | None = target
    else:
        worker_pool_id = get_worker_pool_id_by_name(
            CLIENT, target, CONFIG_COMMON.namespace
        )
        if worker_pool_id is None:
            raise _Unresolved(f"Cannot find Worker Pool '{target}'")
    try:
        worker_pool = get_worker_pool_by_id(CLIENT, cast(str, worker_pool_id))
    except Exception as e:
        if is_http_not_found(e):
            raise _Unresolved(f"Cannot find Worker Pool {worker_pool_id}") from e
        raise
    if _is_finished(worker_pool):
        raise _Unresolved(
            f"Worker Pool '{worker_pool.name}' is already {worker_pool.status}",
            "skipped",
            worker_pool,
        )
    return worker_pool


def _confirmation(pools: list, nodes: list[Node]) -> str:
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
        if ARGS_PARSER.terminate and pools
        else ""
    )
    return f"Shut down {' and '.join(parts)}{terminating}?"


def _warn_not_attempted(count: int):
    if count:
        print_warning(
            f"Not attempting the remaining {count} item(s),"
            " which would fail in the same way"
        )


def _carry_out(pools: list[_Pool], nodes: list[Node]):
    """
    Shut down confirmed Worker Pools (terminating their Compute Requirements,
    with '--terminate'), then Nodes; report, and follow the pools shut down.
    """
    work: list[tuple[str, object]] = []
    work.extend((ET_WORKER_POOLS, pool) for pool in pools)
    work.extend((ET_NODES, node) for node in nodes)
    shut_down_pool_ids: list[str] = []
    nodes_shut_down = 0

    for index, (entity_type, target) in enumerate(work):
        try:
            if entity_type == ET_WORKER_POOLS:
                _shut_down_pool(cast(_Pool, target), shut_down_pool_ids)
            elif _shut_down_node(cast(Node, target)):
                nodes_shut_down += 1
        except _SessionFailure as e:
            not_attempted = work[index + 1 :]
            _warn_not_attempted(len(not_attempted))
            for remaining_type, remaining in not_attempted:
                _record(
                    remaining, "skipped", f"not attempted: {e.cause}", remaining_type
                )
            raise ReportedFailure(e.cause)

    if shut_down_pool_ids or nodes_shut_down:
        if shut_down_pool_ids:
            print_info(f"Shut down {len(shut_down_pool_ids)} Worker Pool(s)")
        if nodes_shut_down:
            print_info(f"Shut down {nodes_shut_down} Node(s)")
        if ARGS_PARSER.follow and shut_down_pool_ids:
            follow_ids(shut_down_pool_ids, auto_cr=ARGS_PARSER.auto_cr)
    else:
        print_info("No Worker Pools or Nodes shut down")


def _failed(target: object, entity_type: str, message: str, e: Exception):
    """
    Report and record a failure, raising _SessionFailure if nothing further
    can succeed.
    """
    print_error(f"{message}: {e}")
    _record(target, "failed", str(e), entity_type)
    if classify(e) in SESSION_FAILURES:
        raise _SessionFailure(e) from e


def _shut_down_node(node: Node) -> bool:
    try:
        CLIENT.worker_pool_client.shutdown_node_by_id(cast(str, node.id))
    except Exception as e:
        _failed(node, ET_NODES, f"Failed to shut down Node {node.id}", e)
        return False
    print_info(f"Shut down Node {node.id}")
    _record(node, _SHUT_DOWN, entity_type=ET_NODES)
    return True


def _shut_down_pool(pool: _Pool, shut_down_pool_ids: list[str]):
    """
    Shut down a Worker Pool and, with '--terminate', terminate its Compute
    Requirement, adding its ID to 'shut_down_pool_ids' if it was shut down.
    """
    pool_id = cast(str, pool.id)
    try:
        CLIENT.worker_pool_client.shutdown_worker_pool_by_id(pool_id)
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
            else get_worker_pool_by_id(CLIENT, pool_id)
        )
    except Exception as e:
        print_info(f"Shut down Worker Pool '{pool.name}'")
        if ARGS_PARSER.terminate:
            print_error(
                "Unable to find the Compute Requirement of Worker Pool"
                f" '{pool.name}': {e}"
            )
            _record_termination({"id": None, "name": None}, pool_id, "failed", str(e))
            if classify(e) in SESSION_FAILURES:
                raise _SessionFailure(e) from e
        return
    print_info(f"Shut down {link_entity(CONFIG_COMMON.url, worker_pool)}")  # type: ignore[arg-type]

    if ARGS_PARSER.terminate:
        _terminate_compute_requirement(worker_pool)


def _terminate_compute_requirement(worker_pool: WorkerPool):
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
        compute_requirement = CLIENT.compute_client.terminate_compute_requirement_by_id(
            cast(str, cr_id)
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
            raise _SessionFailure(e) from e
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
