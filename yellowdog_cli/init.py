#!/usr/bin/env python3

"""
yd init: write a starter configuration file, config.toml in the current
directory or, with '--user', the user's own (paths.user_config_file()).

The [common] key, secret, namespace, tag and URL are asked for, each
offering its environment variable's value (YD_KEY, ...) for Enter to keep,
the secret typed unseen; '--yes' asks nothing and takes the environment's.
A value not given is written commented out, so the file says where it would
go. An existing file is refused before anything is asked, unless
'--overwrite'. A file holding a secret is written readable by its owner
alone. Standalone: it reads no configuration, which it exists to create.
"""

import json
import os
import sys
from dataclasses import dataclass

from yellowdog_cli.utils.atomic_write import write_text_atomically
from yellowdog_cli.utils.command_registry import COMMANDS, build_parser
from yellowdog_cli.utils.exit_codes import ExitCode
from yellowdog_cli.utils.interactive import NoAnswerToPrompt, ask
from yellowdog_cli.utils.invocation import selected_prog
from yellowdog_cli.utils.output_encoding import use_utf8_output
from yellowdog_cli.utils.output_settings import configure_output
from yellowdog_cli.utils.paths import is_user_config_file, user_config_file
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.settings import (
    CONFIG_FILE_NAME,
    DEFAULT_URL,
    YD_KEY,
    YD_NAMESPACE,
    YD_SECRET,
    YD_TAG,
    YD_URL,
)

# A file holding a secret: readable and writable by its owner alone
SECRET_FILE_MODE = 0o600


@dataclass(frozen=True)
class _Property:
    name: str  # in [common]
    question: str
    environment: str  # the variable whose value is offered
    secret: bool = False
    example: str = ""  # what a commented-out line shows


_PROPERTIES = (
    _Property("key", "Application key ID", YD_KEY),
    _Property("secret", "Application key secret", YD_SECRET, secret=True),
    _Property("namespace", "Namespace", YD_NAMESPACE),
    _Property("tag", "Tag", YD_TAG),
    _Property("url", "Platform API URL", YD_URL, example=DEFAULT_URL),
)

_HEADER = """\
# YellowDog CLI configuration, written by 'yd init'. Every property, in this
# section and the others, is described in the Configuration page of the
# documentation ('yd --docs' prints the link). Run 'yd doctor' to check it.

[common]
"""


def _offered(prop: _Property) -> str:
    """
    The question, with what Enter keeps: the environment's value, named but
    not shown for a secret.
    """
    value = os.environ.get(prop.environment)
    if not value:
        return f"{prop.question} (Enter for none):"
    shown = (
        f"{prop.environment}'s" if prop.secret else f"'{value}', {prop.environment}'s"
    )
    return f"{prop.question} (Enter for {shown}):"


def _values(yes: bool) -> dict[str, str]:
    """
    Each property's value, asked for or, with 'yes', the environment's;
    those given none left out.
    """
    values = {}
    for prop in _PROPERTIES:
        offered = os.environ.get(prop.environment, "")
        answer = "" if yes else ask(_offered(prop), secret=prop.secret)
        value = answer or offered
        if value:
            values[prop.name] = value
    return values


def configuration_text(values: dict[str, str]) -> str:
    """
    The file: the [common] values given, as TOML strings (JSON's escapes are
    TOML's), and a commented-out line for each not given.
    """
    lines = [
        f"{prop.name} = {json.dumps(values[prop.name])}"
        if prop.name in values
        else f"# {prop.name} = {json.dumps(prop.example)}"
        for prop in _PROPERTIES
    ]
    return _HEADER + "\n".join(lines) + "\n"


def main() -> None:
    use_utf8_output()
    parser = build_parser(COMMANDS["yd-init"], prog=selected_prog("yd-init"))
    args = parser.parse_args()
    configure_output(args)

    path = user_config_file() if args.user else CONFIG_FILE_NAME
    if os.path.exists(path) and not args.overwrite:
        print_error(f"'{path}' exists: '--overwrite' replaces it")
        sys.exit(ExitCode.FAILURE)

    try:
        values = _values(args.yes)
    except NoAnswerToPrompt as e:
        print_error(f"{e}; nothing was written")
        sys.exit(ExitCode.FAILURE)
    except KeyboardInterrupt:
        print_error("Cancelled; nothing was written")
        sys.exit(ExitCode.INTERRUPTED)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    write_text_atomically(
        path,
        configuration_text(values),
        mode=SECRET_FILE_MODE if "secret" in values else None,
    )
    print_info(f"Wrote '{path}'; run 'yd doctor' to check it")
    if is_user_config_file(path) and os.path.isfile(CONFIG_FILE_NAME):
        print_warning(
            f"The {CONFIG_FILE_NAME} in this directory is read in its place here"
        )


if __name__ == "__main__":
    main()
