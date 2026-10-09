"""
utils/command_runner.py, the run both wrappers share, and what each wrapper
passes it: a bare sys.exit() a success and a message a failure printed; the
^C carriage return written only to a terminal; main_wrapper's error message
chosen as its exit code is (classify()), and PAC resolved under --dry-run
too; rows_as_objects() refusing headings that collide; and no command
module importing ARGS_PARSER, CONFIG_COMMON or CLIENT, which it is given
as its context, bar yd-doctor and yd-schema, on neither wrapper.
"""

import ast
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from requests import HTTPError, Response

import yellowdog_cli.utils.command_runner as runner_module
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils import output_settings
from yellowdog_cli.utils.exit_codes import ExitCode
from yellowdog_cli.utils.results import rows_as_objects


def _http_error(status: int) -> HTTPError:
    response = Response()
    response.status_code = status
    return HTTPError(f"{status} Client Error", response=response)


class TestExitCodeOf:
    def test_a_bare_exit_is_success(self):
        assert runner_module.exit_code_of(SystemExit()) == ExitCode.SUCCESS

    def test_an_integer_is_itself(self):
        assert runner_module.exit_code_of(SystemExit(6)) == 6

    def test_a_message_is_a_failure_and_printed(self, monkeypatch):
        printed = []
        monkeypatch.setattr(runner_module, "print_error", printed.append)
        assert runner_module.exit_code_of(SystemExit("broken")) == ExitCode.FAILURE
        assert printed == ["broken"]


class TestInterrupted:
    @pytest.mark.parametrize("tty", [True, False])
    def test_the_carriage_return_is_for_a_terminal_only(self, monkeypatch, capsys, tty):
        monkeypatch.setattr(runner_module, "print_info", lambda *a, **k: None)
        monkeypatch.setattr(runner_module.sys.stdout, "isatty", lambda: tty)
        runner_module._interrupted()
        assert ("\r" in capsys.readouterr().out) is tty


class TestDescribe:
    def test_a_forbidden_request_is_described_as_permissions(self):
        assert "required permissions" in wrapper_module._describe(_http_error(403))

    def test_an_unauthorised_request_is_described_as_credentials(self):
        assert "not recognised" in wrapper_module._describe(_http_error(401))

    def test_anything_else_is_its_message(self):
        assert wrapper_module._describe(RuntimeError("boom")) == "boom"

    def test_an_error_with_no_message_is_named(self):
        assert wrapper_module._describe(RuntimeError()) == (
            "RuntimeError (no error message)"
        )


class TestPacUnderDryRun:
    def test_pac_is_resolved_in_a_dry_run(self, monkeypatch):
        # Most dry runs call the platform: behind a PAC-only proxy they
        # failed to connect while the real run worked
        resolved = []

        @contextmanager
        def pac(url):
            resolved.append(url)
            yield

        args = SimpleNamespace(
            dry_run=True,
            process_csv_only=False,
            debug=False,
            quiet=True,
            json_output=False,
            count_only=False,
            no_format=True,
            print_pid=False,
        )
        with (
            patch.object(wrapper_module, "ARGS_PARSER", args),
            output_settings.configured(args),
            patch.object(
                wrapper_module,
                "CONFIG_COMMON",
                SimpleNamespace(use_pac=True, url="https://api.yellowdog.ai"),
            ),
            patch("pypac.pac_context_for_url", pac),
            patch.dict(os.environ, {}, clear=True),
        ):
            wrapper_module.set_proxy()
        assert resolved == ["https://api.yellowdog.ai"]


class TestRowsAsObjects:
    def test_headings_that_collide_are_refused(self):
        with pytest.raises(ValueError, match="nodeId"):
            rows_as_objects(["Node ID", "Node Id"], [["a", "b"]])

    def test_a_row_number_column_is_still_dropped(self):
        assert rows_as_objects(["", "Name"], [[1, "a"]]) == [{"name": "a"}]


def test_the_runner_closes_the_client_whatever_happens(monkeypatch):
    # main_wrapper's 'after', through the shared runner, on a failure too
    args = SimpleNamespace(debug=False, print_pid=True, json_output=False)
    for name in (
        "enable_undefined_variable_warnings",
        "report_problems_to",
        "warn_of_undefined_config_variables",
        "warn_of_config_violations",
    ):
        monkeypatch.setattr(runner_module, name, lambda *a, **k: None)
    monkeypatch.setattr(runner_module, "print_error", lambda *a, **k: None)
    monkeypatch.setattr(runner_module, "flush_results", lambda: None)
    monkeypatch.setattr(runner_module, "flush_results_after_failure", lambda: None)
    closed = MagicMock()

    def fail():
        raise _http_error(404)

    with pytest.raises(SystemExit) as raised:
        runner_module.run_command(fail, args=args, config_sections=(), after=closed)
    assert raised.value.code == ExitCode.NOT_FOUND
    closed.assert_called_once()


# Built on neither wrapper, so they read ARGS_PARSER themselves
_OWN_RUN_COMMANDS = {"doctor.py", "schema.py"}
_CONTEXT_GLOBALS = {"ARGS_PARSER", "CONFIG_COMMON", "CLIENT"}


def test_no_command_module_imports_what_its_context_carries():
    package = Path(runner_module.__file__).parent.parent
    offenders = []
    for path in sorted(package.glob("*.py")):
        if path.name in _OWN_RUN_COMMANDS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                offenders += [
                    f"{path.name}: {alias.name}"
                    for alias in node.names
                    if alias.name in _CONTEXT_GLOBALS
                ]
    assert offenders == []
