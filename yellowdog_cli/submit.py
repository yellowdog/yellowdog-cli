#!/usr/bin/env python3

"""
A script to submit a Work Requirement.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import timedelta
from gzip import compress
from json import dumps as json_dumps
from json import loads as json_loads
from math import ceil
from os.path import dirname
from sys import exit as sys_exit
from typing import cast

import requests
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
    load_json_file_with_csv_task_expansion,
    load_jsonnet_file_with_csv_task_expansion,
    load_toml_file_with_csv_task_expansion,
)
from yellowdog_cli.utils.entity_names import ET_WORK_REQUIREMENTS
from yellowdog_cli.utils.entity_utils import (
    AmbiguousNameError,
    find_work_requirement_by_name,
)
from yellowdog_cli.utils.exit_codes import (
    NotFoundError,
)
from yellowdog_cli.utils.file_substitution import (
    load_json_file_with_variable_substitutions,
    load_jsonnet_file_with_variable_substitutions,
    load_toml_file_with_variable_substitutions,
)
from yellowdog_cli.utils.follow_utils import (
    follow_events,
    follow_work_requirement_with_progress,
    work_requirement_failed,
)
from yellowdog_cli.utils.lazy import lazy, value
from yellowdog_cli.utils.limits import (
    DEFAULT_PARALLEL_TASK_BATCH_UPLOAD_THREADS,
    RAW_REQUEST_TIMEOUT,
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
    print_json,
    print_quiet_result,
    print_warning,
)
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
from yellowdog_cli.utils.spec_schema import Family
from yellowdog_cli.utils.spec_validation import check_specification
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
    raise_for_response,
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
        submit_json_raw(run, ctx.args.json_raw)
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
        if ctx.args.jsonnet_dry_run and not wr_data_file.lower().endswith(".jsonnet"):
            raise ValueError(
                "Option '--jsonnet-dry-run' can only be used with files ending in '.jsonnet'"
            )

        wr_data_file = relative_if_possible(wr_data_file)
        print_info(f"Loading Work Requirement data from: '{wr_data_file}'")

        # JSON file
        if wr_data_file.lower().endswith(".json"):
            if csv_files is not None:
                wr_data = load_json_file_with_csv_task_expansion(
                    json_file=wr_data_file,
                    csv_files=csv_files,
                    files_directory=files_directory,
                    csv_only=bool(ctx.args.process_csv_only),
                )
            else:
                wr_data = load_json_file_with_variable_substitutions(
                    filename=wr_data_file, prefix="", postfix=""
                )

        # Jsonnet file
        elif wr_data_file.lower().endswith(".jsonnet"):
            if csv_files is not None:
                wr_data = load_jsonnet_file_with_csv_task_expansion(
                    jsonnet_file=wr_data_file,
                    csv_files=csv_files,
                    files_directory=files_directory,
                    dry_run=bool(ctx.args.jsonnet_dry_run),
                    csv_only=bool(ctx.args.process_csv_only),
                )
            else:
                wr_data = load_jsonnet_file_with_variable_substitutions(
                    filename=wr_data_file,
                    prefix="",
                    postfix="",
                    dry_run=bool(ctx.args.jsonnet_dry_run),
                )

        # TOML file (undocumented)
        elif wr_data_file.lower().endswith(".toml"):
            if csv_files is not None:
                wr_data = load_toml_file_with_csv_task_expansion(
                    toml_file=wr_data_file,
                    csv_files=csv_files,
                    files_directory=files_directory,
                    csv_only=bool(ctx.args.process_csv_only),
                )
            else:
                wr_data = load_toml_file_with_variable_substitutions(
                    filename=wr_data_file
                )

        # None of the above
        else:
            raise ValueError(
                f"Work Requirement data file '{wr_data_file}' "
                "must end with '.json', '.jsonnet', or '.toml'"
            )

        # Every branch above -- JSON, Jsonnet, TOML, each with or without CSV
        # task expansion -- arrives here with the loaded document
        wr_data = check_specification(
            Family.WORK_REQUIREMENT, wr_data, wr_data_file, bool(ctx.args.validate)
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
    Submit a Work Requirement defined in a tasks_data dictionary.
    Supply either tasks_data or task_count.

    The general principle with configuration properties is that a property set
    at a lower level will override its setting at higher levels, so:

    Task > Task Group > Top-Level JSON Property > TOML config file
    """
    # Create a default tasks_data dictionary if required
    if wr_data is None:
        wr_data = (
            {TASK_GROUPS: []} if run.ctx.args.empty else {TASK_GROUPS: [{TASKS: [{}]}]}
        )
    check_dict(wr_data)
    check_task_groups(wr_data)
    promote_task_type(wr_data)

    # Overwrite the WR name?
    run.name = format_yd_name(
        check_str(
            wr_data.get(
                NAME,
                run.name if run.config_wr.wr_name is None else run.config_wr.wr_name,
            ),
            NAME,
        )
    )
    # Lazy substitution of the Work Requirement name, now it's defined
    add_substitutions_without_overwriting(subs={L_WR_NAME: run.name})
    # Announced before its Task Groups, which announce themselves as they're
    # generated; this is the only report of the name in a dry run
    print_info(f"Generated Work Requirement '{run.name}'")
    # Re-process substitutions in the CONFIG_WR object
    run.config_wr = update_config_work_requirement_object(run.config_wr)
    # Re-process substitutions in the wr_data dictionary
    resolve_variables_insitu(wr_data)

    # Handle any files that need to be uploaded
    run.uploaded_files = RcloneUploadedFiles(run.ctx, files_directory=files_directory)

    expand_task_groups(run, wr_data)

    # Create the list of TaskGroup objects
    task_groups: list[TaskGroup] = []
    for tg_number, task_group_data in enumerate(
        cast(dict, wr_data).get(TASK_GROUPS, [])
    ):
        task_groups.append(
            create_task_group(
                run,
                tg_number,
                cast(dict, wr_data),
                task_group_data,
                files_directory=files_directory,
            )
        )

    # Create the Work Requirement
    priority = check_float_or_int(
        wr_data.get(PRIORITY, run.config_wr.priority), PRIORITY
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
    if not run.ctx.args.dry_run:
        work_requirement = run.ctx.client.work_client.add_work_requirement(
            work_requirement
        )
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
    else:
        run.snapshot.set_work_requirement(work_requirement)

    try:
        # Held before any Task is added, so that none starts; inside the
        # clean-up, as a Work Requirement that cannot be held as asked is
        # one left live without its Tasks
        if run.ctx.args.hold and not run.ctx.args.dry_run:
            run.ctx.client.work_client.hold_work_requirement(work_requirement)
            print_info("Work Requirement status is set to 'HELD'")

        # Add Tasks to their Task Groups
        for tg_number, task_group in enumerate(task_groups):
            add_tasks_to_task_group(
                run,
                tg_number,
                task_group,
                cast(dict, wr_data),
                task_count,
                work_requirement,
                files_directory=files_directory,
            )

    # An interrupt too: Ctrl-C part-way through would otherwise leave the
    # Work Requirement live with only some of its Tasks
    except (Exception, KeyboardInterrupt):
        cleanup_on_failure(run, work_requirement)
        raise

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
    task_group_count = check_float_or_int(
        wr_data.get(TASK_GROUP_COUNT, run.config_wr.task_group_count), TASK_GROUP_COUNT
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
        _task_count = check_int(
            task_group_data.get(
                TASK_COUNT, wr_data.get(TASK_COUNT, run.config_wr.task_count)
            ),
            TASK_COUNT,
        )
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
    task_template_data = check_dict(
        task_group_data.get(
            TASK_TEMPLATE, wr_data.get(TASK_TEMPLATE, config_wr.task_template)
        ),
        TASK_TEMPLATE,
    )

    # Assemble the RunSpecification values for the Task Group;
    # 'task_types' can automatically be added to by the task_types
    # specified in the Tasks.
    # De-duplicated in order, the declared types first, rather than through a
    # set, whose order varies from run to run with string hashing
    task_types: list = list(
        dict.fromkeys(
            check_list(
                task_group_data.get(TASK_TYPES, wr_data.get(TASK_TYPES, [])), TASK_TYPES
            )
            + task_types_from_tasks
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

    vcpus = double_range_from_list(
        task_group_data.get(VCPUS, wr_data.get(VCPUS, config_wr.vcpus)), VCPUS
    )

    ram = double_range_from_list(
        task_group_data.get(RAM, wr_data.get(RAM, config_wr.ram)), RAM
    )

    providers_data: list[str] | None = check_list(
        task_group_data.get(PROVIDERS, wr_data.get(PROVIDERS, config_wr.providers)),
        PROVIDERS,
    )
    providers: list[CloudProvider] | None = (
        None
        if providers_data is None
        else [CloudProvider(provider) for provider in providers_data]
    )

    ipp_data: str | None = check_str(
        task_group_data.get(
            INSTANCE_PRICING_PREFERENCE,
            wr_data.get(
                INSTANCE_PRICING_PREFERENCE, config_wr.instance_pricing_preference
            ),
        ),
        INSTANCE_PRICING_PREFERENCE,
    )
    instance_pricing_preference: InstancePricingPreference | None = (
        None if ipp_data is None else InstancePricingPreference(ipp_data)
    )

    task_timeout_minutes: float | None = check_float_or_int(
        task_group_data.get(
            TASK_TIMEOUT, wr_data.get(TASK_TIMEOUT, config_wr.task_timeout)
        ),
        TASK_TIMEOUT,
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
            else check_int(
                task_group_data.get(
                    MAX_RETRIES, wr_data.get(MAX_RETRIES, config_wr.max_retries or 0)
                ),
                MAX_RETRIES,
            )
        ),
        retryPolicy=retry_policy,
        failurePolicy=failure_policy,
        workerTags=check_list(
            task_group_data.get(
                WORKER_TAGS, wr_data.get(WORKER_TAGS, config_wr.worker_tags)
            ),
            WORKER_TAGS,
        ),
        instanceTypes=check_list(
            task_group_data.get(
                INSTANCE_TYPES, wr_data.get(INSTANCE_TYPES, config_wr.instance_types)
            ),
            INSTANCE_TYPES,
        ),
        instancePricingPreference=instance_pricing_preference,
        vcpus=vcpus,
        ram=ram,
        minWorkers=check_int(
            task_group_data.get(
                MIN_WORKERS, wr_data.get(MIN_WORKERS, config_wr.min_workers)
            ),
            MIN_WORKERS,
        ),
        maxWorkers=check_int(
            task_group_data.get(
                MAX_WORKERS, wr_data.get(MAX_WORKERS, config_wr.max_workers)
            ),
            MAX_WORKERS,
        ),
        tasksPerWorker=check_int(
            task_group_data.get(
                TASKS_PER_WORKER,
                wr_data.get(TASKS_PER_WORKER, config_wr.tasks_per_worker),
            ),
            TASKS_PER_WORKER,
        ),
        providers=providers,
        regions=check_list(
            task_group_data.get(REGIONS, wr_data.get(REGIONS, config_wr.regions)),
            REGIONS,
        ),
        taskTimeout=task_timeout,
        namespaces=check_list(
            task_group_data.get(
                NAMESPACES, wr_data.get(NAMESPACES, config_wr.namespaces)
            ),
            NAMESPACES,
        ),
        retryableErrors=(
            None
            if retry_policy is not None
            else generate_task_error_matchers_list(config_wr, wr_data, task_group_data)
        ),
        disablePreallocation=check_bool(
            task_group_data.get(
                DISABLE_PREALLOCATION,
                wr_data.get(DISABLE_PREALLOCATION, config_wr.disable_preallocation),
            ),
            DISABLE_PREALLOCATION,
        ),
    )
    ctttl_data = check_float_or_int(
        task_group_data.get(
            COMPLETED_TASK_TTL,
            wr_data.get(COMPLETED_TASK_TTL, config_wr.completed_task_ttl),
        ),
        COMPLETED_TASK_TTL,
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
    _finish_all = check_bool(
        task_group_data.get(
            FINISH_IF_ALL_TASKS_FINISHED,
            wr_data.get(
                FINISH_IF_ALL_TASKS_FINISHED, config_wr.finish_if_all_tasks_finished
            ),
        ),
        FINISH_IF_ALL_TASKS_FINISHED,
    )
    task_group = TaskGroup(
        name=task_group_name,
        runSpecification=run_specification,
        dependencies=generate_dependencies(task_group_data),
        finishIfAllTasksFinished=_finish_all if _finish_all is not None else True,
        finishIfAnyTaskFailed=check_bool(
            task_group_data.get(
                FINISH_IF_ANY_TASK_FAILED,
                wr_data.get(
                    FINISH_IF_ANY_TASK_FAILED, config_wr.finish_if_any_task_failed
                ),
            ),
            FINISH_IF_ANY_TASK_FAILED,
        )
        or False,
        priority=check_float_or_int(
            task_group_data.get(
                PRIORITY, wr_data.get(PRIORITY, config_wr.priority or 0)
            ),
            PRIORITY,
        ),
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
    task_group_task_count = check_int(
        wr_data[TASK_GROUPS][tg_number].get(
            TASK_COUNT, wr_data.get(TASK_COUNT, run.config_wr.task_count)
        ),
        TASK_COUNT,
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

        set_task_names = (
            check_bool(
                task.get(
                    SET_TASK_NAMES,
                    task_group_data.get(
                        SET_TASK_NAMES,
                        wr_data.get(SET_TASK_NAMES, run.config_wr.set_task_names),
                    ),
                ),
                SET_TASK_NAMES,
            )
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

        arguments_list = check_list(
            task.get(
                ARGS,
                task_group_data.get(ARGS, wr_data.get(ARGS, config_wr.args)),
            ),
            ARGS,
        )
        args_prefix = check_list(
            task_group_data.get(
                ARGS_PREFIX, wr_data.get(ARGS_PREFIX, config_wr.args_prefix)
            ),
            ARGS_PREFIX,
        )
        args_postfix = check_list(
            task_group_data.get(
                ARGS_POSTFIX, wr_data.get(ARGS_POSTFIX, config_wr.args_postfix)
            ),
            ARGS_POSTFIX,
        )
        arguments_list = assemble_arguments(args_prefix, arguments_list, args_postfix)
        env = check_dict(
            task.get(ENV, task_group_data.get(ENV, wr_data.get(ENV, config_wr.env))),
            ENV,
        )
        add_env = check_dict(
            task_group_data.get(
                ADD_ENVIRONMENT,
                wr_data.get(ADD_ENVIRONMENT, config_wr.add_environment),
            ),
            ADD_ENVIRONMENT,
        )
        env = merge_environment(env, add_env)

        add_yd_env_vars = (
            check_bool(
                task.get(
                    ADD_YD_ENV_VARS,
                    task_group_data.get(
                        ADD_YD_ENV_VARS,
                        wr_data.get(ADD_YD_ENV_VARS, config_wr.add_yd_env_vars),
                    ),
                ),
                ADD_YD_ENV_VARS,
            )
            or False
        )

        # Task timeout is automatically inherited from the Task Group level
        # unless overridden by the Task
        task_timeout_minutes = check_float_or_int(
            task.get(TASK_LEVEL_TIMEOUT, config_wr.task_level_timeout),
            TASK_LEVEL_TIMEOUT,
        )
        task_timeout = (
            None
            if task_timeout_minutes is None
            else timedelta(minutes=task_timeout_minutes)
        )

        # Data client inputs and outputs
        task_data_inputs = check_list(
            task.get(
                TASK_DATA_INPUTS,
                task_group_data.get(
                    TASK_DATA_INPUTS,
                    wr_data.get(TASK_DATA_INPUTS, config_wr.task_data_inputs),
                ),
            ),
            TASK_DATA_INPUTS,
        )
        task_data_outputs = check_list(
            task.get(
                TASK_DATA_OUTPUTS,
                task_group_data.get(
                    TASK_DATA_OUTPUTS,
                    wr_data.get(TASK_DATA_OUTPUTS, config_wr.task_data_outputs),
                ),
            ),
            TASK_DATA_OUTPUTS,
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


def add_to_existing_work_requirement(
    run: _Submission,
    files_directory: str,
    wr_data: dict | None = None,
    task_count: int | None = None,
) -> None:
    """
    Add task groups and/or tasks to an existing Work Requirement identified
    by the --add-to argument (name or YellowDog ID).
    """
    work_requirement = _work_requirement_to_add_to(run, cast(str, run.ctx.args.add_to))
    existing_tgs: list[TaskGroup] = work_requirement.taskGroups or []

    # Use the existing WR's name as the ID for substitutions
    run.name = cast(str, work_requirement.name)
    add_substitutions_without_overwriting(subs={L_WR_NAME: run.name})
    run.config_wr = update_config_work_requirement_object(run.config_wr)

    # Initialise rclone file uploads
    run.uploaded_files = RcloneUploadedFiles(run.ctx, files_directory=files_directory)

    # Build spec data
    wr_data = {TASK_GROUPS: [{TASKS: [{}]}]} if wr_data is None else wr_data
    check_dict(wr_data)
    check_task_groups(wr_data)
    promote_task_type(wr_data)

    resolve_variables_insitu(cast(dict, wr_data))

    expand_task_groups(run, wr_data)

    n_existing = len(existing_tgs)
    n_spec = len(wr_data[TASK_GROUPS])

    # Create TaskGroup objects for all spec TGs with WR-relative numbering.
    # The numbering is provisional: until each Task Group has its name, which
    # the numbering can be part of, which of them are already in the Work
    # Requirement is unknown, so each is numbered as if it were new.
    spec_task_groups: list[TaskGroup] = []
    for tg_number, task_group_data in enumerate(wr_data[TASK_GROUPS]):
        spec_task_groups.append(
            create_task_group(
                run,
                tg_number,
                cast(dict, wr_data),
                task_group_data,
                tg_number_offset=n_existing,
                total_num_task_groups=n_existing + n_spec,
                files_directory=files_directory,
            )
        )

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

    try:
        # Add tasks to new TGs (no task offset), numbered by where they were
        # appended
        for new_idx, (spec_idx, spec_tg) in enumerate(new_tgs):
            add_tasks_to_task_group(
                run,
                tg_number=spec_idx,
                task_group=spec_tg,
                wr_data=cast(dict, wr_data),
                task_count=task_count,
                work_requirement=work_requirement,
                files_directory=files_directory,
                wr_tg_number=n_existing + new_idx,
                total_num_task_groups=total_tgs,
                task_number_offset=0,
            )

        # Add tasks to matched (existing) TGs, numbered by their own position
        # and offsetting task numbers
        for spec_idx, _, existing_idx, existing_tg in matched:
            task_summary = existing_tg.taskSummary
            existing_task_count: int = (
                task_summary.taskCount if task_summary is not None else 0
            )
            add_tasks_to_task_group(
                run,
                tg_number=spec_idx,
                task_group=existing_tg,
                wr_data=cast(dict, wr_data),
                task_count=task_count,
                work_requirement=work_requirement,
                files_directory=files_directory,
                wr_tg_number=existing_idx,
                total_num_task_groups=total_tgs,
                task_number_offset=existing_task_count,
            )

    except (Exception, KeyboardInterrupt):
        # Unlike a new Work Requirement, this one is not cancelled, so the
        # Tasks already added to it stay live -- and may read the files
        # uploaded for them, which are therefore left in place too
        if not run.ctx.args.dry_run:
            print_warning(
                f"Adding to Work Requirement '{run.name}' failed part-way: any Tasks"
                " already added remain in it, and any files uploaded for them"
                " have been left in place"
            )
        raise

    if run.ctx.args.progress:
        follow_progress_bar(run, work_requirement)
    elif run.ctx.args.follow:
        follow_progress(run, work_requirement)


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


def submit_json_raw(run: _Submission, wr_file: str):
    """
    Submit a 'raw' JSON Work Requirement, consisting of a combined Work
    Requirement definition and the constituent Tasks.
    """

    # Load file contents, with variable substitutions
    if wr_file.lower().endswith(".jsonnet"):
        wr_data = load_jsonnet_file_with_variable_substitutions(
            wr_file, dry_run=bool(run.ctx.args.jsonnet_dry_run)
        )
    elif wr_file.lower().endswith(".json"):
        wr_data = load_json_file_with_variable_substitutions(wr_file)
    else:
        raise ValueError(
            f"Work Requirement file '{wr_file}' must end in '.json' or '.jsonnet'"
        )

    if not isinstance(wr_data, dict):
        raise ValueError(f"Work Requirement file '{wr_file}' must be a JSON object")
    if "name" not in wr_data:
        raise ValueError(f"Property '{NAME}' is not defined in '{wr_file}'")

    # Lazy substitution of Work Requirement name
    wr_data["name"] = format_yd_name(check_str(wr_data["name"], NAME))
    wr_name = wr_data["name"]
    add_substitutions_without_overwriting(subs={L_WR_NAME: wr_name})
    resolve_variables_insitu(wr_data)

    if run.ctx.args.dry_run:
        # This will show the results of any variable substitutions
        if run.ctx.args.json_output:
            record_document(wr_data)
            return
        print_dry_run("Printing JSON Work Requirement specification:")
        print_json(wr_data)
        print_dry_run("Complete")
        return

    # Extract Tasks from Task Groups
    task_lists = {}
    if TASK_GROUPS not in wr_data:
        raise ValueError(f"Property '{TASK_GROUPS}' is not defined")
    task_groups = check_list(wr_data[TASK_GROUPS], TASK_GROUPS)
    if not task_groups:
        raise ValueError("There must be at least one Task Group")
    for tg_number, task_group in enumerate(task_groups):
        if not isinstance(task_group, dict) or "name" not in task_group:
            raise ValueError(
                f"Task Group {tg_number + 1} of {len(task_groups)} has no"
                f" '{NAME}' property"
            )
        task_lists[task_group["name"]] = task_group.get(TASKS, [])
        task_group.pop(TASKS, None)

    # Submit the Work Requirement and its Task Groups
    response = requests.post(
        url=f"{run.ctx.config.url}/work/requirements",
        headers={
            "Authorization": f"yd-key {run.ctx.config.key}:{run.ctx.config.secret}"
        },
        json=wr_data,
        timeout=RAW_REQUEST_TIMEOUT,
    )

    if response.status_code != 200:
        print_error(f"Failed to create Work Requirement '{wr_name}'")
        raise_for_response(response)

    wr_id = json_loads(response.text)["id"]
    namespace = cast(str, wr_data.get("namespace"))
    print_info(f"Created Work Requirement '{namespace}/{wr_name}' ({wr_id})")
    record_entity(wr_id, wr_name, namespace, ET_WORK_REQUIREMENTS)
    print_quiet_result(wr_id)

    try:
        _submit_json_raw_tasks(run, wr_id, wr_name, namespace, task_lists)
    except (Exception, KeyboardInterrupt):
        # As for a Work Requirement built from a specification: one left
        # with only some of its Tasks is cancelled, and a failure to cancel
        # it is reported without masking the failure that is re-raised
        try:
            run.ctx.client.work_client.cancel_work_requirement_by_id(wr_id)
            print_warning(f"Cancelled Work Requirement '{wr_name}'")
        except Exception as e:
            print_error(f"Unable to cancel Work Requirement '{wr_name}': {e}")
        raise

    if run.ctx.args.progress:
        follow_progress_bar(
            run, run.ctx.client.work_client.get_work_requirement_by_id(wr_id)
        )
    elif run.ctx.args.follow:
        follow_progress(
            run, run.ctx.client.work_client.get_work_requirement_by_id(wr_id)
        )


def _submit_json_raw_tasks(
    run: _Submission,
    wr_id: str,
    wr_name: str,
    namespace: str,
    task_lists: dict[str, list],
) -> None:
    """
    Hold the newly created raw Work Requirement if asked, then submit each
    Task Group's Tasks in batches. A batch that fails raises, once the
    batches already under way have finished; those not yet started are not.
    """
    batch_size = run.batch_size
    if run.ctx.args.hold:
        run.ctx.client.work_client.hold_work_requirement_by_id(wr_id)
        print_info("Work Requirement status set to 'HELD'")

    # Submit Tasks in batches
    for task_group_name, task_list in task_lists.items():
        if not task_list:
            print_info(f"No Tasks to add to Task Group '{task_group_name}'")
            continue
        num_submitted_tasks = run_batches(
            run.ctx,
            len(task_list),
            batch_size,
            _parallel_batches(run),
            make_batch=lambda start, end, task_list=task_list: task_list[start:end],
            send_batch=lambda task_batch, batch_number, num_batches, name=task_group_name: (
                submit_json_task_batch(
                    run,
                    task_batch,
                    batch_number,
                    num_batches,
                    name,
                    wr_name,
                    namespace,
                )
            ),
        )
        print_info(
            f"Added a total of {num_submitted_tasks} Task(s) to Task Group '{task_group_name}'"
        )


def submit_json_task_batch(
    run: _Submission,
    task_batch: list[dict],
    batch_number: int,
    num_batches: int,
    task_group_name: str,
    wr_name: str,
    namespace: str,
) -> int:
    """
    Submit a batch of tasks using the REST API, retrying it as the main path
    does. Return the number of tasks submitted.
    """
    task_batch_compressed = compress(json_dumps(task_batch).encode("utf-8"))
    batch_number_str = formatted_number_str(batch_number, num_batches)

    def attempt() -> None:
        response = requests.post(
            url=(
                f"{run.ctx.config.url}/work/namespaces/{namespace}"
                f"/requirements/{wr_name}/taskGroups/{task_group_name}/tasks"
            ),
            headers={
                "Authorization": f"yd-key {run.ctx.config.key}:{run.ctx.config.secret}",
                "Content-Encoding": "gzip",
                "Content-Type": "application/json",
            },
            data=task_batch_compressed,
            timeout=RAW_REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            raise_for_response(response)

    def report_success() -> None:
        print_info(
            f"Added {len(task_batch)} Task(s) to Task Group "
            f"'{task_group_name}' (Batch {batch_number_str} of {num_batches})"
        )

    batch = (
        f"batch {batch_number_str} of {num_batches} to Task Group '{task_group_name}'"
    )
    submit_with_retries(attempt, report_success, batch=batch, batch_in_full=batch)
    return len(task_batch)


# Entry point
if __name__ == "__main__":
    main()
