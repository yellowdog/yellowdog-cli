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
from sys import exit
from typing import TYPE_CHECKING

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.config_types import ConfigCommon
from yellowdog_cli.utils.exit_codes import (
    MISSING_PERMISSION_TEXT,
    UNAUTHORIZED_TEXT,
    classify,
)
from yellowdog_cli.utils.load_config import (
    load_config_common,
    warn_of_config_violations,
    warn_of_undefined_config_variables,
)
from yellowdog_cli.utils.printing import print_debug, print_error, print_info
from yellowdog_cli.utils.results import (
    any_failed,
    flush_results,
    flush_results_after_failure,
)
from yellowdog_cli.utils.schema_cache import report_problems_to
from yellowdog_cli.utils.settings import ExitCode
from yellowdog_cli.utils.spec_properties import ALL_CONFIG_SECTIONS
from yellowdog_cli.utils.variables import enable_undefined_variable_warnings

if TYPE_CHECKING:
    from yellowdog_client import PlatformClient

    CLIENT: PlatformClient

CONFIG_COMMON: ConfigCommon = load_config_common()
# A strict load never returns None for either; the assert narrows the types
assert CONFIG_COMMON.key is not None and CONFIG_COMMON.secret is not None


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


def dry_run() -> bool:
    """
    Is this a dry-run?
    """
    dry_run_ = ARGS_PARSER.dry_run or ARGS_PARSER.process_csv_only
    if dry_run_ is None:
        return False
    return dry_run_


def set_proxy():
    """
    Set the HTTPS proxy using autoconfiguration (PAC) if enabled.
    """
    if dry_run():
        return

    proxy_var = "HTTPS_PROXY"
    if CONFIG_COMMON.use_pac:
        from pypac import pac_context_for_url

        from yellowdog_cli.utils.user_agent import set_user_agent

        # The PAC file is fetched with 'requests', as the CLI's own request
        set_user_agent()
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


def main_wrapper(func):
    def wrapper():
        # The configuration is loaded, so every variable it defines exists:
        # one still unsubstituted from here on is one nothing defines
        enable_undefined_variable_warnings()
        # Before the first schema is compiled, by the config check below
        report_problems_to(print_debug)
        warn_of_undefined_config_variables()
        warn_of_config_violations(ALL_CONFIG_SECTIONS)
        if not ARGS_PARSER.debug:
            exit_code: int = ExitCode.SUCCESS
            try:
                set_proxy()
                func()
                flush_results()
                if any_failed():
                    # The command handled the error itself and recorded it;
                    # main() raised nothing, but a failed record still fails
                    # the run
                    exit_code = ExitCode.FAILURE
            except Exception as e:
                if MISSING_PERMISSION_TEXT in str(e):
                    print_error(
                        "Your Application does not have the required permissions to"
                        " perform the requested operation. Please check that the"
                        " Application belongs to the required group(s), e.g.,"
                        f" 'administrators', with roles in the required namespace(s): {e}"
                    )
                elif UNAUTHORIZED_TEXT in str(e):
                    print_error(
                        f"Your Application Key ID and SECRET are not recognised: {e}"
                    )
                else:
                    # Include the exception type when there's no message,
                    # to avoid printing a blank error
                    print_error(str(e) or f"{type(e).__name__} (no error message)")
                # Set before the flush, so a flush that fails cannot turn the
                # failure into a success; what was done is still reported
                exit_code = classify(e)
                flush_results_after_failure()
            except SystemExit as e:
                exit_code = e.code if isinstance(e.code, int) else ExitCode.FAILURE
                flush_results_after_failure()
            except KeyboardInterrupt:
                print("\r", end="")  # Overwrite the display of ^C
                print_info("Keyboard interruption ... exiting")
                exit_code = ExitCode.INTERRUPTED
                flush_results_after_failure()
            finally:
                _close_client()
                if exit_code == 0 and not ARGS_PARSER.print_pid:
                    print_info("Done")
                exit(exit_code)
        else:
            # Exceptions are re-raised unclassified, for their tracebacks;
            # what was recorded is still printed, however the command ends
            try:
                set_proxy()
                try:
                    func()
                finally:
                    flush_results()
                if any_failed():
                    exit(ExitCode.FAILURE)
                if not ARGS_PARSER.print_pid:
                    print_info("Done")
                exit(ExitCode.SUCCESS)
            finally:
                _close_client()

    return wrapper
