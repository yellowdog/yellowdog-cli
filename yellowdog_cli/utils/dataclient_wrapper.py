"""
Decorator for data client commands (yd-upload, yd-download, yd-delete, yd-ls).
Mirrors main_wrapper but does not instantiate PlatformClient, so commands can
run without YellowDog API credentials.
"""

from sys import exit

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.exit_codes import ReportedFailure, classify
from yellowdog_cli.utils.load_config import (
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
from yellowdog_cli.utils.spec_properties import DATA_CLIENT_CONFIG_SECTIONS
from yellowdog_cli.utils.variable_substitution import enable_undefined_variable_warnings


def dataclient_wrapper(func):

    def wrapper():
        # The configuration is loaded, so every variable it defines exists:
        # one still unsubstituted from here on is one nothing defines
        enable_undefined_variable_warnings()
        # Before the first schema is compiled, by the config check below
        report_problems_to(print_debug)
        warn_of_undefined_config_variables()
        warn_of_config_violations(DATA_CLIENT_CONFIG_SECTIONS)
        if not ARGS_PARSER.debug:
            exit_code: int = ExitCode.SUCCESS
            try:
                func()
                flush_results()
                if any_failed():
                    # The command handled the error itself and recorded it;
                    # func() raised nothing, but a failed record still fails
                    # the run
                    exit_code = ExitCode.FAILURE
            except SystemExit as e:
                # Preserve an explicit exit code raised by the command
                exit_code = e.code if isinstance(e.code, int) else ExitCode.FAILURE
                flush_results_after_failure()
            except Exception as e:
                if not isinstance(e, ReportedFailure):  # else reported already
                    # Include the exception type when there's no message,
                    # to avoid printing a blank error
                    print_error(str(e) or f"{type(e).__name__} (no error message)")
                # Set before the flush, so a flush that fails cannot turn the
                # failure into a success; what was done is still reported
                exit_code = classify(e)
                flush_results_after_failure()
            except KeyboardInterrupt:
                print("\r", end="")  # Overwrite the display of ^C
                print_info("Keyboard interruption ... exiting")
                exit_code = ExitCode.INTERRUPTED
                flush_results_after_failure()
            if exit_code == 0 and not ARGS_PARSER.print_pid:
                print_info("Done")
            exit(exit_code)
        else:
            # Exceptions are re-raised unclassified, for their tracebacks;
            # what was recorded is still printed, however the command ends
            try:
                func()
            finally:
                flush_results()
            if any_failed():
                exit(ExitCode.FAILURE)
            if not ARGS_PARSER.print_pid:
                print_info("Done")
            exit(ExitCode.SUCCESS)

    return wrapper
