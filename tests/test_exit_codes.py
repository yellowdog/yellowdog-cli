"""
Distinct exit codes: classify() (yellowdog_cli/utils/exit_codes.py), which
maps an exception reaching a command wrapper to an ExitCode, and the wrappers
that use it -- including that whatever a command recorded is still printed
before a failure exits.
"""

from json import loads as json_loads
from unittest.mock import MagicMock

import pytest
from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError, Response, Timeout
from yellowdog_client.model.exceptions.internal_server_exception import (
    InternalServerException,
)
from yellowdog_client.model.exceptions.not_authorised_exception import (
    NotAuthorisedException,
)
from yellowdog_client.model.exceptions.server_error_exception import (
    ServerErrorException,
)

import yellowdog_cli.utils.dataclient_wrapper as dcw_module
import yellowdog_cli.utils.printing as printing_module
import yellowdog_cli.utils.results as results_module
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils.exit_codes import classify
from yellowdog_cli.utils.results import record, reset_results
from yellowdog_cli.utils.settings import ExitCode


def _http_error(status: int) -> HTTPError:
    response = Response()
    response.status_code = status
    return HTTPError(f"{status} error", response=response)


class TestClassify:
    @pytest.mark.parametrize(
        ("status", "code"),
        [
            (401, ExitCode.AUTHENTICATION),
            (403, ExitCode.PERMISSION),
            (404, ExitCode.NOT_FOUND),
            (500, ExitCode.PLATFORM),
            (503, ExitCode.PLATFORM),
            (400, ExitCode.FAILURE),
        ],
    )
    def test_http_status(self, status, code):
        assert classify(_http_error(status)) == code

    def test_http_error_without_a_response(self):
        assert classify(HTTPError("no response")) == ExitCode.FAILURE

    def test_not_authorised(self):
        assert classify(NotAuthorisedException("no")) == ExitCode.AUTHENTICATION

    def test_internal_server(self):
        assert classify(InternalServerException("boom")) == ExitCode.PLATFORM

    def test_server_error(self):
        assert classify(ServerErrorException(500, "boom")) == ExitCode.PLATFORM

    def test_connection_error(self):
        assert classify(RequestsConnectionError()) == ExitCode.CONNECTION

    def test_timeout(self):
        assert classify(Timeout()) == ExitCode.CONNECTION

    def test_missing_permission_text(self):
        assert (
            classify(Exception("... MissingPermissionException ..."))
            == ExitCode.PERMISSION
        )

    def test_unauthorized_text(self):
        assert classify(Exception("401 Unauthorized")) == ExitCode.AUTHENTICATION

    def test_anything_else(self):
        assert classify(RuntimeError("x")) == ExitCode.FAILURE

    def test_values_match_the_table(self):
        assert [int(code) for code in ExitCode] == [0, 1, 2, 3, 4, 5, 6, 7, 8, 130]


def _args(json_output: bool = False, debug: bool = False) -> MagicMock:
    return MagicMock(
        json_output=json_output,
        debug=debug,
        strip_ids=False,
        quiet=False,
        no_format=True,
        count_only=False,
        print_pid=False,
        output_file=None,
    )


@pytest.fixture()
def wrapped(monkeypatch):
    """Both wrappers with their start-up checks and the client stubbed out."""

    def set_up(json_output: bool = False, debug: bool = False) -> MagicMock:
        args = _args(json_output, debug)
        for module in (wrapper_module, dcw_module, results_module, printing_module):
            monkeypatch.setattr(module, "ARGS_PARSER", args)
        for module in (wrapper_module, dcw_module):
            monkeypatch.setattr(
                module, "warn_of_undefined_config_variables", lambda: None
            )
            monkeypatch.setattr(
                module, "enable_undefined_variable_warnings", lambda: None
            )
        monkeypatch.setattr(wrapper_module, "set_proxy", lambda: None)
        monkeypatch.setattr(wrapper_module, "CLIENT", MagicMock())
        return args

    reset_results()
    yield set_up
    reset_results()


WRAPPERS = [wrapper_module.main_wrapper, dcw_module.dataclient_wrapper]


def _exit_code(wrapper, func) -> int:
    with pytest.raises(SystemExit) as info:
        wrapper(func)()
    return info.value.code  # type: ignore[return-value]


class TestWrappers:
    @pytest.mark.parametrize("wrapper", WRAPPERS)
    def test_not_found_exits_6(self, wrapped, wrapper):
        wrapped()

        def func():
            raise _http_error(404)

        assert _exit_code(wrapper, func) == ExitCode.NOT_FOUND

    @pytest.mark.parametrize("wrapper", WRAPPERS)
    def test_success_exits_0(self, wrapped, wrapper):
        wrapped()
        assert _exit_code(wrapper, lambda: None) == ExitCode.SUCCESS

    @pytest.mark.parametrize("wrapper", WRAPPERS)
    def test_recorded_results_are_printed_before_the_failure(
        self, wrapped, wrapper, capsys
    ):
        wrapped(json_output=True)

        def func():
            record({"id": "a", "outcome": "cancelled"})
            record({"id": "b", "outcome": "cancelled"})
            raise _http_error(503)

        assert _exit_code(wrapper, func) == ExitCode.PLATFORM
        out, err = capsys.readouterr()
        assert [item["id"] for item in json_loads(out)] == ["a", "b"]
        assert "503" in err

    @pytest.mark.parametrize("wrapper", WRAPPERS)
    def test_results_are_printed_before_an_explicit_exit(
        self, wrapped, wrapper, capsys
    ):
        wrapped(json_output=True)

        def func():
            record({"id": "a", "succeeded": False})
            raise SystemExit(1)

        assert _exit_code(wrapper, func) == 1
        assert json_loads(capsys.readouterr().out) == [{"id": "a", "succeeded": False}]

    @pytest.mark.parametrize("wrapper", WRAPPERS)
    def test_results_are_printed_on_success(self, wrapped, wrapper, capsys):
        wrapped(json_output=True)
        assert _exit_code(wrapper, lambda: record({"id": "a"})) == 0
        # No 'Done' under --json: stdout is the document alone
        assert json_loads(capsys.readouterr().out) == [{"id": "a"}]

    @pytest.mark.parametrize("wrapper", WRAPPERS)
    def test_a_failing_flush_keeps_the_failure_code(self, wrapped, wrapper, capsys):
        # The exit code is decided before the flush: an unserialisable record
        # must not turn a 404 into a success, nor escape as a traceback
        wrapped(json_output=True)

        def func():
            record({"when": object()})
            raise _http_error(404)

        assert _exit_code(wrapper, func) == ExitCode.NOT_FOUND
        out, err = capsys.readouterr()
        assert "Done" not in out
        assert "Unable to print the results as JSON" in err

    @pytest.mark.parametrize("wrapper", WRAPPERS)
    def test_a_failing_flush_after_success_is_a_failure(self, wrapped, wrapper, capsys):
        wrapped(json_output=True)
        assert _exit_code(wrapper, lambda: record({"when": object()})) == (
            ExitCode.FAILURE
        )
        assert "Done" not in capsys.readouterr().out

    @pytest.mark.parametrize("wrapper", WRAPPERS)
    def test_a_failed_record_exits_1_under_json(self, wrapped, wrapper, capsys):
        wrapped(json_output=True)

        def func():
            record({"id": "a", "outcome": "failed", "error": "boom"})

        assert _exit_code(wrapper, func) == ExitCode.FAILURE
        out, _err = capsys.readouterr()
        assert json_loads(out) == [{"id": "a", "outcome": "failed", "error": "boom"}]
        assert "Done" not in out

    @pytest.mark.parametrize("wrapper", WRAPPERS)
    def test_a_failed_record_exits_1_without_json(self, wrapped, wrapper, capsys):
        wrapped(json_output=False)

        def func():
            record({"id": "a", "outcome": "failed"})

        assert _exit_code(wrapper, func) == ExitCode.FAILURE
        out, _err = capsys.readouterr()
        assert out == ""

    @pytest.mark.parametrize("wrapper", WRAPPERS)
    def test_only_successful_records_exit_0(self, wrapped, wrapper, capsys):
        wrapped(json_output=True)

        def func():
            record({"id": "a", "outcome": "cancelled"})
            record({"id": "b", "action": "created"})

        assert _exit_code(wrapper, func) == ExitCode.SUCCESS
        out, _err = capsys.readouterr()
        assert json_loads(out) == [
            {"id": "a", "outcome": "cancelled"},
            {"id": "b", "action": "created"},
        ]

    @pytest.mark.parametrize("wrapper", WRAPPERS)
    def test_keyboard_interrupt_exits_130(self, wrapped, wrapper):
        wrapped()

        def func():
            raise KeyboardInterrupt

        assert _exit_code(wrapper, func) == ExitCode.INTERRUPTED

    @pytest.mark.parametrize("wrapper", WRAPPERS)
    def test_debug_re_raises(self, wrapped, wrapper):
        wrapped(debug=True)

        def func():
            raise _http_error(404)

        with pytest.raises(HTTPError):
            wrapper(func)()

    @pytest.mark.parametrize("wrapper", WRAPPERS)
    def test_debug_still_prints_results(self, wrapped, wrapper, capsys):
        wrapped(json_output=True, debug=True)
        assert _exit_code(wrapper, lambda: record({"id": "a"})) == 0
        assert json_loads(capsys.readouterr().out) == [{"id": "a"}]


class TestClassifyChained:
    def test_not_found_error(self):
        from yellowdog_cli.utils.exit_codes import NotFoundError

        assert classify(NotFoundError("Worker Pool ID 'x' not found")) == (
            ExitCode.NOT_FOUND
        )

    def test_not_found_error_prints_without_quotes(self):
        from yellowdog_cli.utils.exit_codes import NotFoundError

        assert str(NotFoundError("x not found")) == "x not found"

    @pytest.mark.parametrize(
        "cause, code",
        [
            (RequestsConnectionError("reset"), ExitCode.CONNECTION),
            (_http_error(404), ExitCode.NOT_FOUND),
            (_http_error(503), ExitCode.PLATFORM),
        ],
    )
    def test_a_rewrapped_failure_keeps_its_cause_code(self, cause, code):
        try:
            try:
                raise cause
            except Exception as e:
                raise RuntimeError(f"Unable to do the thing: {e}") from e
        except RuntimeError as wrapped_error:
            assert classify(wrapped_error) == code

    def test_an_unchained_failure_is_still_failure(self):
        assert classify(RuntimeError("odd")) == ExitCode.FAILURE


class TestReportedFailure:
    def test_it_is_classified_by_its_cause(self):
        from yellowdog_cli.utils.exit_codes import ReportedFailure

        assert classify(ReportedFailure(_http_error(401))) == ExitCode.AUTHENTICATION
        assert (
            classify(ReportedFailure(RequestsConnectionError("reset")))
            == ExitCode.CONNECTION
        )

    @pytest.mark.parametrize("wrapper", WRAPPERS)
    def test_the_wrapper_exits_with_its_code_without_reporting_it_again(
        self, wrapped, wrapper, capsys
    ):
        from yellowdog_cli.utils.exit_codes import ReportedFailure

        wrapped(json_output=True)

        def func():
            # What an action command does on a session failure: record the
            # failure and what it did not attempt, then raise
            record({"id": "a", "outcome": "failed", "error": "reset"})
            record({"id": "b", "outcome": "skipped", "error": "not attempted: reset"})
            raise ReportedFailure(RequestsConnectionError("reset"))

        assert _exit_code(wrapper, func) == ExitCode.CONNECTION
        out, err = capsys.readouterr()
        assert [item["outcome"] for item in json_loads(out)] == ["failed", "skipped"]
        assert "reset" not in err  # the command printed it; the wrapper did not
