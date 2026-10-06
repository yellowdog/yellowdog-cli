#!/usr/bin/env python3

"""
A script to submit a Work Requirement.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import timedelta
from math import ceil
from os.path import dirname
from sys import exit as sys_exit
from typing import cast

from yellowdog_client.model import (
    CloudProvider,
    RunSpecification,
    Task,
    TaskGroup,
    TaskTemplate,
    WorkRequirement,
    WorkRequirementStatus,
)
from yellowdog_client.model.instance_pricing_preference import (
    InstancePricingPreference,
)

from yellowdog_cli.utils.config_types import ConfigWorkRequirement
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.csv_data import (
    csv_expand_toml_tasks,
)
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
    work_requirement_failed,
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
    ADD_ENVIRONMENT,
    ADD_YD_ENV_VARS,
    ARGS,
    ARGS_POSTFIX,
    ARGS_PREFIX,
    COMPLETED_TASK_TTL,
    DISABLE_PREALLOCATION,
    ENV,
    FAILURE_POLICY,
    FINISH_IF_ALL_TASKS_FINISHED,
    FINISH_IF_ANY_TASK_FAILED,
    INSTANCE_PRICING_PREFERENCE,
    INSTANCE_TYPES,
    MAX_RETRIES,
    MAX_WORKERS,
    MIN_WORKERS,
    NAME,
    NAMESPACES,
    PRIORITY,
    PROVIDERS,
    RAM,
    REGIONS,
    RETRY_POLICY,
    RETRYABLE_ERRORS,
    SET_TASK_NAMES,
    TASK_COUNT,
    TASK_DATA,
    TASK_DATA_FILE,
    TASK_DATA_FILES,
    TASK_DATA_INPUTS,
    TASK_DATA_OUTPUTS,
    TASK_GROUP_COUNT,
    TASK_GROUP_NAME,
    TASK_GROUP_TAG,
    TASK_GROUPS,
    TASK_LEVEL_TIMEOUT,
    TASK_NAME,
    TASK_TEMPLATE,
    TASK_TIMEOUT,
    TASK_TYPE,
    TASK_TYPES,
    TASKS,
    TASKS_PER_WORKER,
    VCPUS,
    WORKER_TAGS,
    WR_TAG,
)
from yellowdog_cli.utils.rclone_utils import upgrade_rclone, which_rclone
from yellowdog_cli.utils.results import record_document, record_entity
from yellowdog_cli.utils.spec_loading import CsvExpansion, load_specification
from yellowdog_cli.utils.spec_schema import Family
from yellowdog_cli.utils.submit_utils import (
    RcloneUploadedFiles,
    assemble_arguments,
    create_task,
    double_range_from_list,
    formatted_number_str,
    generate_dependencies,
    generate_failure_policy,
    generate_retry_policy,
    generate_task_error_matchers_list,
    generate_taskdata_object,
    get_task_data_property,
    get_task_group_name,
    get_task_name,
    merge_environment,
    resolve_task_data,
    update_config_work_requirement_object,
)
from yellowdog_cli.utils.task_batches import (
    run_batches,
    submit_with_retries,
)
from yellowdog_cli.utils.type_check import (
    check_bool,
    check_dict,
    check_float_or_int,
    check_int,
    check_list,
    check_str,
)
from yellowdog_cli.utils.validate_properties import validate_properties
from yellowdog_cli.utils.variable_substitution import (
    add_or_update_substitution,
    add_substitutions_without_overwriting,
    resolve_variables_insitu,
)
from yellowdog_cli.utils.variable_syntax import (
    L_TASK_COUNT,
    L_TASK_GROUP_COUNT,
    L_TASK_GROUP_NAME,
    L_TASK_GROUP_NUMBER,
    L_TASK_NAME,
    L_TASK_NUMBER,
    L_WR_NAME,
    VAR_NAME_OF_UNNAMED_TASK,
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
        if ctx.args.validate:
            raise ValueError(
                "Option '--validate' needs a Work Requirement specification file"
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
        if ctx.args.validate:
            raise ValueError(
                "Option '--validate' needs a Work Requirement specification file"
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
            _Addition(tg_number, task_group)
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
    expand_task_groups(run, wr_data)
    offset = existing_task_groups or 0
    total = (
        None
        if existing_task_groups is None
        else existing_task_groups + len(wr_data[TASK_GROUPS])
    )
    return [
        create_task_group(
            run,
            tg_number,
            wr_data,
            task_group_data,
            tg_number_offset=offset,
            total_num_task_groups=total,
            files_directory=files_directory,
        )
        for tg_number, task_group_data in enumerate(wr_data[TASK_GROUPS])
    ]


@dataclass
class _Addition:
    """
    Tasks to add to one Task Group: the specification's Task Group
    'tg_number', into 'task_group', which is at 'wr_tg_number' of
    'total_num_task_groups' in the Work Requirement and already holds
    'task_number_offset' Tasks. The defaults are a new Work Requirement's.
    """

    tg_number: int
    task_group: TaskGroup
    wr_tg_number: int | None = None
    total_num_task_groups: int | None = None
    task_number_offset: int = 0


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


def _extend_work_requirement(
    run: _Submission,
    work_requirement: WorkRequirement,
    existing_tgs: list[TaskGroup],
    spec_task_groups: list[TaskGroup],
) -> tuple[WorkRequirement, list[_Addition]]:
    """
    Append to the Work Requirement being added to the specification's Task
    Groups it does not have yet, or in a dry run start the snapshot with
    them, and return it with the Tasks to add: those of the new Task Groups,
    then those of the ones it had already.
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

    all_task_groups = existing_tgs + [tg for _, tg in new_tgs]

    if run.ctx.args.dry_run:
        # Seed the snapshot with every Task Group the Tasks below will attach
        # to, or the first batch has nothing to attach to. The existing Task
        # Groups' own Tasks can't be shown: the API's Task Group carries a
        # summary of them, not the Tasks themselves -- hence the line saying
        # which of the Task Groups below are already there.
        work_requirement.taskGroups = all_task_groups
        run.snapshot.set_work_requirement(work_requirement)
        if existing_tgs:
            print_dry_run(
                f"Work Requirement '{run.name}' already contains {len(existing_tgs)}"
                " Task Group(s), shown below without their existing Tasks: "
                + ", ".join(f"'{tg.name}'" for tg in existing_tgs)
            )
        if new_tgs:
            print_dry_run(
                f"Would add {len(new_tgs)} new Task Group(s) to existing"
                f" Work Requirement '{run.name}'"
            )

    # If there are new TGs, update the Work Requirement with the full TG list
    elif new_tgs:
        work_requirement.taskGroups = all_task_groups
        work_requirement = run.ctx.client.work_client.update_work_requirement(
            work_requirement
        )
        print_info(
            f"Added {len(new_tgs)} new Task Group(s) to existing Work Requirement '{run.name}'"
        )

    if not run.ctx.args.dry_run:
        # The Work Requirement added to, as a creator's document names the
        # one it created
        record_entity(
            work_requirement.id,
            work_requirement.name,
            run.ctx.config.namespace,  # Where it was looked up
            ET_WORK_REQUIREMENTS,
        )

    # New TGs take no task offset, numbered by where they were appended;
    # matched (existing) TGs are numbered by their own position, their task
    # numbers following those already there
    additions = [
        _Addition(spec_idx, spec_tg, n_existing + new_idx, total_tgs)
        for new_idx, (spec_idx, spec_tg) in enumerate(new_tgs)
    ]
    for spec_idx, _, existing_idx, existing_tg in matched:
        task_summary = existing_tg.taskSummary
        additions.append(
            _Addition(
                spec_idx,
                existing_tg,
                existing_idx,
                total_tgs,
                task_summary.taskCount if task_summary is not None else 0,
            )
        )
    return work_requirement, additions


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
                tg_number=addition.tg_number,
                task_group=addition.task_group,
                wr_data=wr_data,
                task_count=task_count,
                work_requirement=work_requirement,
                files_directory=files_directory,
                wr_tg_number=addition.wr_tg_number,
                total_num_task_groups=addition.total_num_task_groups,
                task_number_offset=addition.task_number_offset,
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


def check_task_groups(wr_data: dict) -> None:
    """
    A Work Requirement's 'taskGroups' is a list, each Task Group a table with
    a 'tasks' list, as the schema requires. Checked before anything indexes
    them, so that one missing is named rather than reported as a bare
    KeyError ("ERROR : 'tasks'").
    """
    if TASK_GROUPS not in wr_data:
        raise ValueError(
            f"Property '{TASK_GROUPS}' is not defined (use '--empty' to submit a"
            " Work Requirement with no Task Groups)"
        )
    for tg_number, task_group_data in enumerate(
        check_list(wr_data[TASK_GROUPS], TASK_GROUPS)
    ):
        task_group = f"Task Group {tg_number + 1} of {len(wr_data[TASK_GROUPS])}"
        if not isinstance(task_group_data, dict):
            raise TypeError(f"{task_group} should be of type 'Dict'")
        if TASKS not in task_group_data:
            raise ValueError(f"Property '{TASKS}' is not defined in {task_group}")
        for task_number, task in enumerate(check_list(task_group_data[TASKS], TASKS)):
            if not isinstance(task, dict):
                raise TypeError(
                    f"Task {task_number + 1} in {task_group} should be of type 'Dict'"
                )


def promote_task_type(data: dict) -> None:
    """
    At the Work Requirement or Task Group level, a single 'taskType' stands
    for 'taskTypes', as a convenience, where 'taskTypes' is not set.
    """
    if data.get(TASK_TYPE) is not None and data.get(TASK_TYPES) is None:
        data[TASK_TYPES] = [data[TASK_TYPE]]


def expand_task_groups(run: _Submission, wr_data: dict) -> None:
    """
    Expand a single Task Group into 'taskGroupCount' copies of itself, in
    place. A count given as a whole-valued float ('2.0', which the schema
    accepts as an integer) is taken as that integer; any other non-integer
    is an error.
    """
    task_group_count = Cascade(wr_data).checked(
        TASK_GROUP_COUNT, check_float_or_int, run.config_wr.task_group_count
    )
    if task_group_count is None:
        return
    if isinstance(task_group_count, float):
        if not task_group_count.is_integer():
            raise TypeError(
                f"Property '{TASK_GROUP_COUNT}' value '{task_group_count}'"
                " should be of type 'Integer'"
            )
        task_group_count = int(task_group_count)
    if task_group_count <= 1:
        return

    if len(wr_data[TASK_GROUPS]) == 1:
        print_info(
            f"Expanding number of Task Groups to '{TASK_GROUP_COUNT}="
            f"{task_group_count}'"
        )
        wr_data[TASK_GROUPS] = [
            deepcopy(wr_data[TASK_GROUPS][0]) for _ in range(task_group_count)
        ]
    elif len(wr_data[TASK_GROUPS]) > 1:
        print_warning(
            f"Note: Work Requirement already contains"
            f" {len(wr_data[TASK_GROUPS])} Task Groups: ignoring expansion "
            f"using '{TASK_GROUP_COUNT} = {task_group_count}'"
        )


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


def create_task_group(
    run: _Submission,
    tg_number: int,
    wr_data: dict,
    task_group_data: dict,
    tg_number_offset: int = 0,
    total_num_task_groups: int | None = None,
    files_directory: str = "",
) -> TaskGroup:
    """
    Create a TaskGroup object.

    tg_number_offset: added to tg_number for display/naming purposes when
      adding to an existing Work Requirement.
    total_num_task_groups: total TG count across the WR (existing + new) for
      formatting; defaults to len(wr_data[TASK_GROUPS]).
    """

    promote_task_type(task_group_data)
    # The Task Group's properties, from itself or the Work Requirement; the
    # configuration's, from the copy below, are the defaults
    levels = Cascade(wr_data, task_group_data)

    # Gather task types, in order of first appearance
    task_types_from_tasks = [
        task[TASK_TYPE] for task in task_group_data[TASKS] if TASK_TYPE in task
    ]

    # Name the Task Group
    num_task_groups = (
        total_num_task_groups
        if total_num_task_groups is not None
        else len(wr_data[TASK_GROUPS])
    )
    effective_tg_number = tg_number + tg_number_offset
    num_tasks = len(task_group_data[TASKS])
    if num_tasks == 1:  # Account for Task expansion
        _task_count = levels.checked(TASK_COUNT, check_int, run.config_wr.task_count)
        if _task_count is not None:
            num_tasks = _task_count

    # The following handles possible CSV substitution at the config.toml level
    try:
        if task_group_data.get(NAME) is None:
            task_group_data[NAME] = task_group_data[TASKS][0][TASK_GROUP_NAME]
    except (KeyError, IndexError):
        pass
    task_group_name = format_yd_name(
        get_task_group_name(
            check_str(task_group_data.get(NAME, run.config_wr.task_group_name), NAME),
            effective_tg_number,
            num_task_groups,
            num_tasks,
        )
    )

    # Add lazy substitutions for use in any Task Group property
    add_or_update_substitution(L_TASK_COUNT, str(num_tasks))
    add_or_update_substitution(L_TASK_GROUP_NAME, task_group_name)
    add_or_update_substitution(
        L_TASK_GROUP_NUMBER, formatted_number_str(effective_tg_number, num_task_groups)
    )
    add_or_update_substitution(L_TASK_GROUP_COUNT, str(num_task_groups))
    resolve_variables_insitu(task_group_data)
    # Copy the run's configuration and apply the lazy substitutions to it
    config_wr = update_config_work_requirement_object(deepcopy(run.config_wr))

    # Resolve taskTemplate early so it can satisfy the task-type validation below
    task_template_data = levels.checked(
        TASK_TEMPLATE, check_dict, config_wr.task_template
    )

    # Assemble the RunSpecification values for the Task Group;
    # 'task_types' can automatically be added to by the task_types
    # specified in the Tasks.
    # De-duplicated in order, the declared types first, rather than through a
    # set, whose order varies from run to run with string hashing
    task_types: list = list(
        dict.fromkeys(
            levels.checked(TASK_TYPES, check_list, []) + task_types_from_tasks
        )
    )
    # Use the task type from the config file if present and task_types is empty
    if config_wr.task_type is not None and not task_types:
        task_types.append(config_wr.task_type)
    # Fall back to taskTemplate.taskType if task_types is still empty
    template_provides_type = (
        task_template_data is not None and task_template_data.get(TASK_TYPE) is not None
    )
    if template_provides_type and not task_types:
        task_types.append(task_template_data.get(TASK_TYPE))  # type: ignore[union-attr]
    if not task_types and not template_provides_type and num_tasks > 0:
        raise ValueError(
            f"No Task Type(s) specified in Task Group '{task_group_name}': "
            "is a valid Work Requirement defined?"
        )

    vcpus = levels.checked(VCPUS, double_range_from_list, config_wr.vcpus)
    ram = levels.checked(RAM, double_range_from_list, config_wr.ram)

    providers_data: list[str] | None = levels.checked(
        PROVIDERS, check_list, config_wr.providers
    )
    providers: list[CloudProvider] | None = (
        None
        if providers_data is None
        else [CloudProvider(provider) for provider in providers_data]
    )

    ipp_data: str | None = levels.checked(
        INSTANCE_PRICING_PREFERENCE, check_str, config_wr.instance_pricing_preference
    )
    instance_pricing_preference: InstancePricingPreference | None = (
        None if ipp_data is None else InstancePricingPreference(ipp_data)
    )

    task_timeout_minutes: float | None = levels.checked(
        TASK_TIMEOUT, check_float_or_int, config_wr.task_timeout
    )
    task_timeout: timedelta | None = (
        None
        if task_timeout_minutes is None
        else timedelta(minutes=task_timeout_minutes)
    )

    # Resolve retry/failure policies (new mechanism) and detect any conflict
    # with the deprecated maximumTaskRetries / retryableErrors fields. Only
    # 'retryPolicy' overlaps with the legacy retry mechanism; 'failurePolicy'
    # adds resubmission on top of either retry mechanism and may coexist.
    retry_policy = generate_retry_policy(config_wr, wr_data, task_group_data)
    failure_policy = generate_failure_policy(config_wr, wr_data, task_group_data)

    legacy_retries_set = (
        task_group_data.get(MAX_RETRIES) is not None
        or wr_data.get(MAX_RETRIES) is not None
        or config_wr.max_retries is not None
    )
    legacy_errors_set = (
        task_group_data.get(RETRYABLE_ERRORS) is not None
        or wr_data.get(RETRYABLE_ERRORS) is not None
        or config_wr.retryable_errors is not None
    )
    legacy_in_use = legacy_retries_set or legacy_errors_set

    if retry_policy is not None and legacy_in_use:
        raise ValueError(
            f"'{RETRY_POLICY}' cannot be combined with the deprecated "
            f"'{MAX_RETRIES}' or '{RETRYABLE_ERRORS}'. Pick one mechanism per "
            f"Task Group; '{RETRY_POLICY}' is the supported choice. "
            f"'{FAILURE_POLICY}' may be used alongside either."
        )

    if legacy_in_use:
        _warn_legacy_retry_mechanism_once(run)

    run_specification = RunSpecification(
        taskTypes=task_types,
        maximumTaskRetries=(
            None
            if retry_policy is not None
            else levels.checked(MAX_RETRIES, check_int, config_wr.max_retries or 0)
        ),
        retryPolicy=retry_policy,
        failurePolicy=failure_policy,
        workerTags=levels.checked(WORKER_TAGS, check_list, config_wr.worker_tags),
        instanceTypes=levels.checked(
            INSTANCE_TYPES, check_list, config_wr.instance_types
        ),
        instancePricingPreference=instance_pricing_preference,
        vcpus=vcpus,
        ram=ram,
        minWorkers=levels.checked(MIN_WORKERS, check_int, config_wr.min_workers),
        maxWorkers=levels.checked(MAX_WORKERS, check_int, config_wr.max_workers),
        tasksPerWorker=levels.checked(
            TASKS_PER_WORKER, check_int, config_wr.tasks_per_worker
        ),
        providers=providers,
        regions=levels.checked(REGIONS, check_list, config_wr.regions),
        taskTimeout=task_timeout,
        namespaces=levels.checked(NAMESPACES, check_list, config_wr.namespaces),
        retryableErrors=(
            None
            if retry_policy is not None
            else generate_task_error_matchers_list(config_wr, wr_data, task_group_data)
        ),
        disablePreallocation=levels.checked(
            DISABLE_PREALLOCATION, check_bool, config_wr.disable_preallocation
        ),
    )
    ctttl_data = levels.checked(
        COMPLETED_TASK_TTL, check_float_or_int, config_wr.completed_task_ttl
    )
    completed_task_ttl = None if ctttl_data is None else timedelta(minutes=ctttl_data)

    # Build TaskTemplate object, resolving taskDataFile → taskData if present
    if task_template_data is not None:
        tt = dict(task_template_data)
        try:
            task_data = resolve_task_data(tt, files_directory)
        except ValueError as e:
            raise ValueError(f"taskTemplate: {e}") from e
        tt.pop(TASK_DATA_FILE, None)
        tt.pop(TASK_DATA_FILES, None)
        if task_data is not None:
            tt[TASK_DATA] = task_data
        task_template = TaskTemplate(**tt)
    else:
        task_template = None

    # Create the Task Group
    _finish_all = levels.checked(
        FINISH_IF_ALL_TASKS_FINISHED,
        check_bool,
        config_wr.finish_if_all_tasks_finished,
    )
    task_group = TaskGroup(
        name=task_group_name,
        runSpecification=run_specification,
        dependencies=generate_dependencies(task_group_data),
        finishIfAllTasksFinished=_finish_all if _finish_all is not None else True,
        finishIfAnyTaskFailed=levels.checked(
            FINISH_IF_ANY_TASK_FAILED, check_bool, config_wr.finish_if_any_task_failed
        )
        or False,
        priority=levels.checked(PRIORITY, check_float_or_int, config_wr.priority or 0),
        completedTaskTtl=completed_task_ttl,
        tag=check_str(task_group_data.get(TASK_GROUP_TAG), TASK_GROUP_TAG),
        taskTemplate=task_template,
    )

    print_info(f"Generated Task Group '{task_group_name}'")
    return task_group


def add_tasks_to_task_group(
    run: _Submission,
    tg_number: int,
    task_group: TaskGroup,
    wr_data: dict,
    task_count: int | None,
    work_requirement: WorkRequirement,
    files_directory: str = "",
    wr_tg_number: int | None = None,
    total_num_task_groups: int | None = None,
    task_number_offset: int = 0,
) -> None:
    """
    Add all the constituent Tasks to the Task Group.

    tg_number: the Task Group's index in wr_data[TASK_GROUPS].
    wr_tg_number: the Task Group's (zero-based) position in the Work
      Requirement, for display and naming, when that differs from tg_number
      because Tasks are being added to an existing Work Requirement.
    total_num_task_groups: total TG count (existing + new) for formatting.
    task_number_offset: starting task number within the TG (for adding to an
      existing Task Group that already contains tasks).
    """
    batch_size = run.batch_size

    num_tasks = len(wr_data[TASK_GROUPS][tg_number][TASKS])

    # If the 'taskCount' property is set, and there is only one Task
    # in the Task Group, create 'taskCount' duplicates of the Task.
    task_group_task_count = Cascade(wr_data, wr_data[TASK_GROUPS][tg_number]).checked(
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
                    wr_data[TASK_GROUPS][tg_number][TASKS].append(
                        deepcopy(wr_data[TASK_GROUPS][tg_number][TASKS][0])
                    )
        elif task_group_task_count > 1:
            print_warning(
                f"Note: Task Group '{task_group.name}' already contains"
                f" {num_tasks} Tasks: ignoring expansion using '{TASK_COUNT} ="
                f" {int(task_group_task_count)}'"
            )

    num_task_groups = (
        total_num_task_groups
        if total_num_task_groups is not None
        else len(wr_data[TASK_GROUPS])
    )
    effective_tg_number = tg_number if wr_tg_number is None else wr_tg_number

    # Determine Task batching
    tasks = wr_data[TASK_GROUPS][tg_number][TASKS]
    num_tasks = len(tasks) if task_count is None else task_count
    num_task_batches: int = ceil(num_tasks / batch_size)
    if num_task_batches > 1 and not run.ctx.args.dry_run:
        print_info(
            f"Adding Tasks to Task Group '{task_group.name}' in "
            f"{num_task_batches} batches (batch size = {batch_size})"
        )

    # Add lazy substitutions for use in any Task property
    add_or_update_substitution(L_TASK_COUNT, str(num_tasks))
    add_or_update_substitution(L_TASK_GROUP_NAME, task_group.name)
    add_or_update_substitution(
        L_TASK_GROUP_NUMBER, formatted_number_str(effective_tg_number, num_task_groups)
    )
    add_or_update_substitution(L_TASK_GROUP_COUNT, str(num_task_groups))

    num_submitted_tasks = run_batches(
        run.ctx,
        num_tasks,
        batch_size,
        _parallel_batches(run),
        make_batch=lambda start, end: generate_batch_of_tasks_for_task_group(
            run,
            start,
            end,
            wr_data,
            files_directory,
            task_group,
            effective_tg_number,
            tasks,
            task_count,
            num_tasks,
            num_task_groups,
            task_number_offset=task_number_offset,
            wr_tg_index=tg_number,
        ),
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


def generate_batch_of_tasks_for_task_group(
    run: _Submission,
    start_task_number: int,
    end_task_number: int,
    wr_data: dict,
    files_directory: str,
    task_group: TaskGroup,
    tg_number: int,
    tasks: list,
    task_count: int | None,
    num_tasks: int,
    num_task_groups: int,
    task_number_offset: int = 0,
    wr_tg_index: int | None = None,
) -> list[Task]:
    """
    Generate a batch of tasks for subsequent addition to a task group.

    tg_number: WR-relative display number (already includes any offset).
    task_number_offset: added to task_number for naming when adding to an
      existing Task Group that already contains tasks.
    wr_tg_index: spec-relative index for accessing wr_data[TASK_GROUPS];
      defaults to tg_number when not provided.
    """
    spec_tg_index = wr_tg_index if wr_tg_index is not None else tg_number
    tasks_list: list[Task] = []
    for task_number in range(start_task_number, end_task_number):
        task_group_data = wr_data[TASK_GROUPS][spec_tg_index]
        task = tasks[task_number] if task_count is None else tasks[0]
        # The Task's properties, from itself, its Task Group or the Work
        # Requirement; the configuration's are the defaults
        levels = Cascade(wr_data, task_group_data, task)

        set_task_names = (
            levels.checked(SET_TASK_NAMES, check_bool, run.config_wr.set_task_names)
            or False
        )

        display_task_number = task_number + task_number_offset
        display_num_tasks = task_number_offset + num_tasks

        # The run's configuration, not a per-Task copy: get_task_name() makes the
        # Task-level lazy substitutions in the name itself, and the per-Task
        # copy can only be made once the name it substitutes is known
        task_name = get_task_name(
            check_str(
                task.get(NAME, task.get(TASK_NAME, run.config_wr.task_name)), NAME
            ),
            set_task_names,
            display_task_number,
            display_num_tasks,
            tg_number,
            num_task_groups,
            task_group.name,
        )

        task_name = None if task_name is None else format_yd_name(task_name)

        add_or_update_substitution(
            L_TASK_NAME,
            VAR_NAME_OF_UNNAMED_TASK if task_name is None else task_name,
        )
        add_or_update_substitution(
            L_TASK_NUMBER,
            formatted_number_str(display_task_number, display_num_tasks),
        )
        resolve_variables_insitu(task)
        config_wr = update_config_work_requirement_object(deepcopy(run.config_wr))

        arguments_list = levels.checked(ARGS, check_list, config_wr.args)
        arguments_list = assemble_arguments(
            levels.checked(ARGS_PREFIX, check_list, config_wr.args_prefix),
            arguments_list,
            levels.checked(ARGS_POSTFIX, check_list, config_wr.args_postfix),
        )
        env = merge_environment(
            levels.checked(ENV, check_dict, config_wr.env),
            levels.checked(ADD_ENVIRONMENT, check_dict, config_wr.add_environment),
        )

        add_yd_env_vars = (
            levels.checked(ADD_YD_ENV_VARS, check_bool, config_wr.add_yd_env_vars)
            or False
        )

        # Task timeout is automatically inherited from the Task Group level
        # unless overridden by the Task
        task_timeout_minutes = levels.checked(
            TASK_LEVEL_TIMEOUT, check_float_or_int, config_wr.task_level_timeout
        )
        task_timeout = (
            None
            if task_timeout_minutes is None
            else timedelta(minutes=task_timeout_minutes)
        )

        # Data client inputs and outputs
        task_data_inputs = levels.checked(
            TASK_DATA_INPUTS, check_list, config_wr.task_data_inputs
        )
        task_data_outputs = levels.checked(
            TASK_DATA_OUTPUTS, check_list, config_wr.task_data_outputs
        )
        # This will 'pop' any 'localFile' properties, required for the
        # following 'generate' call
        run.uploaded_files.upload_dataclient_input_files(task_data_inputs)  # type: ignore[union-attr]
        task_data_inputs_and_outputs = generate_taskdata_object(
            task_data_inputs, task_data_outputs
        )

        task_type = _task_type_of(
            task, task_group, config_wr, task_name, display_task_number
        )

        tasks_list.append(
            create_task(
                wr_data=wr_data,
                task_group_data=task_group_data,
                task_data=task,
                task_name=task_name,
                task_number=display_task_number + 1,
                tg_name=task_group.name,
                tg_number=tg_number + 1,
                task_type=cast(str, task_type),
                args=cast(list, arguments_list),
                task_data_property=get_task_data_property(
                    config_wr,
                    wr_data,
                    task_group_data,
                    task,
                    task_name,
                    files_directory,
                ),
                env=env,
                task_timeout=task_timeout,
                add_yd_env_vars=add_yd_env_vars,
                task_data_inputs_and_outputs=task_data_inputs_and_outputs,
                wr_name=run.name,
                namespace=run.ctx.config.namespace,
                total_num_task_groups=num_task_groups,
                total_num_tasks=display_num_tasks,
            )
        )

    return tasks_list


def _task_type_of(
    task: dict,
    task_group: TaskGroup,
    config_wr: ConfigWorkRequirement,
    task_name: str | None,
    task_number: int,
) -> str | None:
    """
    The Task's type: its own, else its Task Group's sole type, else the
    configuration's if the Task Group allows it. Else, None if the Task
    Group's template supplies one; anything else is an error here, rather
    than a Task the Platform refuses.
    """
    if TASK_TYPE in task:
        return task[TASK_TYPE]
    task_types = task_group.runSpecification.taskTypes
    if len(task_types) == 1:
        return task_types[0]
    if config_wr.task_type is not None and config_wr.task_type in task_types:
        return config_wr.task_type
    template = task_group.taskTemplate
    if template is not None and template.taskType is not None:
        return None
    raise ValueError(
        f"Task {task_number + 1}"
        + ("" if task_name is None else f" ('{task_name}')")
        + f" in Task Group '{task_group.name}' has no '{TASK_TYPE}', and the"
        f" Task Group allows several {task_types}: set the Task's '{TASK_TYPE}'"
    )


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

    With --exit-on-failure, exits with code 1 if the Work Requirement ends in
    a failure state (FAILED/CANCELLED), so that a following submission reflects
    the outcome.
    """
    if not run.ctx.args.dry_run:
        print_info("Following Work Requirement event stream")
        wr_id = cast(str, work_requirement.id)
        follow_events(run.ctx, wr_id, YDIDType.WORK_REQUIREMENT)
        if run.ctx.args.exit_on_failure and work_requirement_failed(run.ctx, wr_id):
            sys_exit(1)


def follow_progress_bar(run: _Submission, work_requirement: WorkRequirement) -> None:
    """
    Follow a Work Requirement and display a live progress bar.

    With --exit-on-failure, exits with code 1 if the Work Requirement ends in
    a failure state (FAILED/CANCELLED), so that a following submission reflects
    the outcome.
    """
    if run.ctx.args.dry_run:
        return
    wr_id = cast(str, work_requirement.id)
    follow_work_requirement_with_progress(run.ctx, wr_id)
    if run.ctx.args.exit_on_failure and work_requirement_failed(run.ctx, wr_id):
        sys_exit(1)


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
