#!/usr/bin/env python3

"""
Command to report the processed values of variable substitutions.
"""

from yellowdog_cli.utils.printing import print_json, print_warning
from yellowdog_cli.utils.property_names import (
    DATA_CLIENT_REMOTE,
    DATA_CLIENT_SECTION,
    KEY,
    SECRET,
)
from yellowdog_cli.utils.rclone_utils import shown_remote
from yellowdog_cli.utils.settings import (
    REDACTED_VALUE,
    SECRET_VARIABLE_NAME_PATTERN,
)
from yellowdog_cli.utils.variables import (
    explain_unset_variable,
    get_all_user_variables,
    get_unset_variable_names,
    get_user_variable,
    warn_of_undefined_variables,
)
from yellowdog_cli.utils.wrapper import ARGS_PARSER, main_wrapper

# The credential variables the CLI injects into the substitution table itself:
# load_config_common() adds these two alongside 'url', 'namespace' and 'tag'.
# They're the only ones that can be *known* to be credentials.
#
# Beyond them, the full report also redacts every variable whose name matches
# SECRET_VARIABLE_NAME_PATTERN (settings.py). Name-pattern redaction was once
# rejected because it catches identifiers, misses badly-named secrets, and
# would read as a guarantee the command cannot keep. That objection was to a
# *silent* heuristic: this one is applied visibly, the command printing the
# count and the pattern itself whenever it redacts by it, and saying that
# everything else is shown in full -- so what is withheld, and what is not, is
# stated rather than implied.
#
# The one other thing the CLI can *know* is that an inline rclone connection
# string carries credentials in its parameters: it registers the
# {{dataClient.*.remote}} variables itself, and the rclone parser knows which
# part of the string the parameters are. Those are shown as yd-doctor shows
# them -- name, type and provider, the rest withheld -- under the same rule:
# in the full report only, and not under --show-secrets.
SECRET_VARIABLES = (KEY, SECRET)


def matches_secret_name_pattern(name: str) -> bool:
    """
    Whether 'name' is redacted in the full report as looking like a
    credential, rather than as one of SECRET_VARIABLES.
    """
    return name not in SECRET_VARIABLES and bool(
        SECRET_VARIABLE_NAME_PATTERN.search(name)
    )


def redacted_by_pattern(variable_names: list[str], show_secrets: bool) -> list[str]:
    """
    The variables the report redacts by SECRET_VARIABLE_NAME_PATTERN: none
    when variables are named or 'show_secrets' is set.
    """
    if variable_names or show_secrets:
        return []
    return sorted(
        name for name in get_all_user_variables() if matches_secret_name_pattern(name)
    )


def is_remote_variable(name: str) -> bool:
    """
    Whether 'name' is one of the {{dataClient.remote}} or
    {{dataClient.<profile>.remote}} variables the CLI registers.
    """
    return name == f"{DATA_CLIENT_SECTION}.{DATA_CLIENT_REMOTE}" or (
        name.startswith(f"{DATA_CLIENT_SECTION}.")
        and name.endswith(f".{DATA_CLIENT_REMOTE}")
    )


@main_wrapper
def main():
    # Like yd-show, whose output is also always JSON, the warnings and the
    # wrapper's trailing 'Done' are printed around it unless '--quiet' is
    # given, which is how a caller needing the JSON alone asks for it (as
    # Commander does)
    show_secrets = bool(ARGS_PARSER.show_secrets)
    variables = report_variables(ARGS_PARSER.variable_names, show_secrets=show_secrets)
    by_pattern = redacted_by_pattern(ARGS_PARSER.variable_names, show_secrets)
    # A value redacted by the pattern is already REDACTED_VALUE here, and so
    # carries no reference to check. 'key' and 'secret', which --show-secrets
    # reports in full, are left out of the check by name
    warn_of_undefined_variables(
        {
            name: value
            for name, value in variables.items()
            if name not in SECRET_VARIABLES
        }
    )
    explain_unset_variables(ARGS_PARSER.variable_names)
    if by_pattern:
        print_warning(
            f"Redacted {len(by_pattern)} variable(s) whose names match"
            f" '{SECRET_VARIABLE_NAME_PATTERN.pattern}' (case-insensitive);"
            " everything else is shown in full. --show-secrets reports all."
        )
    print_json(variables)


def explain_unset_variables(variable_names: list[str]) -> None:
    """
    Say why each variable asked for -- every variable, if none is named --
    was defined and yet has no value, because the '::' unset syntax removed
    it. Otherwise a named one reports 'null' exactly as one never defined
    does, and one of every variable is simply missing from the report.
    """
    names = variable_names if variable_names else get_unset_variable_names()
    for name in dict.fromkeys(names):
        if name in SECRET_VARIABLES:
            continue
        explanation = explain_unset_variable(name)
        if explanation is not None:
            print_warning(explanation)


def report_variables(variable_names: list[str], show_secrets: bool = False) -> dict:
    """
    The processed values of the named variables, in alphabetical order by name.
    All variables are reported if no name is supplied.

    A name that isn't the name of a variable reports 'null' rather than being
    an error or being left out: the question 'is this variable set?' is one of
    the things this command exists to answer.

    Reporting every variable redacts the values of SECRET_VARIABLES and of
    every variable whose name matches SECRET_VARIABLE_NAME_PATTERN, and
    withholds the parameters of an inline rclone remote (see shown_remote())
    unless 'show_secrets' is set; naming one reports it either way, a name
    being an explicit request for that variable.
    """
    if variable_names:
        variables = {name: get_user_variable(name) for name in variable_names}
    else:
        variables = get_all_user_variables()
        if not show_secrets:
            for name in variables:
                if name in SECRET_VARIABLES or matches_secret_name_pattern(name):
                    variables[name] = REDACTED_VALUE
            for name, value in variables.items():
                if is_remote_variable(name) and isinstance(value, str):
                    variables[name] = shown_remote(value)

    return dict(sorted(variables.items()))


# Entry point
if __name__ == "__main__":
    main()
