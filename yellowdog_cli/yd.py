#!/usr/bin/env python3

"""
yd: the YellowDog CLI. The word after 'yd' names a noun, whose verb follows
('yd wr submit'), or a command ('yd list', 'yd doctor'); see
utils/top_level.py. Only the module that word runs is imported.
"""

import sys
from importlib import import_module
from typing import NoReturn

from yellowdog_cli.utils.command_registry import command_module
from yellowdog_cli.utils.exit_codes import ExitCode
from yellowdog_cli.utils.invocation import select_command
from yellowdog_cli.utils.noun_dispatch import run_noun
from yellowdog_cli.utils.output_encoding import use_utf8_output
from yellowdog_cli.utils.suggestions import did_you_mean
from yellowdog_cli.utils.top_level import TOP_LEVEL, Kind

_USAGE = "usage: yd <command> [<verb>] [options]"


def _refuse(message: str, word: str | None = None) -> NoReturn:
    # As argparse words a usage error, and with its exit code: the command
    # meant by a misspelt 'word', where one is close, else them all
    suggestion = None if word is None else did_you_mean(word, TOP_LEVEL)
    print(_USAGE, file=sys.stderr)
    print(
        f"yd: error: {message}; "
        + (suggestion or f"choose from: {', '.join(sorted(TOP_LEVEL))}"),
        file=sys.stderr,
    )
    sys.exit(ExitCode.USAGE)


def _listing(stderr: bool) -> None:
    from yellowdog_cli.help import print_listing

    print_listing(stderr=stderr)


def main() -> None:
    use_utf8_output()
    arguments = sys.argv[1:]
    if not arguments:
        _listing(stderr=True)
        sys.exit(ExitCode.USAGE)
    word = arguments[0]
    if word in ("-h", "--help"):
        _listing(stderr=False)
        sys.exit(ExitCode.SUCCESS)
    if word == "--docs":
        from yellowdog_cli.utils.args import docs

        docs()
        sys.exit(ExitCode.SUCCESS)
    entry = TOP_LEVEL.get(word)
    if entry is None:
        if word.startswith("-"):
            _refuse(f"a command must come before '{word}'")
        _refuse(f"unknown command '{word}'", word)

    sys.argv = [sys.argv[0], *arguments[1:]]
    if entry.kind is Kind.NOUN:
        run_noun(entry.target, invoked=f"yd {word}")
        return
    select_command(entry.target, f"yd {word}")
    module = command_module(entry.target)
    assert module is not None, f"{entry.target} has no module"
    import_module(module).main()


if __name__ == "__main__":
    main()
