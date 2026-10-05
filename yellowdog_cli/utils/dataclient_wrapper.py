"""
Decorator for data client commands (yd-upload, yd-download, yd-delete/yd-rm,
yd-ls and yd-copy). Runs as main_wrapper does (command_runner.py), but
builds no PlatformClient and sets no proxy, so the commands run without
YellowDog API credentials, and checks only the configuration sections they
read.
"""

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.command_runner import run_command
from yellowdog_cli.utils.spec_properties import DATA_CLIENT_CONFIG_SECTIONS


def dataclient_wrapper(func):
    def wrapper():
        # ARGS_PARSER is looked up as the command runs, so that a test's
        # patch of it is the one used
        run_command(func, args=ARGS_PARSER, config_sections=DATA_CLIENT_CONFIG_SECTIONS)

    return wrapper
