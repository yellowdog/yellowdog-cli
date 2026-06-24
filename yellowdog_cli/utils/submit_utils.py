"""
Utility functions for use with the submit command.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from os import chdir, getcwd
from os.path import abspath, exists
from pathlib import Path
from time import sleep
from typing import cast

from rclone_api import Config
from yellowdog_client.model import (
    DoubleRange,
    Task,
    TaskData,
    TaskDataInput,
    TaskDataOutput,
    TaskErrorMatcher,
    TaskStatus,
)

from yellowdog_cli.utils.config_types import ConfigWorkRequirement
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.property_names import (
    DATA_CLIENT_LOCAL_PATH,
    DATA_CLIENT_UPLOAD_PATH,
    DEPENDENCIES,
    DEPENDENT_ON,
    ERROR_TYPES,
    PROCESS_EXIT_CODES,
    RETRYABLE_ERRORS,
    STATUSES_AT_FAILURE,
    TASK_DATA,
    TASK_DATA_FILE,
    TASK_DATA_FILES,
    TASK_DATA_SOURCE,
    TASK_GROUPS,
    TASK_TAG,
    TASKS,
)
from yellowdog_cli.utils.rclone_utils import make_rclone, parse_rclone_config
from yellowdog_cli.utils.settings import (
    L_TASK_COUNT,
    L_TASK_GROUP_COUNT,
    L_TASK_GROUP_NAME,
    L_TASK_GROUP_NUMBER,
    L_TASK_NUMBER,
    RCLONE_PREFIX,
    VAR_CLOSING_DELIMITER,
    VAR_OPENING_DELIMITER,
)
from yellowdog_cli.utils.type_check import check_list, check_str
from yellowdog_cli.utils.variables import (
    process_variable_substitutions_in_file_contents,
    process_variable_substitutions_insitu,
    resolve_filename,
)
from yellowdog_cli.utils.wrapper import ARGS_PARSER

# Names for environment variables optionally added to each Task's environment
YD_NAMESPACE = "YD_NAMESPACE"
YD_NUM_TASK_GROUPS = "YD_NUM_TASK_GROUPS"
YD_NUM_TASKS = "YD_NUM_TASKS"
YD_TAG = "YD_TAG"
YD_TASK_GROUP_NAME = "YD_TASK_GROUP_NAME"
YD_TASK_GROUP_NUMBER = "YD_TASK_GROUP_NUMBER"
YD_TASK_NAME = "YD_TASK_NAME"
YD_TASK_NUMBER = "YD_TASK_NUMBER"
YD_WORK_REQUIREMENT_NAME = "YD_WORK_REQUIREMENT_NAME"


def assemble_arguments(
    prefix: list | None,
    args: list | None,
    postfix: list | None,
) -> list | None:
    """
    Combine argumentsPrefix + arguments + argumentsPostfix.
    If both prefix and postfix are empty/None, returns args unchanged.
    """
    if not prefix and not postfix:
        return args
    return (prefix or []) + (args or []) + (postfix or [])


def merge_environment(
    base: dict | None,
    additions: dict | None,
) -> dict | None:
    """
    Merge addEnvironment entries into the task's environment dict.
    Keys in additions override existing keys in base.
    Returns base unchanged if additions is empty/None.
    """
    if not additions:
        return base
    return {**(base or {}), **additions}


def update_config_work_requirement_object(
    config_wr: ConfigWorkRequirement,
) -> ConfigWorkRequirement:
    """
    Update a ConfigWorkRequirement Object using the current
    variable substitutions. Returns the updated object.
    """
    config_wr_dict = config_wr.__dict__
    process_variable_substitutions_insitu(config_wr_dict)
    return ConfigWorkRequirement(**config_wr_dict)


def pause_between_batches(task_batch_size: int, batch_number: int, num_tasks: int):
    """
    Process a pause between Task batches.
    """
    if ARGS_PARSER.pause_between_batches is None:
        return

    first_batch: bool = batch_number == 0
    task_num_start = (task_batch_size * batch_number) + 1
    task_num_end = min(task_batch_size * (batch_number + 1), num_tasks)
    task_range_str = (
        f"Tasks {task_num_start}-{task_num_end}"
        if task_num_start != task_num_end
        else f"Task {task_num_start}"
    )

    if ARGS_PARSER.pause_between_batches <= 0:  # Manual delay
        print_info(
            (
                f"Submitting batch number {batch_number + 1} ({task_range_str})"
                if first_batch
                else (
                    "Pausing before submitting batch number"
                    f" {batch_number + 1} ({task_range_str}). Press enter to continue:"
                )
            ),
            override_quiet=True,
        )
        if not first_batch:
            input()

    elif ARGS_PARSER.pause_between_batches > 0:  # Automatic delay
        print_info(
            f"Submitting batch number {batch_number + 1} ({task_range_str})"
            if first_batch
            else (
                f"Pausing for {ARGS_PARSER.pause_between_batches} seconds before"
                f" submitting batch number {batch_number + 1}"
                f" ({task_range_str})"
            )
        )
        if not first_batch:
            sleep(ARGS_PARSER.pause_between_batches)


def generate_taskdata_object(
    task_data_inputs: list[dict] | None, task_data_outputs: list[dict] | None
) -> TaskData | None:
    """
    Generate a TaskData object based on task data inputs/outputs.
    """
    if task_data_inputs is None and task_data_outputs is None:
        return None

    try:
        return TaskData(
            inputs=(
                None
                if task_data_inputs is None
                else [TaskDataInput(**x) for x in task_data_inputs]
            ),
            outputs=(
                None
                if task_data_outputs is None
                else [TaskDataOutput(**x) for x in task_data_outputs]
            ),
        )
    except TypeError as e:
        raise TypeError(
            f"Unable to generate 'taskDataInputs' or 'taskDataOutputs' list: {e!s}"
        )


def generate_task_error_matchers_list(
    config_wr: ConfigWorkRequirement, wr_data: dict, tg_data: dict
) -> list[TaskErrorMatcher] | None:
    """
    Generate a list of TaskErrorMatcher objects.
    """
    error_matchers: list[dict] | None = check_list(
        tg_data.get(
            RETRYABLE_ERRORS,
            wr_data.get(RETRYABLE_ERRORS, config_wr.retryable_errors),
        )
    )

    return (
        None
        if error_matchers is None
        else [
            _generate_task_error_matcher(task_error_matcher_data)
            for task_error_matcher_data in error_matchers
        ]
    )


def double_range_from_list(value: object, property_name: str) -> DoubleRange | None:
    """
    Build a DoubleRange from a two-element list of numbers, e.g. [2.0, 4.0].
    Either element may be left unset to allow one-sided constraints such as
    [2.0, null] (no upper limit) or [null, 4.0] (no lower limit). An unset
    bound is expressed as 'null' (JSON/Jsonnet) or the string "none" (which
    TOML requires, as it has no null literal). Returns None if 'value' is None,
    or if both bounds are unset (equivalent to omitting the property).
    """
    value_list = cast("list | None", check_list(value))
    if value_list is None:
        return None

    if len(value_list) != 2:
        raise ValueError(
            f"The '{property_name}' property must be a list of two values "
            '(either of which may be null/"none"), e.g. [2.0, 4.0]'
        )

    def _bound(bound: object) -> float | None:
        if bound is None:
            return None
        if isinstance(bound, str) and bound.strip().lower() in ("none", "null"):
            return None
        if isinstance(bound, bool) or not isinstance(bound, (int, float)):
            raise ValueError(
                f"Each '{property_name}' value must be a number, null, or \"none\""
            )
        return float(bound)

    minimum, maximum = _bound(value_list[0]), _bound(value_list[1])
    if minimum is None and maximum is None:
        return None  # No constraint; equivalent to omitting the property
    return DoubleRange(minimum, maximum)


def generate_dependencies(task_group_data: dict) -> list[str] | None:
    """
    Generate the contents of the 'dependencies' property of the TaskGroup.
    """
    dependent_on = check_str(task_group_data.get(DEPENDENT_ON))
    dependencies = check_list(task_group_data.get(DEPENDENCIES))

    if dependent_on is not None and dependencies is not None:
        raise ValueError(
            "Only one of 'dependencies' or 'dependentOn' (deprecated) can "
            "be specified in a task group"
        )

    if dependent_on is None and dependencies is None:
        return None

    if dependencies is not None:
        return dependencies

    if dependent_on is not None:
        print_warning(
            "The 'dependentOn' task group property is deprecated; "
            "please use 'dependencies' instead"
        )
        return [dependent_on]

    return None


def _generate_task_error_matcher(task_error_matcher_data: dict) -> TaskErrorMatcher:
    """
    Generate a TaskErrorMatcher object.
    """
    try:
        exit_codes_str: list[int] | None = check_list(
            task_error_matcher_data.get(PROCESS_EXIT_CODES)
        )
        try:
            # Ensure ints
            exit_codes = (
                None
                if exit_codes_str is None
                else [int(exit_code_str) for exit_code_str in exit_codes_str]
            )
        except Exception as e:
            raise ValueError(f"Unable to process error exit codes: {e}")

        statuses_str: list[str] | None = check_list(
            task_error_matcher_data.get(STATUSES_AT_FAILURE)
        )
        try:
            statuses = (
                None
                if statuses_str is None
                else [TaskStatus(status) for status in statuses_str]
            )
        except Exception as e:
            raise ValueError(f"Unable to process error status: {e}")

        error_types: list[str] | None = check_list(
            task_error_matcher_data.get(ERROR_TYPES)
        )

        return TaskErrorMatcher(
            errorTypes=error_types,
            statusesAtFailure=statuses,
            processExitCodes=exit_codes,
        )

    except Exception as e:
        raise RuntimeError(
            f"Unable to process task retry error matcher data '{task_error_matcher_data}': {e}"
        )


@dataclass
class RcloneUploadedFile:
    """
    Capture the local and destination state of an rcloned file.
    """

    local_file_path: str
    upload_file_path: str


class RcloneUploadedFiles:
    """
    Upload and manage uploaded files from taskData.inputs.
    """

    def __init__(
        self,
        files_directory: str = ".",
    ):
        self._rcloned_files: list[RcloneUploadedFile] = []
        self._files_directory = abspath(files_directory)
        self._working_directory = getcwd()

    def upload_dataclient_input_files(self, task_data_inputs: list[dict] | None):
        """
        Extract files to be uploaded from a task_data_inputs objects, and
        upload them. Important: removes any 'localFile' and 'uploadPath'
        properties.
        """
        if task_data_inputs is None:
            return

        for task_data_input in task_data_inputs:
            local_file = task_data_input.pop(DATA_CLIENT_LOCAL_PATH, None)
            if local_file is None:
                continue
            upload_path = task_data_input.pop(DATA_CLIENT_UPLOAD_PATH, None)
            if upload_path is None:
                upload_path = task_data_input.get(TASK_DATA_SOURCE)
            if upload_path is None:
                continue
            self._upload_rclone_file(
                # Ugly cast to keep PyCharm type system happy
                cast(str, cast(object, local_file)),
                cast(str, upload_path),
            )

    def _upload_rclone_file(self, local_file: str, rclone_upload_path: str):
        """
        Rclone a DataClient inputs file if it hasn't already been uploaded to
        the same location.
        """
        chdir(self._files_directory)
        try:
            if not exists(local_file):
                raise FileNotFoundError(
                    f"File '{Path(self._files_directory) / local_file}' does not exist "
                    "and cannot be uploaded"
                )

            rclone_uploaded_file = RcloneUploadedFile(local_file, rclone_upload_path)
            if rclone_uploaded_file in self._rcloned_files:
                # Duplicate
                return

            if not ARGS_PARSER.dry_run:
                try:
                    self._upload_rclone_file_core(rclone_uploaded_file)
                except Exception as e:
                    raise RuntimeError(
                        f"Unable to upload '{local_file}' -> '{rclone_upload_path}': {e}"
                    )
            else:
                print_info(
                    f"Dry-run: Would upload '{local_file}' -> "
                    f"'{self._bucket_and_prefix(rclone_uploaded_file)}'"
                )

            self._rcloned_files.append(rclone_uploaded_file)
        finally:
            chdir(self._working_directory)

    def _upload_rclone_file_core(self, rclone_upload_file: RcloneUploadedFile):
        """
        Core upload method for a single file.
        """
        remote_name, config_section, remote_path = self._parse_rclone_connection_string(
            rclone_upload_file.upload_file_path
        )

        # Auto-downloads rclone binary if missing (~20-40 MB, only once)
        rclone = make_rclone(
            Config(config_section) if config_section is not None else None
        )

        remote_dest = f"{remote_name}:{remote_path}"

        if not ARGS_PARSER.overwrite and rclone.exists(remote_dest):
            print_info(
                f"Skipping upload of '{rclone_upload_file.local_file_path}'"
                f" (already exists at '{self._bucket_and_prefix(rclone_upload_file)}')"
            )
            return

        local_file = Path(rclone_upload_file.local_file_path).resolve()
        print_info(
            f"Uploading '{rclone_upload_file.local_file_path}' → "
            f"'{self._bucket_and_prefix(rclone_upload_file)}'"
        )

        result = rclone.copy_to(
            src=str(local_file),
            dst=remote_dest,
            other_args=[],
        )

        if result.returncode != 0:
            raise RuntimeError(f"Upload failed: {result.stderr}")

    def delete(self):
        """
        Delete all files that have been rcloned. Note: can't delete
        a list of files in one rclone-api call because they may be
        stored in different places. This can be optimised later by
        grouping into batches of files with the same connection info.
        """
        for rcloned_file in self._rcloned_files:
            self._delete_rcloned_file(rcloned_file.upload_file_path)

        self._rcloned_files = []

    def _delete_rcloned_file(self, conn_str: str):
        """
        Deletes exactly one rcloned file specified in the connection string.

        Example:
            conn_str = "rclone:S3,type=s3,provider=AWS,env_auth=true,\
                        region=eu-west-2,location_constraint=eu-west-2:\
                        tech.yellowdog.devsandbox.dev-platform/yd-demo/pwt/file.txt"
            delete_single_s3_object(conn_str)
        """
        remote_name, config_section, remote_path = self._parse_rclone_connection_string(
            conn_str
        )

        # Auto-downloads rclone binary if missing (~20-40 MB, only once)
        rclone = make_rclone(
            Config(config_section) if config_section is not None else None
        )

        rcloned_file = f"{remote_name}:{remote_path}"
        print_info(f"Deleting rcloned file '{rcloned_file}'")
        if not rclone.exists(rcloned_file):
            print_warning(f"Rcloned file does not exist: '{rcloned_file}'")
            return

        result = rclone.delete_files([rcloned_file])

        if result.returncode != 0:
            print_error(
                f"Failed to delete rcloned file '{remote_path}' ({result.stderr})"
            )

    @staticmethod
    def _parse_rclone_connection_string(
        connection_str: str,
    ) -> tuple[str, str | None, str]:
        """
        Parses rclone connection strings in two forms:

        Inline config (all parameters embedded in the string):
          'rclone:NAME,type=...,key=val...:bucket/path/to/file.txt'

        Local rclone.conf remote (remote name only, no inline parameters):
          'rclone:yds3:/path/to/file.txt'

        The leading 'rclone:' is optional in both forms.

        Returns:
            (remote_name, config_ini_section_str_or_None, bucket_and_path_prefix)
            config_ini_section_str is None for locally configured remotes,
            indicating that the system rclone.conf should be used.
        """
        # Remove optional leading 'rclone:'
        if connection_str.startswith(RCLONE_PREFIX):
            connection_str = connection_str[len(RCLONE_PREFIX) :]

        if ":" not in connection_str:
            raise ValueError("No colon separator found in connection string")

        # Split on LAST colon → config vs path
        remote_part, path_part = connection_str.rsplit(":", 1)
        remote_name, config_section = parse_rclone_config(remote_part)
        path_part = path_part.strip()  # keep internal slashes

        return remote_name, config_section, path_part

    @staticmethod
    def _bucket_and_prefix(rclone_uploaded_file: RcloneUploadedFile):
        """
        Remove everything except the service, bucket name and object name.
        """
        try:
            _service, _rclone_details, bucket_name_and_object = (
                rclone_uploaded_file.upload_file_path.split(":")
            )
            return bucket_name_and_object
        except Exception:
            return rclone_uploaded_file.upload_file_path


def formatted_number_str(
    current_item_number: int, num_items: int, zero_indexed: bool = True
) -> str:
    """
    Return a nicely formatted number string given a current item number
    and a total number of items.
    """
    return str(current_item_number + 1 if zero_indexed else current_item_number).zfill(
        len(str(num_items))
    )


def get_task_name(
    name: str | None,
    set_task_names: bool,
    task_number: int,
    num_tasks: int,
    task_group_number: int,
    num_task_groups: int,
    task_group_name: str,
) -> str | None:
    """
    Create the name of a Task. Supports lazy substitution.
    """
    if name:
        n: str = name  # Keep PyCharm typing happy
        return (
            n.replace(
                f"{VAR_OPENING_DELIMITER + L_TASK_NUMBER + VAR_CLOSING_DELIMITER}",
                formatted_number_str(task_number, num_tasks),
            )
            .replace(
                f"{VAR_OPENING_DELIMITER + L_TASK_COUNT + VAR_CLOSING_DELIMITER}",
                str(num_tasks),
            )
            .replace(
                f"{VAR_OPENING_DELIMITER + L_TASK_GROUP_NUMBER + VAR_CLOSING_DELIMITER}",
                formatted_number_str(task_group_number, num_task_groups),
            )
            .replace(
                f"{VAR_OPENING_DELIMITER + L_TASK_GROUP_COUNT + VAR_CLOSING_DELIMITER}",
                str(num_task_groups),
            )
            .replace(
                f"{VAR_OPENING_DELIMITER + L_TASK_GROUP_NAME + VAR_CLOSING_DELIMITER}",
                task_group_name,
            )
        )
    elif set_task_names:
        name = "task_" + formatted_number_str(task_number, num_tasks)
    else:
        name = None

    return name


def get_task_group_name(
    name: str | None,
    task_group_number: int,
    num_task_groups: int,
    task_count: int,
) -> str:
    """
    Create the name of a Task Group. Supports lazy substitution.
    """
    if name:
        n: str = name  # Keep PyCharm typing happy
        return (
            n.replace(
                f"{VAR_OPENING_DELIMITER + L_TASK_GROUP_NUMBER + VAR_CLOSING_DELIMITER}",
                formatted_number_str(task_group_number, num_task_groups),
            )
            .replace(
                f"{VAR_OPENING_DELIMITER + L_TASK_GROUP_COUNT + VAR_CLOSING_DELIMITER}",
                str(num_task_groups),
            )
            .replace(
                f"{VAR_OPENING_DELIMITER + L_TASK_COUNT + VAR_CLOSING_DELIMITER}",
                str(task_count),
            )
        )

    return "task_group_" + formatted_number_str(task_group_number, num_task_groups)


def resolve_task_data(
    data: dict,
    files_directory: str = "",
    task_data_default: str | None = None,
    task_data_file_default: str | None = None,
    task_data_files_default: list[str] | None = None,
) -> str | None:
    """
    Resolve 'taskData' from a single dict level.

    Returns the task data string — inline, read from a single file, or
    concatenated from a list of files. Returns None if none of the three
    properties are present at this level. Raises ValueError if more than
    one of 'taskData', 'taskDataFile', 'taskDataFiles' is set.
    """
    task_data = data.get(TASK_DATA, task_data_default)
    task_data_file = data.get(TASK_DATA_FILE, task_data_file_default)
    task_data_files = data.get(TASK_DATA_FILES, task_data_files_default)
    if sum(bool(x) for x in [task_data, task_data_file, task_data_files]) > 1:
        raise ValueError(
            f"Only one of '{TASK_DATA}', '{TASK_DATA_FILE}' or "
            f"'{TASK_DATA_FILES}' should be set"
        )
    if task_data:
        return task_data
    if task_data_file:
        with open(resolve_filename(files_directory, task_data_file)) as f:
            return process_variable_substitutions_in_file_contents(f.read())
    if task_data_files:
        result = ""
        for filename in task_data_files:
            with open(resolve_filename(files_directory, filename)) as f:
                result += process_variable_substitutions_in_file_contents(f.read())
                result += "\n"
        return result
    return None


def get_task_data_property(
    config_wr: ConfigWorkRequirement,
    wr_data: dict,
    task_group_data: dict,
    task: dict,
    task_name: str | None,
    files_directory: str = "",
) -> str | None:
    """
    Get the 'taskData' property for a Task, checking Task → Task Group → WR
    level in order. 'taskDataFile' is resolved to its file contents at whichever
    level it is found.
    """
    for data, task_data_default, task_data_file_default, task_data_files_default in [
        (task, None, None, None),
        (task_group_data, None, None, None),
        (
            wr_data,
            config_wr.task_data,
            config_wr.task_data_file,
            config_wr.task_data_files,
        ),
    ]:
        try:
            result = resolve_task_data(
                data,
                files_directory,
                task_data_default,
                task_data_file_default,
                task_data_files_default,
            )
        except ValueError:
            raise ValueError(
                f"Task '{task_name}': Only one of '{TASK_DATA}', "
                f"'{TASK_DATA_FILE}' or '{TASK_DATA_FILES}' should be set"
            )
        if result is not None:
            return result

    return None


def create_task(
    wr_data: dict,
    task_group_data: dict,
    task_data: dict,
    task_name: str | None,
    task_number: int,
    tg_name: str,
    tg_number: int,
    task_type: str,
    args: list[str],
    task_data_property: str | None,
    env: dict[str, str] | None,
    task_timeout: timedelta | None,
    add_yd_env_vars: bool = False,
    task_data_inputs_and_outputs: TaskData | None = None,
    wr_name: str = "",
    namespace: str = "",
    total_num_task_groups: int | None = None,
    total_num_tasks: int | None = None,
) -> Task:
    """
    Create a Task object.
    """
    env_copy: dict[str, str] = deepcopy(env) if env is not None else {}
    task_tag = task_data.get(TASK_TAG)

    # Optionally add Task details to the environment as a convenience
    if add_yd_env_vars:
        num_task_groups = (
            total_num_task_groups
            if total_num_task_groups is not None
            else len(wr_data[TASK_GROUPS])
        )
        num_tasks = (
            total_num_tasks
            if total_num_tasks is not None
            else len(task_group_data[TASKS])
        )
        env_copy[YD_TASK_NAME] = task_name or ""
        env_copy[YD_TASK_NUMBER] = str(task_number)
        env_copy[YD_NUM_TASKS] = str(num_tasks)
        env_copy[YD_TASK_GROUP_NAME] = tg_name
        env_copy[YD_TASK_GROUP_NUMBER] = str(tg_number)
        env_copy[YD_NUM_TASK_GROUPS] = str(num_task_groups)
        env_copy[YD_WORK_REQUIREMENT_NAME] = wr_name
        env_copy[YD_NAMESPACE] = namespace
        if task_tag is not None:
            env_copy[YD_TAG] = cast(str, task_tag)

    return Task(
        name=task_name,
        taskType=task_type,
        arguments=args or None,
        environment=env_copy or None,
        taskData=task_data_property,
        timeout=task_timeout,
        tag=task_tag,
        data=task_data_inputs_and_outputs,
    )
