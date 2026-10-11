"""
Running a noun command: 'yd-workrequirement submit ...' runs yd-submit's
main() with the derived command for the noun and verb selected
(noun_registry.py), so that its parser is the verb's: its prog the form
invoked, its options narrowed to the object, the verb's fixed arguments
supplied ahead of the user's.

Only the verb's command module is imported, so a noun imports nothing the
command it runs would not: 'yd-data ls' loads no SDK, as yd-ls does not.
"""

import sys
from importlib import import_module
from typing import NoReturn

from yellowdog_cli.utils.args import docs, invoked_name, select_command
from yellowdog_cli.utils.command_registry import command_module
from yellowdog_cli.utils.exit_codes import ExitCode
from yellowdog_cli.utils.noun_registry import NOUNS_BY_NAME, Noun


def _usage(invoked: str) -> str:
    return f"usage: {invoked} <verb> [options]"


def noun_help(noun: Noun, invoked: str) -> str:
    """
    A noun's help: its usage, what it does, its verbs and what each does.
    """
    width = max(len(verb.name) for verb in noun.verbs)
    lines = [_usage(invoked), "", f"{noun.summary}."]
    if noun.alias is not None:
        lines.append(f"'{noun.alias}' is short for '{noun.name}'.")
    lines += ["", "verbs:"]
    lines += [f"  {verb.name:<{width}}  {verb.summary}" for verb in noun.verbs]
    lines += ["", f"Run '{invoked} <verb> --help' for a verb's options."]
    return "\n".join(lines)


def _refuse(invoked: str, noun: Noun, message: str) -> NoReturn:
    # As argparse words a usage error, and with its exit code
    print(_usage(invoked), file=sys.stderr)
    print(
        f"{invoked}: error: {message}; choose from:"
        f" {', '.join(verb.name for verb in noun.verbs)}",
        file=sys.stderr,
    )
    sys.exit(ExitCode.USAGE)


def run_noun(noun_name: str) -> None:
    """
    Run the verb sys.argv[1] names on the noun 'noun_name', with the rest of
    the command line as its arguments.
    """
    noun = NOUNS_BY_NAME[noun_name]
    # The noun as invoked, its alias included; 'python -m' gives a module
    # file, shown as the noun's full name
    invoked = invoked_name(sys.argv[0])
    if invoked not in noun.invoked_names():
        invoked = noun.name

    arguments = sys.argv[1:]
    if not arguments:
        print(noun_help(noun, invoked), file=sys.stderr)
        sys.exit(ExitCode.USAGE)
    if arguments[0] in ("-h", "--help"):
        print(noun_help(noun, invoked))
        sys.exit(ExitCode.SUCCESS)
    if arguments[0] == "--docs":
        docs()
        sys.exit(ExitCode.SUCCESS)

    verb = noun.verb(arguments[0])
    if verb is None:
        if arguments[0].startswith("-"):
            _refuse(invoked, noun, f"a verb must come before '{arguments[0]}'")
        _refuse(invoked, noun, f"unknown verb '{arguments[0]}'")

    select_command(f"{noun.name} {verb.name}", f"{invoked} {verb.name}")
    sys.argv = [sys.argv[0], *verb.fixed, *arguments[1:]]
    module = command_module(verb.command)
    assert module is not None, f"{verb.command} has no module"
    import_module(module).main()
