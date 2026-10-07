#!/usr/bin/env python3

"""
A script to submit a Work Requirement.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from math import ceil
from os.path import dirname
from sys import exit as sys_exit
from typing import cast

from yellowdog_client.model import (
    Task,
    TaskGroup,
    WorkRequirement,
    WorkRequirementStatus,
)

from yellowdog_cli.utils.config_types import ConfigWorkRequirement
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.csv_data import (
    csv_expand_toml_tasks,
)
from yellowdog_cli.utils.dataclient.rclone import upgrade_rclone, which_rclone
from yellowdog_cli.utils.entity_names import ET_WORK_REQUIREMENTS
from yellowdog_cli.utils.entity_utils import (
    AmbiguousNameError,
    find_work_requirement_by_name,
)
from yellowdog_cli.utils.exit_codes import (
    NotFoundError,
)
from yellowdog_cli.utils.follow_utils import (
    follow_events,
    follow_work_requirement_with_progress,
    work_requirement_exit_code,
)
from yellowdog_cli.utils.json_raw import submit_json_raw
from yellowdog_cli.utils.lazy import lazy, value
from yellowdog_cli.utils.limits import (
    DEFAULT_PARALLEL_TASK_BATCH_UPLOAD_THREADS,
)
from yellowdog_cli.utils.load_config import (
    config_file_dir,
    load_config_work_requirement,
)
from yellowdog_cli.utils.misc_utils import (
    format_yd_name,
    generate_id,
    is_http_not_found,
    link_entity,
)
from yellowdog_cli.utils.paths import relative_if_possible
from yellowdog_cli.utils.printing import (
    WorkRequirementSnapshot,
    print_dry_run,
    print_error,
    print_info,
    print_quiet_result,
    print_warning,
)
from yellowdog_cli.utils.property_cascade import Cascade
from yellowdog_cli.utils.property_names import (
    FAILURE_POLICY,
    MAX_RETRIES,
    NAME,
    PRIORITY,
    RETRY_POLICY,
    RETRYABLE_ERRORS,
    TASK_COUNT,
    TASK_GROUPS,
    TASKS,
    WR_TAG,
)
from yellowdog_cli.utils.results import record_document, record_entity
from yellowdog_cli.utils.specs.loading import (
    CsvExpansion,
    load_specification,
    refuse_file_options,
)
from yellowdog_cli.utils.specs.schema import Family
from yellowdog_cli.utils.submit_utils import (
    RcloneUploadedFiles,
    formatted_number_str,
    update_config_work_requirement_object,
)
from yellowdog_cli.utils.task_batches import (
    run_batches,
    submit_with_retries,
)
from yellowdog_cli.utils.task_generation import TaskSource, generate_batch_of_tasks
from yellowdog_cli.utils.task_group_position import TaskGroupPosition
from yellowdog_cli.utils.task_groups import (
    check_task_groups,
    create_task_group,
    expand_task_groups,
    promote_task_type,
)
from yellowdog_cli.utils.type_check import (
    check_dict,
    check_float_or_int,
    check_int,
    check_str,
)
from yellowdog_cli.utils.validate_properties import validate_properties
from yellowdog_cli.utils.variable_substitution import (
    add_substitutions_without_overwriting,
    resolve_variables_insitu,
)
from yellowdog_cli.utils.variable_syntax import (
    L_WR_NAME,
)
from yellowdog_cli.utils.wrapper import main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

# The Work Requirement configuration from the TOML file, read on first use
CONFIG_WR: ConfigWorkRequirement = lazy(load_config_work_requirement)


# Generated in main() rather than at import, so that a name tag too long for
# it is reported as an error by main_wrapper rather than as a traceback
@dataclass
class _Submission:
    """
    One yd-submit run: what it runs with (ctx), and its own state, which the
    functions below share and change as the submission proceeds, in place of
    module globals.
    """

    ctx: RunContext
    # The [workRequirement] configuration, re-substituted once the run has
    # named its Work Requirement and Task Groups
    config_wr: ConfigWorkRequirement
    # The Work Requirement's name, generated, then from the specification
    name: str = ""
    # What a dry run reports, built up as the Work Requirement is
    snapshot: WorkRequirementSnapshot = field(default_factory=WorkRequirementSnapshot)
    uploaded_files: RcloneUploadedFiles | None = None
    # The Task batch size, if not the configuration's (as a test sets it)
    task_batch_size: int | None = None
    legacy_retry_warned: bool = False

    @property
    def batch_size(self) -> int:
        """
        The Task batch size: task_batch_size if set, else the configuration's.
        """
        if self.task_batch_size is None:
            return self.config_wr.task_batch_size
        return self.task_batch_size


@main_wrapper
def main(ctx: RunContext):
    run = _Submission(ctx, config_wr=value(CONFIG_WR))

    if ctx.args.upgrade_rclone:
        upgrade_rclone()
        return

    if ctx.args.which_rclone:
        which_rclone()
        return

    run.name = generate_id(ctx.config.name_tag)

    # The task batch size is checked as the configuration is loaded, and
    # the options '--json-raw' cannot be combined with as the command line is
    # parsed ('check_submit_combinations' in the registry)
    if ctx.args.json_raw:
        submit_json_raw(
            ctx,
            ctx.args.json_raw,
            batch_size=run.batch_size,
            parallel_batches=_parallel_batches(run),
            follow=lambda wr_id: _follow(
                run, ctx.client.work_client.get_work_requirement_by_id(wr_id)
            ),
        )
        return

    # Direct file > file supplied using '-r' > file supplied in config file
    wr_data_file = (
        (
            run.config_wr.wr_data_file
            if ctx.args.work_req_file is None
            else ctx.args.work_req_file
        )
        if ctx.args.work_requirement_file_positional is None
        else ctx.args.work_requirement_file_positional
    )

    csv_files = _csv_files(run)

    if csv_files is None and ctx.args.process_csv_only:
        raise ValueError(
            "Option '--process-csv-only' is only valid if CSV file(s) specified"
        )

    # Where do we find the data files?
    # content-path > wr_data_file location > config file location
    files_directory = (
        (config_file_dir() if wr_data_file is None else dirname(wr_data_file))
        if ctx.args.content_path is None
        else ctx.args.content_path
    )

    if wr_data_file is None and csv_files is not None:
        # No specification file: the Work Requirement is built from the TOML
        # configuration and the CSV file, with task-level prototype
        # properties (taskName, taskGroupName, taskTimeout) no file may
        # carry, so there is nothing of the user's to check it against
        refuse_file_options(
            "Work Requirement",
            validate=bool(ctx.args.validate),
            jsonnet_dry_run=bool(ctx.args.jsonnet_dry_run),
        )
        wr_data = _work_requirement_from_csv(run, csv_files, files_directory)
        _submit_or_add_to(run, files_directory=files_directory, wr_data=wr_data)

    elif wr_data_file is not None:
        wr_data = load_specification(
            relative_if_possible(wr_data_file),
            "Work Requirement",
            family=Family.WORK_REQUIREMENT,
            jsonnet_dry_run=bool(ctx.args.jsonnet_dry_run),
            validate=bool(ctx.args.validate),
            # TOML is undocumented
            toml=True,
            csv=(
                None
                if csv_files is None
                else CsvExpansion(
                    csv_files, files_directory, bool(ctx.args.process_csv_only)
                )
            ),
        )
        validate_properties(wr_data, "Work Requirement JSON")
        _submit_or_add_to(run, files_directory=files_directory, wr_data=wr_data)

    else:
        refuse_file_options(
            "Work Requirement",
            validate=bool(ctx.args.validate),
            jsonnet_dry_run=bool(ctx.args.jsonnet_dry_run),
        )
        _submit_or_add_to(
            run, files_directory=files_directory, task_count=run.config_wr.task_count
        )

    if ctx.args.dry_run:
        if ctx.args.json_output:
            record_document(run.snapshot.wr_data)
        else:
            run.snapshot.print()


def _csv_files(run: _Submission) -> list[str] | None:
    """
    The CSV files named, on the command line or else in the configuration;
    None if none is, as 'csvFiles = []' in the configuration names none.
    """
    csv_files = (
        run.config_wr.csv_files
        if run.ctx.args.csv_files is None
        else run.ctx.args.csv_files
    )
    return csv_files or None


def _work_requirement_from_csv(
    run: _Submission, csv_files: list[str], files_directory: str
) -> dict:
    """
    The Work Requirement built from the TOML configuration and a CSV file,
    when there is no specification file. The configuration describes a single
    Task Group, which takes one CSV file; with a specification, a CSV file per
    Task Group is held to the same rule.
    """
    if len(csv_files) > 1:
        raise ValueError(
            f"Number of CSV files ({len(csv_files)}) exceeds number of Task"
            " Groups (1): without a Work Requirement specification file, only"
            " one CSV file can be used"
        )
    return csv_expand_toml_tasks(
        run.config_wr,
        csv_files[0],
        files_directory,
        csv_only=bool(run.ctx.args.process_csv_only),
    )


def _submit_or_add_to(
    run: _Submission,
    files_directory: str,
    wr_data: dict | None = None,
    task_count: int | None = None,
) -> None:
    """
    Route a submission: with '--add-to', into an existing Work Requirement;
    otherwise into a new one. Both honour '--dry-run', though only the former
    needs to read from the platform to do so.
    """
    if run.ctx.args.add_to:
        add_to_existing_work_requirement(
            run,
            files_directory=files_directory,
            wr_data=wr_data,
            task_count=task_count,
        )
    else:
        submit_work_requirement(
            run,
            files_directory=files_directory,
            wr_data=wr_data,
            task_count=task_count,
        )


def submit_work_requirement(
    run: _Submission,
    files_directory: str,
    wr_data: dict | None = None,
    task_count: int | None = None,
):
    """
    Submit a new Work Requirement defined in a 'wr_data' dictionary, or
    with Tasks from the configuration alone when there is none.

    The general principle with configuration properties is that a property set
    at a lower level will override its setting at higher levels, so:

    Task > Task Group > Top-Level JSON Property > TOML config file
    """
    wr_data = _specification(run, wr_data)
    _name_the_run(
        run,
        format_yd_name(
            check_str(
                wr_data.get(
                    NAME,
                    run.name
                    if run.config_wr.wr_name is None
                    else run.config_wr.wr_name,
                ),
                NAME,
            )
        ),
    )
    # Announced before its Task Groups, which announce themselves as they're
    # generated; this is the only report of the name in a dry run
    print_info(f"Generated Work Requirement '{run.name}'")
    task_groups = _task_groups(run, wr_data, files_directory)
    work_requirement = _create_work_requirement(run, wr_data, task_groups)
    _add_tasks(
        run,
        work_requirement,
        [
            _Addition(
                TaskGroupPosition(tg_number, tg_number, len(task_groups)), task_group
            )
            for tg_number, task_group in enumerate(task_groups)
        ],
        wr_data,
        task_count,
        files_directory,
    )
    _follow(run, work_requirement)


def add_to_existing_work_requirement(
    run: _Submission,
    files_directory: str,
    wr_data: dict | None = None,
    task_count: int | None = None,
) -> None:
    """
    Add Task Groups and/or Tasks to the existing Work Requirement that
    '--add-to' names (by name or YellowDog ID): a Task Group of the
    specification named as one already there takes its Tasks, numbered on
    from those it has, and any other is appended to the Work Requirement.
    """
    work_requirement = _work_requirement_to_add_to(run, cast(str, run.ctx.args.add_to))
    existing_tgs: list[TaskGroup] = work_requirement.taskGroups or []
    wr_data = _specification(run, wr_data)
    _name_the_run(run, cast(str, work_requirement.name))
    # Numbered as if each were new: until each Task Group has its name,
    # which the numbering can be part of, which of them are already in the
    # Work Requirement is unknown
    spec_task_groups = _task_groups(
        run, wr_data, files_directory, existing_task_groups=len(existing_tgs)
    )
    work_requirement, additions = _extend_work_requirement(
        run, work_requirement, existing_tgs, spec_task_groups
    )
    _add_tasks(run, work_requirement, additions, wr_data, task_count, files_directory)
    _follow(run, work_requirement)


# The steps the two share, in the order they run


def _specification(run: _Submission, wr_data: dict | None) -> dict:
    """
    The specification to submit, checked: as given, or one Task Group of one
    Task taking everything from the configuration (none with '--empty').
    """
    if wr_data is None:
        wr_data = (
            {TASK_GROUPS: []} if run.ctx.args.empty else {TASK_GROUPS: [{TASKS: [{}]}]}
        )
    check_dict(wr_data)
    check_task_groups(wr_data)
    promote_task_type(wr_data)
    return wr_data


def _name_the_run(run: _Submission, name: str) -> None:
    """
    Name the Work Requirement being submitted or added to, and define the
    lazy substitution of its name, now it is known.
    """
    run.name = name
    add_substitutions_without_overwriting(subs={L_WR_NAME: run.name})


def _task_groups(
    run: _Submission,
    wr_data: dict,
    files_directory: str,
    existing_task_groups: int | None = None,
) -> list[TaskGroup]:
    """
    The specification's Task Groups, built once the configuration and the
    specification have been re-substituted with the Work Requirement's name
    and 'taskGroupCount' has expanded them. 'existing_task_groups' is how
    many the Work Requirement being added to already has, which they are
    numbered on from; None for a new one.
    """
    run.config_wr = update_config_work_requirement_object(run.config_wr)
    resolve_variables_insitu(wr_data)
    run.uploaded_files = RcloneUploadedFiles(run.ctx, files_directory=files_directory)
    expand_task_groups(run.config_wr, wr_data)
    offset = existing_task_groups or 0
    count = offset + len(wr_data[TASK_GROUPS])
    return [
        create_task_group(
            run.config_wr,
            TaskGroupPosition(tg_number, offset + tg_number, count),
            wr_data,
            task_group_data,
            files_directory=files_directory,
            on_legacy_retry=lambda: _warn_legacy_retry_mechanism_once(run),
        )
        for tg_number, task_group_data in enumerate(wr_data[TASK_GROUPS])
    ]


@dataclass
class _Addition:
    """
    Tasks to add to one Task Group: those of the specification's Task Group
    at 'position', into 'task_group'.
    """

    position: TaskGroupPosition
    task_group: TaskGroup


def _create_work_requirement(
    run: _Submission, wr_data: dict, task_groups: list[TaskGroup]
) -> WorkRequirement:
    """
    Create the new Work Requirement with its Task Groups, or in a dry run
    start the snapshot with it.
    """
    priority = Cascade(wr_data).checked(
        PRIORITY, check_float_or_int, run.config_wr.priority
    )
    wr_tag = check_str(
        wr_data.get(
            WR_TAG,
            run.ctx.config.name_tag
            if run.config_wr.wr_tag is None
            else run.config_wr.wr_tag,
        ),
        WR_TAG,
    )
    work_requirement = WorkRequirement(
        namespace=run.ctx.config.namespace,
        name=run.name,
        taskGroups=task_groups,
        tag=wr_tag,
        priority=priority,
    )
    if run.ctx.args.dry_run:
        run.snapshot.set_work_requirement(work_requirement)
        return work_requirement

    work_requirement = run.ctx.client.work_client.add_work_requirement(work_requirement)
    # Recorded now, so a failure adding its Tasks still reports it
    record_entity(
        work_requirement.id,
        work_requirement.name,
        run.ctx.config.namespace,
        ET_WORK_REQUIREMENTS,
    )
    print_quiet_result(work_requirement.id)
    print_info(
        "Created "
        f"{link_entity(run.ctx.config.url, work_requirement)} "
        f"('{run.ctx.config.namespace}/{work_requirement.name}')"
    )
    print_info(f"YellowDog ID is '{work_requirement.id}'")
    return work_requirement


@dataclass
class _Extension:
    """
    How the specification's Task Groups extend a Work Requirement:
    'task_groups', its Task Groups once the 'new' ones are appended, and the
    'additions' of Tasks to make, the new Task Groups' first.
    """

    task_groups: list[TaskGroup]
    new: list[TaskGroup]
    additions: list[_Addition]


def _plan_extension(
    existing_tgs: list[TaskGroup], spec_task_groups: list[TaskGroup]
) -> _Extension:
    """
    The specification's Task Groups matched by name to those the Work
    Requirement already has, which take their Tasks, the rest appended as
    new; a ValueError if a matched one's Tasks need a task type it does not
    allow. Decides everything and does nothing, so it needs no client.
    """
    n_existing = len(existing_tgs)

    # Partition spec TGs: those whose name matches an existing TG (add tasks
    # to existing TG) vs those that are new (add TG to WR first)
    # (spec_idx, spec_tg, existing_idx, existing_tg)
    matched: list[tuple[int, TaskGroup, int, TaskGroup]] = []
    new_tgs: list[tuple[int, TaskGroup]] = []  # (spec_idx, spec_tg)
    for spec_idx, spec_tg in enumerate(spec_task_groups):
        existing_idx = next(
            (i for i, tg in enumerate(existing_tgs) if tg.name == spec_tg.name),
            None,
        )
        if existing_idx is not None:
            matched.append(
                (spec_idx, spec_tg, existing_idx, existing_tgs[existing_idx])
            )
        else:
            new_tgs.append((spec_idx, spec_tg))

    # The Work Requirement's Task Groups once the new ones are appended: what
    # the Tasks' Task Group numbers and count are relative to
    total_tgs = n_existing + len(new_tgs)

    # For matched (existing) Task Groups, the platform does not allow
    # mutating a Task Group's taskTypes after creation. Detect any spec
    # Tasks whose taskType is not in the existing Task Group's allowlist
    # and fail fast with a clear error, rather than letting the platform
    # reject those Tasks downstream.
    for _, spec_tg, _, existing_tg in matched:
        existing_types = set(existing_tg.runSpecification.taskTypes)
        spec_types = set(spec_tg.runSpecification.taskTypes)
        missing_types = spec_types - existing_types
        if missing_types:
            raise ValueError(
                f"Cannot add Tasks to existing Task Group '{existing_tg.name}':"
                f" their task type(s) {sorted(missing_types)} are not in the"
                f" Task Group's taskTypes allowlist {sorted(existing_types)}."
                " A Task Group's taskTypes cannot be modified after creation;"
                " either change the Tasks to use a supported task type, or"
                " add them under a new Task Group name."
            )

    # New TGs take no task offset, numbered by where they were appended;
    # matched (existing) TGs are numbered by their own position, their task
    # numbers following those already there
    additions = [
        _Addition(TaskGroupPosition(spec_idx, n_existing + new_idx, total_tgs), spec_tg)
        for new_idx, (spec_idx, spec_tg) in enumerate(new_tgs)
    ]
    for spec_idx, _, existing_idx, existing_tg in matched:
        task_summary = existing_tg.taskSummary
        additions.append(
            _Addition(
                TaskGroupPosition(
                    spec_idx,
                    existing_idx,
                    total_tgs,
                    task_summary.taskCount if task_summary is not None else 0,
                ),
                existing_tg,
            )
        )
    new = [tg for _, tg in new_tgs]
    return _Extension(existing_tgs + new, new, additions)


def _extend_work_requirement(
    run: _Submission,
    work_requirement: WorkRequirement,
    existing_tgs: list[TaskGroup],
    spec_task_groups: list[TaskGroup],
) -> tuple[WorkRequirement, list[_Addition]]:
    """
    Append to the Work Requirement being added to the specification's Task
    Groups it does not have yet, as _plan_extension() decides, or in a dry
    run start the snapshot with them, and return it with the Tasks to add.
    """
    extension = _plan_extension(existing_tgs, spec_task_groups)

    if run.ctx.args.dry_run:
        # Seed the snapshot with every Task Group the Tasks below will attach
        # to, or the first batch has nothing to attach to. The existing Task
        # Groups' own Tasks can't be shown: the API's Task Group carries a
        # summary of them, not the Tasks themselves -- hence the line saying
        # which of the Task Groups below are already there.
        work_requirement.taskGroups = extension.task_groups
        run.snapshot.set_work_requirement(work_requirement)
        if existing_tgs:
            print_dry_run(
                f"Work Requirement '{run.name}' already contains {len(existing_tgs)}"
                " Task Group(s), shown below without their existing Tasks: "
                + ", ".join(f"'{tg.name}'" for tg in existing_tgs)
            )
        if extension.new:
            print_dry_run(
                f"Would add {len(extension.new)} new Task Group(s) to existing"
                f" Work Requirement '{run.name}'"
            )
        return work_requirement, extension.additions

    # If there are new TGs, update the Work Requirement with the full TG list
    if extension.new:
        work_requirement.taskGroups = extension.task_groups
        work_requirement = run.ctx.client.work_client.update_work_requirement(
            work_requirement
        )
        print_info(
            f"Added {len(extension.new)} new Task Group(s) to existing Work"
            f" Requirement '{run.name}'"
        )

    # The Work Requirement added to, as a creator's document names the one it
    # created
    record_entity(
        work_requirement.id,
        work_requirement.name,
        run.ctx.config.namespace,  # Where it was looked up
        ET_WORK_REQUIREMENTS,
    )
    return work_requirement, extension.additions


def _add_tasks(
    run: _Submission,
    work_requirement: WorkRequirement,
    additions: list[_Addition],
    wr_data: dict,
    task_count: int | None,
    files_directory: str,
) -> None:
    """
    Add the Tasks to their Task Groups, a new Work Requirement first held
    if '--hold' asks. A failure, or an interrupt, part-way cancels a new
    Work Requirement and deletes the files uploaded for it; one being added
    to is left as it is, said so, since the Tasks already added to it stay
    live and may read those files.
    """
    adding = run.ctx.args.add_to is not None
    try:
        # Held before any Task is added, so that none starts; inside the
        # clean-up, as a Work Requirement that cannot be held as asked is
        # one left live without its Tasks
        if not adding and run.ctx.args.hold and not run.ctx.args.dry_run:
            run.ctx.client.work_client.hold_work_requirement(work_requirement)
            print_info("Work Requirement status is set to 'HELD'")

        for addition in additions:
            add_tasks_to_task_group(
                run,
                addition.position,
                task_group=addition.task_group,
                wr_data=wr_data,
                task_count=task_count,
                work_requirement=work_requirement,
                files_directory=files_directory,
            )

    # An interrupt too: Ctrl-C part-way through would otherwise leave a new
    # Work Requirement live with only some of its Tasks
    except (Exception, KeyboardInterrupt):
        if not adding:
            cleanup_on_failure(run, work_requirement)
        elif not run.ctx.args.dry_run:
            print_warning(
                f"Adding to Work Requirement '{run.name}' failed part-way: any Tasks"
                " already added remain in it, and any files uploaded for them"
                " have been left in place"
            )
        raise


def _follow(run: _Submission, work_requirement: WorkRequirement) -> None:
    """
    Follow the Work Requirement, if '--progress' or '--follow' asks.
    """
    if run.ctx.args.progress:
        follow_progress_bar(run, work_requirement)
    elif run.ctx.args.follow:
        follow_progress(run, work_requirement)


# Per-invocation flag so the deprecation warning fires once even when many
# Task Groups use the legacy retry mechanism
def _warn_legacy_retry_mechanism_once(run: _Submission) -> None:
    if run.legacy_retry_warned:
        return
    run.legacy_retry_warned = True
    print_warning(
        f"'{MAX_RETRIES}' and '{RETRYABLE_ERRORS}' are deprecated; "
        f"please use '{RETRY_POLICY}' and (optionally) '{FAILURE_POLICY}' "
        "instead. See the README's 'Task Retries and Failure Policies' section."
    )


def add_tasks_to_task_group(
    run: _Submission,
    position: TaskGroupPosition,
    task_group: TaskGroup,
    wr_data: dict,
    task_count: int | None,
    work_requirement: WorkRequirement,
    files_directory: str = "",
) -> None:
    """
    Add the Tasks of the specification's Task Group at 'position' to
    'task_group', numbered on from any it already holds.
    """
    batch_size = run.batch_size
    task_group_data = wr_data[TASK_GROUPS][position.spec_index]

    num_tasks = len(task_group_data[TASKS])

    # If the 'taskCount' property is set, and there is only one Task
    # in the Task Group, create 'taskCount' duplicates of the Task.
    task_group_task_count = Cascade(wr_data, task_group_data).checked(
        TASK_COUNT, check_int, run.config_wr.task_count
    )
    if task_group_task_count is not None:
        if num_tasks == 1 and task_group_task_count > 1:
            # Expand the number of Tasks to match the specified Task count
            print_info(
                f"Expanding number of Tasks in Task Group '{task_group.name}' to"
                f" '{TASK_COUNT}={task_group_task_count}' Tasks"
            )
            # With 'task_count' given, every Task is generated from the first,
            # so the copies would only be built to go unread
            if task_count is None:
                for _ in range(1, task_group_task_count):
                    task_group_data[TASKS].append(deepcopy(task_group_data[TASKS][0]))
        elif task_group_task_count > 1:
            print_warning(
                f"Note: Task Group '{task_group.name}' already contains"
                f" {num_tasks} Tasks: ignoring expansion using '{TASK_COUNT} ="
                f" {int(task_group_task_count)}'"
            )

    # Determine Task batching
    tasks = task_group_data[TASKS]
    num_tasks = len(tasks) if task_count is None else task_count
    num_task_batches: int = ceil(num_tasks / batch_size)
    if num_task_batches > 1 and not run.ctx.args.dry_run:
        print_info(
            f"Adding Tasks to Task Group '{task_group.name}' in "
            f"{num_task_batches} batches (batch size = {batch_size})"
        )

    # Add lazy substitutions for use in any Task property
    position.substitute(cast(str, task_group.name), num_tasks)

    source = TaskSource(
        config_wr=run.config_wr,
        wr_name=run.name,
        namespace=run.ctx.config.namespace,
        wr_data=wr_data,
        files_directory=files_directory,
        task_group=task_group,
        position=position,
        tasks=tasks,
        task_count=task_count,
        num_tasks=num_tasks,
        uploaded_files=run.uploaded_files,
    )
    num_submitted_tasks = run_batches(
        run.ctx,
        num_tasks,
        batch_size,
        _parallel_batches(run),
        make_batch=lambda start, end: generate_batch_of_tasks(source, start, end),
        send_batch=lambda tasks_list, batch_number, num_batches: (
            submit_batch_of_tasks_to_task_group(
                run,
                tasks_list,
                work_requirement,
                task_group,
                num_batches,
                batch_number,
                batch_size,
                num_tasks,
            )
        ),
    )

    if not run.ctx.args.dry_run:
        if num_submitted_tasks > 0:
            print_info(
                f"Added a total of {num_submitted_tasks:,d} Task(s) to Task Group"
                f" '{task_group.name}'"
            )
        else:
            print_info(f"No Tasks added to Task Group '{task_group.name}'")


def _parallel_batches(run: _Submission) -> int:
    """
    The number of Task batches to upload in parallel: the command line's,
    else the configuration's, else the default.
    """
    for parallel_batches in (
        run.ctx.args.parallel_batches,
        run.config_wr.parallel_batches,
    ):
        if parallel_batches is not None:
            return parallel_batches
    return DEFAULT_PARALLEL_TASK_BATCH_UPLOAD_THREADS


def submit_batch_of_tasks_to_task_group(
    run: _Submission,
    tasks_list: list[Task],
    work_requirement: WorkRequirement,
    task_group: TaskGroup,
    num_task_batches: int,
    batch_number: int,
    task_batch_size: int,
    total_num_tasks: int,
) -> int:
    """
    Submit a batch of tasks to a task group. Return the number of tasks
    submitted.
    """
    if run.ctx.args.dry_run:
        run.snapshot.add_tasks(
            task_group.name, tasks_list, first_task=batch_number * task_batch_size
        )
        return len(tasks_list)

    batch_number_str = formatted_number_str(batch_number, num_task_batches)
    start_task = (batch_number * task_batch_size) + 1
    start_task_str = formatted_number_str(
        start_task, total_num_tasks, zero_indexed=False
    )
    end_task = start_task + len(tasks_list) - 1
    end_task_str = formatted_number_str(end_task, total_num_tasks, zero_indexed=False)
    task_range_str = (
        f"({start_task_str}-{end_task_str}) " if len(tasks_list) > 1 else ""
    )

    def report_success():
        if num_task_batches > 1:
            print_info(
                f"Batch {batch_number_str} :"
                f" Added {len(tasks_list):,d} Task(s) {task_range_str}to Work Requirement Task"
                f" Group '{task_group.name}'"
            )

    def attempt() -> None:
        run.ctx.client.work_client.add_tasks_to_task_group_by_name(
            run.ctx.config.namespace,
            work_requirement.name,
            task_group.name,
            tasks_list,
        )

    submit_with_retries(
        attempt,
        report_success,
        batch=f"batch {batch_number_str} of {num_task_batches}",
        batch_in_full=f"batch {batch_number_str} {task_range_str}of {num_task_batches}",
    )
    return len(tasks_list)


def follow_progress(run: _Submission, work_requirement: WorkRequirement) -> None:
    """
    Follow and report the progress of a Work Requirement.

    With --exit-on-failure, exits non-zero if the outcome is not a success
    (work_requirement_exit_code()), so that a following submission reflects
    the outcome.
    """
    if not run.ctx.args.dry_run:
        print_info("Following Work Requirement event stream")
        wr_id = cast(str, work_requirement.id)
        follow_events(run.ctx, wr_id, YDIDType.WORK_REQUIREMENT)
        _exit_on_failure(run, wr_id)


def follow_progress_bar(run: _Submission, work_requirement: WorkRequirement) -> None:
    """
    Follow a Work Requirement and display a live progress bar.

    With --exit-on-failure, exits non-zero if the outcome is not a success,
    as follow_progress() does.
    """
    if run.ctx.args.dry_run:
        return
    wr_id = cast(str, work_requirement.id)
    follow_work_requirement_with_progress(run.ctx, wr_id)
    _exit_on_failure(run, wr_id)


def _exit_on_failure(run: _Submission, wr_id: str) -> None:
    """
    With --exit-on-failure, exit with the code of a Work Requirement that
    failed, or that could not be followed to its end; without it, the exit
    code reflects the submission alone.
    """
    if run.ctx.args.exit_on_failure and (
        code := work_requirement_exit_code(run.ctx, wr_id)
    ):
        sys_exit(code)


def cleanup_on_failure(run: _Submission, work_requirement: WorkRequirement) -> None:
    """
    Clean up the Work Requirement and any uploaded Objects on failure. Each
    step's own failure is reported and the next step still made, so that the
    failure being cleaned up after, which the caller re-raises, is the one
    the command reports.
    """
    if run.ctx.args.dry_run:
        return

    try:
        run.ctx.client.work_client.cancel_work_requirement(work_requirement)
        print_warning(f"Cancelled Work Requirement '{work_requirement.name}'")
    except Exception as e:
        print_error(f"Unable to cancel Work Requirement '{work_requirement.name}': {e}")

    try:
        run.uploaded_files.delete()  # type: ignore[union-attr]
    except Exception as e:
        print_error(f"Unable to delete the files uploaded for its Tasks: {e}")


# The states of a Work Requirement that can still take Tasks: a FINISHING one
# takes no new ones, and the rest have finished or are being cancelled
_ADDABLE_STATUSES = (WorkRequirementStatus.RUNNING, WorkRequirementStatus.HELD)


def _work_requirement_to_add_to(run: _Submission, target: str) -> WorkRequirement:
    """
    The Work Requirement '--add-to' names, fetched in full: by its YDID,
    whatever its namespace, or by its name, preferring the one that can still
    take Tasks. Raises NotFoundError if there is none, and ValueError if it
    cannot take Tasks (or the name is ambiguous).
    """
    if get_ydid_type(target) == YDIDType.WORK_REQUIREMENT:
        work_requirement_id = target
    else:
        try:
            summary = find_work_requirement_by_name(
                run.ctx.client, target, run.ctx.config.namespace, _ADDABLE_STATUSES
            )
        except AmbiguousNameError as e:
            raise ValueError(str(e)) from e
        work_requirement_id = cast(str, summary.id)
    try:
        work_requirement = run.ctx.client.work_client.get_work_requirement_by_id(
            work_requirement_id
        )
    except Exception as e:
        if is_http_not_found(e):
            raise NotFoundError(f"Cannot find Work Requirement {target}") from e
        raise
    if work_requirement.status not in _ADDABLE_STATUSES:
        raise ValueError(
            f"Work Requirement '{work_requirement.namespace}/{work_requirement.name}'"
            f" is {work_requirement.status}, and cannot take Tasks: only a"
            " RUNNING or HELD one can"
        )
    return work_requirement


# Entry point
if __name__ == "__main__":
    main()
