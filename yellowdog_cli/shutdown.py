#!/usr/bin/env python3

"""
A script to shut down Worker Pools and/or Nodes.
"""

from typing import cast

from yellowdog_client.model import (
    ConfiguredWorkerPool,
    ProvisionedWorkerPool,
    WorkerPool,
    WorkerPoolSummary,
)

from yellowdog_cli.utils.dryrun_utils import report_dry_run
from yellowdog_cli.utils.entity_utils import (
    describe_glob_scope,
    expand_name_globs,
    get_worker_pool_by_id,
    get_worker_pool_id_by_name,
    get_worker_pool_summaries,
)
from yellowdog_cli.utils.follow_utils import follow_ids
from yellowdog_cli.utils.glob_utils import contains_glob_chars
from yellowdog_cli.utils.interactive import confirmed, select
from yellowdog_cli.utils.misc_utils import link_entity
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.settings import (
    ET_COMPUTE_REQUIREMENTS,
    ET_NODES,
    ET_WORKER_POOLS,
)
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON, main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

# The '--json' record's action and outcome
_SHUTDOWN = "shutdown"
_SHUT_DOWN = "shut down"


def _record(
    entity: object,
    outcome: str,
    error: str | None = None,
    entity_type: str = ET_WORKER_POOLS,
) -> None:
    record_action(entity, entity_type, _SHUTDOWN, outcome, error)


@main_wrapper
def main():
    names = ARGS_PARSER.worker_pool_nodes_list or []
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
        selected_worker_pool_summaries: list[WorkerPoolSummary] = [
            wp
            for wp in worker_pool_summaries
            if not wp.status.finished  # type: ignore[union-attr]
        ]
    else:
        print_info(
            "Shutting down Worker Pools in "
            f"namespace '{CONFIG_COMMON.namespace}' with "
            f"names including '{CONFIG_COMMON.name_tag}'"
        )

        worker_pool_summaries = get_worker_pool_summaries(
            CLIENT,
            CONFIG_COMMON.namespace,
            CONFIG_COMMON.name_tag,
            partial_name_matches=True,
        )

        selected_worker_pool_summaries = []
        for worker_pool_summary in worker_pool_summaries:
            if not worker_pool_summary.status.finished:  # type: ignore[union-attr]
                if (
                    worker_pool_summary.name is not None
                    and worker_pool_summary.namespace == CONFIG_COMMON.namespace
                    and CONFIG_COMMON.name_tag in worker_pool_summary.name
                ):
                    selected_worker_pool_summaries.append(worker_pool_summary)

    shutdown_count = 0

    if ARGS_PARSER.dry_run:
        report_dry_run(
            CLIENT,
            selected_worker_pool_summaries,
            "Worker Pool",
            "shut down",
            ET_WORKER_POOLS,
            _SHUTDOWN,
            bool(ARGS_PARSER.json_output),
        )
        return

    if selected_worker_pool_summaries:
        selected_worker_pool_summaries = select(CLIENT, selected_worker_pool_summaries)

    if selected_worker_pool_summaries and not confirmed(
        f"Shutdown {len(selected_worker_pool_summaries)} Worker Pool(s)?"
    ):
        for worker_pool_summary in selected_worker_pool_summaries:
            _record(worker_pool_summary, "skipped")
        selected_worker_pool_summaries = []

    for worker_pool_summary in selected_worker_pool_summaries:
        try:
            CLIENT.worker_pool_client.shutdown_worker_pool_by_id(
                worker_pool_summary.id  # type: ignore[arg-type]
            )
        except Exception as e:
            print_error(f"Failed to shut down '{worker_pool_summary.name}': {e}")
            _record(worker_pool_summary, "failed", str(e))
            continue
        shutdown_count += 1
        _record(worker_pool_summary, _SHUT_DOWN)
        # The refetch is only needed to generate the link; the shutdown has
        # already succeeded
        try:
            worker_pool: WorkerPool = get_worker_pool_by_id(
                CLIENT, cast(str, worker_pool_summary.id)
            )
            print_info(
                f"Shut down {link_entity(CONFIG_COMMON.url, cast(ConfiguredWorkerPool, worker_pool))}"
            )
        except Exception:
            print_info(f"Shut down Worker Pool '{worker_pool_summary.name}'")
        optionally_terminate_compute_requirement(cast(str, worker_pool_summary.id))

    if shutdown_count > 0:
        print_info(f"Shut down {shutdown_count} Worker Pool(s)")
        if ARGS_PARSER.follow:
            follow_ids(
                [cast(str, wp.id) for wp in selected_worker_pool_summaries],
                auto_cr=ARGS_PARSER.auto_cr,
            )
    else:
        print_info("No Worker Pools shut down")


def shutdown_by_names_or_ids(names_or_ids: list[str]):
    """
    Shutdown Worker Pools and/or Nodes by their names or IDs.
    """
    worker_pool_ids: list[str] = []
    node_ids: list[str] = []

    for name_or_id in set(names_or_ids):  # Remove duplicates
        ydid_type = get_ydid_type(name_or_id)
        if ydid_type == YDIDType.NODE:
            node_ids.append(name_or_id)
            continue
        if ydid_type == YDIDType.WORKER_POOL:
            worker_pool_id = name_or_id
        else:
            worker_pool_id = get_worker_pool_id_by_name(
                CLIENT, name_or_id, CONFIG_COMMON.namespace
            )
            if worker_pool_id is None:
                print_warning(f"Worker Pool '{name_or_id}' not found")
                _record(name_or_id, "failed", "not found")
                continue
        worker_pool_ids.append(worker_pool_id)

    if not worker_pool_ids and not node_ids:
        print_info("No Worker Pools or Nodes to shut down")
        return

    if not confirmed(
        f"Shut down {len(worker_pool_ids) + len(node_ids)} Worker Pool(s) and/or Node(s)?"
        f": ({', '.join(worker_pool_ids + node_ids)})"
    ):
        for worker_pool_id in worker_pool_ids:
            _record(worker_pool_id, "skipped")
        for node_id in node_ids:
            _record(node_id, "skipped", entity_type=ET_NODES)
        return

    for worker_pool_id in worker_pool_ids:
        try:
            CLIENT.worker_pool_client.shutdown_worker_pool_by_id(worker_pool_id)
        except Exception as e:
            print_error(f"Failed to shut down Worker Pool '{worker_pool_id}': ({e})")
            _record(worker_pool_id, "failed", str(e))
            continue
        print_info(f"Shut down Worker Pool '{worker_pool_id}'")
        _record(worker_pool_id, _SHUT_DOWN)
        optionally_terminate_compute_requirement(worker_pool_id)

    for node_id in node_ids:
        try:
            CLIENT.worker_pool_client.shutdown_node_by_id(node_id)
            print_info(f"Shut down Node '{node_id}'")
            _record(node_id, _SHUT_DOWN, entity_type=ET_NODES)
        except Exception as e:
            print_error(f"Failed to shut down Node '{node_id}': ({e})")
            _record(node_id, "failed", str(e), entity_type=ET_NODES)

    if ARGS_PARSER.follow:
        follow_ids(worker_pool_ids, auto_cr=ARGS_PARSER.auto_cr)


def optionally_terminate_compute_requirement(worker_pool_id: str):
    """
    Optionally terminate the associated compute requirement.
    """
    if not ARGS_PARSER.terminate:
        return

    try:
        worker_pool: ProvisionedWorkerPool = (
            CLIENT.worker_pool_client.get_worker_pool_by_id(worker_pool_id)  # type: ignore[assignment]
        )
    except Exception as e:
        print_error(f"Failed to terminate Compute Requirement: ({e})")
        # Keyed by the Worker Pool's ID, the Compute Requirement's being unknown
        record_action(
            {"id": worker_pool_id, "name": None},
            ET_COMPUTE_REQUIREMENTS,
            "terminate",
            "failed",
            str(e),
        )
        return
    # Recorded by ID, the Compute Requirement's name being unknown here
    cr_record = {"id": worker_pool.computeRequirementId, "name": None}
    try:
        CLIENT.compute_client.terminate_compute_requirement_by_id(
            worker_pool.computeRequirementId  # type: ignore[arg-type]
        )
        print_info(
            f"Terminated associated Compute Requirement '{worker_pool.computeRequirementId}'"
        )
        record_action(cr_record, ET_COMPUTE_REQUIREMENTS, "terminate", "terminated")
    except Exception as e:
        print_error(f"Failed to terminate Compute Requirement: ({e})")
        record_action(cr_record, ET_COMPUTE_REQUIREMENTS, "terminate", "failed", str(e))


# Entry point
if __name__ == "__main__":
    main()
