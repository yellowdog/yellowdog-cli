"""
Utilities for applying variable substitutions.
"""

import ast
import math
import os
import re
import sys
import tempfile
from bisect import bisect_right
from copy import deepcopy
from getpass import getuser
from json import JSONDecodeError
from json import dumps as json_dumps
from json import loads as json_loads
from typing import cast

from tomli import load as toml_load

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.check_imports import check_jsonnet_import
from yellowdog_cli.utils.misc_utils import (
    PID,
    PROCESS_DISCRIMINATOR,
    UTCNOW,
    config_file_explicitly_selected,
    find_delimited_expression_spans,
    find_delimited_expressions,
    format_yd_name,
    load_dotenv_file,
    random_base36,
    split_delimited_string,
)
from yellowdog_cli.utils.printing import (
    print_debug,
    print_dry_run,
    print_error,
    print_json,
    print_warning,
)
from yellowdog_cli.utils.property_names import (
    COMMON_SECTION,
    USERDATA,
    VARIABLES,
)
from yellowdog_cli.utils.results import record
from yellowdog_cli.utils.settings import (
    ARRAY_TYPE_TAG,
    BOOL_TYPE_TAG,
    ENV_VAR_SUB_PREFIX,
    ENV_VARIABLE_NAME_PATTERN,
    FORMAT_NAME_TYPE_TAG,
    LAZY_VARIABLE_NAMES,
    NUMBER_TYPE_TAG,
    RAND_VAR_6_DIGITS,
    RAND_VAR_DIGITS,
    RESERVED_VARIABLE_NAMES,
    TABLE_TYPE_TAG,
    TYPE_TAG_DEFAULT_GUARD,
    VAR_CLOSING_DELIMITER,
    VAR_DEFAULT_SEPARATOR,
    VAR_OPENING_DELIMITER,
    VAR_SUBSTITUTION_MAX_PASSES,
    VAR_UNSET_SUFFIX,
    VARIABLE_NAME_PATTERN,
    VARIABLE_NAME_RULE,
    WP_VARIABLES_POSTFIX,
    WP_VARIABLES_PREFIX,
    YD_ENV_VAR_PREFIX,
    ExitCode,
)

# Sentinel returned by process_variable_substitutions() when a property
# bearing the '::' unset suffix has no value defined; callers that walk
# a dict/list (i.e. _walk_data) use this to delete the property entirely.
_UNSET = object()

# Stands in for an unset expression nested inside another one while the outer
# expression is resolved. Whether the outer one is then unset too depends on
# whether the value was needed -- to build a name, or as a default that is
# used -- which is known only once it is resolved: if the marker is still
# there, it was. A private-use character, which no delimiter, separator or
# regular expression below can match, and no variable value will contain.
_UNSET_MARKER = "\ue000"

# Whether an expression left unsubstituted is reported as an undefined
# variable. Off until a command's own processing begins (the command
# wrappers turn it on), because the configuration's own passes run while
# its variables are still being defined -- 'namespace', 'tag', 'key',
# 'dataClient.*' -- and would report each of them.
_UNDEFINED_VARIABLE_WARNINGS = False

# The expressions already reported, so that each is reported once however
# many passes, Task Groups or Tasks it turns up in; or, for a check made
# 'per_source', the (expression, source) pairs, so that each file holding
# an expression is reported once, however many times it is read
_UNDEFINED_VARIABLES_REPORTED: set[str | tuple[str, str]] = set()

# What an expression naming a variable looks like, once resolution has left
# it: an optional type tag, then either 'env:' and an environment variable's
# name, or a variable name. Anything else -- Docker's '{{.ID}}', a Go
# template's '{{ .Values.x }}', Handlebars' '{{#each}}' -- is text meant for
# something else, since no variable can be defined with such a name.


def _finite(value: float) -> float:
    """
    A number JSON can carry: not NaN or an infinity, which Python's float()
    and json.loads() both accept, and which no request body can hold.
    """
    if not math.isfinite(value):
        raise ValueError("is not a finite number")
    return value


def _number(text: str) -> int | float:
    """
    A number, in JSON's syntax or Python's ('1e3', '1E3', '1_000', ' 5 ').
    """
    try:
        return int(text)
    except ValueError:
        pass
    try:
        value = float(text)
    except ValueError:
        raise ValueError("is not a number") from None
    return _finite(value)


def _boolean(text: str) -> bool:
    """
    'true' or 'false', in any case and with any space around it, so JSON's
    spelling and Python's.
    """
    match text.strip().lower():
        case "true":
            return True
        case "false":
            return False
    raise ValueError("is not true or false")


def _json_form(value: object) -> None:
    """
    Raise ValueError, saying why, unless a value read as a Python literal is
    one JSON could have held: lists, tables with string keys, strings,
    finite numbers, booleans and None. A tuple, a set, bytes or a complex
    number has no JSON form, and a key that is not a string would be changed
    by being written as JSON ('{1: "a"}' as '{"1": "a"}'), so each is refused.
    """
    match value:
        case bool() | int() | str() | None:
            return
        case float():
            _finite(value)
        case list():
            for item in value:
                _json_form(item)
        case dict():
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError(f"its key {key!r} is not a string")
                _json_form(item)
        case tuple():
            raise ValueError("it is a tuple: write an array in '[' and ']'")
        case _:
            raise ValueError(f"a {type(value).__name__} has no JSON form")


def _collection_of(kind: type, description: str, example: str):
    """
    A converter reading text as a value of the given kind: as JSON, refusing
    the NaN and infinities json.loads() accepts but JSON does not, or where
    that fails as a Python literal ("['a', True]"), which is easier to quote
    on a command line, but only one JSON could have held. Python's spelling
    never changes what JSON's means: it is read only where JSON fails, and
    by ast.literal_eval(), which evaluates no code.
    """

    def _convert(text: str) -> list | dict:
        def _refuse(constant: str):
            raise ValueError(f"'{constant}' is not JSON")

        not_one = f"is not a JSON {description}, e.g. {example}"
        try:
            value = json_loads(
                text,
                parse_constant=_refuse,
                parse_float=lambda f: _finite(float(f)),
            )
        except ValueError as json_error:
            try:
                value = ast.literal_eval(text)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                raise ValueError(
                    f"{not_one}, nor in Python's spelling ({json_error})"
                ) from json_error
            try:
                _json_form(value)
            except ValueError as e:
                raise ValueError(f"{not_one} ({e})") from None
        if not isinstance(value, kind):
            raise ValueError(not_one)
        return value

    return _convert


# Each type tag and what its value is converted by: every tag the syntax
# recognises is here, and the tags are read from here, so one added here is
# recognised everywhere and none can be recognised without a converter
_TYPE_CONVERTERS = {
    NUMBER_TYPE_TAG: _number,
    BOOL_TYPE_TAG: _boolean,
    ARRAY_TYPE_TAG: _collection_of(list, "array", "[1, 2, 3]"),
    TABLE_TYPE_TAG: _collection_of(dict, "table", '{"key": "value"}'),
    FORMAT_NAME_TYPE_TAG: lambda text: format_yd_name(text, add_prefix=False),
}
_TYPE_TAGS = tuple(_TYPE_CONVERTERS)
_VARIABLE_REFERENCE = re.compile(
    "(?:"
    + "|".join(re.escape(tag) for tag in _TYPE_TAGS)
    + f")?({re.escape(ENV_VAR_SUB_PREFIX)}{ENV_VARIABLE_NAME_PATTERN}"
    + f"|{VARIABLE_NAME_PATTERN})"
)
_VARIABLE_NAME = re.compile(VARIABLE_NAME_PATTERN)


def check_variable_name(name: str, source: str) -> None:
    """
    Raise ValueError if 'name' is not a valid variable name, naming 'source'
    -- where the definition came from -- and the rule.
    """
    if not _VARIABLE_NAME.fullmatch(name):
        raise ValueError(
            f"Invalid variable name '{name}' in {source}: {VARIABLE_NAME_RULE}"
        )


def check_user_variable_name(name: str, source: str) -> None:
    """
    As check_variable_name(), and also raise ValueError if 'name' is one of
    the variables the CLI defines from its configuration, saying where it is
    set instead. For the definitions a user writes -- '-v', 'YD_VAR_*',
    '[common.variables]' and '--property common.variables.<name>' -- never for
    the CLI's own registration of those values.
    """
    check_variable_name(name, source)
    if name in RESERVED_VARIABLE_NAMES:
        raise ValueError(
            f"Variable '{name}' in {source} cannot be defined: it is set by the"
            f" configuration, using {RESERVED_VARIABLE_NAMES[name]}"
        )


def enable_undefined_variable_warnings() -> None:
    """
    Report, from now on, variables left unsubstituted because nothing
    defines them. Called by the command wrappers as a command begins.
    """
    global _UNDEFINED_VARIABLE_WARNINGS
    _UNDEFINED_VARIABLE_WARNINGS = True


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
    "random": random_base36(RAND_VAR_DIGITS),
    "random6": random_base36(RAND_VAR_6_DIGITS),
    "pid": str(PID),
    "pid2": PROCESS_DISCRIMINATOR,
}

# Load .env file before scanning os.environ so YD_VAR_* variables defined
# there are picked up regardless of import order.
load_dotenv_file()

# Substitutions from environment variables
subs_list = []
for key, value in os.environ.items():
    if key.startswith(YD_ENV_VAR_PREFIX):
        try:
            check_user_variable_name(
                key[len(YD_ENV_VAR_PREFIX) :], f"environment variable '{key}'"
            )
        except ValueError as e:
            print_error(e)
            exit(ExitCode.CONFIGURATION)  # Note: exception trap not yet in place
        key = key[len(YD_ENV_VAR_PREFIX) :]
        VARIABLE_SUBSTITUTIONS[key] = value
        subs_list.append(f"'{key}'")

if subs_list:
    print_debug(
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
            try:
                check_user_variable_name(key_value[0], f"'--variable {variable}'")
            except ValueError as e:
                print_error(e)
                exit(ExitCode.CONFIGURATION)  # Note: exception trap not yet in place
            VARIABLE_SUBSTITUTIONS[key_value[0]] = key_value[1]
            CLI_DEFINED_VARIABLES.add(key_value[0])
            subs_list.append(f"'{key_value[0]}'")
        else:
            print_error(
                f"Error in variable substitution '{variable}'",
            )
            exit(ExitCode.CONFIGURATION)  # Note: exception trap not yet in place

if subs_list:
    print_debug(
        "Adding command-line-defined variable substitution(s) for: "
        f"{', '.join(subs_list)}"
    )

del subs_list

# Each variable's definition as written, before any substitution, which is
# what explain_unset_variable() works from: once the '::' syntax has removed
# a variable from the table, nothing left there says why -- a variable that
# referred to an unset one holds that one's '{{::}}' as text by then, and is
# removed on the next pass for that. Kept in step with the table by
# _update_and_resolve_substitutions() and add_or_update_substitution().
_DEFINITIONS: dict[str, str] = dict(VARIABLE_SUBSTITUTIONS)


def _stringify(value) -> str:
    """
    Render a variable's value as the string the substitutions dictionary
    holds.

    Values are rendered as JSON rather than with str(), whose Python repr
    quotes strings with apostrophes and capitalises booleans: the type tags
    read the value back as JSON -- 'array:' and 'table:' with json_loads(),
    'bool:' as the JSON spelling -- so a repr of a list or table cannot be
    read back at all, and a TOML array of strings would be unusable as an
    array. Rendering the scalars the same way keeps a boolean spelled the
    same whether it stands alone or sits inside an array.

    A string is passed through untouched: every value is re-rendered on
    each resolution pass, so a string given JSON's quotes would gain another
    pair on every pass. A value with no JSON form at all -- TOML's date,
    time and datetime values are date/datetime objects -- falls back to
    str(), which renders them as the text they were written as.
    """
    if isinstance(value, str):
        return value
    try:
        return json_dumps(value)
    except TypeError:
        return str(value)


def _update_and_resolve_substitutions(merged: dict):
    """
    Replace the substitutions dictionary with 'merged' and re-resolve
    variables. The dict is updated in-place so that all callers holding a
    reference to it see the change (rebinding the name would silently
    break imported references).
    """
    # A value the table already holds is a definition already recorded (its
    # resolved value, which is not the definition); anything else is new
    for key_, value_ in merged.items():
        if key_ in VARIABLE_SUBSTITUTIONS and VARIABLE_SUBSTITUTIONS[key_] == value_:
            _DEFINITIONS.setdefault(key_, _stringify(value_))
        else:
            _DEFINITIONS[key_] = _stringify(value_)

    VARIABLE_SUBSTITUTIONS.clear()
    VARIABLE_SUBSTITUTIONS.update(merged)

    # A variable that resolves to _UNSET (it is '{{::}}', or refers to an
    # undefined variable with the '::' unset suffix) is removed entirely --
    # and removed before anything else is substituted, since while it is
    # still in the table a reference to it would take in its '{{::}}' as
    # text, and so be unset in turn by the next pass: an unset that spreads
    # to every variable merely referring to it, but only to those resolved
    # in the same pass as it. Removed first, it is simply undefined, as it
    # is to everything resolved later. Repeated, because a removal can
    # unset a variable referring to it with the '::' suffix.
    while unset := [
        key_
        for key_, value_ in VARIABLE_SUBSTITUTIONS.items()
        if process_variable_substitutions(_stringify(value_)) is _UNSET
    ]:
        for key_ in unset:
            del VARIABLE_SUBSTITUTIONS[key_]

    # Populate variables that can now be substituted, stored as strings
    for key_, value_ in VARIABLE_SUBSTITUTIONS.items():
        VARIABLE_SUBSTITUTIONS[key_] = cast(
            str, process_variable_substitutions(_stringify(value_))
        )


def add_substitutions_without_overwriting(
    subs: dict, source: str = "a variable definition"
):
    """
    Add a dictionary of substitutions. Do not overwrite existing values, but
    resolve remaining variables if possible. Raises ValueError, naming
    'source', for a name that is not a valid variable name.
    """
    for name in subs:
        check_variable_name(name, source)
    # Merge: existing entries (CLI / env vars) take priority over incoming
    # ones
    _update_and_resolve_substitutions({**subs, **VARIABLE_SUBSTITUTIONS})


def add_substitutions_from_config_file(
    subs: dict, source: str = "'[common.variables]'"
):
    """
    Add variable substitutions from a TOML configuration file's
    [common.variables] section.

    If the config file was explicitly selected using '--config'/'-c', its
    variables override environment-defined variables (but never variables
    set on the command line); otherwise existing definitions take
    precedence as usual.
    """
    for name in subs:
        check_user_variable_name(name, source)
    if not config_file_explicitly_selected(ARGS_PARSER):
        add_substitutions_without_overwriting(subs, source)
        return

    subs = {k: v for k, v in subs.items() if k not in CLI_DEFINED_VARIABLES}
    _update_and_resolve_substitutions({**VARIABLE_SUBSTITUTIONS, **subs})


def add_or_update_substitution(key: str, value, source: str = "a variable definition"):
    """
    Add a substitution to the dictionary, overwriting existing values. Raises
    ValueError, naming 'source', for a name that is not a valid variable name.
    """
    check_variable_name(key, source)
    VARIABLE_SUBSTITUTIONS[key] = _DEFINITIONS[key] = _stringify(value)


def get_user_variable(variable_name: str) -> str | None:
    """
    Get the value of a variable.
    """
    return VARIABLE_SUBSTITUTIONS.get(variable_name)


def get_unset_variable_names() -> list[str]:
    """
    The variables that were defined but are not in the table, because the
    '::' unset syntax removed them, in alphabetical order.
    """
    return sorted(name for name in _DEFINITIONS if name not in VARIABLE_SUBSTITUTIONS)


def explain_unset_variable(name: str) -> str | None:
    """
    Why the variable 'name' was defined and yet has no value, or None if it
    has a value or was never defined.
    """
    if name in VARIABLE_SUBSTITUTIONS or name not in _DEFINITIONS:
        return None
    return f"Variable '{name}' is unset: " + "; ".join(_unset_reasons(name))


def _unset_reasons(name: str) -> list[str]:
    """
    What in the definition of the unset variable 'name' unset it. Only its
    own definition can have: a plain reference to an unset variable leaves
    that reference unsubstituted, as one to any undefined variable does. A
    '{{x::}}' reference to an unset 'x' is followed to what unset 'x', and
    so on to the '{{::}}' or undefined '{{y::}}' at the end of the chain.
    """
    reasons: list[str] = []
    explained: set[str] = set()
    pending = [name]
    while pending:
        name_ = pending.pop(0)
        if name_ in explained:
            continue
        explained.add(name_)
        definition = _DEFINITIONS[name_]
        causes = _unset_causes(definition)
        if not causes:
            reasons.append(
                f"'{name_}' is unset by the '{VAR_UNSET_SUFFIX}' in its"
                f" definition, '{definition}'"
            )
        for clause, unset_reference in causes:
            reasons.append(f"'{name_}' {clause}")
            if unset_reference is not None:
                pending.append(unset_reference)
    return reasons


def _unset_causes(definition: str) -> list[tuple[str, str | None]]:
    """
    The expressions in a variable's definition that can unset it -- a
    '{{::}}', or a '{{x::}}' with no 'x' to substitute -- each as a clause
    saying why, with the name of the variable it refers to where that was
    defined and is itself unset, so that the chain can be followed.
    """
    causes: list[tuple[str, str | None]] = []

    def _check(text: str):
        for expression in find_delimited_expressions(
            text, VAR_OPENING_DELIMITER, VAR_CLOSING_DELIMITER
        ):
            inner = expression[len(VAR_OPENING_DELIMITER) : -len(VAR_CLOSING_DELIMITER)]
            if VAR_OPENING_DELIMITER in inner:
                _check(inner)
                continue
            for tag in _TYPE_TAGS:
                if inner.startswith(tag):
                    inner = inner[len(tag) :]
                    break
            if not inner.endswith(VAR_UNSET_SUFFIX):
                continue
            reference = inner[: -len(VAR_UNSET_SUFFIX)]
            if reference == "":
                verb = "is" if expression == definition else "contains"
                causes.append((f"{verb} '{expression}', which always unsets it", None))
            elif reference.startswith(ENV_VAR_SUB_PREFIX):
                env_name = reference[len(ENV_VAR_SUB_PREFIX) :]
                if os.getenv(env_name) is None:
                    causes.append(
                        (
                            f"refers to '{expression}', and the environment"
                            f" variable '{env_name}' is not set",
                            None,
                        )
                    )
            elif reference in _DEFINITIONS and reference not in VARIABLE_SUBSTITUTIONS:
                causes.append(
                    (f"refers to '{expression}', and '{reference}' is unset", reference)
                )
            elif reference not in VARIABLE_SUBSTITUTIONS:
                causes.append(
                    (
                        f"refers to '{expression}', and '{reference}' is not defined",
                        None,
                    )
                )

    _check(definition)
    return causes


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
    _substitute_insitu_pass(data, prefix=prefix, postfix=postfix)
    return data


def _substitute_insitu_pass(
    data: dict | list, prefix: str = "", postfix: str = ""
) -> list[str]:
    """
    One substitution pass over 'data', in-situ, returning the paths of the
    properties it changed or removed (e.g. 'taskGroups[0].name').
    """
    changed: list[str] = []

    def _substitute(key_, value_: str, path: str):
        # Require the use of post/prefix only for userData in TOML
        if key_ == USERDATA:
            result = process_variable_substitutions(
                value_, prefix=WP_VARIABLES_PREFIX, postfix=WP_VARIABLES_POSTFIX
            )
        else:
            result = process_variable_substitutions(
                value_, prefix=prefix, postfix=postfix
            )
        if result is _UNSET or result != value_:
            changed.append(path)
        return result

    def _walk_data(data: dict | list, path: str):
        """
        Helper function to walk the data structure performing
        variable substitutions.
        """
        if isinstance(data, dict):
            keys_to_delete = []
            for key_, value_ in data.items():
                key_path = f"{path}.{key_}" if path else str(key_)
                if isinstance(value_, str):
                    result = _substitute(key_, value_, key_path)
                    if result is _UNSET:
                        keys_to_delete.append(key_)
                    else:
                        data[key_] = result
                elif isinstance(value_, dict) or isinstance(value_, list):
                    _walk_data(value_, key_path)
            for key_ in keys_to_delete:
                del data[key_]
        elif isinstance(data, list):
            indices_to_delete = []
            for index, item in enumerate(data):
                index_path = f"{path}[{index}]"
                if isinstance(item, str):
                    # A list element is never userData, so no key applies
                    result = _substitute(None, item, index_path)
                    if result is _UNSET:
                        indices_to_delete.append(index)
                    else:
                        data[index] = result
                elif isinstance(item, dict) or isinstance(item, list):
                    _walk_data(item, index_path)
            for index in reversed(indices_to_delete):
                del data[index]

    _walk_data(data, "")
    return changed


def resolve_variables_insitu(
    data: dict | list, prefix: str = "", postfix: str = ""
) -> None:
    """
    Repeat the in-situ pass until one changes nothing, so that a substituted
    value which itself contains a variable reference is resolved too, however
    long the chain. A circular reference -- a variable that refers back to
    itself, directly or through others -- raises ValueError: either the
    values are still changing after VAR_SUBSTITUTION_MAX_PASSES passes, or
    they have settled with a defined variable still unsubstituted, which only
    a circular one can be. An undefined variable is neither: it is unchanged
    by the first pass and is passed through as it stands.
    """
    for _ in range(VAR_SUBSTITUTION_MAX_PASSES):
        changed = _substitute_insitu_pass(data, prefix=prefix, postfix=postfix)
        if not changed:
            break
    else:
        raise ValueError(
            "Variable substitution did not settle after"
            f" {VAR_SUBSTITUTION_MAX_PASSES} passes, which suggests a circular"
            f" variable reference, in {_list_paths(changed)}"
        )

    _warn_of_undefined(
        _undefined_unless_circular(
            _unsubstituted_references(data, prefix=prefix, postfix=postfix)
        )
    )


def _undefined_unless_circular(
    references: list[tuple[str, str, str]],
) -> dict[str, list[str]]:
    """
    Sort the references left once the passes have settled: raise ValueError
    for any to a defined variable, which is still there only because it is
    circular, and return the rest -- the undefined ones, lazy variables
    aside -- as the properties each expression was found in.
    """
    circular: dict[str, list[str]] = {}
    undefined: dict[str, list[str]] = {}
    for expression, reference, path in references:
        if reference in VARIABLE_SUBSTITUTIONS:
            circular.setdefault(reference, []).append(path)
        elif reference not in LAZY_VARIABLE_NAMES:
            undefined.setdefault(expression, []).append(path)

    if circular:
        names = ", ".join(f"'{name}'" for name in sorted(circular))
        paths = [path for paths in circular.values() for path in paths]
        raise ValueError(
            f"Circular variable reference: {names} refers back to itself,"
            f" in {_list_paths(paths)}"
        )
    return undefined


def resolve_variables_in_string(
    value: str | int | bool | float | list | dict | None, source: str | None = None
) -> str | int | bool | float | list | dict | None:
    """
    resolve_variables_insitu() for a single value: repeat the substitution
    until it changes nothing, so that a chain of references resolves however
    long it is, then raise ValueError for a circular reference and warn of
    an undefined variable, naming 'source' (the property, or the value itself
    where there is no better name). A type-tagged result, a value that is not
    a string, and the unset marker are returned as they are.
    """
    result = value
    for _ in range(VAR_SUBSTITUTION_MAX_PASSES):
        if not isinstance(result, str):
            return result
        substituted = process_variable_substitutions(result)
        if substituted == result:
            break
        result = substituted
    else:
        raise ValueError(
            "Variable substitution did not settle after"
            f" {VAR_SUBSTITUTION_MAX_PASSES} passes, which suggests a circular"
            f" variable reference, in '{source if source is not None else value}'"
        )

    if isinstance(result, str):
        label = source if source is not None else str(value)
        _warn_of_undefined(
            _undefined_unless_circular(_unsubstituted_references({label: result}))
        )
    return result


def undefined_variable_references(
    data: dict | list, prefix: str = "", postfix: str = ""
) -> list[str]:
    """
    The names of the variables referenced in 'data' that nothing defines,
    sorted and without duplicates. Reports nothing; yd-doctor's seam.
    """
    return sorted(
        {
            reference
            for _, reference, _ in _unsubstituted_references(
                data, prefix=prefix, postfix=postfix
            )
            if reference not in VARIABLE_SUBSTITUTIONS
            and reference not in LAZY_VARIABLE_NAMES
        }
    )


def warn_of_undefined_variables(
    data: dict | list, prefix: str = "", postfix: str = "", per_source: bool = False
) -> None:
    """
    Report the undefined variables left in 'data', as resolve_variables_insitu()
    does, without substituting anything: for data resolved before the warnings
    were enabled, which would otherwise never be checked.

    With 'per_source', an expression is reported once for each source (each
    key of 'data') it turns up in, rather than once in all: for files, each of
    which is checked by a call of its own, so that an expression in several of
    a '*Files' list is reported for each of them, not for the first alone.
    """
    undefined: dict[str, list[str]] = {}
    for expression, reference, path in _unsubstituted_references(
        data, prefix=prefix, postfix=postfix
    ):
        if (
            reference not in VARIABLE_SUBSTITUTIONS
            and reference not in LAZY_VARIABLE_NAMES
        ):
            undefined.setdefault(expression, []).append(path)
    _warn_of_undefined(undefined, per_source=per_source)


def _warn_of_undefined(
    undefined: dict[str, list[str]], per_source: bool = False
) -> None:
    """
    Warn of each undefined variable expression, with the properties it was
    found in, unless warnings are not yet enabled or it was reported before:
    the expression at all, or with 'per_source' in that property.
    """
    if not _UNDEFINED_VARIABLE_WARNINGS:
        return
    for expression, paths in undefined.items():
        if per_source:
            paths = [
                path
                for path in dict.fromkeys(paths)
                if (expression, path) not in _UNDEFINED_VARIABLES_REPORTED
            ]
            if not paths:
                continue
            _UNDEFINED_VARIABLES_REPORTED.update((expression, path) for path in paths)
        else:
            if expression in _UNDEFINED_VARIABLES_REPORTED:
                continue
            _UNDEFINED_VARIABLES_REPORTED.add(expression)
        reference = _reference_of(expression)
        if reference in _DEFINITIONS and reference not in VARIABLE_SUBSTITUTIONS:
            # Defined, but removed by the unset syntax, which is what anyone
            # looking for the typo that 'not defined' implies needs to know
            print_warning(
                f"Variable '{expression}' is unset, and has been left"
                f" unsubstituted in {_list_paths(paths)}: "
                + "; ".join(_unset_reasons(reference))
            )
        else:
            print_warning(
                f"Variable '{expression}' is not defined, and has been left"
                f" unsubstituted in {_list_paths(paths)}"
            )


def _reference_of(expression: str) -> str | None:
    """
    The variable name an expression refers to ('site' for '{{site}}',
    '{{num:site}}' or '__{{site}}__'), or None if it is not a reference to
    a variable by name.
    """
    inner = expression[
        expression.index(VAR_OPENING_DELIMITER)
        + len(VAR_OPENING_DELIMITER) : expression.rindex(VAR_CLOSING_DELIMITER)
    ]
    match = _VARIABLE_REFERENCE.fullmatch(inner)
    return match.group(1) if match is not None else None


def _list_paths(paths: list[str], limit: int = 5) -> str:
    shown = ", ".join(f"'{path}'" for path in paths[:limit])
    more = f" and {len(paths) - limit} more" if len(paths) > limit else ""
    return shown + more


def _unsubstituted_references(
    data: dict | list, prefix: str = "", postfix: str = ""
) -> list[tuple[str, str, str]]:
    """
    The (expression, variable reference, property path) of every variable
    reference left in 'data' in the delimiters being substituted -- the
    Worker Pool ones for 'userData', as the passes use. The reference is the
    expression's variable name, or 'env:' and the environment variable's,
    without delimiters or type tag. An expression that is not a reference
    itself but contains one ('{{template_{{x}}}}') yields the one inside.

    Once the passes have settled, a reference to a defined variable is still
    there only if its value leads back to its own name, and any other names
    a variable nothing defines.
    """
    found: list[tuple[str, str, str]] = []

    def _check(value_: str, opening: str, closing: str, path: str):
        for expression in find_delimited_expressions(value_, opening, closing):
            inner = expression[len(opening) : -len(closing)]
            match = _VARIABLE_REFERENCE.fullmatch(inner)
            if match is not None:
                found.append((expression, match.group(1), path))
            elif opening in inner:
                _check(inner, opening, closing, path)

    def _walk_data(data: dict | list, path: str):
        items = (
            (
                (key_, f"{path}.{key_}" if path else str(key_), value_)
                for key_, value_ in data.items()
            )
            if isinstance(data, dict)
            else ((None, f"{path}[{index}]", item) for index, item in enumerate(data))
        )
        for key_, item_path, value_ in items:
            if isinstance(value_, str):
                if key_ == USERDATA:
                    opening, closing = WP_VARIABLES_PREFIX, WP_VARIABLES_POSTFIX
                else:
                    opening, closing = prefix, postfix
                opening += VAR_OPENING_DELIMITER
                closing = VAR_CLOSING_DELIMITER + closing
                if opening in value_:
                    _check(value_, opening, closing, item_path)
            elif isinstance(value_, (dict, list)):
                _walk_data(value_, item_path)

    _walk_data(data, "")
    return found


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
            f"^{re.escape(opening_delimiter)}"
            f"({'|'.join(re.escape(tag) for tag in _TYPE_TAGS)})"
            f"(?!{re.escape(TYPE_TAG_DEFAULT_GUARD)})",
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

        element_processed = cast(str, element_processed)
        if _is_whole_expression(
            element_processed, opening_delimiter, closing_delimiter
        ):
            # Its name was undefined once its nested parts were resolved:
            # passed through, tag and all, as an untyped one is, for a later
            # pass or the undefined-variable warning
            element_processed = (
                opening_delimiter
                + type_tag
                + element_processed[len(opening_delimiter) :]
            )
            if len(elements) == 1:
                return element_processed
            return_str += element_processed
            continue

        value = process_typed_variable_substitution(
            type_tag, element_processed, expression=element
        )
        if len(elements) == 1:
            # The only element: the value itself, of the tag's type
            return value
        return_str += _typed_value_as_text(type_tag, value, element_processed)

    return return_str


def _is_whole_expression(
    text: str, opening_delimiter: str, closing_delimiter: str
) -> bool:
    """
    Whether text is one delimited expression and nothing else.
    """
    return find_delimited_expressions(text, opening_delimiter, closing_delimiter) == [
        text
    ]


def process_untyped_variable_substitutions(
    input_string: str | None,
    opening_delimiter: str,
    closing_delimiter: str,
) -> str | None:
    """
    Substitute one untyped expression, '{{name}}', '{{name:=default}}',
    '{{name::}}' or any of them with 'env:' before the name, returning its
    value, its default, _UNSET for an unset one with neither, or else the
    expression with its nested parts resolved. Text that is not an expression
    (a piece of one's interior, when nested) is returned as it is.

    The expression is parsed before anything is substituted into it, so that
    a value -- a variable's, an environment variable's or a nested
    expression's -- is never read as the syntax: a value may contain ':=',
    '::' or the closing delimiter. Only the syntax written in the expression
    itself, outside any nested expression, counts.

    A nested expression is resolved first ('{{{{key_var}}}}', where key_var
    is 'x', looks up 'x'); an unset one stands as _UNSET_MARKER while the outer
    one is resolved, and if the marker survives -- the name was needed, or the
    default was used -- the outer one is unset too.
    """
    if input_string is None:
        return None
    if not (
        len(input_string) >= len(opening_delimiter) + len(closing_delimiter)
        and input_string.startswith(opening_delimiter)
        and input_string.endswith(closing_delimiter)
    ):
        return input_string

    inner = input_string[len(opening_delimiter) : -len(closing_delimiter)]
    unset = inner.endswith(VAR_UNSET_SUFFIX)
    if unset:
        inner = inner[: -len(VAR_UNSET_SUFFIX)]
    name_text, default_text = _split_default(
        inner, input_string, opening_delimiter, closing_delimiter
    )
    if unset and default_text is not None:
        raise ValueError(
            f"Malformed substitution '{input_string}': a default value"
            f" ('{VAR_DEFAULT_SEPARATOR}') and the unset suffix"
            f" ('{VAR_UNSET_SUFFIX}') cannot be combined; for a default that"
            " is itself unset if undefined, nest it:"
            f" '{opening_delimiter}<variable>{VAR_DEFAULT_SEPARATOR}"
            f"{opening_delimiter}<default>{VAR_UNSET_SUFFIX}{closing_delimiter}"
            f"{closing_delimiter}'"
        )

    name = _resolve_nested(name_text, opening_delimiter, closing_delimiter)
    value = _value_of(name)
    if value is None and default_text is not None:
        value = _resolve_nested(default_text, opening_delimiter, closing_delimiter)
    if value is None:
        if unset:
            return _UNSET  # type: ignore
        value = opening_delimiter + name + closing_delimiter

    if _UNSET_MARKER in value:
        return _UNSET  # type: ignore
    return value


def _split_default(
    inner: str, expression: str, opening_delimiter: str, closing_delimiter: str
) -> tuple[str, str | None]:
    """
    Split an expression's interior at its default separator into the name
    and the default (None if there is none), looking only outside any nested
    expression, since the separator is syntax only where it is written there.
    """
    positions: list[int] = []
    offset = 0
    for piece in _pieces(inner, opening_delimiter, closing_delimiter):
        if not piece.startswith(opening_delimiter):  # Not a nested expression
            found = piece.find(VAR_DEFAULT_SEPARATOR)
            while found != -1:
                positions.append(offset + found)
                found = piece.find(VAR_DEFAULT_SEPARATOR, found + 1)
        offset += len(piece)

    if not positions:
        return inner, None
    name = inner[: positions[0]]
    if len(positions) > 1 or name in ("", ENV_VAR_SUB_PREFIX):
        raise ValueError(
            f"Malformed '<variable>{VAR_DEFAULT_SEPARATOR}<default>' substitution:"
            f" '{expression}'"
        )
    return name, inner[positions[0] + len(VAR_DEFAULT_SEPARATOR) :]


def _resolve_nested(text: str, opening_delimiter: str, closing_delimiter: str) -> str:
    """
    Text with each expression nested in it substituted, an unset one standing
    as _UNSET_MARKER.
    """
    resolved = ""
    for piece in _pieces(text, opening_delimiter, closing_delimiter):
        result = process_untyped_variable_substitutions(
            piece, opening_delimiter, closing_delimiter
        )
        resolved += _UNSET_MARKER if result is _UNSET else cast(str, result)
    return resolved


def _pieces(text: str, opening_delimiter: str, closing_delimiter: str) -> list[str]:
    """
    Text split into its expressions and the text between them.
    """
    if opening_delimiter in text and closing_delimiter in text:
        return split_delimited_string(text, opening_delimiter, closing_delimiter)
    return [text]


def _value_of(name: str) -> str | None:
    """
    The value of a variable, or with 'env:' of an environment variable, or
    None if it is not defined.
    """
    if name.startswith(ENV_VAR_SUB_PREFIX):
        return os.getenv(name[len(ENV_VAR_SUB_PREFIX) :])
    if name in VARIABLE_SUBSTITUTIONS:
        return str(VARIABLE_SUBSTITUTIONS[name])
    return None


def process_typed_variable_substitution(
    type_string: str, input_string: str, expression: str | None = None
) -> str | int | bool | float | list | dict:
    """
    Convert the value of a type-tagged substitution to its type, raising
    ValueError if it is not one, naming the 'expression' where it is given.
    """
    converter = _TYPE_CONVERTERS.get(type_string)
    if converter is None:
        raise ValueError(f"Unknown variable type tag '{type_string}'")
    try:
        return converter(input_string)
    except ValueError as e:
        named = f"Cannot substitute '{expression}': " if expression else ""
        # format_yd_name()'s message names the value itself
        reason = (
            str(e) if type_string == FORMAT_NAME_TYPE_TAG else f"'{input_string}' {e}"
        )
        raise ValueError(named + reason) from e


def _typed_value_as_text(
    type_string: str, value: str | int | bool | float | list | dict, text: str
) -> str:
    """
    A typed value written into a longer string: as its JSON, as a variable's
    value of any other type is held (see _stringify()), but a number as it
    was written, so that '1.10' stays '1.10'. A name is already text.
    """
    if type_string == NUMBER_TYPE_TAG:
        return text.strip()
    return value if isinstance(value, str) else json_dumps(value)


def load_json_file_with_variable_substitutions(
    filename: str, prefix: str = "", postfix: str = ""
) -> dict:
    """
    Takes a JSON filename and returns a dictionary with its variable
    substitutions processed.

    The file is parsed first and its values substituted after, as a TOML
    file's are, rather than its text substituted before it is parsed: there a
    value was read through JSON's escapes (a default's '\\"' was not a
    quote) and inserted without them (a Windows path's '\\t' became a tab,
    a quote ended the string). So a substitution goes inside a JSON string,
    and in a value, not a property name.
    """
    opening = prefix + VAR_OPENING_DELIMITER
    closing = VAR_CLOSING_DELIMITER + postfix
    with open(filename) as f:
        file_contents = f.read()
    try:
        result = json_loads(file_contents)
    except JSONDecodeError as e:
        # The parser stops within the opening delimiter of one that is not
        # inside a string: at its first brace, or after it, taken for an object
        around_error = file_contents[
            max(0, e.pos - len(opening) + 1) : e.pos + len(opening)
        ]
        hint = (
            "; a variable substitution must be inside a JSON string,"
            f' e.g. "{opening}num:count{closing}"'
            if opening in around_error
            else ""
        )
        raise ValueError(f"Invalid JSON in '{filename}': {e}{hint}") from e

    names = _substituted_property_names(result, opening, closing)
    if names:
        raise ValueError(
            "Variable substitutions are made in property values, not property"
            f" names, in '{filename}': {_list_paths(names)}"
        )
    resolve_variables_insitu(result, prefix=prefix, postfix=postfix)
    return result


def _substituted_property_names(
    data: dict | list, opening_delimiter: str, closing_delimiter: str, path: str = ""
) -> list[str]:
    """
    The paths of the property names in 'data' that hold a substitution.
    """
    found: list[str] = []
    if isinstance(data, dict):
        children = []
        for key, value in data.items():
            key_path = f"{path}.{key}" if path else key
            if find_delimited_expressions(key, opening_delimiter, closing_delimiter):
                found.append(key_path)
            children.append((key_path, value))
    else:
        children = [(f"{path}[{index}]", item) for index, item in enumerate(data)]
    for child_path, child in children:
        if isinstance(child, (dict, list)):
            found += _substituted_property_names(
                child, opening_delimiter, closing_delimiter, child_path
            )
    return found


def load_jsonnet_file_with_variable_substitutions(
    filename: str,
    prefix: str = "",
    postfix: str = "",
    exit_on_dry_run=True,
) -> dict:
    """
    Takes a Jsonnet filename and returns a dictionary with its variable
    substitutions processed.
    """
    check_jsonnet_import()
    from _jsonnet import evaluate_file

    with VariableSubstitutedJsonnetFile(
        filename=filename,
        prefix=prefix,
        postfix=postfix,
    ) as preprocessed_filename:
        try:
            dict_data = json_loads(evaluate_file(preprocessed_filename))
        except RuntimeError as e:
            # Include only the first line of the exception message
            raise RuntimeError(str(e).partition("\n")[0])

    # Secondary processing after Jsonnet expansion
    resolve_variables_insitu(dict_data, prefix=prefix, postfix=postfix)

    if ARGS_PARSER.jsonnet_dry_run:
        print_dry_run(f"Printing Jsonnet to JSON conversion for '{filename}'")
        if ARGS_PARSER.json_output and not exit_on_dry_run:
            # A caller converting several files (yd-create, yd-remove): each
            # is one element of the '--json' document, printed at exit; a
            # copy, as the caller goes on to change what it was handed
            record(deepcopy(dict_data))
        else:
            print_json(dict_data)
        print_dry_run("Complete")
        if exit_on_dry_run:
            sys.exit(0)

    return dict_data


def load_toml_file_with_variable_substitutions(
    filename: str, prefix: str = "", postfix: str = ""
) -> dict:
    """
    Takes a TOML filename and returns a dictionary with its variable
    substitutions processed.
    """
    with open(filename, "rb") as f:
        config = toml_load(f)

    # Add any variable substitutions in the TOML file before processing the
    # file as a whole
    try:
        # Convert all values to strings before adding
        add_substitutions_from_config_file(
            {
                var_name: _stringify(var_value)
                for var_name, var_value in config[COMMON_SECTION][VARIABLES].items()
            },
            source=f"'[{COMMON_SECTION}.{VARIABLES}]' in '{filename}'",
        )
    except KeyError:
        pass

    resolve_variables_insitu(config, prefix=prefix, postfix=postfix)

    return config


def process_variable_substitutions_in_file_contents(
    file_contents: str,
    prefix: str = "",
    postfix: str = "",
    source: str | None = None,
    jsonnet: bool = False,
) -> str:
    """
    Process substitutions in the raw contents of a complete file, repeating
    the pass until one changes nothing, as resolve_variables_insitu() does:
    a substituted value that itself contains a variable reference is
    resolved too, and a circular reference raises ValueError, naming
    'source' (the file) where it is given. An unset ('::') token is left in
    place, for the in-situ processing of a parsed specification to remove.

    With 'jsonnet', the contents are Jsonnet code, and each substitution is
    read and written through the escaping of the string it is in (see
    _substitute_jsonnet_pass()); otherwise they are text, substituted as it.
    """
    label = source if source is not None else "file contents"
    opening = prefix + VAR_OPENING_DELIMITER
    closing = VAR_CLOSING_DELIMITER + postfix
    for _ in range(VAR_SUBSTITUTION_MAX_PASSES):
        substituted = (
            _substitute_jsonnet_pass(file_contents, prefix, postfix)
            if jsonnet
            else _substitute_file_contents_pass(file_contents, prefix, postfix)
        )
        if substituted == file_contents:
            break
        previous, file_contents = file_contents, substituted
    else:
        # Name what is still changing: the expressions the last pass made
        changing = sorted(
            set(find_delimited_expressions(file_contents, opening, closing))
            - set(find_delimited_expressions(previous, opening, closing))
        )
        expressions = f" ({', '.join(repr(e) for e in changing)})" if changing else ""
        raise ValueError(
            "Variable substitution did not settle after"
            f" {VAR_SUBSTITUTION_MAX_PASSES} passes, which suggests a circular"
            f" variable reference, in '{label}'{expressions}"
        )

    # A type-tagged expression inside a longer string is not substituted here
    # but left for the in-situ pass to substitute as text, so one still here
    # is not a sign of a circular reference
    _undefined_unless_circular(
        [
            reference
            for reference in _unsubstituted_references(
                {label: file_contents}, prefix=prefix, postfix=postfix
            )
            if not reference[0][len(opening) :].startswith(_TYPE_TAGS)
        ]
    )
    return file_contents


def _substitute_file_contents_pass(
    file_contents: str, prefix: str = "", postfix: str = ""
) -> str:
    """
    One substitution pass over the raw contents of a complete file.
    """
    # Found one expression at a time: a match running from the first opening
    # delimiter on a line to the last closing one took every expression on
    # the line as one, which lost a type-tagged value's type and, where the
    # line went on to close a JSON object ('}}'), failed on the delimiters
    v_expressions = dict.fromkeys(
        find_delimited_expressions(
            file_contents,
            prefix + VAR_OPENING_DELIMITER,
            VAR_CLOSING_DELIMITER + postfix,
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


# Jsonnet's string literals, each with the group its contents are in, and its
# comments, matched only so that a quote inside one opens no string. A text
# block's contents run from the line after its '|||' to the line before the
# one closing it
_JSONNET_LITERAL = re.compile(
    r"//[^\n]*|\#[^\n]*|/\*.*?\*/"
    r'|@"(?P<verbatim_double>(?:[^"]|"")*)"'
    r"|@'(?P<verbatim_single>(?:[^']|'')*)'"
    r'|"(?P<double>(?:[^"\\]|\\.)*)"'
    r"|'(?P<single>(?:[^'\\]|\\.)*)'"
    r"|\|\|\|-?[ \t]*\n(?P<block>.*?\n)[ \t]*\|\|\|",
    re.DOTALL,
)

# A text block's indentation, read from its first line
_INDENTATION = re.compile(r"[ \t]*")

# A double- or single-quoted string's escapes: JSON's, with '\\'' too
_JSONNET_ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|.)", re.DOTALL)
_JSONNET_ESCAPED = {
    '"': '"',
    "'": "'",
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


def _jsonnet_unescaped(kind: str, text: str) -> str:
    """
    Text from inside a Jsonnet string of the given kind, as what it stands for.
    """
    match kind:
        case "double" | "single":
            return _JSONNET_ESCAPE.sub(
                lambda m: (
                    chr(int(m[1][1:], 16))
                    if len(m[1]) == 5
                    else _JSONNET_ESCAPED.get(m[1], m[0])
                ),
                text,
            )
        case "verbatim_double":
            return text.replace('""', '"')
        case "verbatim_single":
            return text.replace("''", "'")
    return text  # A text block has no escapes


def _jsonnet_escaped(kind: str, text: str, indentation: str) -> str:
    """
    Text written for a Jsonnet string of the given kind: escaped, or in a
    text block indented as the block is on every line after its first.
    """
    match kind:
        case "double":
            return json_dumps(text)[1:-1]
        case "single":
            return json_dumps(text)[1:-1].replace("'", "\\'")
        case "verbatim_double":
            return text.replace('"', '""')
        case "verbatim_single":
            return text.replace("'", "''")
    return text.replace("\n", "\n" + indentation)


def _substitute_jsonnet_pass(
    file_contents: str, prefix: str = "", postfix: str = ""
) -> str:
    """
    One substitution pass over the code of a Jsonnet file, which is evaluated
    only once it is substituted, so it is the text that is substituted: each
    expression by its position, since what is written depends on where it is.

    Inside a string, an expression is read through the string's escapes and
    its value written back with them, so a path's backslashes, a quote, and a
    default's escaped JSON ('[\\"x\\"]') are themselves. A typed value is
    written as its JSON in place of the whole string when the expression is
    all of it, and otherwise left for the in-situ pass after evaluation to
    substitute as text, as the text pass leaves one. Outside a string, in the
    code, a value is written as it is, a typed one as its JSON: Jsonnet code.
    """
    opening = prefix + VAR_OPENING_DELIMITER
    closing = VAR_CLOSING_DELIMITER + postfix
    strings = [
        (
            match.lastgroup,
            match.start(match.lastgroup),
            match.end(match.lastgroup),
            match,
        )
        for match in _JSONNET_LITERAL.finditer(file_contents)
        if match.lastgroup is not None  # Not a comment
    ]
    starts = [start for _, start, _, _ in strings]

    # Substituted once each per pass, however often it appears: an expression
    # as written, with the kind of string it is in (None in the code)
    values: dict[tuple[str | None, str], object] = {}
    parts: list[str] = []
    position = 0
    for span in find_delimited_expression_spans(file_contents, opening, closing):
        if span.start < position:
            continue  # Inside a whole string already written as its value
        index = bisect_right(starts, span.start) - 1
        kind, content_start, content_end, literal = (
            strings[index] if index >= 0 else (None, 0, 0, None)
        )
        if kind is None or span.end > content_end:
            kind = None  # In the code, or across a string's end
        as_written = file_contents[span.start : span.end]
        expression = (
            _jsonnet_unescaped(kind, as_written) if kind is not None else as_written
        )
        if (kind, as_written) not in values:
            values[(kind, as_written)] = process_variable_substitutions(
                expression, prefix=prefix, postfix=postfix
            )
        value = values[(kind, as_written)]

        if value is _UNSET or value == expression:
            # Left as it is: the in-situ pass removes an unset one's property
            continue
        if kind is None:
            written = value if isinstance(value, str) else json_dumps(value)
            start, end = span.start, span.end
        elif isinstance(value, str):
            indentation = (
                _INDENTATION.match(file_contents, content_start).group()  # type: ignore[union-attr]
                if kind == "block"
                else ""
            )
            written = _jsonnet_escaped(kind, value, indentation)
            start, end = span.start, span.end
        elif (span.start, span.end) == (content_start, content_end) and kind != "block":
            assert literal is not None
            written = json_dumps(value)
            start, end = literal.start(), literal.end()
        else:
            continue
        parts += [file_contents[position:start], written]
        position = end

    parts.append(file_contents[position:])
    return "".join(parts)


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
            file_contents,
            self.prefix,
            self.postfix,
            source=self.filename,
            jsonnet=True,
        )
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, dir=os.getcwd()
        ) as temp_file:
            temp_file.write(processed_file_contents)
        self.temp_filename: str = temp_file.name
        return self.temp_filename

    def __exit__(self, exc_type, exc_val, exc_tb):
        os.remove(self.temp_filename)
