"""
Decorator to handle standard setup, shutdown and exception handling
for all commands.

CONFIG_COMMON and CLIENT are each built on first use (see lazy.py), so
importing this module, or a command module naming them, reads no
configuration and builds no client. The wrapper builds CONFIG_COMMON, and
whatever else the command's module holds lazily, before the command runs
(command_runner.prepare_run()), so a broken configuration still exits
before it starts; CLIENT is left to the command's first use of it, since
importing the SDK at all builds the whole Platform client (~140ms) and a
command that never uses it -- yd-variables -- need not pay for it. The
User-Agent is applied as it is built, before any request can be made, and
pypac and 'requests' are imported only when used.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.command_runner import describe_error, prepare_run, run_command
from yellowdog_cli.utils.config_types import ConfigCommon
from yellowdog_cli.utils.exit_codes import (
    ExitCode,
    classify,
)
from yellowdog_cli.utils.lazy import built, lazy
from yellowdog_cli.utils.load_config import (
    load_config_common,
)
from yellowdog_cli.utils.printing import print_debug
from yellowdog_cli.utils.spec_properties import ALL_CONFIG_SECTIONS

if TYPE_CHECKING:
    from yellowdog_client import PlatformClient

# Strict, so a missing key or secret exits, for every command that uses the
# Platform; yd-variables, which never does, runs without them
CONFIG_COMMON: ConfigCommon = lazy(
    lambda: load_config_common(strict=ARGS_PARSER.credentials_required)
)


def _create_client() -> PlatformClient:
    """
    Build the Platform client, as CLIENT's first use does.
    """
    from yellowdog_client import PlatformClient
    from yellowdog_client.model import ApiKey, ServicesSchema

    from yellowdog_cli.utils.user_agent import set_user_agent

    # Apply the CLI's User-Agent to all outgoing HTTP requests (SDK and
    # direct) before the client is created or any request is made: every
    # command that makes a request imports CLIENT
    set_user_agent()
    # A strict load, which every command using the client has, never
    # returns None for either
    assert CONFIG_COMMON.key is not None and CONFIG_COMMON.secret is not None
    client = PlatformClient.create(
        ServicesSchema(defaultUrl=CONFIG_COMMON.url),
        ApiKey(CONFIG_COMMON.key, CONFIG_COMMON.secret),
    )
    return client


# Built on the command's first use of it, never by prepare_run()
CLIENT: PlatformClient = lazy(_create_client, prepare=False)


def _close_client() -> None:
    """Close CLIENT if it was ever built (or a test put one there)."""
    client = globals().get("CLIENT")
    if client is not None and built(client):
        client.close()


def set_proxy():
    """
    Set the HTTPS proxy using autoconfiguration (PAC) if enabled: under
    --dry-run too, since most dry runs call the platform (to list what they
    would act on, or to resolve a template's name).
    """
    proxy_var = "HTTPS_PROXY"
    if CONFIG_COMMON.use_pac:
        from pypac import pac_context_for_url

        from yellowdog_cli.utils.user_agent import set_default_user_agent

        # The PAC file is fetched with 'requests', as the CLI's own request;
        # the baseline only, which imports no SDK (yd-variables uses none)
        set_default_user_agent()
        print_debug("Using Proxy Auto-Configuration (PAC)")
        with pac_context_for_url(CONFIG_COMMON.url):
            https_proxy = os.getenv(proxy_var, None)
        if https_proxy is not None:
            os.environ[proxy_var] = https_proxy
        else:
            print_debug("No PAC proxy settings found")
    else:
        https_proxy = os.getenv(proxy_var, None)
    if https_proxy is not None:
        print_debug(f"Using {proxy_var}={https_proxy}")


def _describe(error: Exception) -> str:
    """
    An error as an API command reports it: a permission or credential
    failure in words saying what to check, chosen by classify(), which
    decides the exit code too, so the message and the code agree.
    """
    code = classify(error)
    if code == ExitCode.PERMISSION:
        return (
            "Your Application does not have the required permissions to"
            " perform the requested operation. Please check that the"
            " Application belongs to the required group(s), e.g.,"
            f" 'administrators', with roles in the required namespace(s): {error}"
        )
    if code == ExitCode.AUTHENTICATION:
        return f"Your Application Key ID and SECRET are not recognised: {error}"
    return describe_error(error)


def main_wrapper(func):
    def wrapper():
        # ARGS_PARSER and set_proxy are looked up as the command runs, so
        # that a test's patch of either is the one used
        prepare_run(func, ARGS_PARSER, CONFIG_COMMON)
        run_command(
            func,
            args=ARGS_PARSER,
            config_sections=ALL_CONFIG_SECTIONS,
            before=set_proxy,
            after=_close_client,
            describe=_describe,
        )

    return wrapper
