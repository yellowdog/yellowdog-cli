"""
Utilities for applying variable substitutions.
"""

import os
import re
import sys
import tempfile
from copy import deepcopy
from getpass import getuser
from json import dumps as json_dumps
from json import loads as json_loads
from random import randint
from typing import cast

from tomli import load as toml_load

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.check_imports import check_jsonnet_import
from yellowdog_cli.utils.misc_utils import (
    UTCNOW,
    config_file_explicitly_selected,
    format_yd_name,
    load_dotenv_file,
    remove_outer_delimiters,
    split_delimited_string,
)
from yellowdog_cli.utils.printing import print_error, print_info, print_json
from yellowdog_cli.utils.property_names import (
    COMMON_SECTION,
    USERDATA,
    VARIABLES,
)
from yellowdog_cli.utils.settings import (
    ARRAY_TYPE_TAG,
    BOOL_TYPE_TAG,
    ENV_VAR_SUB_PREFIX,
    FORMAT_NAME_TYPE_TAG,
    NUMBER_TYPE_TAG,
    RAND_VAR_SIZE,
    TABLE_TYPE_TAG,
    TOML_VAR_NESTED_DEPTH,
    TYPE_TAG_DEFAULT_GUARD,
    VAR_CLOSING_DELIMITER,
    VAR_DEFAULT_SEPARATOR,
    VAR_OPENING_DELIMITER,
    VAR_UNSET_SUFFIX,
    WP_VARIABLES_POSTFIX,
    WP_VARIABLES_PREFIX,
    YD_ENV_VAR_PREFIX,
)

# Sentinel returned by process_variable_substitutions() when a property
# bearing the '::' unset suffix has no value defined; callers that walk
# a dict/list (i.e. _walk_data) use this to delete the property entirely.
_UNSET = object()

# Set up default variable substitutions
try:
    USERNAME = getuser().replace(" ", "_").lower()
except Exception:
    USERNAME = "default-yd-user"

VARIABLE_SUBSTITUTIONS = {
    "username": USERNAME,
    "date": UTCNOW.strftime("%y%m%d"),
    "time": UTCNOW.strftime("%H%M%S%f")[:-4],
    "datetime": UTCNOW.strftime("%y%m%d-%H%M%S"),
    "random": (
        hex(randint(0, RAND_VAR_SIZE))[2:].lower().zfill(len(hex(RAND_VAR_SIZE)) - 2)
    ),
}

# Load .env file before scanning os.environ so YD_VAR_* variables defined
# there are picked up regardless of import order.
load_dotenv_file()

# Substitutions from environment variables
subs_list = []
for key, value in os.environ.items():
    if key.startswith(YD_ENV_VAR_PREFIX):
        key = key[len(YD_ENV_VAR_PREFIX) :]
        VARIABLE_SUBSTITUTIONS[key] = value
        subs_list.append(f"'{key}'")

if subs_list:
    print_info(
        "Adding environment-defined variable substitution(s) for: "
        f"{', '.join(subs_list)}"
    )

# Substitutions from the command line, which take precedence over
# environment variables
# Names of variables defined on the command line ('-v', or '--property'
# overrides of 'common.variables'); these always take precedence, including
# over the contents of an explicitly selected config file
CLI_DEFINED_VARIABLES: set[str] = set()

subs_list = []
if ARGS_PARSER.variables is not None:
    for variable in ARGS_PARSER.variables:
        # Split on the first '=' only: values may themselves contain '='
        key_value: list = variable.split("=", 1)
        if len(key_value) == 2 and key_value[0] != "":
            VARIABLE_SUBSTITUTIONS[key_value[0]] = key_value[1]
            CLI_DEFINED_VARIABLES.add(key_value[0])
            subs_list.append(f"'{key_value[0]}'")
        else:
            print_error(
                f"Error in variable substitution '{variable}'",
            )
            exit(1)  # Note: exception trap not yet in place

if subs_list:
    print_info(
        "Adding command-line-defined variable substitution(s) for: "
        f"{', '.join(subs_list)}"
    )

del subs_list


def _update_and_resolve_substitutions(merged: dict):
    """
    Replace the substitutions dictionary with 'merged' and re-resolve
    variables. The dict is updated in-place so that all callers holding a
    reference to it see the change (rebinding the name would silently
    break imported references).
    """
    VARIABLE_SUBSTITUTIONS.clear()
    VARIABLE_SUBSTITUTIONS.update(merged)

    # Populate variables that can now be substituted.
    # Ensure that the value is stored as a string.
    # If a variable resolves to _UNSET (e.g. it references an undefined
    # variable with the '::' unset suffix), remove it entirely.
    keys_to_unset = []
    for key_, value_ in VARIABLE_SUBSTITUTIONS.items():
        result = process_variable_substitutions(str(value_))
        if result is _UNSET:
            keys_to_unset.append(key_)
        else:
            VARIABLE_SUBSTITUTIONS[key_] = cast(str, result)
    for key_ in keys_to_unset:
        del VARIABLE_SUBSTITUTIONS[key_]


def add_substitutions_without_overwriting(subs: dict):
    """
    Add a dictionary of substitutions. Do not overwrite existing values, but
    resolve remaining variables if possible.
    """
    # Merge: existing entries (CLI / env vars) take priority over incoming
    # ones
    _update_and_resolve_substitutions({**subs, **VARIABLE_SUBSTITUTIONS})


def add_substitutions_from_config_file(subs: dict):
    """
    Add variable substitutions from a TOML configuration file's
    [common.variables] section.

    If the config file was explicitly selected using '--config'/'-c', its
    variables override environment-defined variables (but never variables
    set on the command line); otherwise existing definitions take
    precedence as usual.
    """
    if not config_file_explicitly_selected(ARGS_PARSER):
        add_substitutions_without_overwriting(subs)
        return

    subs = {k: v for k, v in subs.items() if k not in CLI_DEFINED_VARIABLES}
    _update_and_resolve_substitutions({**VARIABLE_SUBSTITUTIONS, **subs})


def add_or_update_substitution(key: str, value: str):
    """
    Add a substitution to the dictionary, overwriting existing values.
    """
    VARIABLE_SUBSTITUTIONS[key] = str(value)


def get_user_variable(variable_name: str) -> str | None:
    """
    Get the value of a variable.
    """
    return VARIABLE_SUBSTITUTIONS.get(variable_name)


def get_all_user_variables() -> dict:
    """
    Return all the user variables. Copy to avoid amendment.
    """
    return deepcopy(VARIABLE_SUBSTITUTIONS)


def process_variable_substitutions_insitu(
    data: dict | list, prefix: str = "", postfix: str = ""
) -> dict | list:
    """
    Process a dictionary or list representing JSON or TOML data.
    Updates the dictionary in-situ.

    Optional 'prefix' and 'postfix' allow variable substitutions intended
    for client-side processing to be disambiguated from those to be passed
    through for server-side processing.
    """

    def _walk_data(data: dict | list):
        """
        Helper function to walk the data structure performing
        variable substitutions.
        """
        if isinstance(data, dict):
            keys_to_delete = []
            for key_, value_ in data.items():
                if isinstance(value_, str):
                    # Require the use of post/prefix only for userData in TOML
                    if key_ == USERDATA:
                        result = process_variable_substitutions(
                            value_,
                            prefix=WP_VARIABLES_PREFIX,
                            postfix=WP_VARIABLES_POSTFIX,
                        )
                    else:
                        result = process_variable_substitutions(
                            value_, prefix=prefix, postfix=postfix
                        )
                    if result is _UNSET:
                        keys_to_delete.append(key_)
                    else:
                        data[key_] = result
                elif isinstance(value_, dict) or isinstance(value_, list):
                    _walk_data(value_)
            for key_ in keys_to_delete:
                del data[key_]
        elif isinstance(data, list):
            indices_to_delete = []
            for index, item in enumerate(data):
                if isinstance(item, str):
                    result = process_variable_substitutions(
                        item, prefix=prefix, postfix=postfix
                    )
                    if result is _UNSET:
                        indices_to_delete.append(index)
                    else:
                        data[index] = result
                elif isinstance(item, dict) or isinstance(item, list):
                    _walk_data(item)
            for index in reversed(indices_to_delete):
                del data[index]

    _walk_data(data)
    return data


def process_variable_substitutions(
    input_string: str | int | bool | float | list | dict | None,
    prefix: str = "",
    postfix: str = "",
) -> str | int | bool | float | list | dict | None:
    """
    Process type-tagged and non-type-tagged variables, returning the required
    type if there's a type-tagged variable at the start of the input string.
    Non-string, non-None values are returned unchanged.
    """
    if input_string is None:
        return None
    if not isinstance(input_string, str):
        return input_string

    opening_delimiter = prefix + VAR_OPENING_DELIMITER
    closing_delimiter = VAR_CLOSING_DELIMITER + postfix

    if not (opening_delimiter in input_string and closing_delimiter in input_string):
        return input_string  # Nothing to process

    return_str = ""

    # Loop through the delimited elements in the input string
    elements = split_delimited_string(
        input_string, opening_delimiter, closing_delimiter
    )
    for index, element in enumerate(elements):
        if not (
            element.startswith(opening_delimiter)
            and element.endswith(closing_delimiter)
        ):  # No variable to process; just reinsert the element
            return_str += element
            continue

        # Type tags include their ':' terminator (e.g. 'num:'), so the lookahead
        # only needs TYPE_TAG_DEFAULT_GUARD ('=') — the character after ':' that
        # distinguishes ':=' (default separator) from a type tag.
        # This prevents '{{num:=default}}' from being treated as a typed variable.
        m = re.match(
            f"^{opening_delimiter}({NUMBER_TYPE_TAG}|{BOOL_TYPE_TAG}"
            f"|{TABLE_TYPE_TAG}|{ARRAY_TYPE_TAG}|{FORMAT_NAME_TYPE_TAG})"
            f"(?!{TYPE_TAG_DEFAULT_GUARD})",
            element,
        )
        type_tag = m.group(0).replace(opening_delimiter, "") if m is not None else ""

        element_minus_type_tag = (
            element.replace(opening_delimiter + type_tag, opening_delimiter)
            if type_tag != ""
            else element
        )

        element_processed = process_untyped_variable_substitutions(
            element_minus_type_tag, opening_delimiter, closing_delimiter
        )
        assert (
            element_processed is not None or element_processed is _UNSET
        )  # element_minus_type_tag is always str

        if element_processed is _UNSET:
            return _UNSET  # type: ignore

        if element_processed == element_minus_type_tag:  # No variable processing
            return_str += element
            continue

        if type_tag == "":  # Variable(s) processed, but no type tag
            return_str += cast(str, element_processed)
            continue

        if index == 0 and len(elements) == 1:
            # The first and only element has a type tag:
            # immediately return the type matching the tag
            return process_typed_variable_substitution(
                type_tag, cast(str, element_processed)
            )

        # Just append the type as a string
        return_str += str(
            process_typed_variable_substitution(type_tag, cast(str, element_processed))
        )

    return return_str


def process_untyped_variable_substitutions(
    input_string: str | None,
    opening_delimiter: str,
    closing_delimiter: str,
) -> str | None:
    """
    Apply untyped variable substitutions to a supplied input string,
    including applying default values if present and required.

    Algorithm (in order):
    1. Nesting: if the variable name itself contains '{{...}}', resolve the
       innermost expression first — e.g. '{{{{key_var}}}}' where key_var='x'
       becomes '{{x}}' before the outer substitution runs.
    2. Unset suffix ('::') — '{{varname::}}' returns the variable's value if
       defined, otherwise returns _UNSET to signal the caller to remove the
       property entirely.
    3. First substitution pass: replace exact '{{varname}}' matches from the
       substitutions dict. This handles the common no-default case without the
       overhead of the regex-based default extraction below.
    4. Env-var handling: '{{env:VARNAME}}' and '{{env:VARNAME:=default}}'.
    5. Default extraction: collect (varname, default) pairs from any remaining
       '{{varname:=default}}' patterns. The first pass (step 3) leaves these
       untouched because the full '{{varname:=default}}' string does not match
       the exact '{{varname}}' key in the dict.
    6. Strip defaults: rewrite '{{varname:=default}}' as '{{varname}}' so the
       substitutions dict can match them.
    7. Second substitution pass: replace '{{varname}}' from the dict, now that
       defaults have been stripped.
    8. Apply defaults: for any '{{varname}}' still unresolved, substitute its
       collected default value.
    """
    if input_string is None:
        return None

    # Check if there are inner variables
    undelimited_input_string = remove_outer_delimiters(
        input_string, opening_delimiter, closing_delimiter
    )
    if (
        opening_delimiter in undelimited_input_string
        and closing_delimiter in undelimited_input_string
    ):
        # Recursive call to resolve innermost variables first
        processed_string = ""
        for element in split_delimited_string(
            undelimited_input_string, opening_delimiter, closing_delimiter
        ):
            result = process_untyped_variable_substitutions(
                element, opening_delimiter, closing_delimiter
            )
            if result is _UNSET:
                # An unset inner variable: leave its token intact so the
                # caller's dict-level processing can remove the property
                processed_string += element
            else:
                processed_string += result or ""
        input_string = opening_delimiter + processed_string + closing_delimiter

    assert isinstance(input_string, str)  # narrow: None already returned above
    s: str = input_string

    # Check for the unset suffix ('::') — must be done before the general
    # substitution loop so the bare variable name can be looked up cleanly.
    # Syntax: "{{varname::}}" — if varname is defined, use its value;
    # if not, return _UNSET to signal the caller to remove the property.
    unset_marker = (
        f"{re.escape(opening_delimiter)}.*"
        f"{re.escape(VAR_UNSET_SUFFIX)}{re.escape(closing_delimiter)}"
    )
    if re.fullmatch(unset_marker, s):
        bare_name = remove_outer_delimiters(s, opening_delimiter, closing_delimiter)[
            : -len(VAR_UNSET_SUFFIX)
        ]
        if bare_name in VARIABLE_SUBSTITUTIONS:
            s = str(VARIABLE_SUBSTITUTIONS[bare_name])
        elif bare_name.startswith(ENV_VAR_SUB_PREFIX):
            env_value = os.getenv(bare_name[len(ENV_VAR_SUB_PREFIX) :])
            if env_value is not None:
                s = env_value
            else:
                return _UNSET  # type: ignore
        else:
            return _UNSET  # type: ignore

    # Perform initial substitutions from the substitutions dictionary; this
    # will not substitute variables that have default values
    for substitution, value in VARIABLE_SUBSTITUTIONS.items():
        s = s.replace(
            f"{opening_delimiter}{substitution}{closing_delimiter}", str(value)
        )

    # Check for substitutions from general environment variables
    if s.startswith(f"{opening_delimiter}{ENV_VAR_SUB_PREFIX}"):
        var_name = s.replace(f"{opening_delimiter}{ENV_VAR_SUB_PREFIX}", "").replace(
            closing_delimiter, ""
        )
        if VAR_DEFAULT_SEPARATOR in var_name:  # Check for a default
            split_result = var_name.split(VAR_DEFAULT_SEPARATOR)
            if split_result[0] == "" or len(split_result) != 2:
                raise ValueError(
                    f"Malformed '<variable>:=<default>' substitution: '{var_name}'"
                )
            var_name, var_default = split_result
        else:
            var_default = None
        var = os.getenv(var_name, None)
        if var is not None:  # Matching environment variable
            if var_default is None:  # Just replace the prefix and the variable name
                s = s.replace(
                    f"{opening_delimiter}{ENV_VAR_SUB_PREFIX}{var_name}{closing_delimiter}",
                    var,
                )
            else:  # Also replace the default separator & value
                s = s.replace(
                    f"{opening_delimiter}{ENV_VAR_SUB_PREFIX}{var_name}"
                    f"{VAR_DEFAULT_SEPARATOR}{var_default}{closing_delimiter}",
                    var,
                )
        elif var_default is not None:  # Variable not found, but default exists
            s = s.replace(
                f"{opening_delimiter}{ENV_VAR_SUB_PREFIX}{var_name}"
                f"{VAR_DEFAULT_SEPARATOR}{var_default}{closing_delimiter}",
                var_default,
            )

    # Create list of variable substitutions with their default values
    substitutions_with_defaults = re.findall(
        f"{re.escape(opening_delimiter)}.*{re.escape(VAR_DEFAULT_SEPARATOR)}"
        f".*{re.escape(closing_delimiter)}",
        s,
    )
    default_value_substitutions = []  # List of (variable_name, default_value)
    for substitution in substitutions_with_defaults:
        variable_default = remove_outer_delimiters(
            substitution, opening_delimiter, closing_delimiter
        ).split(VAR_DEFAULT_SEPARATOR)
        if variable_default[0] == "" or len(variable_default) != 2:
            raise ValueError(
                f"Malformed '<variable>:=<default>' substitution: '{substitution}'"
            )
        default_value_substitutions.append(variable_default)

    # Remove default variable values if present (i.e., remove ':=<default>')
    s = str(
        re.sub(
            VAR_DEFAULT_SEPARATOR + f".*{closing_delimiter}",
            f"{closing_delimiter}",
            s,
        )
    )

    # Repeat substitutions from the substitutions dictionary, now that defaults
    # have been removed
    for substitution, value in VARIABLE_SUBSTITUTIONS.items():
        s = s.replace(
            f"{opening_delimiter}{substitution}{closing_delimiter}", str(value)
        )

    # Perform default substitutions for variables that remain unpopulated;
    # allows for multiple variables with the same name, but with different
    # default values
    for var_name, default_value in default_value_substitutions:
        s = s.replace(
            f"{opening_delimiter}{var_name}{closing_delimiter}",
            str(default_value),
            1,
        )

    return s


def process_typed_variable_substitution(
    type_string: str, input_string: str
) -> str | int | bool | float | list | dict | None:
    """
    Process a single typed substitution, returning the appropriate type.
    Assumes there is a substitution present.
    """
    if type_string == FORMAT_NAME_TYPE_TAG:
        return format_yd_name(input_string, add_prefix=False)

    if type_string == NUMBER_TYPE_TAG:
        try:
            return int(input_string)
        except ValueError:
            try:
                return float(input_string)
            except ValueError:
                raise ValueError(
                    f"Non-number used in variable number substitution: '{input_string}'"
                )

    if type_string == BOOL_TYPE_TAG:
        if input_string.lower() == "true":
            return True
        if input_string.lower() == "false":
            return False
        raise ValueError(
            f"Non-boolean used in variable boolean substitution: '{input_string}'"
        )

    if type_string == ARRAY_TYPE_TAG:
        try:
            return_value = json_loads(input_string)
            if not isinstance(return_value, list):
                raise TypeError("Not an array/list")
            return return_value
        except Exception as e:
            raise ValueError(
                f"Property cannot be parsed as an array: '{input_string}' ({e})"
            )

    if type_string == TABLE_TYPE_TAG:
        try:
            return_value = json_loads(input_string)
            if not isinstance(return_value, dict):
                raise TypeError("Not a table/dict")
            return return_value
        except Exception as e:
            raise ValueError(
                f"Property cannot be parsed as a table: '{input_string}' "
                f'(Use JSON syntax, e.g. {{"key": "value"}}) ({e})'
            )

    return None


def resolve_filename(files_directory: str, filename: str) -> str:
    """
    Check whether 'files_directory' is redundant.
    This is a suboptimal approach, but works for now.
    """
    if os.path.dirname(os.path.abspath(filename)) == os.path.abspath(files_directory):
        return filename
    return os.path.join(files_directory, filename)


def load_json_file_with_variable_substitutions(
    filename: str, prefix: str = "", postfix: str = "", files_directory: str = ""
) -> dict:
    """
    Takes a JSON filename and returns a dictionary with its variable
    substitutions processed.
    """
    with open(resolve_filename(files_directory, filename)) as f:
        file_contents = f.read()
    file_contents = process_variable_substitutions_in_file_contents(
        file_contents, prefix=prefix, postfix=postfix
    )
    result = json_loads(file_contents)
    process_variable_substitutions_insitu(result, prefix=prefix, postfix=postfix)
    return result


def load_jsonnet_file_with_variable_substitutions(
    filename: str,
    prefix: str = "",
    postfix: str = "",
    files_directory: str = "",
    exit_on_dry_run=True,
) -> dict:
    """
    Takes a Jsonnet filename and returns a dictionary with its variable
    substitutions processed.
    """
    check_jsonnet_import()
    from _jsonnet import evaluate_file

    with VariableSubstitutedJsonnetFile(
        filename=resolve_filename(files_directory, filename),
        prefix=prefix,
        postfix=postfix,
    ) as preprocessed_filename:
        try:
            dict_data = json_loads(evaluate_file(preprocessed_filename))
        except RuntimeError as e:
            # Include only the first line of the exception message
            raise RuntimeError(str(e).partition("\n")[0])

    # Secondary processing after Jsonnet expansion
    process_variable_substitutions_insitu(dict_data, prefix, postfix)

    if ARGS_PARSER.jsonnet_dry_run:
        print_info(f"Dry-run: Printing Jsonnet to JSON conversion for '{filename}'")
        print_json(dict_data)
        print_info("Dry-run: Complete")
        if exit_on_dry_run:
            sys.exit(0)

    return dict_data


def load_toml_file_with_variable_substitutions(
    filename: str, prefix: str = "", postfix: str = "", files_directory: str = ""
) -> dict:
    """
    Takes a TOML filename and returns a dictionary with its variable
    substitutions processed.
    """
    with open(resolve_filename(files_directory, filename), "rb") as f:
        config = toml_load(f)

    # Add any variable substitutions in the TOML file before processing the
    # file as a whole
    try:
        # Convert all values to strings before adding
        add_substitutions_from_config_file(
            {
                var_name: str(var_value)
                for var_name, var_value in config[COMMON_SECTION][VARIABLES].items()
            }
        )
    except KeyError:
        pass

    # Repeat processing to resolve nested variables
    for _ in range(TOML_VAR_NESTED_DEPTH):
        process_variable_substitutions_insitu(config, prefix=prefix, postfix=postfix)

    return config


def process_variable_substitutions_in_file_contents(
    file_contents: str, prefix: str = "", postfix: str = ""
) -> str:
    """
    Process substitutions in the raw contents of a complete file.
    """
    v_expressions = set(
        re.findall(
            f"{re.escape(prefix)}{re.escape(VAR_OPENING_DELIMITER)}"
            f".*{re.escape(VAR_CLOSING_DELIMITER)}{re.escape(postfix)}",
            file_contents,
        )
    )

    for v_expression in v_expressions:
        replacement_expression = process_variable_substitutions(
            v_expression, prefix=prefix, postfix=postfix
        )
        if replacement_expression is _UNSET:
            continue  # leave the token intact; dict-level processing will remove the key
        if isinstance(replacement_expression, str):
            file_contents = file_contents.replace(v_expression, replacement_expression)
        else:
            # If the replacement is a number, a boolean, a table, or an array,
            # we need to remove the enclosing quotes when we substitute.
            # json.dumps() emits valid JSON/Jsonnet ('true'/'false', double
            # quotes) and preserves the case of string values.
            # Account for both double and single quotes (for Jsonnet support).
            replacement = json_dumps(replacement_expression)
            file_contents = file_contents.replace(f'"{v_expression}"', replacement)
            file_contents = file_contents.replace(f"'{v_expression}'", replacement)

    return file_contents


class VariableSubstitutedJsonnetFile:
    """
    The jsonnet 'evaluate_file' function will only operate on files,
    not strings, so this context manager class will create a
    temporary, variable-processed file that can be used by the
    evaluator, then deleted.
    """

    def __init__(self, filename: str, prefix: str = "", postfix: str = ""):
        self.filename = filename
        self.prefix = prefix
        self.postfix = postfix

    def __enter__(self) -> str:
        """
        Return the filename of the temporary variable-processed
        jsonnet file.
        """
        with open(self.filename) as file:
            file_contents = file.read()
        processed_file_contents: str = process_variable_substitutions_in_file_contents(
            file_contents, self.prefix, self.postfix
        )
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, dir=os.getcwd()
        ) as temp_file:
            temp_file.write(processed_file_contents)
        self.temp_filename: str = temp_file.name
        return self.temp_filename

    def __exit__(self, exc_type, exc_val, exc_tb):
        os.remove(self.temp_filename)
