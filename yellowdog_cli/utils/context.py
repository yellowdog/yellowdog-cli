"""
What a command runs with, passed to it rather than read from module globals:
its command line, the [common] configuration, and the Platform client.

main_wrapper builds a RunContext and passes it to a main() that takes one
(main(ctx)), from the same ARGS_PARSER, CONFIG_COMMON and CLIENT a command
would otherwise import; the client is still built on first use (see
lazy.py). A command taking a context reads them from it, and passes it on
to the code it calls, so that a test can run that code with a context of
its own rather than by patching each module's globals. The commands move
to it one at a time; the action commands came first. Printing and
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
