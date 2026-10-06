"""
yd-submit's Tasks, generated a batch at a time from a Work Requirement
specification: generate_batch_of_tasks() turns the Tasks of one of its Task
Groups, numbered from 'start' to 'end', into the SDK's Tasks.

A library, not part of the command: what a Task Group's Tasks are generated
from is given to it as one TaskSource, built once per Task Group, so it never
imports submit.py.

The order of _generate_task()'s steps is load-bearing. The Task's name is
decided first, from the run's configuration rather than a copy of it, and
with it the Task-level lazy substitutions; only then is the Task substituted
in place and the configuration copied with them applied, and everything else
of the Task read from those.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from typing import cast

from yellowdog_client.model import Task, TaskGroup

from yellowdog_cli.utils.config_types import ConfigWorkRequirement
from yellowdog_cli.utils.misc_utils import format_yd_name
from yellowdog_cli.utils.property_cascade import Cascade
from yellowdog_cli.utils.property_names import (
    ADD_ENVIRONMENT,
    ADD_YD_ENV_VARS,
    ARGS,
    ARGS_POSTFIX,
    ARGS_PREFIX,
    ENV,
    NAME,
    SET_TASK_NAMES,
    TASK_DATA_INPUTS,
    TASK_DATA_OUTPUTS,
    TASK_GROUPS,
    TASK_LEVEL_TIMEOUT,
    TASK_NAME,
    TASK_TYPE,
)
from yellowdog_cli.utils.submit_utils import (
    RcloneUploadedFiles,
    assemble_arguments,
    create_task,
    formatted_number_str,
    generate_taskdata_object,
    get_task_data_property,
    get_task_name,
    merge_environment,
    update_config_work_requirement_object,
)
from yellowdog_cli.utils.task_group_position import TaskGroupPosition
from yellowdog_cli.utils.type_check import (
    check_bool,
    check_dict,
    check_float_or_int,
    check_list,
    check_str,
)
from yellowdog_cli.utils.variable_substitution import (
    add_or_update_substitution,
    resolve_variables_insitu,
)
from yellowdog_cli.utils.variable_syntax import (
    L_TASK_NAME,
    L_TASK_NUMBER,
    VAR_NAME_OF_UNNAMED_TASK,
)


@dataclass(frozen=True)
class TaskSource:
    """
    What one Task Group's Tasks are generated from: the run's configuration,
    the Work Requirement's name and namespace, the specification and the
    directory its files are found from, the Task Group being added to and
    its position, the specification's Tasks for it ('task_count' copies of
    the first when set) and how many are being added, and where the Tasks'
    data client input files are uploaded.
    """

    config_wr: ConfigWorkRequirement
    wr_name: str
    namespace: str
    wr_data: dict
    files_directory: str
    task_group: TaskGroup
    position: TaskGroupPosition
    tasks: list
    task_count: int | None
    num_tasks: int
    uploaded_files: RcloneUploadedFiles | None

    @property
    def task_group_data(self) -> dict:
        """
        The specification's Task Group the Tasks belong to.
        """
        return self.wr_data[TASK_GROUPS][self.position.spec_index]


def generate_batch_of_tasks(
    source: TaskSource, start_task_number: int, end_task_number: int
) -> list[Task]:
    """
    Generate the Tasks numbered 'start_task_number' up to 'end_task_number'
    of the Task Group 'source' describes, for subsequent addition to it,
    numbered on from the Tasks it already holds.
    """
    return [
        _generate_task(source, task_number)
        for task_number in range(start_task_number, end_task_number)
    ]


def _generate_task(source: TaskSource, task_number: int) -> Task:
    """
    One Task, its data client input files uploaded as it is generated.
    """
    task_group_data = source.task_group_data
    task = source.tasks[task_number] if source.task_count is None else source.tasks[0]
    # The Task's properties, from itself, its Task Group or the Work
    # Requirement; the configuration's are the defaults
    levels = Cascade(source.wr_data, task_group_data, task)

    display_task_number = task_number + source.position.existing_tasks
    display_num_tasks = source.position.existing_tasks + source.num_tasks

    task_name = _name_task(source, task, levels, display_task_number, display_num_tasks)
    resolve_variables_insitu(task)
    config_wr = update_config_work_requirement_object(deepcopy(source.config_wr))

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
        levels.checked(ADD_YD_ENV_VARS, check_bool, config_wr.add_yd_env_vars) or False
    )

    # The Task's own 'timeout', set on the Task or in the configuration only;
    # without one, the Platform applies its Task Group's 'taskTimeout'
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
    # Uploads the inputs' local files, and 'pop's their 'localFile'
    # properties, which the following 'generate' call requires
    source.uploaded_files.upload_dataclient_input_files(task_data_inputs)  # type: ignore[union-attr]
    task_data_inputs_and_outputs = generate_taskdata_object(
        task_data_inputs, task_data_outputs
    )

    task_type = _task_type_of(
        task, source.task_group, config_wr, task_name, display_task_number
    )

    return create_task(
        wr_data=source.wr_data,
        task_group_data=task_group_data,
        task_data=task,
        task_name=task_name,
        task_number=display_task_number + 1,
        tg_name=source.task_group.name,
        tg_number=source.position.number + 1,
        task_type=cast(str, task_type),
        args=cast(list, arguments_list),
        task_data_property=get_task_data_property(
            config_wr,
            source.wr_data,
            task_group_data,
            task,
            task_name,
            source.files_directory,
        ),
        env=env,
        task_timeout=task_timeout,
        add_yd_env_vars=add_yd_env_vars,
        task_data_inputs_and_outputs=task_data_inputs_and_outputs,
        wr_name=source.wr_name,
        namespace=source.namespace,
        total_num_task_groups=source.position.count,
        total_num_tasks=display_num_tasks,
    )


def _name_task(
    source: TaskSource,
    task: dict,
    levels: Cascade,
    display_task_number: int,
    display_num_tasks: int,
) -> str | None:
    """
    The Task's name, None if it is to have none, with its Task-level lazy
    substitutions defined from it and its number.
    """
    set_task_names = (
        levels.checked(SET_TASK_NAMES, check_bool, source.config_wr.set_task_names)
        or False
    )

    # The run's configuration, not a per-Task copy: get_task_name() makes the
    # Task-level lazy substitutions in the name itself, and the per-Task
    # copy can only be made once the name it substitutes is known
    task_name = get_task_name(
        check_str(
            task.get(NAME, task.get(TASK_NAME, source.config_wr.task_name)), NAME
        ),
        set_task_names,
        display_task_number,
        display_num_tasks,
        source.position.number,
        source.position.count,
        source.task_group.name,
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
    return task_name


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
