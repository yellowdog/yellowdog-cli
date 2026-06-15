"""
Module for handling Task data supplied in CSV files.
"""

import csv
import re
from ast import literal_eval
from collections import OrderedDict
from json import load as json_load
from os.path import relpath

from tomli import load as toml_load

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.config_types import ConfigWorkRequirement
from yellowdog_cli.utils.misc_utils import format_yd_name
from yellowdog_cli.utils.printing import print_info, print_json
from yellowdog_cli.utils.property_names import *
from yellowdog_cli.utils.settings import (
    BOOL_TYPE_TAG,
    CSV_VAR_CLOSING_DELIMITER,
    CSV_VAR_OPENING_DELIMITER,
    FORMAT_NAME_TYPE_TAG,
    NUMBER_TYPE_TAG,
)
from yellowdog_cli.utils.variables import (
    load_jsonnet_file_with_variable_substitutions,
    process_variable_substitutions_insitu,
    resolve_filename,
)


class CSVTaskData:
    """
    A class for reading and storing CSV data
    """

    def __init__(self, csv_filename: str):
        """
        Load the data from the CSV file; validate row lengths
        """
        self._csv_data = []
        row_length = None

        with open(csv_filename) as csv_file:
            csv_reader = csv.reader(csv_file, delimiter=",", skipinitialspace=True)
            for row_number, row in enumerate(csv_reader):
                if row_length is None:
                    row_length = len(row)
                else:
                    if len(row) != row_length:
                        raise ValueError(
                            f"Malformed CSV file (row {row_number + 1}): "
                            "all rows must have the same number of items"
                        )
                self._csv_data.append(row)

        self._index = 0
        self._total_tasks = len(self._csv_data) - 1

    def __iter__(self):
        return self

    @property
    def var_names(self) -> list[str]:
        """
        Return the list of headings (variable names)
        """
        return self._csv_data[0]

    def __next__(self):
        """
        Iterate through the task data rows
        """
        if self.remaining_tasks == 0:
            raise StopIteration
        self._index += 1
        return self._csv_data[self._index]

    def reset(self):
        """
        Rewind the list of Tasks to the beginning
        """
        self._index = 0

    @property
    def total_tasks(self):
        return self._total_tasks

    @property
    def remaining_tasks(self):
        return self._total_tasks - self._index


class CSVDataCache:
    """
    Caches CSV data to prevent multiple loads of the same CSV file
    """

    def __init__(self, max_entries: int | None = None):
        """
        'max_entries' limits the size of the cache.
        - Use default 'None' for unlimited caching
        - Set to zero to disable caching
        """
        self._max_entries: int | None = max_entries
        self._csv_task_data_objects: OrderedDict[str, CSVTaskData] = OrderedDict()

    def get_csv_task_data(self, csv_filename: str) -> CSVTaskData:
        csv_task_data = self._csv_task_data_objects.get(csv_filename)
        if csv_task_data:  # Cache hit
            csv_task_data.reset()
        else:  # Cache miss
            if self._max_entries is not None:
                if (
                    len(self._csv_task_data_objects) == self._max_entries
                    and self._csv_task_data_objects
                ):
                    self._csv_task_data_objects.popitem(last=False)
            csv_task_data = CSVTaskData(csv_filename)
            if self._max_entries != 0:
                self._csv_task_data_objects[csv_filename] = csv_task_data
        return csv_task_data


# Singleton instance of the CSVDataCache class
CSV_DATA_CACHE = CSVDataCache(max_entries=2)


def load_json_file_with_csv_task_expansion(
    json_file: str, csv_files: list[str], files_directory: str = ""
) -> dict:
    """
    Load a JSON file, expanding its Task lists using data from CSV
    files. Return the expanded and variables-processed Work Requirement data.
    """

    with open(resolve_filename(files_directory, json_file)) as f:
        wr_data = json_load(f)

    return perform_csv_task_expansion(wr_data, csv_files, files_directory)


def load_jsonnet_file_with_csv_task_expansion(
    jsonnet_file: str, csv_files: list[str], files_directory: str = ""
) -> dict:
    """
    Load a Jsonnet file, expanding its Task lists using data from CSV
    files. Return the expanded and variables-processed Work Requirement data.
    """

    wr_data = load_jsonnet_file_with_variable_substitutions(
        resolve_filename(files_directory, jsonnet_file)
    )
    return perform_csv_task_expansion(wr_data, csv_files, files_directory)


def load_toml_file_with_csv_task_expansion(
    toml_file: str, csv_files: list[str], files_directory: str = ""
) -> dict:
    """
    Load a TOML file Work Requirement, expanding its Task lists using data
    from CSV files. Return the expanded and variables-processed Work Requirement
    data.
    """

    with open(resolve_filename(files_directory, toml_file), "rb") as f:
        wr_data = toml_load(f)

    return perform_csv_task_expansion(wr_data, csv_files, files_directory)


def perform_csv_task_expansion(
    wr_data: dict, csv_files: list[str], files_directory: str = ""
) -> dict:
    """
    Expand a Work Requirement using CSV data.
    """
    if len(wr_data[TASK_GROUPS]) > len(csv_files):
        print_info(
            f"Note: Number of Task Groups ({len(wr_data[TASK_GROUPS])}) "
            "in Work Requirement is greater than number of CSV files "
            f"({len(csv_files)})"
        )

    if len(csv_files) > len(wr_data[TASK_GROUPS]):
        raise ValueError("Number of CSV files exceeds number of Task Groups")

    for counter, csv_file in enumerate(csv_files):
        csv_file, index = get_csv_file_index(csv_file, wr_data[TASK_GROUPS])
        if index is None:
            index = counter

        resolved_csv_file = relpath(resolve_filename(files_directory, csv_file))

        task_group = wr_data[TASK_GROUPS][index]
        print_info(
            f"Loading CSV Task data for Task Group {index + 1} from:"
            f" '{resolved_csv_file}'"
        )
        if len(wr_data[TASK_GROUPS][index][TASKS]) != 1:
            raise ValueError(
                f"Task Group {index + 1} must have only a single (prototype) Task "
                "when using CSV file for data"
            )

        csv_data = CSV_DATA_CACHE.get_csv_task_data(resolved_csv_file)
        task_prototype = task_group[TASKS][0]

        if not substitutions_present(csv_data.var_names, str(task_prototype)):
            print_info(
                "Warning: No CSV substitutions to apply to Task Group "
                f"{index + 1}; not expanding Task list"
            )
            continue

        generated_task_list = []
        for task_data in csv_data:
            generated_task_list.append(
                csv_variables_substitution(
                    task_prototype, csv_data.var_names, task_data
                )
            )
        task_group[TASKS] = generated_task_list
        print_info(f"Generated {len(generated_task_list)} Task(s) from CSV data")

    if ARGS_PARSER.process_csv_only:
        print_info("Displaying CSV substitutions only:")
        print_json(wr_data)
        exit(0)

    # Process remaining substitutions
    process_variable_substitutions_insitu(wr_data)
    return wr_data


def csv_variables_substitution(
    task_prototype: dict, csv_var_names: list, task_data: list
) -> dict:
    """
    Helper function to substitute using CSV data only. Leave all other
    substitutions unchanged.
    """
    subs_dict = {var_name: task_data[i] for i, var_name in enumerate(csv_var_names)}
    new_task = str(task_prototype)
    for var_name, value in subs_dict.items():
        new_task = make_string_substitutions(new_task, var_name, value)
    return literal_eval(new_task)  # Convert back from string


def make_string_substitutions(input: str, var_name: str, value: str) -> str:
    """
    Helper function to make string substitutions for CSV variables only.
    """
    input = input.replace(
        f"{CSV_VAR_OPENING_DELIMITER}{var_name}{CSV_VAR_CLOSING_DELIMITER}", value
    )

    num_sub_str = f"{CSV_VAR_OPENING_DELIMITER}{NUMBER_TYPE_TAG}{var_name}{CSV_VAR_CLOSING_DELIMITER}"
    if num_sub_str in input:
        try:
            float(value)
        except ValueError:
            raise ValueError(f"Invalid number substitution in CSV: '{value}'")
        input = input.replace(f"'{num_sub_str}'", value)

    bool_sub_str = f"{CSV_VAR_OPENING_DELIMITER}{BOOL_TYPE_TAG}{var_name}{CSV_VAR_CLOSING_DELIMITER}"
    if bool_sub_str in input:
        if value.lower() == "true":
            value = "True"
        elif value.lower() == "false":
            value = "False"
        else:
            raise ValueError(f"Invalid Boolean substitution in CSV: '{value}'")
        input = input.replace(f"'{bool_sub_str}'", value)

    lower_sub_str = f"{CSV_VAR_OPENING_DELIMITER}{FORMAT_NAME_TYPE_TAG}{var_name}{CSV_VAR_CLOSING_DELIMITER}"
    if lower_sub_str in input:
        input = input.replace(
            f"{lower_sub_str}",
            format_yd_name(value, add_prefix=False),
        )

    return input


USED_FILE_INDEXES = []


def get_csv_file_index(
    csv_filename: str, task_groups: list[dict]
) -> tuple[str, int | None]:
    """
    Check if the CSV filename ends in an integer index (':<integer>'),
    or in a Task Group name (':<task_group_name>').
    If so, return the filename with the index stripped, and the index
    integer (zero-based).
    """

    # Task Group number matching
    matches = re.findall(r":\d+$", csv_filename)
    if len(matches) == 1:
        index = int(matches[0][1:])
        if not 0 < index <= len(task_groups):
            raise ValueError(
                f"CSV file Task Group index '{index}' is outside Task Group range"
            )
        if index in USED_FILE_INDEXES:
            raise ValueError(f"CSV file Task Group index '{index}' used more than once")
        USED_FILE_INDEXES.append(index)
        return csv_filename.replace(matches[0], ""), index - 1

    # Task Group name matching; filter on valid name patterns
    matches = re.findall(":[a-z][a-z0-9_-]+$", csv_filename)
    if len(matches) == 1:
        for index, task_group in enumerate(task_groups):
            try:
                if matches[0][1:] == task_group[NAME]:
                    return csv_filename.replace(matches[0], ""), index
            except KeyError:
                pass
        else:
            raise KeyError(f"No matches for Task Group name '{matches[0][1:]}'")

    # Invalid Task Group naming?
    split_name = csv_filename.split(":")
    if len(split_name) > 1:
        print_info(
            f"Warning: Possible invalid Task Group name/number '{split_name[-1]}'?"
        )

    return csv_filename, None


def substitutions_present(var_names: list[str], task_prototype: str) -> bool:
    """
    Check if there are any CSV substitutions present in the Task prototype.
    """
    return (
        any(
            f"{CSV_VAR_OPENING_DELIMITER}{var_name}{CSV_VAR_CLOSING_DELIMITER}"
            in task_prototype
            for var_name in var_names
        )
        or any(
            f"{CSV_VAR_OPENING_DELIMITER}{NUMBER_TYPE_TAG}{var_name}{CSV_VAR_CLOSING_DELIMITER}"
            in task_prototype
            for var_name in var_names
        )
        or any(
            f"{CSV_VAR_OPENING_DELIMITER}{BOOL_TYPE_TAG}{var_name}{CSV_VAR_CLOSING_DELIMITER}"
            in task_prototype
            for var_name in var_names
        )
        or any(
            f"{CSV_VAR_OPENING_DELIMITER}{FORMAT_NAME_TYPE_TAG}{var_name}{CSV_VAR_CLOSING_DELIMITER}"
            in task_prototype
            for var_name in var_names
        )
    )


def csv_expand_toml_tasks(
    config_wr: ConfigWorkRequirement, csv_file: str, files_directory=""
) -> dict:
    """
    When there's a CSV file specified, but no JSON file, create the expanded
    list of Tasks using the CSV data.
    """
    wr_data = {TASK_GROUPS: [{TASKS: [{}]}]}
    task_proto = wr_data[TASK_GROUPS][0][TASKS][0]
    csv_data = CSV_DATA_CACHE.get_csv_task_data(
        resolve_filename(files_directory, csv_file.split(":")[0])
    )
    # Populate properties that can be set at Task level only
    for config_value, config_name in [
        (config_wr.add_yd_env_vars, ADD_YD_ENV_VARS),
        (config_wr.args, ARGS),
        (config_wr.env, ENV),
        (config_wr.set_task_names, SET_TASK_NAMES),
        (config_wr.task_data, TASK_DATA),
        (config_wr.task_data_file, TASK_DATA_FILE),
        (config_wr.task_data_files, TASK_DATA_FILES),
        (config_wr.task_data_inputs, TASK_DATA_INPUTS),
        (config_wr.task_data_outputs, TASK_DATA_OUTPUTS),
        (config_wr.task_group_name, TASK_GROUP_NAME),  # Note: oddity
        (config_wr.task_level_timeout, TASK_LEVEL_TIMEOUT),
        (config_wr.task_name, TASK_NAME),
        (config_wr.task_timeout, TASK_TIMEOUT),
        (config_wr.task_type, TASK_TYPE),
        # Note: not TASK_COUNT; count determined by CSV data
    ]:
        if config_value is not None and substitutions_present(
            csv_data.var_names, str(config_value)
        ):
            task_proto[config_name] = config_value

    return perform_csv_task_expansion(wr_data, [csv_file], files_directory)
