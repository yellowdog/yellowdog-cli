"""
The run every wrapped command shares: main_wrapper (wrapper.py) and
dataclient_wrapper (dataclient_wrapper.py) differ only in what they set up
and tear down around the command, and in how an error is described, which
they pass in. Once in one place, a fix to how a command is run, flushed and
exited is made once.

It imports neither wrapper, nor anything that builds a Platform client: the
data client commands, which import no SDK, run through it too.
"""

import sys
from collections.abc import Callable
from typing import Any, NoReturn

from yellowdog_cli.utils.exit_codes import ExitCode, ReportedFailure, classify
from yellowdog_cli.utils.lazy import prepare
from yellowdog_cli.utils.load_config import (
    ensure_config_loaded,
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
from yellowdog_cli.utils.variable_substitution import enable_undefined_variable_warnings


def prepare_run(func: Callable[[], Any], args: Any, *values: object) -> None:
    """
    Build what a command will use, before it runs and outside run_command()'s
    handling, in the order importing once did: the command line ('args'),
    the configuration file, 'values' (the wrapper's own, such as
    CONFIG_COMMON), then every lazy value the command's module holds that is
    marked to be prepared (its configuration sections; not CLIENT). So an
    argument error or a broken configuration is reported, and exits, before
    the command starts, as it did when these were built at import. A test's
    stand-in is left alone.
    """
    prepare(args)
    ensure_config_loaded()
    prepare(*values)
    prepare(*func.__globals__.values())


def describe_error(error: Exception) -> str:
    """
    An error as a command reports it: its message, or its type when it has
    none, so that nothing is ever printed blank.
    """
    return str(error) or f"{type(error).__name__} (no error message)"


def exit_code_of(exit_: SystemExit) -> int:
    """
    The exit code a SystemExit carries, as Python itself reads it: None (a
    bare sys.exit()) is success, an integer is itself, and anything else --
    a message -- is a failure, the message printed as Python would print it.
    """
    if exit_.code is None:
        return ExitCode.SUCCESS
    if isinstance(exit_.code, int):
        return exit_.code
    print_error(str(exit_.code))
    return ExitCode.FAILURE


def _interrupted() -> None:
    # Overwrite the terminal's display of ^C; written only to a terminal,
    # since anywhere else it is a stray byte in the output
    if sys.stdout.isatty():
        print("\r", end="", flush=True)
    print_info("Keyboard interruption ... exiting")


def run_command(
    func: Callable[[], Any],
    args: Any,
    config_sections: Any,
    before: Callable[[], None] = lambda: None,
    after: Callable[[], None] = lambda: None,
    describe: Callable[[Exception], str] = describe_error,
) -> NoReturn:
    """
    Run a command's main() and exit with its exit code.

    'args' is the calling wrapper's ARGS_PARSER (looked up there, so that a
    test's patch of it is the one used); 'config_sections' the configuration
    sections whose schema violations are warned of as the command starts;
    'before' what is set up before the command (main_wrapper's proxy), and
    'after' what is torn down whatever happens (its client); 'describe' how
    an error is reported.

    The results recorded for '--json' are flushed however the command ends;
    a failed record fails the run although main() raised nothing; and under
    '--debug' an exception is re-raised, unclassified, for its traceback.
    """
    # The configuration is loaded, so every variable it defines exists: one
    # still unsubstituted from here on is one nothing defines
    enable_undefined_variable_warnings()
    # Before the first schema is compiled, by the config check below
    report_problems_to(print_debug)
    warn_of_undefined_config_variables()
    warn_of_config_violations(config_sections)

    if args.debug:
        # Exceptions are re-raised unclassified, for their tracebacks; what
        # was recorded is still printed, however the command ends
        try:
            before()
            try:
                func()
            finally:
                flush_results()
            if any_failed():
                sys.exit(ExitCode.FAILURE)
            if not args.print_pid:
                print_info("Done")
            sys.exit(ExitCode.SUCCESS)
        finally:
            after()

    exit_code: int = ExitCode.SUCCESS
    try:
        before()
        func()
        flush_results()
        if any_failed():
            # The command handled the error itself and recorded it; main()
            # raised nothing, but a failed record still fails the run
            exit_code = ExitCode.FAILURE
    except SystemExit as e:
        # An explicit exit code raised by the command is kept
        exit_code = exit_code_of(e)
        flush_results_after_failure()
    except Exception as e:
        if not isinstance(e, ReportedFailure):  # else reported already
            print_error(describe(e))
        # Set before the flush, so a flush that fails cannot turn the
        # failure into a success; what was done is still reported
        exit_code = classify(e)
        flush_results_after_failure()
    except KeyboardInterrupt:
        _interrupted()
        exit_code = ExitCode.INTERRUPTED
        flush_results_after_failure()
    finally:
        after()
    if exit_code == ExitCode.SUCCESS and not args.print_pid:
        print_info("Done")
    sys.exit(exit_code)
