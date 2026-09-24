#!/usr/bin/env python3

"""
Command to report the processed values of variable substitutions.
"""

from yellowdog_cli.utils.printing import print_json, print_warning
from yellowdog_cli.utils.property_names import KEY, SECRET
from yellowdog_cli.utils.settings import REDACTED_VALUE
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
# They're the only ones that can be known to be credentials, so they're the only
# ones redacted -- a user-defined variable holding a credential is reported in
# full, because nothing here can tell it from any other variable, and guessing
# from the name would be a guarantee the command cannot keep.
SECRET_VARIABLES = (KEY, SECRET)


@main_wrapper
def main():
    # Like yd-show, whose output is also always JSON, the warnings and the
    # wrapper's trailing 'Done' are printed around it unless '--quiet' is
    # given, which is how a caller needing the JSON alone asks for it (as
    # Commander does)
    variables = report_variables(
        ARGS_PARSER.variable_names, show_secrets=bool(ARGS_PARSER.show_secrets)
    )
    warn_of_undefined_variables(
        {
            name: value
            for name, value in variables.items()
            if name not in SECRET_VARIABLES
        }
    )
    explain_unset_variables(ARGS_PARSER.variable_names)
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

    Reporting every variable redacts the values of SECRET_VARIABLES unless
    'show_secrets' is set; naming one reports it either way, a name being an
    explicit request for that variable.
    """
    if variable_names:
        variables = {name: get_user_variable(name) for name in variable_names}
    else:
        variables = get_all_user_variables()
        if not show_secrets:
            for name in SECRET_VARIABLES:
                if name in variables:
                    variables[name] = REDACTED_VALUE

    return dict(sorted(variables.items()))


# Entry point
if __name__ == "__main__":
    main()
