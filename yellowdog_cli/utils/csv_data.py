"""
Module for handling Task data supplied in CSV files.
"""

import csv
import re
import sys
from collections import OrderedDict
from os.path import join
from typing import cast

from tomli import load as toml_load

from yellowdog_cli.utils.config_types import ConfigWorkRequirement
from yellowdog_cli.utils.file_substitution import (
    load_jsonnet_file_with_variable_substitutions,
    parse_json_file,
)
from yellowdog_cli.utils.paths import relative_if_possible
from yellowdog_cli.utils.printing import print_info, print_json, print_warning
from yellowdog_cli.utils.property_names import *
from yellowdog_cli.utils.variable_substitution import (
    TYPE_TAGS,
    process_typed_variable_substitution,
    resolve_variables_insitu,
    typed_value_as_text,
)
from yellowdog_cli.utils.variable_syntax import (
    CSV_VAR_CLOSING_DELIMITER,
    CSV_VAR_OPENING_DELIMITER,
)

# A CSV substitution: '<<name>>', or with a type tag, '<<num:name>>'. The
# name is a CSV heading, which may be anything but a delimiter or a line
# break; one that is no heading in the file is not substituted
_CSV_EXPRESSION = re.compile(
    re.escape(CSV_VAR_OPENING_DELIMITER)
    + "("
    + "|".join(re.escape(tag) for tag in TYPE_TAGS)
    + ")?"
    + f"([^<>\n]*?){re.escape(CSV_VAR_CLOSING_DELIMITER)}"
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
        # The line each row ends on, as an editor numbers it
        self._line_numbers: list[int] = []
        row_length = None

        # 'utf-8-sig' reads UTF-8, dropping the byte order mark Excel's "CSV
        # UTF-8" begins with, which would otherwise begin the first heading;
        # newline='' is what the csv module needs to keep a quoted line break
        with open(csv_filename, encoding="utf-8-sig", newline="") as csv_file:
            csv_reader = csv.reader(csv_file, delimiter=",", skipinitialspace=True)
            for row in csv_reader:
                if not row:
                    continue  # A blank line
                if row_length is None:
                    row_length = len(row)
                elif len(row) != row_length:
                    raise ValueError(
                        f"Malformed CSV file (line {csv_reader.line_num}): "
                        "all rows must have the same number of items"
                    )
                self._csv_data.append(row)
                self._line_numbers.append(csv_reader.line_num)

        if not self._csv_data:
            raise ValueError(
                f"CSV file '{csv_filename}' is empty: it needs a row of headings"
            )
        headings = self._csv_data[0]
        if any(heading == "" for heading in headings):
            raise ValueError(
                f"CSV file '{csv_filename}' has an empty heading (column"
                f" {headings.index('') + 1})"
            )
        repeated = sorted({h for h in headings if headings.count(h) > 1})
        if repeated:
            raise ValueError(
                f"CSV file '{csv_filename}' repeats the heading(s)"
                f" {', '.join(repr(h) for h in repeated)}: each column needs its"
                " own name"
            )
        if len(self._csv_data) == 1:
            raise ValueError(
                f"CSV file '{csv_filename}' has headings but no data rows, so no Tasks"
            )
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
    def line_number(self) -> int:
        """
        The line in the file of the row last returned
        """
        return self._line_numbers[self._index]

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
    json_file: str,
    csv_files: list[str],
    files_directory: str = "",
    csv_only: bool = False,
) -> dict:
    """
    Load a JSON file, expanding its Task lists using data from CSV
    files. Return the expanded and variables-processed Work Requirement data.
    """

    wr_data = parse_json_file(json_file)
    return perform_csv_task_expansion(wr_data, csv_files, files_directory, csv_only)


def load_jsonnet_file_with_csv_task_expansion(
    jsonnet_file: str,
    csv_files: list[str],
    files_directory: str = "",
    csv_only: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Load a Jsonnet file, expanding its Task lists using data from CSV
    files. Return the expanded and variables-processed Work Requirement data.
    """

    wr_data = load_jsonnet_file_with_variable_substitutions(
        jsonnet_file, dry_run=dry_run
    )
    return perform_csv_task_expansion(wr_data, csv_files, files_directory, csv_only)


def load_toml_file_with_csv_task_expansion(
    toml_file: str,
    csv_files: list[str],
    files_directory: str = "",
    csv_only: bool = False,
) -> dict:
    """
    Load a TOML file Work Requirement, expanding its Task lists using data
    from CSV files. Return the expanded and variables-processed Work Requirement
    data.
    """

    with open(toml_file, "rb") as f:
        wr_data = toml_load(f)

    return perform_csv_task_expansion(wr_data, csv_files, files_directory, csv_only)


def perform_csv_task_expansion(
    wr_data: dict,
    csv_files: list[str],
    files_directory: str = "",
    csv_only: bool = False,
) -> dict:
    """
    Expand a Work Requirement using CSV data. Each Task Group is given at
    most one CSV file, however it was chosen: by position, number or name.
    """
    task_groups = wr_data.get(TASK_GROUPS)
    if not isinstance(task_groups, list) or not task_groups:
        raise ValueError(
            f"A Work Requirement given CSV data needs a '{TASK_GROUPS}' list"
        )

    if len(task_groups) > len(csv_files):
        print_info(
            f"Note: Number of Task Groups ({len(task_groups)}) "
            "in Work Requirement is greater than number of CSV files "
            f"({len(csv_files)})"
        )

    if len(csv_files) > len(task_groups):
        raise ValueError("Number of CSV files exceeds number of Task Groups")

    given: dict[int, str] = {}  # Task Group index -> the CSV file given it
    for counter, csv_file_argument in enumerate(csv_files):
        csv_file, index = get_csv_file_index(csv_file_argument, task_groups)
        if index is None:
            index = counter
        if index in given:
            name = task_groups[index].get(NAME)
            raise ValueError(
                f"Task Group {index + 1}{'' if name is None else f' ({name!r})'}"
                f" is given more than one CSV file: '{given[index]}',"
                f" '{csv_file_argument}'"
            )
        given[index] = csv_file_argument
        if not isinstance(task_groups[index].get(TASKS), list):
            raise ValueError(
                f"Task Group {index + 1} needs a '{TASKS}' list holding one"
                " prototype Task when using a CSV file for data"
            )

        # Named from the files directory, as every file a specification
        # refers to is (the specification itself is named from the current one)
        resolved_csv_file = relative_if_possible(join(files_directory, csv_file))

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

        if not substitutions_present(csv_data.var_names, task_prototype):
            print_warning(
                "No CSV substitutions to apply to Task Group "
                f"{index + 1}; not expanding Task list"
            )
            continue

        generated_task_list = []
        for task_data in csv_data:
            generated_task_list.append(
                csv_variables_substitution(
                    task_prototype,
                    csv_data.var_names,
                    task_data,
                    where=f"'{resolved_csv_file}' line {csv_data.line_number}",
                )
            )
        task_group[TASKS] = generated_task_list
        print_info(f"Generated {len(generated_task_list)} Task(s) from CSV data")

    if csv_only:  # '--process-csv-only'
        print_info("Displaying CSV substitutions only:")
        print_json(wr_data)
        sys.exit(0)

    # Process remaining substitutions
    resolve_variables_insitu(wr_data)
    return wr_data


def csv_variables_substitution(
    task_prototype: dict, csv_var_names: list, task_data: list, where: str = ""
) -> dict:
    """
    A Task from the prototype, with one CSV row's values substituted, and all
    other substitutions left unchanged. The values are substituted into the
    prototype's data, string by string, never into its text, so that a value
    -- an apostrophe, a backslash, a quote, '<<other>>' -- is only ever a
    value. 'where' names the row, for an error.
    """
    row = dict(zip(csv_var_names, task_data))
    return cast(dict, _substituted(task_prototype, row, where))


def _substituted(data: object, row: dict[str, str], where: str) -> object:
    """
    A copy of 'data' with the row's values substituted into its strings,
    property names included.
    """
    if isinstance(data, dict):
        return {
            str(_substituted_string(key, row, where, as_text=True)): _substituted(
                value, row, where
            )
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_substituted(item, row, where) for item in data]
    if isinstance(data, str):
        return _substituted_string(data, row, where)
    return data


def _substituted_string(
    text: str, row: dict[str, str], where: str, as_text: bool = False
) -> object:
    """
    A string with the row's values substituted. A string that is only a
    type-tagged substitution is its value, of the tag's type, unless
    'as_text' (a property name); one inside a longer string is written as
    text, as a '{{...}}' one is.
    """
    matches = [m for m in _CSV_EXPRESSION.finditer(text) if m.group(2) in row]
    if not matches:
        return text

    def _value(match: re.Match) -> object:
        tag, name = match.group(1), match.group(2)
        if tag is None:
            return row[name]
        try:
            return process_typed_variable_substitution(tag, row[name])
        except ValueError as e:
            raise ValueError(f"{where}, column '{name}': {e}") from e

    if not as_text and len(matches) == 1 and matches[0].group(0) == text:
        return _value(matches[0])

    parts: list[str] = []
    position = 0
    for match in matches:
        value = _value(match)
        tag = match.group(1)
        written = (
            typed_value_as_text(tag, value, row[match.group(2)])  # type: ignore[arg-type]
            if tag is not None
            else cast(str, value)
        )
        parts += [text[position : match.start()], written]
        position = match.end()
    parts.append(text[position:])
    return "".join(parts)


def get_csv_file_index(
    csv_filename: str, task_groups: list[dict]
) -> tuple[str, int | None]:
    """
    Check if the CSV filename ends in an integer index (':<integer>'),
    or in a Task Group name (':<task_group_name>').
    If so, return the filename with the index stripped, and the index
    integer (zero-based). That a Task Group is given only one file is
    checked by the caller, which sees them all.
    """

    filename, suffix = split_csv_file_suffix(csv_filename)
    if suffix is None:
        return filename, None

    # Task Group number matching
    if suffix.isdigit():
        index = int(suffix)
        if not 0 < index <= len(task_groups):
            raise ValueError(
                f"CSV file Task Group index '{index}' is outside Task Group range"
            )
        return filename, index - 1

    # Task Group name matching
    for index, task_group in enumerate(task_groups):
        if task_group.get(NAME) == suffix:
            return filename, index
    names = ", ".join(repr(tg.get(NAME)) for tg in task_groups if tg.get(NAME))
    raise ValueError(
        f"No matches for Task Group name '{suffix}' in CSV file '{csv_filename}'"
        + (f" (the Task Groups are named {names})" if names else "")
    )


# A Task Group suffix: a number, or something that could be a name
_TASK_GROUP_NUMBER = re.compile(r"\d+")
_TASK_GROUP_NAME = re.compile(r"[a-z][a-z0-9_-]+")


def split_csv_file_suffix(csv_filename: str) -> tuple[str, str | None]:
    """
    A CSV file name and its Task Group suffix, ':<number>' or ':<name>', or
    None if it has none. Only the text after the last ':' can be one, so a
    Windows drive letter ('C:\\data\\tasks.csv') is never taken for one; what
    is neither, and not part of a path, is warned of as a possible mistake.
    """
    filename, separator, suffix = csv_filename.rpartition(":")
    if not separator:
        return csv_filename, None
    if _TASK_GROUP_NUMBER.fullmatch(suffix) or _TASK_GROUP_NAME.fullmatch(suffix):
        return filename, suffix
    if "/" not in suffix and "\\" not in suffix:
        print_warning(f"Possible invalid Task Group name/number '{suffix}'?")
    return csv_filename, None


def substitutions_present(var_names: list[str], task_prototype: object) -> bool:
    """
    Check if there are any CSV substitutions present in the Task prototype:
    in any of its strings, property names included.
    """
    names = set(var_names)

    def _present(data: object) -> bool:
        if isinstance(data, str):
            return any(m.group(2) in names for m in _CSV_EXPRESSION.finditer(data))
        if isinstance(data, dict):
            return any(_present(key) or _present(value) for key, value in data.items())
        if isinstance(data, list):
            return any(_present(item) for item in data)
        return False

    return _present(task_prototype)


def csv_expand_toml_tasks(
    config_wr: ConfigWorkRequirement,
    csv_file: str,
    files_directory="",
    csv_only: bool = False,
) -> dict:
    """
    When there's a CSV file specified, but no JSON file, create the expanded
    list of Tasks using the CSV data.
    """
    wr_data = {TASK_GROUPS: [{TASKS: [{}]}]}
    task_proto = wr_data[TASK_GROUPS][0][TASKS][0]
    csv_data = CSV_DATA_CACHE.get_csv_task_data(
        join(files_directory, split_csv_file_suffix(csv_file)[0])
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
            csv_data.var_names, config_value
        ):
            task_proto[config_name] = config_value

    return perform_csv_task_expansion(wr_data, [csv_file], files_directory, csv_only)
