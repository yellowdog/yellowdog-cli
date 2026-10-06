"""
What a command runs with, passed to it rather than read from module globals:
its command line, the [common] configuration, and the Platform client.

main_wrapper builds a RunContext and passes it to main(ctx), from the same
ARGS_PARSER, CONFIG_COMMON and CLIENT a command would otherwise import; the
client is still built on first use (see lazy.py). dataclient_wrapper passes
a DataClientContext, the command line alone. A command reads them from its
context, and passes it on to the code it calls, so that a test can run that
code with a context of its own rather than by patching each module's
globals. A command's own configuration sections (CONFIG_WR, CONFIG_WP,
CONFIG_DATA_CLIENT) stay its module's, built lazily. Printing and the
interactive prompts still read ARGS_PARSER themselves.

Imports nothing that does work: the types are for type checking only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yellowdog_client import PlatformClient

    from yellowdog_cli.utils.args import CLIParser
    from yellowdog_cli.utils.config_types import ConfigCommon


@dataclass(frozen=True)
class RunContext:
    args: CLIParser
    config: ConfigCommon
    client: PlatformClient


@dataclass(frozen=True)
class DataClientContext:
    """
    What a data client command runs with (dataclient_wrapper): its command
    line. It uses no Platform client and no [common] configuration, and its
    [dataClient] section is its module's own, as a command's sections are.
    """

    args: CLIParser
