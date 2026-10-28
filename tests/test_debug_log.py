"""
The '--debug' trace (utils/debug_log.py): on stderr, the CLI's own lines and
urllib3's request lines, each written once, and nothing at all when off.
"""

import logging
import os
import re
from types import SimpleNamespace

import pytest

from yellowdog_cli.utils import output_settings
from yellowdog_cli.utils.debug_log import CLI_LOGGER, HTTP_LOGGER, set_debug_logging

TRACE_LINE = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?: \(\d+\))? : DEBUG : \[\+\d+\.\d{3}s\] (\S+): (.*)$"
)


@pytest.fixture
def trace_on():
    set_debug_logging(True)
    yield
    set_debug_logging(False)


def _lines(err: str) -> list[tuple[str, str]]:
    return [
        (m.group(1), m.group(2))
        for line in err.splitlines()
        if (m := TRACE_LINE.match(line))
    ]


class TestOnAndOff:
    def test_off_nothing_is_written(self, capsys):
        logging.getLogger("yellowdog_cli.utils.submit_utils").debug("hidden")
        logging.getLogger("urllib3.connectionpool").debug("hidden")
        assert capsys.readouterr().err == ""

    def test_off_the_cli_logger_formats_nothing(self):
        # So a run without '--debug' pays nothing for a line's arguments
        assert not logging.getLogger(CLI_LOGGER).isEnabledFor(logging.DEBUG)

    def test_on_a_cli_line_is_named_by_the_module_logging_it(self, capsys, trace_on):
        logging.getLogger("yellowdog_cli.utils.submit_utils").debug("a %s", "line")
        assert _lines(capsys.readouterr().err) == [("test_debug_log", "a line")]

    def test_on_a_request_line_is_named_urllib3(self, capsys, trace_on):
        logging.getLogger("urllib3.connectionpool").debug(
            '%s://%s:%s "%s %s %s" %s %s',
            "https",
            "api.yellowdog.ai",
            443,
            "GET",
            "/work/requirements?namespace=ns",
            "HTTP/1.1",
            200,
            512,
        )
        [(name, message)] = _lines(capsys.readouterr().err)
        assert name == "urllib3"
        assert '"GET /work/requirements?namespace=ns HTTP/1.1" 200 512' in message

    def test_turning_it_on_twice_writes_each_line_once(self, capsys, trace_on):
        set_debug_logging(True)
        logging.getLogger(CLI_LOGGER).debug("once")
        assert len(_lines(capsys.readouterr().err)) == 1

    def test_a_traceback_follows_its_line(self, capsys, trace_on):
        try:
            raise RuntimeError("kaboom")
        except RuntimeError:
            logging.getLogger("yellowdog_cli.utils.x").debug("failed", exc_info=True)
        err = capsys.readouterr().err
        assert re.match(
            r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?: \(\d+\))? : DEBUG : \[\+\d+\.\d{3}s\] test_debug_log: failed\nTraceback",
            err,
        )
        assert "RuntimeError: kaboom" in err

    def test_a_line_is_prefixed_as_an_info_line_is(self, capsys, trace_on):
        logging.getLogger(CLI_LOGGER).debug("stamped")
        assert re.match(
            r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d : DEBUG : \[\+\d+\.\d{3}s\] ",
            capsys.readouterr().err,
        )

    def test_print_pid_puts_the_process_id_after_the_time(self, capsys):
        with output_settings.configured(SimpleNamespace(debug=True, print_pid=True)):
            logging.getLogger(CLI_LOGGER).debug("stamped")
        assert re.match(
            rf"\d{{4}}-\d\d-\d\d \d\d:\d\d:\d\d \({os.getpid():06d}\) : DEBUG : ",
            capsys.readouterr().err,
        )

    def test_configured_output_turns_it_on_and_restoring_turns_it_off(self, capsys):
        with output_settings.configured(SimpleNamespace(debug=True)):
            logging.getLogger(CLI_LOGGER).debug("on")
        logging.getLogger(CLI_LOGGER).debug("off")
        assert [m for _, m in _lines(capsys.readouterr().err)] == ["on"]


class TestTheRootLogger:
    """
    rclone_api configures the root logger for itself (basicConfig, a handler
    on stdout at INFO); the trace neither touches it nor writes through it.
    """

    @pytest.fixture
    def root_handler(self):
        records: list[logging.LogRecord] = []

        class Collect(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = Collect()
        root = logging.getLogger()
        level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        yield records
        root.removeHandler(handler)
        root.setLevel(level)

    def test_its_handlers_are_left_alone(self, trace_on):
        assert all(
            type(h).__name__ != "_StderrHandler" for h in logging.getLogger().handlers
        )

    def test_on_no_line_reaches_it(self, root_handler, trace_on):
        logging.getLogger(CLI_LOGGER).debug("trace")
        logging.getLogger(HTTP_LOGGER).debug("request")
        assert root_handler == []

    def test_off_urllib3_reaches_it_as_without_the_cli(self, root_handler):
        logging.getLogger(HTTP_LOGGER).warning("retrying")
        assert [r.getMessage() for r in root_handler] == ["retrying"]
