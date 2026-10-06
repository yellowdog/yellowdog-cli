#!/usr/bin/env python3

"""
Command to report the processed values of variable substitutions.
"""

from dataclasses import dataclass, field

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.dataclient.rclone import is_inline_remote, shown_remote
from yellowdog_cli.utils.output_style import REDACTED_VALUE
from yellowdog_cli.utils.printing import print_json, print_warning
from yellowdog_cli.utils.property_names import (
    DATA_CLIENT_REMOTE,
    DATA_CLIENT_SECTION,
    KEY,
    SECRET,
)
from yellowdog_cli.utils.variable_substitution import (
    explain_unset_variable,
    get_all_user_variables,
    get_unset_variable_names,
    get_user_variable,
    warn_of_undefined_variables,
)
from yellowdog_cli.utils.variable_syntax import SECRET_VARIABLE_NAME_PATTERN
from yellowdog_cli.utils.wrapper import main_wrapper

# The credential variables the CLI injects into the substitution table itself:
# load_config_common() adds these two alongside 'url', 'namespace' and 'tag'.
# They're the only ones that can be *known* to be credentials.
#
# Beyond them, the report also redacts every variable whose name matches
# SECRET_VARIABLE_NAME_PATTERN (variable_syntax.py). Name-pattern redaction
# was once rejected because it catches identifiers, misses badly-named
# secrets, and would read as a guarantee the command cannot keep. That
# objection was to a *silent* heuristic: this one is applied visibly, the
# command printing the count and the pattern itself whenever it redacts by it,
# and saying that everything else is shown in full -- so what is withheld, and
# what is not, is stated rather than implied.
#
# The one other thing the CLI can *know* is that an inline rclone connection
# string carries credentials in its parameters: it registers the
# {{dataClient.*.remote}} variables itself, and the rclone parser knows which
# part of the string the parameters are. Those are shown as yd-doctor shows
# them -- name, type and provider, the rest withheld -- under the same rule:
# not under --show-secrets. The same holds of any
# other variable whose *value* is an inline connection string (a user-defined
# 'remote_with_keys', say), since what makes the parameters credentials is the
# shape of the value, not who registered it; is_inline_remote() recognises
# the shape strictly, so an ordinary comma-separated value is left alone. Like
# the name pattern, it is stated whenever it withholds anything from a
# variable the CLI did not register itself.
#
# All of it applies to a variable named on the command line too. Naming one
# once reported it in full, as an explicit request for it; but the MCP
# server withholds --show-secrets from its tools so that a credential held
# in the configuration cannot be asked back out through a tool result, and
# naming 'secret' did exactly that. --show-secrets is now the one way to see
# a redacted value, named or not.
SECRET_VARIABLES = (KEY, SECRET)


def matches_secret_name_pattern(name: str) -> bool:
    """
    Whether 'name' is redacted in the report as looking like a
    credential, rather than as one of SECRET_VARIABLES.
    """
    return name not in SECRET_VARIABLES and bool(
        SECRET_VARIABLE_NAME_PATTERN.search(name)
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


@dataclass
class Report:
    """
    What the command reports: the variables, and which of them it redacted
    by name pattern, or withheld the parameters of as inline rclone
    connection strings the CLI did not register itself, for its notes.
    """

    variables: dict
    by_pattern: list[str] = field(default_factory=list)
    by_value: list[str] = field(default_factory=list)
    credentials: list[str] = field(default_factory=list)


def report_variables(variable_names: list[str], show_secrets: bool = False) -> Report:
    """
    The processed values of the named variables, in alphabetical order by name.
    All variables are reported if no name is supplied.

    A name that isn't the name of a variable reports 'null' rather than being
    an error or being left out: the question 'is this variable set?' is one of
    the things this command exists to answer. The full report includes 'key'
    and 'secret' as 'null' when they are not configured, which this command
    alone of those using the Platform's configuration does not require.

    Unless 'show_secrets' is set, the values of SECRET_VARIABLES and of every
    variable whose name matches SECRET_VARIABLE_NAME_PATTERN are redacted,
    and the parameters of every value that is an inline rclone connection
    string withheld (see is_inline_remote() and shown_remote()) -- whether
    the variable is named or not, so that naming one is no way round the
    redaction for a caller that cannot pass --show-secrets (the MCP server's
    tools).
    """
    if variable_names:
        variables = {name: get_user_variable(name) for name in variable_names}
    else:
        variables = get_all_user_variables()
        for name in SECRET_VARIABLES:
            variables.setdefault(name, None)
    report = Report(dict(sorted(variables.items())))
    if show_secrets:
        return report

    for name, value in report.variables.items():
        if value is None:
            continue
        if name in SECRET_VARIABLES:
            report.variables[name] = REDACTED_VALUE
            report.credentials.append(name)
        elif matches_secret_name_pattern(name):
            report.variables[name] = REDACTED_VALUE
            report.by_pattern.append(name)
        elif isinstance(value, str) and (
            is_remote_variable(name) or is_inline_remote(value)
        ):
            report.variables[name] = shown_remote(value)
            if not is_remote_variable(name) and report.variables[name] != value:
                report.by_value.append(name)
    return report


@main_wrapper
def main(ctx: RunContext):
    # Like yd-show, whose output is also always JSON, the warnings and the
    # wrapper's trailing 'Done' are printed around it unless '--quiet' is
    # given, which is how a caller needing the JSON alone asks for it (as
    # Commander does)
    variable_names = ctx.args.variable_names
    report = report_variables(variable_names, show_secrets=bool(ctx.args.show_secrets))
    # A redacted value is REDACTED_VALUE here, and so carries no reference
    # to check. 'key' and 'secret', which --show-secrets reports in full, are
    # left out of the check by name
    warn_of_undefined_variables(
        {
            name: value
            for name, value in report.variables.items()
            if name not in SECRET_VARIABLES and value is not None
        }
    )
    explain_unset_variables(variable_names)
    warn_of_variables_not_defined(variable_names)
    if variable_names and report.credentials:
        print_warning(
            f"Redacted {', '.join(repr(name) for name in report.credentials)}:"
            " --show-secrets reports them."
        )
    if report.by_pattern:
        print_warning(
            f"Redacted {len(report.by_pattern)} variable(s) whose names"
            f" match '{SECRET_VARIABLE_NAME_PATTERN.pattern}' (case-insensitive);"
            " everything else is shown in full. --show-secrets reports all."
        )
    if report.by_value:
        print_warning(
            f"Withheld the parameters of {len(report.by_value)} variable(s) holding an"
            " inline rclone connection string, keeping its name, type and"
            " provider. --show-secrets reports all."
        )
    print_json(report.variables)


def warn_of_variables_not_defined(variable_names: list[str]) -> None:
    """
    Say that a variable asked for by name was never defined: its 'null'
    would otherwise read just as an unset one's does, which is explained.
    """
    for name in dict.fromkeys(variable_names):
        if get_user_variable(name) is None and name not in get_unset_variable_names():
            print_warning(f"Variable '{name}' is not defined")


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


# Entry point
if __name__ == "__main__":
    main()
