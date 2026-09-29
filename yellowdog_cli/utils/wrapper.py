"""
Decorator to handle standard setup, shutdown and exception handling
for all commands.
"""

import os
from sys import exit

from pypac import pac_context_for_url
from yellowdog_client import PlatformClient
from yellowdog_client.model import ApiKey, ServicesSchema

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
from yellowdog_cli.utils.settings import ExitCode
from yellowdog_cli.utils.spec_properties import ALL_CONFIG_SECTIONS
from yellowdog_cli.utils.user_agent import set_user_agent
from yellowdog_cli.utils.variables import enable_undefined_variable_warnings

# Apply the CLI's User-Agent to all outgoing HTTP requests (SDK and direct)
# before any client is created or request is made.
set_user_agent()

CONFIG_COMMON: ConfigCommon = load_config_common()
# A strict load never returns None for either; the assert narrows the types
assert CONFIG_COMMON.key is not None and CONFIG_COMMON.secret is not None
CLIENT = PlatformClient.create(
    ServicesSchema(defaultUrl=CONFIG_COMMON.url),
    ApiKey(CONFIG_COMMON.key, CONFIG_COMMON.secret),
)


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
                CLIENT.close()
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
                CLIENT.close()

    return wrapper
