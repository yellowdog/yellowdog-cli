"""
Decorator for data client commands (yd-upload, yd-download, yd-delete, yd-ls).
Mirrors main_wrapper but does not instantiate PlatformClient, so commands can
run without YellowDog API credentials.
"""

from sys import exit

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.printing import print_error, print_info
from yellowdog_cli.utils.variables import enable_undefined_variable_warnings


def dataclient_wrapper(func):

    def wrapper():
        # The configuration is loaded, so every variable it defines exists:
        # one still unsubstituted from here on is one nothing defines
        enable_undefined_variable_warnings()
        if not ARGS_PARSER.debug:
            exit_code = 0
            try:
                func()
            except SystemExit as e:
                # Preserve an explicit exit code raised by the command
                exit_code = e.code if isinstance(e.code, int) else 1
            except Exception as e:
                # Include the exception type when there's no message,
                # to avoid printing a blank error
                print_error(str(e) or f"{type(e).__name__} (no error message)")
                exit_code = 1
            except KeyboardInterrupt:
                print("\r", end="")  # Overwrite the display of ^C
                print_info("Keyboard interruption ... exiting")
                exit_code = 1
            if exit_code == 0 and not ARGS_PARSER.print_pid:
                print_info("Done")
            exit(exit_code)
        else:
            func()
            if not ARGS_PARSER.print_pid:
                print_info("Done")
            exit(0)

    return wrapper
