#!/usr/bin/env python3

"""
A script to resize Worker Pools and Compute Requirements.
"""

from typing import cast

from yellowdog_client.model import (
    ComputeRequirement,
    ComputeRequirementStatus,
    ComputeRequirementSummary,
    WorkerPool,
)

from yellowdog_cli.utils.entity_utils import (
    get_compute_requirement_summaries,
    get_worker_pool_id_by_name,
)
from yellowdog_cli.utils.follow_utils import follow_events, follow_ids
from yellowdog_cli.utils.interactive import confirmed
from yellowdog_cli.utils.printing import print_dry_run, print_info, print_warning
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.settings import (
    DRY_RUN_MARKER,
    ET_COMPUTE_REQUIREMENTS,
    ET_WORKER_POOLS,
)
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON, main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type


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


@main_wrapper
def main():
    if ARGS_PARSER.compute_req_resize:
        _resize_compute_requirement()
    else:
        _resize_worker_pool()


def _resize_worker_pool():
    """
    Resize a Worker Pool
    """
    action = f"{DRY_RUN_MARKER}Would resize" if ARGS_PARSER.dry_run else "Resizing"
    print_info(
        f"{action} Worker Pool '{ARGS_PARSER.worker_pool_name}' to"
        f" {ARGS_PARSER.worker_pool_size:,d} node(s)"
    )
    if get_ydid_type(ARGS_PARSER.worker_pool_name) == YDIDType.WORKER_POOL:
        worker_pool_id = ARGS_PARSER.worker_pool_name
    else:
        worker_pool_id = get_worker_pool_id_by_name(
            CLIENT,
            ARGS_PARSER.worker_pool_name,  # type: ignore[arg-type]
            namespace=CONFIG_COMMON.namespace,
        )
        if worker_pool_id is None:
            _record(
                ARGS_PARSER.worker_pool_name, ET_WORKER_POOLS, "failed", "not found"
            )
            raise KeyError(f"Worker Pool '{ARGS_PARSER.worker_pool_name}' not found")

    worker_pool: WorkerPool = CLIENT.worker_pool_client.get_worker_pool_by_id(
        worker_pool_id=worker_pool_id  # type: ignore[arg-type]
    )

    if ARGS_PARSER.dry_run:
        print_dry_run(f"Found Worker Pool '{worker_pool.id}'")
        print_dry_run("Complete")
        _record(worker_pool, ET_WORKER_POOLS, "would resize")
        return

    if not confirmed(
        f"Confirm resize Worker Pool to {ARGS_PARSER.worker_pool_size} node(s)?"
    ):
        _record(worker_pool, ET_WORKER_POOLS, "skipped")
        return

    try:
        CLIENT.worker_pool_client.resize_worker_pool(
            worker_pool=worker_pool,  # type: ignore[arg-type]
            size=ARGS_PARSER.worker_pool_size,  # type: ignore[arg-type]
        )
    except Exception as e:
        _record(worker_pool, ET_WORKER_POOLS, "failed", str(e))
        raise
    _record(worker_pool, ET_WORKER_POOLS, "resized")
    print_info(
        f"Resized Worker Pool '{ARGS_PARSER.worker_pool_name}' to"
        f" {ARGS_PARSER.worker_pool_size:,d} node(s)"
    )

    if ARGS_PARSER.follow:
        print_info("Following event stream(s)")
        follow_ids([cast(str, worker_pool.id)], auto_cr=ARGS_PARSER.auto_cr)


def _resize_compute_requirement():
    """
    Resize a Compute Requirement
    """
    action = (
        f"{DRY_RUN_MARKER}Would resize"
        if ARGS_PARSER.dry_run
        else "Attempting to resize"
    )
    print_info(
        f"{action} Compute Requirement '{ARGS_PARSER.worker_pool_name}' "
        f"to {ARGS_PARSER.worker_pool_size:,d} instance(s)"
    )
    print_info(
        f"Finding Compute Requirement in Namespace '{CONFIG_COMMON.namespace}' "
        f"with status '{ComputeRequirementStatus.RUNNING}'"
    )

    cr_summaries: list[ComputeRequirementSummary] = get_compute_requirement_summaries(
        CLIENT,
        namespace=CONFIG_COMMON.namespace,
        tag=None,
        statuses=[ComputeRequirementStatus.RUNNING],
    )

    for cr_summary in cr_summaries:
        if ARGS_PARSER.worker_pool_name not in [cr_summary.name, cr_summary.id]:
            continue

        print_info(
            "Current target/expected instance counts ="
            f" {cr_summary.targetInstanceCount:,d}/"
            f"{cr_summary.expectedInstanceCount:,d}"
        )

        if cr_summary.targetInstanceCount == ARGS_PARSER.worker_pool_size:
            print_info("No resize attempted: target instance count would be unchanged")
            _record(cr_summary, ET_COMPUTE_REQUIREMENTS, "skipped")
            return

        if ARGS_PARSER.dry_run:
            print_dry_run(f"Found Compute Requirement '{cr_summary.id}'")
            print_dry_run("Complete")
            _record(cr_summary, ET_COMPUTE_REQUIREMENTS, "would resize")
            return

        if not confirmed(
            f"Confirm resize Compute Requirement '{cr_summary.name}'"
            f" to {ARGS_PARSER.worker_pool_size:,d} instance(s)?"
        ):
            _record(cr_summary, ET_COMPUTE_REQUIREMENTS, "skipped")
            return

        try:
            cr: ComputeRequirement = (
                CLIENT.compute_client.get_compute_requirement_by_id(
                    cr_summary.id  # type: ignore[arg-type]
                )
            )
            cr.targetInstanceCount = ARGS_PARSER.worker_pool_size  # type: ignore[misc]
            CLIENT.compute_client.update_compute_requirement(cr, reprovision=False)
        except Exception as e:
            _record(cr_summary, ET_COMPUTE_REQUIREMENTS, "failed", str(e))
            raise
        _record(cr_summary, ET_COMPUTE_REQUIREMENTS, "resized")

        print_info(
            f"Resizing complete: new target instance count = {cr.targetInstanceCount}"
        )

        if ARGS_PARSER.follow:
            if ARGS_PARSER.auto_cr:
                print_warning(
                    "Option '--auto-follow-compute-requirements/-a' is"
                    " ignored when resizing Compute Requirements"
                )
            print_info("Following event stream")
            follow_events(cast(str, cr.id), YDIDType.COMPUTE_REQUIREMENT)

        return

    else:
        _record(
            ARGS_PARSER.worker_pool_name,
            ET_COMPUTE_REQUIREMENTS,
            "failed",
            f"not found or not in status '{ComputeRequirementStatus.RUNNING}'",
        )
        raise KeyError(
            f"Compute Requirement '{ARGS_PARSER.worker_pool_name}' not found or not in "
            f"status '{ComputeRequirementStatus.RUNNING}'"
        )


# Standalone entry point
if __name__ == "__main__":
    main()
