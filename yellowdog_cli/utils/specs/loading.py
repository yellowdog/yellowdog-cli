"""
Loading a specification file, for the commands that take one: yd-submit
(including '--json-raw'), yd-provision, yd-instantiate and yd-nodeaction.

load_specification() chooses the loader by the file's extension (JSON or
Jsonnet, and TOML where the command takes it), with variable substitution
and, for yd-submit, CSV Task expansion, and then checks the document against
its family's schema (specs.validation.check_specification()), so that every
command loads, substitutes and checks a file the same way. yd-create and
yd-remove, which take several files of mixed resources, have their own
loader (load_resources.py).
"""

from dataclasses import dataclass
from typing import Any

from yellowdog_cli.utils.csv_data import (
    load_json_file_with_csv_task_expansion,
    load_jsonnet_file_with_csv_task_expansion,
    load_toml_file_with_csv_task_expansion,
)
from yellowdog_cli.utils.file_substitution import (
    load_json_file_with_variable_substitutions,
    load_jsonnet_file_with_variable_substitutions,
    load_toml_file_with_variable_substitutions,
)
from yellowdog_cli.utils.printing import print_info
from yellowdog_cli.utils.specs.schema import Family
from yellowdog_cli.utils.specs.validation import check_specification

JSON_EXTENSION = ".json"
JSONNET_EXTENSION = ".jsonnet"
TOML_EXTENSION = ".toml"


@dataclass(frozen=True)
class CsvExpansion:
    """
    The CSV files a Work Requirement's Task lists are expanded from, the
    directory files are found in, and whether only the Task Groups given a
    CSV file are kept ('--process-csv-only').
    """

    files: list[str]
    files_directory: str
    csv_only: bool = False


def refuse_file_options(what: str, *, validate: bool, jsonnet_dry_run: bool) -> None:
    """
    Refuse '--validate' and '--jsonnet-dry-run' where the command has no
    '<what>' specification file to apply them to, and is building what it
    submits from the configuration instead: ignored, either would let the
    command go on to submit or provision what was only to be checked.
    """
    if validate:
        raise ValueError(f"Option '--validate' needs a {what} specification file")
    if jsonnet_dry_run:
        raise ValueError(
            f"Option '--jsonnet-dry-run' needs a Jsonnet {what} specification file"
        )


def load_specification(
    path: str,
    what: str,
    *,
    family: Family | None,
    jsonnet_dry_run: bool = False,
    validate: bool = False,
    prefix: str = "",
    postfix: str = "",
    toml: bool = False,
    other_extensions_as_json: bool = False,
    csv: CsvExpansion | None = None,
) -> Any:
    """
    Load the '<what>' specification at 'path', substituting variables
    delimited by 'prefix' and 'postfix' (the defaults when empty), and check
    it against 'family''s schema (None for a document that is not a
    specification, such as '--json-raw''s), warning of what it finds, or
    with 'validate' reporting it and exiting.

    By extension: '.jsonnet' is Jsonnet, evaluated or, with
    'jsonnet_dry_run', printed as JSON and the run ended; '.toml' is TOML
    where 'toml' allows it; '.json' is JSON, and so is any other extension
    where 'other_extensions_as_json' allows it, else it is refused.
    '--jsonnet-dry-run' is refused for a file that is not Jsonnet, before
    anything is loaded.
    """
    lower = path.lower()
    jsonnet = lower.endswith(JSONNET_EXTENSION)
    if jsonnet_dry_run and not jsonnet:
        raise ValueError(
            "Option '--jsonnet-dry-run' can only be used with files ending in"
            f" '{JSONNET_EXTENSION}'"
        )
    is_toml = toml and lower.endswith(TOML_EXTENSION)
    if not (
        jsonnet or is_toml or lower.endswith(JSON_EXTENSION) or other_extensions_as_json
    ):
        extensions = [JSON_EXTENSION, JSONNET_EXTENSION]
        if toml:
            extensions.append(TOML_EXTENSION)
        raise ValueError(
            f"{what} data file '{path}' must end with "
            + ", ".join(f"'{extension}'" for extension in extensions[:-1])
            + ("," if len(extensions) > 2 else "")
            + f" or '{extensions[-1]}'"
        )

    print_info(f"Loading {what} data from: '{path}'")
    if jsonnet:
        data = (
            load_jsonnet_file_with_variable_substitutions(
                path, prefix=prefix, postfix=postfix, dry_run=jsonnet_dry_run
            )
            if csv is None
            else load_jsonnet_file_with_csv_task_expansion(
                jsonnet_file=path,
                csv_files=csv.files,
                files_directory=csv.files_directory,
                dry_run=jsonnet_dry_run,
                csv_only=csv.csv_only,
            )
        )
    elif is_toml:
        data = (
            load_toml_file_with_variable_substitutions(
                path, prefix=prefix, postfix=postfix
            )
            if csv is None
            else load_toml_file_with_csv_task_expansion(
                toml_file=path,
                csv_files=csv.files,
                files_directory=csv.files_directory,
                csv_only=csv.csv_only,
            )
        )
    else:
        data = (
            load_json_file_with_variable_substitutions(
                path, prefix=prefix, postfix=postfix
            )
            if csv is None
            else load_json_file_with_csv_task_expansion(
                json_file=path,
                csv_files=csv.files,
                files_directory=csv.files_directory,
                csv_only=csv.csv_only,
            )
        )

    if family is None:
        return data
    return check_specification(family, data, path, validate)
