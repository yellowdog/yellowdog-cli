"""
Decorator to handle standard setup, shutdown and exception handling
for all commands.

CLIENT is built the first time it is asked for, by the module __getattr__:
importing the SDK at all builds the whole Platform client (~140ms), and a
command that never uses it -- yd-variables -- need not pay for it. Every
other command imports CLIENT by name, so for them it is built at import,
exactly as before. The User-Agent is applied as it is built, before any
request can be made, and pypac and 'requests' are imported only when used.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.command_runner import describe_error, run_command
from yellowdog_cli.utils.config_types import ConfigCommon
from yellowdog_cli.utils.exit_codes import (
    ExitCode,
    classify,
)
from yellowdog_cli.utils.load_config import (
    load_config_common,
)
from yellowdog_cli.utils.printing import print_debug
from yellowdog_cli.utils.spec_properties import ALL_CONFIG_SECTIONS

if TYPE_CHECKING:
    from yellowdog_client import PlatformClient

    CLIENT: PlatformClient

# Strict, so a missing key or secret exits, for every command that uses the
# Platform; yd-variables, which never does, runs without them
CONFIG_COMMON: ConfigCommon = load_config_common(
    strict=ARGS_PARSER.credentials_required
)


def _create_client() -> PlatformClient:
    """
    Build the Platform client, and keep it as this module's CLIENT, so that
    it is built once and the wrapper closes it.
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
    globals()["CLIENT"] = client
    return client


def __getattr__(name: str) -> PlatformClient:
    if name == "CLIENT":
        return _create_client()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _close_client() -> None:
    """Close CLIENT if it was ever built (or a test put one there)."""
    client = globals().get("CLIENT")
    if client is not None:
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
        run_command(
            func,
            args=ARGS_PARSER,
            config_sections=ALL_CONFIG_SECTIONS,
            before=set_proxy,
            after=_close_client,
            describe=_describe,
        )

    return wrapper
