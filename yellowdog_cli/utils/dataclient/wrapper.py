"""
Decorator for data client commands (yd-upload, yd-download, yd-delete, yd-ls
and yd-copy). Runs as main_wrapper does (command_runner.py), but
builds no PlatformClient and sets no proxy, so the commands run without
YellowDog API credentials, and checks only the configuration sections they
read.
"""

import functools
import inspect
from collections.abc import Callable
from typing import Any

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.command_runner import prepare_run, run_command
from yellowdog_cli.utils.context import DataClientContext
from yellowdog_cli.utils.specs.properties import DATA_CLIENT_CONFIG_SECTIONS


def dataclient_wrapper(func: Callable[..., Any]) -> Callable[[], None]:
    """
    Run a data client command's main(), passing it a DataClientContext if it
    takes one (main(ctx)); see context.py.
    """
    takes_context = len(inspect.signature(func).parameters) == 1

    def wrapper() -> None:
        # ARGS_PARSER is looked up as the command runs, so that a test's
        # patch of it is the one used
        prepare_run(func, ARGS_PARSER)
        run_command(
            (
                functools.partial(func, DataClientContext(ARGS_PARSER))
                if takes_context
                else func
            ),
            args=ARGS_PARSER,
            config_sections=DATA_CLIENT_CONFIG_SECTIONS,
        )

    return wrapper
