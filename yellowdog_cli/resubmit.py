#!/usr/bin/env python3

"""
A script to resubmit a Work Requirement's failed (and optionally aborted)
Tasks: submitted as a new Work Requirement, or written to a file that
'yd workrequirement submit --json-raw' takes. The Tasks are read from the
Platform and copied as they are, by utils/resubmission.py; the new Work
Requirement is submitted by utils/json_raw.py's submit_platform_document(),
so nothing is substituted in the copies.
"""

import json
from typing import cast

from yellowdog_client.model import WorkRequirement

from yellowdog_cli.utils.add_target import work_requirement_to_add_to
from yellowdog_cli.utils.atomic_write import write_text_atomically
from yellowdog_cli.utils.config_types import ConfigWorkRequirement
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import ET_WORK_REQUIREMENTS
from yellowdog_cli.utils.entity_utils import (
    AmbiguousNameError,
    get_work_requirement_summary_by_name_or_id,
)
from yellowdog_cli.utils.exit_codes import NotFoundError
from yellowdog_cli.utils.follow_utils import (
    follow_events,
    follow_work_requirement_with_progress,
)
from yellowdog_cli.utils.json_raw import add_platform_tasks, submit_platform_document
from yellowdog_cli.utils.lazy import lazy, value
from yellowdog_cli.utils.load_config import load_config_work_requirement
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.printing import (
    counted,
    print_dry_run,
    print_info,
    print_quiet_result,
    print_warning,
)
from yellowdog_cli.utils.resource_exporters import written_raw
from yellowdog_cli.utils.resubmission import (
    Selection,
    extension_plan,
    print_selection_warnings,
    refuse_task_name_clashes,
    resubmission_document,
    resubmission_name,
    select_tasks,
    selected_statuses,
)
from yellowdog_cli.utils.results import record, record_entity
from yellowdog_cli.utils.task_batches import parallel_batch_count
from yellowdog_cli.utils.wrapper import main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

CONFIG_WR: ConfigWorkRequirement = lazy(load_config_work_requirement)


@main_wrapper
def main(ctx: RunContext):
    resubmit(ctx, value(CONFIG_WR))


def resubmit(ctx: RunContext, config_wr: ConfigWorkRequirement) -> None:
    """
    Resubmit the Tasks the command line selects, as it asks, with the batch
    size and parallelism of the '[workRequirement]' configuration.
    """
    work_requirement = _original(ctx)
    statuses = selected_statuses(bool(ctx.args.failed), bool(ctx.args.aborted))
    selection = select_tasks(ctx, work_requirement, statuses)
    print_selection_warnings(selection)

    where = f"'{work_requirement.namespace}/{work_requirement.name}'"
    status_words = " and ".join(statuses)
    if selection.task_count == 0:
        print_info(f"No {status_words} Tasks to resubmit in Work Requirement {where}")
        return
    print_info(
        f"Resubmitting {counted(selection.task_count, 'Task')} ({status_words})"
        f" from {counted(len(selection.groups), 'Task Group')} of Work Requirement"
        f" {where} ({work_requirement.id})"
    )

    if ctx.args.add_to is not None:
        _resubmit_to(ctx, config_wr, selection, ctx.args.add_to)
        return

    name = ctx.args.resubmit_name or resubmission_name(
        ctx, cast(str, work_requirement.namespace), work_requirement.name
    )
    document = resubmission_document(selection, name)
    extra = {
        "resubmittedFrom": work_requirement.id,
        "taskCount": selection.task_count,
    }

    if ctx.args.export_file is not None:
        if ctx.args.dry_run:
            print_dry_run(
                f"Would write the new Work Requirement to '{ctx.args.export_file}'"
            )
        else:
            _write_document(ctx.args.export_file, document, extra)
            return

    # A dry run shows the document as '-o' would write it
    submit_platform_document(
        ctx,
        written_raw(document) if ctx.args.dry_run else document,
        batch_size=config_wr.task_batch_size,
        parallel_batches=parallel_batch_count(ctx, config_wr.parallel_batches),
        follow=lambda wr_id: _follow(ctx, wr_id),
        record_extra=extra,
    )


def _original(ctx: RunContext) -> WorkRequirement:
    """
    The Work Requirement whose Tasks are resubmitted, in full, found by name
    or ID as the other 'yd wr' verbs find one.
    """
    target = cast(str, ctx.args.resubmit_target)
    if get_ydid_type(target) == YDIDType.WORK_REQUIREMENT:
        try:
            return ctx.client.work_client.get_work_requirement_by_id(target)
        except Exception as e:
            if is_http_not_found(e):
                raise NotFoundError(f"Cannot find Work Requirement '{target}'") from e
            raise
    try:
        summary = get_work_requirement_summary_by_name_or_id(
            ctx.client, target, ctx.config.namespace
        )
    except AmbiguousNameError as e:
        raise ValueError(str(e)) from e
    if summary is None:
        raise NotFoundError(f"Cannot find Work Requirement '{target}'")
    return ctx.client.work_client.get_work_requirement_by_id(cast(str, summary.id))


def _write_document(filename: str, document: dict, extra: dict) -> None:
    """
    Write the new Work Requirement as 'yd wr submit --json-raw' takes it,
    every '{{...}}' written raw, which that command would otherwise
    substitute.
    """
    write_text_atomically(
        filename,
        json.dumps(written_raw(document), indent=2, ensure_ascii=False) + "\n",
    )
    print_info(
        f"Wrote Work Requirement '{document['namespace']}/{document['name']}'"
        f" ({counted(extra['taskCount'], 'Task')}) to '{filename}'"
    )
    record({"file": filename, **extra})


def _follow(ctx: RunContext, wr_id: str) -> None:
    """
    Follow the new Work Requirement, if '--progress' or '--follow' asks.
    """
    if ctx.args.progress:
        follow_work_requirement_with_progress(ctx, wr_id)
    elif ctx.args.follow:
        print_info("Following Work Requirement event stream")
        follow_events(ctx, wr_id, YDIDType.WORK_REQUIREMENT)


def _resubmit_to(
    ctx: RunContext,
    config_wr: ConfigWorkRequirement,
    selection: Selection,
    target_name: str,
) -> None:
    """
    Add the selected Tasks to the existing Work Requirement 'target_name'.
    Everything that can be refused is, before anything is written: a target
    that cannot take Tasks, a task type a matched Task Group lacks, a Task
    name a matched Task Group already holds. A failure part-way cancels
    nothing, the target not being ours to cancel.
    """
    target = work_requirement_to_add_to(ctx, target_name)
    new_groups, task_lists = extension_plan(target, selection)
    refuse_task_name_clashes(ctx, target, task_lists)
    where = f"'{target.namespace}/{target.name}'"

    if ctx.args.dry_run:
        print_dry_run(
            f"Would add {counted(selection.task_count, 'Task')} to existing Work"
            f" Requirement {where}, appending {counted(len(new_groups), 'Task Group')}"
        )
        record_entity(
            target.id,
            target.name,
            target.namespace,
            ET_WORK_REQUIREMENTS,
            resubmittedFrom=selection.work_requirement.id,
            taskCount=selection.task_count,
            appendedTaskGroups=[group.name for group in new_groups],
        )
        return

    if new_groups:
        target.taskGroups = [*(target.taskGroups or []), *new_groups]
        target = ctx.client.work_client.update_work_requirement(target)
        print_info(
            f"Added {counted(len(new_groups), 'new Task Group')} to existing Work"
            f" Requirement {where}"
        )
    record_entity(
        target.id,
        target.name,
        target.namespace,
        ET_WORK_REQUIREMENTS,
        resubmittedFrom=selection.work_requirement.id,
        taskCount=selection.task_count,
    )
    print_quiet_result(target.id)
    try:
        add_platform_tasks(
            ctx,
            cast(str, target.namespace),
            target.name,
            task_lists,
            config_wr.task_batch_size,
            parallel_batch_count(ctx, config_wr.parallel_batches),
        )
    except (Exception, KeyboardInterrupt):
        print_warning(
            f"Adding to Work Requirement {where} failed part-way: any Tasks"
            " already added remain in it"
        )
        raise
    _follow(ctx, cast(str, target.id))


if __name__ == "__main__":
    main()
