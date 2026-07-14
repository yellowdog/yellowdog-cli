#!/usr/bin/env python3

"""
A script to submit a Work Requirement.
"""

from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from gzip import compress
from json import dumps as json_dumps
from json import loads as json_loads
from math import ceil
from os.path import dirname, relpath
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
from yellowdog_cli.utils.csv_data import (
    csv_expand_toml_tasks,
    load_json_file_with_csv_task_expansion,
    load_jsonnet_file_with_csv_task_expansion,
    load_toml_file_with_csv_task_expansion,
)
from yellowdog_cli.utils.entity_utils import get_work_requirement_summary_by_name_or_id
from yellowdog_cli.utils.follow_utils import (
    follow_events,
    follow_work_requirement_with_progress,
    work_requirement_failed,
)
from yellowdog_cli.utils.load_config import (
    CONFIG_FILE_DIR,
    load_config_work_requirement,
)
from yellowdog_cli.utils.misc_utils import format_yd_name, generate_id, link_entity
from yellowdog_cli.utils.printing import (
    WorkRequirementSnapshot,
    print_error,
    print_info,
    print_json,
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
from yellowdog_cli.utils.settings import (
    DEFAULT_PARALLEL_TASK_BATCH_UPLOAD_THREADS,
    L_TASK_COUNT,
    L_TASK_GROUP_COUNT,
    L_TASK_GROUP_NAME,
    L_TASK_GROUP_NUMBER,
    L_TASK_NAME,
    L_TASK_NUMBER,
    L_WR_NAME,
    MAX_BATCH_SUBMIT_ATTEMPTS,
    VAR_NAME_OF_UNNAMED_TASK,
)
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
    pause_between_batches,
    resolve_task_data,
    update_config_work_requirement_object,
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
from yellowdog_cli.utils.variables import (
    add_or_update_substitution,
    add_substitutions_without_overwriting,
    load_json_file_with_variable_substitutions,
    load_jsonnet_file_with_variable_substitutions,
    load_toml_file_with_variable_substitutions,
    process_variable_substitutions_insitu,
)
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, CONFIG_COMMON, main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType

# Import the Work Requirement configuration from the TOML file
CONFIG_WR: ConfigWorkRequirement = load_config_work_requirement()


ID = generate_id(CONFIG_COMMON.name_tag)
TASK_BATCH_SIZE = CONFIG_WR.task_batch_size

if ARGS_PARSER.dry_run:
    WR_SNAPSHOT = WorkRequirementSnapshot()

RCLONE_UPLOADED_FILES: RcloneUploadedFiles | None = None


@main_wrapper
def main():

    if ARGS_PARSER.upgrade_rclone:
        upgrade_rclone()
        return

    if ARGS_PARSER.which_rclone:
        which_rclone()
        return

    if not 1 <= TASK_BATCH_SIZE <= 10000:
        raise ValueError("Task batch size must be between 1 and 10,000")

    if ARGS_PARSER.json_raw:
        submit_json_raw(ARGS_PARSER.json_raw)
        return

    # Direct file > file supplied using '-r' > file supplied in config file
    wr_data_file = (
        (
            CONFIG_WR.wr_data_file
            if ARGS_PARSER.work_req_file is None
            else ARGS_PARSER.work_req_file
        )
        if ARGS_PARSER.work_requirement_file_positional is None
        else ARGS_PARSER.work_requirement_file_positional
    )

    csv_files = (
        CONFIG_WR.csv_files if ARGS_PARSER.csv_files is None else ARGS_PARSER.csv_files
    )

    if not csv_files and ARGS_PARSER.process_csv_only:
        raise ValueError(
            "Option '--process-csv-only' is only valid if CSV file(s) specified"
        )

    # Where do we find the data files?
    # content-path > wr_data_file location > config file location
    files_directory = (
        (CONFIG_FILE_DIR if wr_data_file is None else dirname(wr_data_file))
        if ARGS_PARSER.content_path is None
        else ARGS_PARSER.content_path
    )

    if wr_data_file is None and csv_files is not None:
        wr_data = csv_expand_toml_tasks(CONFIG_WR, csv_files[0], files_directory)
        if ARGS_PARSER.add_to and not ARGS_PARSER.dry_run:
            add_to_existing_work_requirement(
                files_directory=files_directory,
                wr_data=wr_data,
                task_count=None,
            )
        else:
            submit_work_requirement(
                files_directory=files_directory,
                wr_data=wr_data,
            )

    elif wr_data_file is not None:
        if ARGS_PARSER.jsonnet_dry_run and not wr_data_file.lower().endswith("jsonnet"):
            raise ValueError(
                "Option '--jsonnet-dry-run' can only be used with files ending in '.jsonnet'"
            )

        wr_data_file = relpath(wr_data_file)
        print_info(f"Loading Work Requirement data from: '{wr_data_file}'")

        # JSON file
        if wr_data_file.lower().endswith("json"):
            if csv_files is not None:
                wr_data = load_json_file_with_csv_task_expansion(
                    json_file=wr_data_file,
                    csv_files=csv_files,
                    files_directory=files_directory,
                )
            else:
                wr_data = load_json_file_with_variable_substitutions(
                    filename=wr_data_file,
                    prefix="",
                    postfix="",
                    files_directory=files_directory,
                )

        # Jsonnet file
        elif wr_data_file.lower().endswith("jsonnet"):
            if csv_files is not None:
                wr_data = load_jsonnet_file_with_csv_task_expansion(
                    jsonnet_file=wr_data_file,
                    csv_files=csv_files,
                )
            else:
                wr_data = load_jsonnet_file_with_variable_substitutions(
                    filename=wr_data_file,
                    prefix="",
                    postfix="",
                    files_directory=files_directory,
                )

        # TOML file (undocumented)
        elif wr_data_file.lower().endswith("toml"):
            if csv_files is not None:
                wr_data = load_toml_file_with_csv_task_expansion(
                    toml_file=wr_data_file,
                    csv_files=csv_files,
                    files_directory=files_directory,
                )
            else:
                wr_data = load_toml_file_with_variable_substitutions(
                    filename=wr_data_file, files_directory=files_directory
                )

        # None of the above
        else:
            raise ValueError(
                f"Work Requirement data file '{wr_data_file}' "
                "must end with '.json', '.jsonnet', or '.toml'"
            )

        validate_properties(wr_data, "Work Requirement JSON")
        if ARGS_PARSER.add_to and not ARGS_PARSER.dry_run:
            add_to_existing_work_requirement(
                files_directory=files_directory,
                wr_data=wr_data,
                task_count=None,
            )
        else:
            submit_work_requirement(
                files_directory=files_directory,
                wr_data=wr_data,
            )

    else:
        if ARGS_PARSER.add_to and not ARGS_PARSER.dry_run:
            add_to_existing_work_requirement(
                files_directory=files_directory,
                wr_data=None,
                task_count=CONFIG_WR.task_count,
            )
        else:
            submit_work_requirement(
                files_directory=files_directory,
                task_count=CONFIG_WR.task_count,
            )

    if ARGS_PARSER.dry_run:
        WR_SNAPSHOT.print()


def submit_work_requirement(
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
            {TASK_GROUPS: []} if ARGS_PARSER.empty else {TASK_GROUPS: [{TASKS: [{}]}]}
        )
    check_dict(wr_data)

    # Remap 'task_type' at WR level to 'task_types' if 'task_types' is empty
    if wr_data.get(TASK_TYPE) is not None:
        if wr_data.get(TASK_TYPES) is None:
            wr_data[TASK_TYPES] = [wr_data[TASK_TYPE]]

    # Overwrite the WR name?
    global ID, CONFIG_WR
    ID = format_yd_name(
        wr_data.get(NAME, ID if CONFIG_WR.wr_name is None else CONFIG_WR.wr_name)
    )
    # Lazy substitution of the Work Requirement name, now it's defined
    add_substitutions_without_overwriting(subs={L_WR_NAME: ID})
    # Re-process substitutions in the CONFIG_WR object
    CONFIG_WR = update_config_work_requirement_object(CONFIG_WR)
    # Re-process substitutions in the wr_data dictionary
    process_variable_substitutions_insitu(wr_data)

    # Handle any files that need to be uploaded
    global RCLONE_UPLOADED_FILES
    RCLONE_UPLOADED_FILES = RcloneUploadedFiles(files_directory=files_directory)

    # Expand number of task groups if there's a single task group
    # and taskGroupCount is set
    task_group_count = check_float_or_int(
        wr_data.get(TASK_GROUP_COUNT, CONFIG_WR.task_group_count)
    )
    if task_group_count is not None and task_group_count > 1:
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
                f"using '{TASK_GROUP_COUNT} = {int(task_group_count)}'"
            )

    # Create the list of TaskGroup objects
    task_groups: list[TaskGroup] = []
    for tg_number, task_group_data in enumerate(
        cast(dict, wr_data).get(TASK_GROUPS, [])
    ):
        task_groups.append(
            create_task_group(
                tg_number,
                cast(dict, wr_data),
                task_group_data,
                files_directory=files_directory,
            )
        )

    # Create the Work Requirement
    priority = check_float_or_int(wr_data.get(PRIORITY, CONFIG_WR.priority))
    wr_tag = check_str(
        wr_data.get(
            WR_TAG,
            CONFIG_COMMON.name_tag if CONFIG_WR.wr_tag is None else CONFIG_WR.wr_tag,
        )
    )
    work_requirement = WorkRequirement(
        namespace=CONFIG_COMMON.namespace,
        name=ID,
        taskGroups=task_groups,
        tag=wr_tag,
        priority=priority,
    )
    if not ARGS_PARSER.dry_run:
        work_requirement = CLIENT.work_client.add_work_requirement(work_requirement)
        if ARGS_PARSER.quiet:
            print(work_requirement.id)
        print_info(
            "Created "
            f"{link_entity(CONFIG_COMMON.url, work_requirement)} "
            f"('{CONFIG_COMMON.namespace}/{work_requirement.name}')"
        )
        print_info(f"YellowDog ID is '{work_requirement.id}'")
        if ARGS_PARSER.hold:
            CLIENT.work_client.hold_work_requirement(work_requirement)
            print_info("Work Requirement status is set to 'HELD'")
    else:
        global WR_SNAPSHOT
        WR_SNAPSHOT.set_work_requirement(work_requirement)

    # Add Tasks to their Task Groups
    for tg_number, task_group in enumerate(task_groups):
        try:
            add_tasks_to_task_group(
                tg_number,
                task_group,
                cast(dict, wr_data),
                task_count,
                work_requirement,
                files_directory=files_directory,
            )

        except Exception as e:
            cleanup_on_failure(work_requirement)
            raise e

    if ARGS_PARSER.progress:
        follow_progress_bar(work_requirement)
    elif ARGS_PARSER.follow:
        follow_progress(work_requirement)


# Per-invocation flag so the deprecation warning fires once even when many
# Task Groups use the legacy retry mechanism
_LEGACY_RETRY_WARNED = False


def _warn_legacy_retry_mechanism_once() -> None:
    global _LEGACY_RETRY_WARNED
    if _LEGACY_RETRY_WARNED:
        return
    _LEGACY_RETRY_WARNED = True
    print_warning(
        f"'{MAX_RETRIES}' and '{RETRYABLE_ERRORS}' are deprecated; "
        f"please use '{RETRY_POLICY}' and (optionally) '{FAILURE_POLICY}' "
        "instead. See the README's 'Task Retries and Failure Policies' section."
    )


def create_task_group(
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

    # Remap 'task_type' to 'task_types' in the Task Group if 'task_types'
    # is empty, as a convenience
    if task_group_data.get(TASK_TYPE) is not None:
        if task_group_data.get(TASK_TYPES) is None:
            task_group_data[TASK_TYPES] = [task_group_data[TASK_TYPE]]

    # Gather task types
    task_types_from_tasks = set()
    for task in task_group_data[TASKS]:
        try:
            task_types_from_tasks.add(task[TASK_TYPE])
        except KeyError:
            pass

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
                TASK_COUNT, wr_data.get(TASK_COUNT, CONFIG_WR.task_count)
            )
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
            task_group_data.get(NAME, CONFIG_WR.task_group_name),
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
    process_variable_substitutions_insitu(task_group_data)
    # Create a copy of global CONFIG_WR and apply lazy substitutions
    config_wr = update_config_work_requirement_object(deepcopy(CONFIG_WR))

    # Resolve taskTemplate early so it can satisfy the task-type validation below
    task_template_data = check_dict(
        task_group_data.get(
            TASK_TEMPLATE, wr_data.get(TASK_TEMPLATE, config_wr.task_template)
        )
    )

    # Assemble the RunSpecification values for the Task Group;
    # 'task_types' can automatically be added to by the task_types
    # specified in the Tasks.
    task_types: list = list(
        set(
            check_list(task_group_data.get(TASK_TYPES, wr_data.get(TASK_TYPES, [])))
        ).union(task_types_from_tasks)
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
        task_group_data.get(PROVIDERS, wr_data.get(PROVIDERS, config_wr.providers))
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
        )
    )
    instance_pricing_preference: InstancePricingPreference | None = (
        None if ipp_data is None else InstancePricingPreference(ipp_data)
    )

    task_timeout_minutes: float | None = check_float_or_int(
        task_group_data.get(TASK_TIMEOUT, config_wr.task_timeout)
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
        _warn_legacy_retry_mechanism_once()

    run_specification = RunSpecification(
        taskTypes=task_types,
        maximumTaskRetries=(
            None
            if retry_policy is not None
            else check_int(
                task_group_data.get(
                    MAX_RETRIES, wr_data.get(MAX_RETRIES, config_wr.max_retries or 0)
                )
            )
        ),
        retryPolicy=retry_policy,
        failurePolicy=failure_policy,
        workerTags=check_list(
            task_group_data.get(
                WORKER_TAGS, wr_data.get(WORKER_TAGS, config_wr.worker_tags)
            )
        ),
        instanceTypes=check_list(
            task_group_data.get(
                INSTANCE_TYPES, wr_data.get(INSTANCE_TYPES, config_wr.instance_types)
            )
        ),
        instancePricingPreference=instance_pricing_preference,
        vcpus=vcpus,
        ram=ram,
        minWorkers=check_int(task_group_data.get(MIN_WORKERS, config_wr.min_workers)),
        maxWorkers=check_int(task_group_data.get(MAX_WORKERS, config_wr.max_workers)),
        tasksPerWorker=check_int(
            task_group_data.get(TASKS_PER_WORKER, config_wr.tasks_per_worker)
        ),
        providers=providers,
        regions=check_list(
            task_group_data.get(REGIONS, wr_data.get(REGIONS, config_wr.regions))
        ),
        taskTimeout=task_timeout,
        namespaces=check_list(
            task_group_data.get(
                NAMESPACES, wr_data.get(NAMESPACES, config_wr.namespaces)
            )
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
            )
        ),
    )
    ctttl_data = check_float_or_int(
        task_group_data.get(
            COMPLETED_TASK_TTL,
            wr_data.get(COMPLETED_TASK_TTL, config_wr.completed_task_ttl),
        )
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
        )
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
            )
        )
        or False,
        priority=check_float_or_int(
            task_group_data.get(
                PRIORITY, wr_data.get(PRIORITY, config_wr.priority or 0)
            )
        ),
        completedTaskTtl=completed_task_ttl,
        tag=task_group_data.get(TASK_GROUP_TAG),
        taskTemplate=task_template,
    )

    print_info(f"Generated Task Group '{task_group_name}'")
    return task_group


def add_tasks_to_task_group(
    tg_number: int,
    task_group: TaskGroup,
    wr_data: dict,
    task_count: int | None,
    work_requirement: WorkRequirement,
    files_directory: str = "",
    tg_number_offset: int = 0,
    total_num_task_groups: int | None = None,
    task_number_offset: int = 0,
) -> None:
    """
    Add all the constituent Tasks to the Task Group.

    tg_number_offset: added to tg_number for display/naming when adding to an
      existing Work Requirement.
    total_num_task_groups: total TG count (existing + new) for formatting.
    task_number_offset: starting task number within the TG (for adding to an
      existing Task Group that already contains tasks).
    """

    num_tasks = len(wr_data[TASK_GROUPS][tg_number][TASKS])

    # If the 'taskCount' property is set, and there is only one Task
    # in the Task Group, create 'taskCount' duplicates of the Task.
    task_group_task_count = check_int(
        wr_data[TASK_GROUPS][tg_number].get(
            TASK_COUNT, wr_data.get(TASK_COUNT, CONFIG_WR.task_count)
        )
    )
    if task_group_task_count is not None:
        if num_tasks == 1 and task_group_task_count > 1:
            # Expand the number of Tasks to match the specified Task count
            print_info(
                f"Expanding number of Tasks in Task Group '{task_group.name}' to"
                f" '{TASK_COUNT}={task_group_task_count}' Tasks"
            )
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
    effective_tg_number = tg_number + tg_number_offset

    # Determine Task batching
    tasks = wr_data[TASK_GROUPS][tg_number][TASKS]
    num_tasks = len(tasks) if task_count is None else task_count
    num_task_batches: int = ceil(num_tasks / TASK_BATCH_SIZE)
    if num_task_batches > 1 and not ARGS_PARSER.dry_run:
        print_info(
            f"Adding Tasks to Task Group '{task_group.name}' in "
            f"{num_task_batches} batches (batch size = {TASK_BATCH_SIZE})"
        )

    # Add lazy substitutions for use in any Task property
    add_or_update_substitution(L_TASK_COUNT, str(num_tasks))
    add_or_update_substitution(L_TASK_GROUP_NAME, task_group.name)
    add_or_update_substitution(
        L_TASK_GROUP_NUMBER, formatted_number_str(effective_tg_number, num_task_groups)
    )
    add_or_update_substitution(L_TASK_GROUP_COUNT, str(num_task_groups))

    num_submitted_tasks = 0

    # Determine number of parallel upload threads
    parallel_upload_threads = (
        CONFIG_WR.parallel_batches
        if ARGS_PARSER.parallel_batches is None
        else ARGS_PARSER.parallel_batches
    )
    parallel_upload_threads = (
        DEFAULT_PARALLEL_TASK_BATCH_UPLOAD_THREADS
        if parallel_upload_threads is None
        else parallel_upload_threads
    )

    # Single batch or sequential batch submission
    if parallel_upload_threads == 1 or num_task_batches == 1:
        if num_task_batches > 1:
            print_info(f"Uploading {num_task_batches} Task batches sequentially")
        for batch_number in range(num_task_batches):
            if ARGS_PARSER.pause_between_batches is not None and num_task_batches > 1:
                pause_between_batches(
                    task_batch_size=TASK_BATCH_SIZE,
                    batch_number=batch_number,
                    num_tasks=num_tasks,
                )
            tasks_list = generate_batch_of_tasks_for_task_group(
                (TASK_BATCH_SIZE * batch_number),
                min(TASK_BATCH_SIZE * (batch_number + 1), num_tasks),
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
            )
            num_submitted_tasks += submit_batch_of_tasks_to_task_group(
                tasks_list,
                work_requirement,
                task_group,
                num_task_batches,
                batch_number,
                TASK_BATCH_SIZE,
                num_tasks,
            )

    # Parallel batches
    else:
        if ARGS_PARSER.pause_between_batches is not None:
            print_warning(
                "Option 'pause-between-batches/-P' is ignored for parallel batch uploads"
            )
        max_workers = min(num_task_batches, parallel_upload_threads)
        print_info(
            f"Submitting Task batches using {max_workers} parallel submission threads"
        )
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            executors: list[Future] = []
            for batch_number in range(num_task_batches):
                executors.append(
                    executor.submit(
                        submit_batch_of_tasks_to_task_group,
                        generate_batch_of_tasks_for_task_group(
                            (TASK_BATCH_SIZE * batch_number),
                            min(TASK_BATCH_SIZE * (batch_number + 1), num_tasks),
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
                        work_requirement,
                        task_group,
                        num_task_batches,
                        batch_number,
                        TASK_BATCH_SIZE,
                        num_tasks,
                    )
                )

        num_submitted_tasks = sum(x.result() for x in executors)

    if not ARGS_PARSER.dry_run:
        if num_submitted_tasks > 0:
            print_info(
                f"Added a total of {num_submitted_tasks:,d} Task(s) to Task Group"
                f" '{task_group.name}'"
            )
        else:
            print_info(f"No Tasks added to Task Group '{task_group.name}'")


def generate_batch_of_tasks_for_task_group(
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
                        wr_data.get(SET_TASK_NAMES, CONFIG_WR.set_task_names),
                    ),
                )
            )
            or False
        )

        display_task_number = task_number + task_number_offset
        display_num_tasks = task_number_offset + num_tasks

        task_name = get_task_name(
            task.get(NAME, task.get(TASK_NAME, CONFIG_WR.task_name)),
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
        process_variable_substitutions_insitu(task)
        config_wr = update_config_work_requirement_object(deepcopy(CONFIG_WR))

        arguments_list = check_list(
            task.get(
                ARGS,
                wr_data.get(ARGS, task_group_data.get(ARGS, config_wr.args)),
            )
        )
        args_prefix = check_list(
            wr_data.get(
                ARGS_PREFIX, task_group_data.get(ARGS_PREFIX, config_wr.args_prefix)
            )
        )
        args_postfix = check_list(
            wr_data.get(
                ARGS_POSTFIX, task_group_data.get(ARGS_POSTFIX, config_wr.args_postfix)
            )
        )
        arguments_list = assemble_arguments(args_prefix, arguments_list, args_postfix)
        env = check_dict(
            task.get(ENV, task_group_data.get(ENV, wr_data.get(ENV, config_wr.env)))
        )
        add_env = check_dict(
            wr_data.get(
                ADD_ENVIRONMENT,
                task_group_data.get(ADD_ENVIRONMENT, config_wr.add_environment),
            )
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
                )
            )
            or False
        )

        # Task timeout is automatically inherited from the Task Group level
        # unless overridden by the Task
        task_timeout_minutes = check_float_or_int(
            task.get(TASK_LEVEL_TIMEOUT, CONFIG_WR.task_level_timeout)
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
            )
        )
        task_data_outputs = check_list(
            task.get(
                TASK_DATA_OUTPUTS,
                task_group_data.get(
                    TASK_DATA_OUTPUTS,
                    wr_data.get(TASK_DATA_OUTPUTS, config_wr.task_data_outputs),
                ),
            )
        )
        # This will 'pop' any 'localFile' properties, required for the
        # following 'generate' call
        RCLONE_UPLOADED_FILES.upload_dataclient_input_files(task_data_inputs)  # type: ignore[union-attr]
        task_data_inputs_and_outputs = generate_taskdata_object(
            task_data_inputs, task_data_outputs
        )

        # If there's no task type in the task definition, AND
        # there's only one task type at the task group level,
        # use that task type
        try:
            task_type = task[TASK_TYPE]
        except KeyError:
            if len(task_group.runSpecification.taskTypes) == 1:
                task_type = task_group.runSpecification.taskTypes[0]
            else:
                task_type = config_wr.task_type

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
                wr_name=ID,
                namespace=CONFIG_COMMON.namespace,
                total_num_task_groups=num_task_groups,
                total_num_tasks=display_num_tasks,
            )
        )

    return tasks_list


def submit_batch_of_tasks_to_task_group(
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
    if ARGS_PARSER.dry_run:
        global WR_SNAPSHOT
        WR_SNAPSHOT.add_tasks(task_group.name, tasks_list)
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

    warning_already_displayed = False
    last_exception = None

    for attempts in range(MAX_BATCH_SUBMIT_ATTEMPTS):
        try:
            CLIENT.work_client.add_tasks_to_task_group_by_name(
                CONFIG_COMMON.namespace,
                work_requirement.name,
                task_group.name,
                tasks_list,
            )
            report_success()
            return len(tasks_list)

        except Exception as e:
            if "InvalidRequestException" in str(e):
                # Permanent failure; don't retry
                last_exception = e
                break

            if "Task names must be unique within task group" in str(e):
                # Interpret this as success ... it implies that a previous
                # errored (500?) submission of this batch must have succeeded
                report_success()
                return len(tasks_list)

            if not warning_already_displayed:
                print_warning(
                    f"Failed to submit batch {batch_number_str} of {num_task_batches}: {e}"
                )
                warning_already_displayed = True

            if attempts < MAX_BATCH_SUBMIT_ATTEMPTS - 1:
                print_info(
                    f"Retrying submission of batch {batch_number_str} "
                    f"(retry attempt {attempts + 1} of {MAX_BATCH_SUBMIT_ATTEMPTS - 1})"
                )
            last_exception = e

    raise RuntimeError(
        f"Failed to submit batch {batch_number_str} {task_range_str}of {num_task_batches}: "
        f"{last_exception}"
    )


def follow_progress(work_requirement: WorkRequirement) -> None:
    """
    Follow and report the progress of a Work Requirement.

    With --exit-on-failure, exits with code 1 if the Work Requirement ends in
    a failure state (FAILED/CANCELLED), so that a following submission reflects
    the outcome.
    """
    if not ARGS_PARSER.dry_run:
        print_info("Following Work Requirement event stream")
        wr_id = cast(str, work_requirement.id)
        follow_events(wr_id, YDIDType.WORK_REQUIREMENT)
        if ARGS_PARSER.exit_on_failure and work_requirement_failed(wr_id):
            sys_exit(1)


def follow_progress_bar(work_requirement: WorkRequirement) -> None:
    """
    Follow a Work Requirement and display a live progress bar.

    With --exit-on-failure, exits with code 1 if the Work Requirement ends in
    a failure state (FAILED/CANCELLED), so that a following submission reflects
    the outcome.
    """
    if ARGS_PARSER.dry_run:
        return
    wr_id = cast(str, work_requirement.id)
    follow_work_requirement_with_progress(wr_id)
    if ARGS_PARSER.exit_on_failure and work_requirement_failed(wr_id):
        sys_exit(1)


def cleanup_on_failure(work_requirement: WorkRequirement) -> None:
    """
    Clean up the Work Requirement and any uploaded Objects on failure.
    """
    if ARGS_PARSER.dry_run:
        return

    CLIENT.work_client.cancel_work_requirement(work_requirement)
    print_warning(f"Cancelled Work Requirement '{work_requirement.name}'")

    RCLONE_UPLOADED_FILES.delete()  # type: ignore[union-attr]


def add_to_existing_work_requirement(
    files_directory: str,
    wr_data: dict | None = None,
    task_count: int | None = None,
) -> None:
    """
    Add task groups and/or tasks to an existing Work Requirement identified
    by the --add-to argument (name or YellowDog ID).
    """
    wr_summary = get_work_requirement_summary_by_name_or_id(
        CLIENT,
        ARGS_PARSER.add_to,  # type: ignore[arg-type]
        CONFIG_COMMON.namespace,
    )
    if wr_summary is None:
        raise ValueError(
            f"Work Requirement '{ARGS_PARSER.add_to}' not found in namespace"
            f" '{CONFIG_COMMON.namespace}'"
        )

    if (
        wr_summary.status.finished  # type: ignore[union-attr]
        or wr_summary.status == WorkRequirementStatus.CANCELLING
    ):
        raise ValueError(
            f"Work Requirement '{wr_summary.name}' has terminal status"
            f" '{wr_summary.status}': cannot add tasks"
        )

    work_requirement = CLIENT.work_client.get_work_requirement_by_id(
        cast(str, wr_summary.id)
    )
    existing_tgs: list[TaskGroup] = work_requirement.taskGroups or []

    # Use the existing WR's name as the ID for substitutions
    global ID, CONFIG_WR
    ID = cast(str, work_requirement.name)
    add_substitutions_without_overwriting(subs={L_WR_NAME: ID})
    CONFIG_WR = update_config_work_requirement_object(CONFIG_WR)

    # Initialise rclone file uploads
    global RCLONE_UPLOADED_FILES
    RCLONE_UPLOADED_FILES = RcloneUploadedFiles(files_directory=files_directory)

    # Build spec data
    wr_data = {TASK_GROUPS: [{TASKS: [{}]}]} if wr_data is None else wr_data
    check_dict(wr_data)

    if cast(dict, wr_data).get(TASK_TYPE) is not None:
        if wr_data.get(TASK_TYPES) is None:
            wr_data[TASK_TYPES] = [wr_data[TASK_TYPE]]

    process_variable_substitutions_insitu(cast(dict, wr_data))

    # Expand task groups from taskGroupCount if needed
    task_group_count = check_float_or_int(
        wr_data.get(TASK_GROUP_COUNT, CONFIG_WR.task_group_count)
    )
    if task_group_count is not None and task_group_count > 1:
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
                f"using '{TASK_GROUP_COUNT} = {int(task_group_count)}'"
            )

    n_existing = len(existing_tgs)
    n_spec = len(wr_data[TASK_GROUPS])
    total_tgs = n_existing + n_spec

    # Create TaskGroup objects for all spec TGs with WR-relative numbering
    spec_task_groups: list[TaskGroup] = []
    for tg_number, task_group_data in enumerate(wr_data[TASK_GROUPS]):
        spec_task_groups.append(
            create_task_group(
                tg_number,
                cast(dict, wr_data),
                task_group_data,
                tg_number_offset=n_existing,
                total_num_task_groups=total_tgs,
                files_directory=files_directory,
            )
        )

    # Partition spec TGs: those whose name matches an existing TG (add tasks
    # to existing TG) vs those that are new (add TG to WR first)
    matched: list[
        tuple[int, TaskGroup, TaskGroup]
    ] = []  # (spec_idx, spec_tg, existing_tg)
    new_tgs: list[tuple[int, TaskGroup]] = []  # (spec_idx, spec_tg)
    for spec_idx, spec_tg in enumerate(spec_task_groups):
        matched_existing = next(
            (tg for tg in existing_tgs if tg.name == spec_tg.name), None
        )
        if matched_existing is not None:
            matched.append((spec_idx, spec_tg, matched_existing))
        else:
            new_tgs.append((spec_idx, spec_tg))

    # For matched (existing) Task Groups, the platform does not allow
    # mutating a Task Group's taskTypes after creation. Detect any spec
    # Tasks whose taskType is not in the existing Task Group's allowlist
    # and fail fast with a clear error, rather than letting the platform
    # reject those Tasks downstream.
    for _, spec_tg, existing_tg in matched:
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

    # If there are new TGs, update the Work Requirement with the full TG list
    if new_tgs:
        work_requirement.taskGroups = existing_tgs + [tg for _, tg in new_tgs]
        work_requirement = CLIENT.work_client.update_work_requirement(work_requirement)
        print_info(
            f"Added {len(new_tgs)} new Task Group(s) to existing Work Requirement '{ID}'"
        )

    # Add tasks to new TGs (no task offset)
    for spec_idx, spec_tg in new_tgs:
        add_tasks_to_task_group(
            tg_number=spec_idx,
            task_group=spec_tg,
            wr_data=cast(dict, wr_data),
            task_count=task_count,
            work_requirement=work_requirement,
            files_directory=files_directory,
            tg_number_offset=n_existing,
            total_num_task_groups=total_tgs,
            task_number_offset=0,
        )

    # Add tasks to matched (existing) TGs, offsetting task numbers
    for spec_idx, spec_tg, existing_tg in matched:
        task_summary = existing_tg.taskSummary
        existing_task_count: int = (
            task_summary.taskCount if task_summary is not None else 0
        )
        add_tasks_to_task_group(
            tg_number=spec_idx,
            task_group=existing_tg,
            wr_data=cast(dict, wr_data),
            task_count=task_count,
            work_requirement=work_requirement,
            files_directory=files_directory,
            tg_number_offset=n_existing,
            total_num_task_groups=total_tgs,
            task_number_offset=existing_task_count,
        )

    if ARGS_PARSER.progress:
        follow_progress_bar(work_requirement)
    elif ARGS_PARSER.follow:
        follow_progress(work_requirement)


def submit_json_raw(wr_file: str):
    """
    Submit a 'raw' JSON Work Requirement, consisting of a combined Work
    Requirement definition and the constituent Tasks.
    """

    # Load file contents, with variable substitutions
    if wr_file.lower().endswith(".jsonnet"):
        wr_data = load_jsonnet_file_with_variable_substitutions(wr_file)
    elif wr_file.lower().endswith(".json"):
        wr_data = load_json_file_with_variable_substitutions(wr_file)
    else:
        raise ValueError(
            f"Work Requirement file '{wr_file}' must end in '.json' or '.jsonnet'"
        )

    # Lazy substitution of Work Requirement name
    wr_data["name"] = format_yd_name(wr_data["name"])
    wr_name = wr_data["name"]
    add_substitutions_without_overwriting(subs={L_WR_NAME: wr_name})
    process_variable_substitutions_insitu(wr_data)

    if ARGS_PARSER.dry_run:
        # This will show the results of any variable substitutions
        print_info("Dry-run: Printing JSON Work Requirement specification:")
        print_json(wr_data)
        print_info("Dry-run: Complete")
        return

    # Extract Tasks from Task Groups
    task_lists = {}
    try:
        task_groups = wr_data["taskGroups"]
    except KeyError:
        raise KeyError("Property 'taskGroups' is not defined")
    if not task_groups:
        raise ValueError("There must be at least one Task Group")
    for task_group in task_groups:
        task_lists[task_group["name"]] = task_group.get("tasks", [])
        task_group.pop("tasks", None)

    # Submit the Work Requirement and its Task Groups
    response = requests.post(
        url=f"{CONFIG_COMMON.url}/work/requirements",
        headers={"Authorization": f"yd-key {CONFIG_COMMON.key}:{CONFIG_COMMON.secret}"},
        json=wr_data,
    )

    if response.status_code == 200:
        wr_id = json_loads(response.text)["id"]
        print_info(
            f"Created Work Requirement '{wr_data['namespace']}/{wr_name}' ({wr_id})"
        )
        if ARGS_PARSER.quiet:
            print(wr_id)
    else:
        print_error(f"Failed to create Work Requirement '{wr_name}'")
        raise RuntimeError(f"{response.text}")

    if ARGS_PARSER.hold:
        CLIENT.work_client.hold_work_requirement_by_id(wr_id)
        print_info("Work Requirement status set to 'HELD'")

    # Submit Tasks in batches
    for task_group_name, task_list in task_lists.items():
        if not task_list:
            print_info(f"No Tasks to add to Task Group '{task_group_name}'")
            continue
        num_batches = ceil(len(task_list) / TASK_BATCH_SIZE)
        max_workers = min(
            num_batches,
            (
                DEFAULT_PARALLEL_TASK_BATCH_UPLOAD_THREADS
                if ARGS_PARSER.parallel_batches is None
                else ARGS_PARSER.parallel_batches
            ),
        )
        print_info(
            f"Submitting task batches using {max_workers} parallel submission thread(s)"
        )
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            executors: list[Future] = []
            for batch_number in range(num_batches):
                task_batch = task_list[
                    batch_number * TASK_BATCH_SIZE : min(
                        len(task_list), (batch_number + 1) * TASK_BATCH_SIZE
                    )
                ]
                executors.append(
                    executor.submit(
                        submit_json_task_batch,
                        task_batch,
                        batch_number,
                        num_batches,
                        task_group_name,
                        wr_name,
                        wr_data["namespace"],
                    )
                )

            executor.shutdown()
            num_submitted_tasks = sum([x.result() for x in executors])
            print_info(
                f"Added a total of {num_submitted_tasks} Task(s) to Task Group '{task_group_name}'"
            )

    if ARGS_PARSER.follow:
        follow_progress(CLIENT.work_client.get_work_requirement_by_id(wr_id))


def submit_json_task_batch(
    task_batch: dict,
    batch_number: int,
    num_batches: int,
    task_group_name: str,
    wr_name: str,
    namespace: str,
) -> int:
    """
    Submit a batch of tasks using the REST API. Return the number of tasks submitted.
    """
    task_batch_compressed = compress(json_dumps(task_batch).encode("utf-8"))

    response = requests.post(
        url=(
            f"{CONFIG_COMMON.url}/work/namespaces/{namespace}"
            f"/requirements/{wr_name}/taskGroups/{task_group_name}/tasks"
        ),
        headers={
            "Authorization": f"yd-key {CONFIG_COMMON.key}:{CONFIG_COMMON.secret}",
            "Content-Encoding": "gzip",
            "Content-Type": "application/json",
        },
        data=task_batch_compressed,
    )

    if response.status_code == 200:
        print_info(
            f"Added {len(task_batch)} Task(s) to Task Group "
            f"'{task_group_name}' (Batch {formatted_number_str(batch_number, num_batches)} "
            f"of {num_batches})"
        )
        return len(task_batch)

    print_error(
        f"Failed to submit batch {batch_number + 1} of {num_batches}: {response.text}"
    )

    return 0


# Standalone entry point
if __name__ == "__main__":
    main()
