"""
yd-submit's Task Groups, built from a Work Requirement specification: the
checks on its 'taskGroups', the 'taskType' shorthand, 'taskGroupCount'
expansion, and create_task_group(), which turns one Task Group of the
specification into the SDK's TaskGroup.

A library, not part of the command: what it needs of the run is given to it
(the [workRequirement] configuration, the Task Group's TaskGroupPosition,
and a callback for the legacy retry mechanism's deprecation warning, which
the command gives once per run), so it never imports submit.py.

The order of create_task_group()'s steps is load-bearing. Task types given
by the Tasks are gathered, and 'taskCount' read, before the Task Group's
variables are substituted; its name is decided, and with it the lazy
substitutions, before anything else of it is read; and the steps after run
in the order their errors and warnings have always been reported in.
"""

from collections.abc import Callable
from copy import deepcopy
from datetime import timedelta

from yellowdog_client.model import (
    CloudProvider,
    FailurePolicy,
    RetryPolicy,
    RunSpecification,
    TaskGroup,
    TaskTemplate,
)
from yellowdog_client.model.instance_pricing_preference import (
    InstancePricingPreference,
)

from yellowdog_cli.utils.config_types import ConfigWorkRequirement
from yellowdog_cli.utils.misc_utils import format_yd_name
from yellowdog_cli.utils.printing import print_info, print_warning
from yellowdog_cli.utils.property_cascade import Cascade
from yellowdog_cli.utils.property_names import (
    COMPLETED_TASK_TTL,
    DISABLE_PREALLOCATION,
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
    TASK_COUNT,
    TASK_DATA,
    TASK_DATA_FILE,
    TASK_DATA_FILES,
    TASK_GROUP_COUNT,
    TASK_GROUP_NAME,
    TASK_GROUP_TAG,
    TASK_GROUPS,
    TASK_TEMPLATE,
    TASK_TIMEOUT,
    TASK_TYPE,
    TASK_TYPES,
    TASKS,
    TASKS_PER_WORKER,
    VCPUS,
    WORKER_TAGS,
)
from yellowdog_cli.utils.submit_utils import (
    double_range_from_list,
    generate_dependencies,
    generate_failure_policy,
    generate_retry_policy,
    generate_task_error_matchers_list,
    get_task_group_name,
    resolve_task_data,
    update_config_work_requirement_object,
)
from yellowdog_cli.utils.task_group_position import TaskGroupPosition
from yellowdog_cli.utils.type_check import (
    check_bool,
    check_dict,
    check_float_or_int,
    check_int,
    check_list,
    check_str,
)
from yellowdog_cli.utils.variable_substitution import resolve_variables_insitu


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


def expand_task_groups(config_wr: ConfigWorkRequirement, wr_data: dict) -> None:
    """
    Expand a single Task Group into 'taskGroupCount' copies of itself, in
    place. A count given as a whole-valued float ('2.0', which the schema
    accepts as an integer) is taken as that integer; any other non-integer
    is an error.
    """
    task_group_count = Cascade(wr_data).checked(
        TASK_GROUP_COUNT, check_float_or_int, config_wr.task_group_count
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


def create_task_group(
    config_wr: ConfigWorkRequirement,
    position: TaskGroupPosition,
    wr_data: dict,
    task_group_data: dict,
    files_directory: str = "",
    on_legacy_retry: Callable[[], None] = lambda: None,
) -> TaskGroup:
    """
    Create a TaskGroup object from 'task_group_data', numbered and named by
    its 'position' in the Work Requirement. 'config_wr' is the run's
    configuration, copied here before the Task Group's substitutions are
    applied to it; 'on_legacy_retry' is called if the Task Group uses the
    deprecated retry properties.
    """
    promote_task_type(task_group_data)
    # The Task Group's properties, from itself or the Work Requirement; the
    # configuration's, from the copy below, are the defaults
    levels = Cascade(wr_data, task_group_data)

    # Gather task types, in order of first appearance
    task_types_from_tasks = [
        task[TASK_TYPE] for task in task_group_data[TASKS] if TASK_TYPE in task
    ]

    task_group_name, num_tasks = _name_task_group(
        config_wr, position, task_group_data, levels
    )
    # Copy the run's configuration and apply the lazy substitutions to it
    config_wr = update_config_work_requirement_object(deepcopy(config_wr))

    # Resolve taskTemplate early so it can satisfy the task-type validation below
    task_template_data = levels.checked(
        TASK_TEMPLATE, check_dict, config_wr.task_template
    )
    task_types = _task_types(
        levels,
        config_wr,
        task_types_from_tasks,
        task_template_data,
        task_group_name,
        num_tasks,
    )
    run_specification = _run_specification(
        levels, config_wr, wr_data, task_group_data, task_types, on_legacy_retry
    )
    ctttl_data = levels.checked(
        COMPLETED_TASK_TTL, check_float_or_int, config_wr.completed_task_ttl
    )
    completed_task_ttl = None if ctttl_data is None else timedelta(minutes=ctttl_data)
    task_template = _task_template(task_template_data, files_directory)

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


def _name_task_group(
    config_wr: ConfigWorkRequirement,
    position: TaskGroupPosition,
    task_group_data: dict,
    levels: Cascade,
) -> tuple[str, int]:
    """
    The Task Group's name and its number of Tasks ('taskCount' if a single
    Task is to be expanded), with its lazy substitutions defined from them
    and then applied to the Task Group's own properties, in place.
    """
    num_tasks = len(task_group_data[TASKS])
    if num_tasks == 1:  # Account for Task expansion
        _task_count = levels.checked(TASK_COUNT, check_int, config_wr.task_count)
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
            check_str(task_group_data.get(NAME, config_wr.task_group_name), NAME),
            position.number,
            position.count,
            num_tasks,
        )
    )

    # Add lazy substitutions for use in any Task Group property
    position.substitute(task_group_name, num_tasks)
    resolve_variables_insitu(task_group_data)
    return task_group_name, num_tasks


def _task_types(
    levels: Cascade,
    config_wr: ConfigWorkRequirement,
    task_types_from_tasks: list,
    task_template_data: dict | None,
    task_group_name: str,
    num_tasks: int,
) -> list:
    """
    The Task Group's task types: those it or the Work Requirement declares,
    then those its Tasks name, else the configuration's, else its template's;
    an error if it has Tasks and none of these gives one.
    """
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
    return task_types


def _run_specification(
    levels: Cascade,
    config_wr: ConfigWorkRequirement,
    wr_data: dict,
    task_group_data: dict,
    task_types: list,
    on_legacy_retry: Callable[[], None],
) -> RunSpecification:
    """
    The Task Group's RunSpecification: where and how its Tasks run, and how
    they are retried.
    """
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

    retry_policy, failure_policy = _retry_policies(
        config_wr, wr_data, task_group_data, on_legacy_retry
    )

    return RunSpecification(
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


def _retry_policies(
    config_wr: ConfigWorkRequirement,
    wr_data: dict,
    task_group_data: dict,
    on_legacy_retry: Callable[[], None],
) -> tuple[RetryPolicy | None, FailurePolicy | None]:
    """
    The Task Group's retry and failure policies. Only 'retryPolicy' overlaps
    with the deprecated 'maximumTaskRetries'/'retryableErrors', and combining
    them is an error; 'failurePolicy' adds resubmission on top of either
    retry mechanism. 'on_legacy_retry' is called if the deprecated one is
    in use.
    """
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
        on_legacy_retry()
    return retry_policy, failure_policy


def _task_template(
    task_template_data: dict | None, files_directory: str
) -> TaskTemplate | None:
    """
    The Task Group's TaskTemplate, its 'taskDataFile(s)' read into
    'taskData'; None if it has none.
    """
    if task_template_data is None:
        return None
    tt = dict(task_template_data)
    try:
        task_data = resolve_task_data(tt, files_directory)
    except ValueError as e:
        raise ValueError(f"taskTemplate: {e}") from e
    tt.pop(TASK_DATA_FILE, None)
    tt.pop(TASK_DATA_FILES, None)
    if task_data is not None:
        tt[TASK_DATA] = task_data
    return TaskTemplate(**tt)
