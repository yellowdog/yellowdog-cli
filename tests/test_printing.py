"""
Unit tests for yellowdog_cli.utils.printing

Only pure/utility functions are tested here; functions that drive Rich
console output (print_info, print_warning, etc.) are exercised indirectly
by the rest of the test suite.
"""

import re
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from rich.console import Console
from yellowdog_client.model import KeyringSummary, Task, WorkRequirementSummary

import yellowdog_cli.utils.printing as printing_module
from yellowdog_cli.utils.printing import (
    StatusCount,
    _truncate_text,
    _yes_or_no,
    get_type_name,
    indent,
    keyring_table,
    print_debug,
    print_dry_run,
    print_info,
    print_string,
    status_counts_msg,
    task_table,
    work_requirement_table,
)
from yellowdog_cli.utils.settings import (
    DEBUG_STYLE,
    DRY_RUN_MARKER,
    MAX_TABLE_DESCRIPTION,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_args(print_pid=False, no_format=True, **kwargs):
    """
    Return a mock ARGS_PARSER with sensible test defaults.
    """
    ns = SimpleNamespace(print_pid=print_pid, no_format=no_format, **kwargs)
    return ns


# ---------------------------------------------------------------------------
# _truncate_text
# ---------------------------------------------------------------------------


class TestTruncateText:
    def test_none_returns_empty_string(self):
        assert _truncate_text(None) == ""

    def test_empty_string_unchanged(self):
        assert _truncate_text("") == ""

    def test_short_string_unchanged(self):
        assert _truncate_text("hello") == "hello"

    def test_exactly_max_length_unchanged(self):
        s = "x" * MAX_TABLE_DESCRIPTION
        assert _truncate_text(s) == s

    def test_over_max_length_truncated_with_ellipsis(self):
        s = "x" * (MAX_TABLE_DESCRIPTION + 1)
        result = _truncate_text(s)
        assert result.endswith("...")
        assert len(result) == MAX_TABLE_DESCRIPTION

    def test_long_string_content_preserved_up_to_truncation(self):
        s = "abcde" * 20  # well over the limit
        result = _truncate_text(s)
        assert s.startswith(result[: MAX_TABLE_DESCRIPTION - 3])


# ---------------------------------------------------------------------------
# _yes_or_no
# ---------------------------------------------------------------------------


class TestYesOrNo:
    def test_true_returns_yes(self):
        assert _yes_or_no(True) == "Yes"

    def test_false_returns_no(self):
        assert _yes_or_no(False) == "No"


# ---------------------------------------------------------------------------
# indent
# ---------------------------------------------------------------------------


class TestIndent:
    def test_default_four_spaces(self):
        result = indent("hello")
        assert result == "    hello"

    def test_custom_indent_width(self):
        result = indent("hi", indent_width=2)
        assert result == "  hi"

    def test_zero_indent(self):
        result = indent("hi", indent_width=0)
        assert result == "hi"

    def test_multiline_all_lines_indented(self):
        result = indent("line1\nline2\nline3", indent_width=4)
        for line in result.splitlines():
            assert line.startswith("    ")

    def test_empty_string(self):
        assert indent("", indent_width=4) == ""


# ---------------------------------------------------------------------------
# status_counts_msg
# ---------------------------------------------------------------------------


class TestStatusCountsMsg:
    def test_single_nonzero_count(self):
        counts = [StatusCount("RUNNING")]
        result = status_counts_msg(counts, {"RUNNING": 5})
        assert result == "5 RUNNING"

    def test_zero_count_include_if_zero_true(self):
        counts = [StatusCount("RUNNING", include_if_zero=True)]
        result = status_counts_msg(counts, {"RUNNING": 0})
        assert result == "0 RUNNING"

    def test_zero_count_include_if_zero_false_omitted(self):
        counts = [StatusCount("STOPPED")]  # include_if_zero defaults to False
        result = status_counts_msg(counts, {"STOPPED": 0})
        assert result == ""

    def test_missing_key_skipped_silently(self):
        counts = [StatusCount("RUNNING")]
        result = status_counts_msg(counts, {})
        assert result == ""

    def test_multiple_statuses_joined_with_comma(self):
        counts = [StatusCount("RUNNING"), StatusCount("STOPPED"), StatusCount("FAILED")]
        result = status_counts_msg(counts, {"RUNNING": 3, "STOPPED": 0, "FAILED": 2})
        assert result == "3 RUNNING, 2 FAILED"

    def test_thousands_formatted_with_comma(self):
        counts = [StatusCount("RUNNING")]
        result = status_counts_msg(counts, {"RUNNING": 1000})
        assert result == "1,000 RUNNING"

    def test_empty_msg_if_zero_total_true_suppresses_output(self):
        # Even though include_if_zero=True adds "0 RUNNING" to the buffer,
        # when empty_msg_if_zero_total=True and total==0 the result is "".
        counts = [StatusCount("RUNNING", include_if_zero=True)]
        result = status_counts_msg(counts, {"RUNNING": 0}, empty_msg_if_zero_total=True)
        assert result == ""

    def test_empty_msg_if_zero_total_false_keeps_output(self):
        counts = [StatusCount("RUNNING", include_if_zero=True)]
        result = status_counts_msg(
            counts, {"RUNNING": 0}, empty_msg_if_zero_total=False
        )
        assert result == "0 RUNNING"

    def test_nonzero_total_always_returned(self):
        counts = [StatusCount("RUNNING")]
        result = status_counts_msg(counts, {"RUNNING": 1}, empty_msg_if_zero_total=True)
        assert result == "1 RUNNING"

    def test_none_counts_data_handled(self):
        counts = [StatusCount("RUNNING")]
        # None causes TypeError on key lookup → caught and skipped
        result = status_counts_msg(counts, None)  # type: ignore[arg-type]
        assert result == ""

    def test_empty_status_counts_list(self):
        result = status_counts_msg([], {"RUNNING": 5})
        assert result == ""


# ---------------------------------------------------------------------------
# get_type_name
# ---------------------------------------------------------------------------


class TestGetTypeName:
    def test_class_ending_in_instance_returns_instance(self):
        class SomethingInstance:
            pass

        assert get_type_name(SomethingInstance()) == "Instance"  # type: ignore[arg-type]

    def test_class_ending_in_allowance_returns_allowance(self):
        class SomethingAllowance:
            pass

        assert get_type_name(SomethingAllowance()) == "Allowance"  # type: ignore[arg-type]

    def test_unknown_type_returns_empty_string(self):
        class CompletelyUnknownType:
            pass

        assert get_type_name(CompletelyUnknownType()) == ""  # type: ignore[arg-type]

    def test_instance_check_takes_priority_over_type_map(self):
        # A class whose name ends in "Instance" is caught by the first guard
        # regardless of whether it appears in TYPE_MAP.
        class KeyringSummaryInstance:
            pass

        assert get_type_name(KeyringSummaryInstance()) == "Instance"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# print_string
# ---------------------------------------------------------------------------


class TestPrintString:
    def setup_method(self):
        # Reset module-level cached prefix length between tests
        printing_module.PREFIX_LEN = 0
        printing_module.SUBSEQUENT_INDENT = ""

    def test_output_contains_message(self):
        with patch("yellowdog_cli.utils.printing.ARGS_PARSER", _mock_args()):
            result = print_string("hello world")
        assert "hello world" in result

    def test_timestamp_format(self):
        with patch("yellowdog_cli.utils.printing.ARGS_PARSER", _mock_args()):
            result = print_string("msg")
        assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", result)

    def test_no_pid_by_default(self):
        with patch(
            "yellowdog_cli.utils.printing.ARGS_PARSER", _mock_args(print_pid=False)
        ):
            result = print_string("msg")
        # PID is 6 digits in parens; should not appear
        assert "(" not in result

    def test_with_pid_includes_pid(self):
        with patch(
            "yellowdog_cli.utils.printing.ARGS_PARSER", _mock_args(print_pid=True)
        ):
            result = print_string("msg")
        assert re.search(r"\(\d{6}\)", result)

    def test_empty_message_no_fill(self):
        with patch("yellowdog_cli.utils.printing.ARGS_PARSER", _mock_args()):
            result = print_string("")
        # Empty message: prefix + "" with no wrapping
        assert result.endswith(" : ")

    def test_no_format_returns_prefix_plus_msg_directly(self):
        with patch(
            "yellowdog_cli.utils.printing.ARGS_PARSER", _mock_args(no_format=True)
        ):
            result = print_string("raw message")
        assert result.endswith("raw message")


# ---------------------------------------------------------------------------
# print_debug
# ---------------------------------------------------------------------------


class TestPrintDebug:
    """
    The startup/configuration messages: printed only when '--debug' is set,
    and still suppressed by '--quiet' and by the JSON output modes.
    """

    def setup_method(self):
        printing_module.PREFIX_LEN = 0
        printing_module.SUBSEQUENT_INDENT = ""

    @staticmethod
    def _args(**kwargs):
        defaults = dict(
            debug=False,
            quiet=False,
            json_output=False,
            count_only=False,
            no_format=True,
            print_pid=False,
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def _output(self, capsys, **kwargs) -> str:
        with patch("yellowdog_cli.utils.printing.ARGS_PARSER", self._args(**kwargs)):
            print_debug("Loading configuration data")
        return capsys.readouterr().out

    def test_nothing_is_printed_without_debug(self, capsys):
        assert self._output(capsys, debug=False) == ""

    def test_message_is_printed_with_debug(self, capsys):
        assert "Loading configuration data" in self._output(capsys, debug=True)

    def test_debug_marker_precedes_the_message(self, capsys):
        output = self._output(capsys, debug=True)
        assert "DEBUG : Loading configuration data" in output

    def test_timestamp_prefix_is_the_standard_one(self, capsys):
        # The same prefix as print_info carries
        output = self._output(capsys, debug=True)
        assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} : DEBUG : ", output)

    def test_message_is_printed_with_formatting_enabled(self, capsys):
        # '--no-format' picks plain print() over the Rich console; the gate
        # and the marker are the same either way
        output = self._output(capsys, debug=True, no_format=False)
        assert "DEBUG : Loading configuration data" in output

    def test_nothing_is_printed_without_debug_with_formatting_enabled(self, capsys):
        assert self._output(capsys, debug=False, no_format=False) == ""

    def test_quiet_suppresses_it_even_with_debug(self, capsys):
        assert self._output(capsys, debug=True, quiet=True) == ""

    def test_json_output_suppresses_it_even_with_debug(self, capsys):
        assert self._output(capsys, debug=True, json_output=True) == ""


# ---------------------------------------------------------------------------
# print_dry_run
# ---------------------------------------------------------------------------


class TestPrintDryRun:
    """
    The dry-run messages: an ordinary message carrying the DRY-RUN marker.
    Unlike print_debug(), it does no gating of its own — every caller is
    already inside a dry-run branch.
    """

    def setup_method(self):
        printing_module.PREFIX_LEN = 0
        printing_module.SUBSEQUENT_INDENT = ""

    @staticmethod
    def _args(**kwargs):
        defaults = dict(
            quiet=False,
            json_output=False,
            count_only=False,
            no_format=True,
            print_pid=False,
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def _output(self, capsys, **kwargs) -> str:
        with patch("yellowdog_cli.utils.printing.ARGS_PARSER", self._args(**kwargs)):
            print_dry_run("Would resize Worker Pool")
        return capsys.readouterr().out

    def test_marker_precedes_the_message(self, capsys):
        assert f"{DRY_RUN_MARKER}Would resize Worker Pool" in self._output(capsys)

    def test_timestamp_prefix_is_the_standard_one(self, capsys):
        assert re.match(
            rf"\d{{4}}-\d{{2}}-\d{{2}} \d{{2}}:\d{{2}}:\d{{2}} : {DRY_RUN_MARKER}",
            self._output(capsys),
        )

    def test_it_prints_without_any_gating(self, capsys):
        # No '--debug' or '--dry-run' attribute is consulted
        assert self._output(capsys) != ""

    def test_quiet_suppresses_it(self, capsys):
        assert self._output(capsys, quiet=True) == ""

    def test_json_output_suppresses_it(self, capsys):
        assert self._output(capsys, json_output=True) == ""

    def test_message_is_printed_with_formatting_enabled(self, capsys):
        assert DRY_RUN_MARKER in self._output(capsys, no_format=False)


# ---------------------------------------------------------------------------
# Colouring: the '--debug' preamble is styled, ordinary output is not
# ---------------------------------------------------------------------------


# Rich's 'dark_orange', as the 256-colour console below renders it
DEBUG_COLOUR = "\x1b[38;5;208m"


class TestStyledOutput:
    """
    print_info() carries an optional Rich style, which is what lets
    print_debug() colour the preamble without reimplementing print_info().
    """

    def setup_method(self):
        printing_module.PREFIX_LEN = 0
        printing_module.SUBSEQUENT_INDENT = ""

    @staticmethod
    def _args(**kwargs):
        defaults = dict(
            debug=True,
            quiet=False,
            json_output=False,
            count_only=False,
            no_format=False,
            print_pid=False,
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def _render(self, call, **kwargs) -> str:
        """
        Run 'call' against a real Rich console that emits colour, and return
        what it wrote — escape sequences included.
        """
        buffer = StringIO()
        console = Console(
            file=buffer, force_terminal=True, color_system="256", width=200
        )
        with (
            patch("yellowdog_cli.utils.printing.ARGS_PARSER", self._args(**kwargs)),
            patch("yellowdog_cli.utils.printing.CONSOLE", console),
        ):
            call()
        return buffer.getvalue()

    def test_debug_messages_are_coloured(self):
        output = self._render(lambda: print_debug("Loading configuration data"))
        assert DEBUG_COLOUR in output
        assert "Loading configuration data" in output

    def test_ordinary_messages_are_not_coloured(self):
        assert DEBUG_COLOUR not in self._render(lambda: print_info("Submitting"))

    def test_dry_run_messages_are_not_coloured(self):
        assert DEBUG_COLOUR not in self._render(lambda: print_dry_run("Complete"))

    def test_the_style_reaches_the_console_from_print_info(self):
        output = self._render(lambda: print_info("Plain", style=DEBUG_STYLE))
        assert DEBUG_COLOUR in output

    def test_no_format_emits_no_colour_at_all(self):
        # The '--no-format' branch is plain print(), so nothing is styled
        output = self._render(
            lambda: print_debug("Loading configuration data"), no_format=True
        )
        assert "\x1b[" not in output


# ---------------------------------------------------------------------------
# Table-building helpers (smoke tests using SimpleNamespace stubs)
# ---------------------------------------------------------------------------


class TestKeyringTable:
    def _keyring(
        self, name="k1", description="A keyring", id="ydid:keyring:abc"
    ) -> KeyringSummary:
        return SimpleNamespace(name=name, description=description, id=id)  # type: ignore[return-value]

    def test_headers_present(self):
        headers, _ = keyring_table([self._keyring()])
        assert "Name" in headers
        assert "Keyring ID" in headers

    def test_single_row_data(self):
        ks = self._keyring(name="my-keyring", id="ydid:keyring:xyz")
        _, rows = keyring_table([ks])
        assert len(rows) == 1
        assert rows[0][1] == "my-keyring"
        assert rows[0][3] == "ydid:keyring:xyz"

    def test_row_numbering(self):
        keyrings = [self._keyring(name=f"k{i}") for i in range(3)]
        _, rows = keyring_table(keyrings)
        assert [r[0] for r in rows] == [1, 2, 3]

    def test_long_description_truncated(self):
        long_desc = "x" * (MAX_TABLE_DESCRIPTION + 10)
        _, rows = keyring_table([self._keyring(description=long_desc)])
        assert rows[0][2].endswith("...")

    def test_empty_list_returns_empty_table(self):
        _, rows = keyring_table([])
        assert rows == []


class TestTaskTable:
    def _task(self, name="task-1", status="COMPLETED", id="ydid:task:001") -> Task:
        return SimpleNamespace(name=name, status=status, id=id)  # type: ignore[return-value]

    def test_headers_present(self):
        headers, _ = task_table([self._task()])
        assert "Task Name" in headers
        assert "Status" in headers
        assert "Task ID" in headers

    def test_single_row_data(self):
        t = self._task(name="my-task", status="FAILED", id="ydid:task:999")
        _, rows = task_table([t])
        assert rows[0][1] == "my-task"
        assert rows[0][2] == "FAILED"
        assert rows[0][3] == "ydid:task:999"

    def test_multiple_rows_numbered(self):
        tasks = [self._task(name=f"t{i}") for i in range(4)]
        _, rows = task_table(tasks)
        assert [r[0] for r in rows] == [1, 2, 3, 4]


class TestWorkRequirementTable:
    def _wr(
        self,
        name="wr-1",
        namespace: str | None = "ns",
        tag: str | None = "t",
        status="RUNNING",
        completed=3,
        total=5,
        healthy=True,
        id="ydid:wr:001",
    ) -> WorkRequirementSummary:
        return SimpleNamespace(  # type: ignore[return-value]
            name=name,
            namespace=namespace,
            tag=tag,
            status=status,
            completedTaskCount=completed,
            totalTaskCount=total,
            healthy=healthy,
            id=id,
        )

    def test_headers_present(self):
        headers, _ = work_requirement_table([self._wr()])
        assert "Work Requirement Name" in headers
        assert "Status" in headers

    def test_single_row_counts(self):
        wr = self._wr(completed=2, total=10)
        _, rows = work_requirement_table([wr])
        assert rows[0][5] == "2/10"

    def test_none_namespace_becomes_empty_string(self):
        wr = self._wr(namespace=None)
        _, rows = work_requirement_table([wr])
        assert rows[0][2] == ""

    def test_none_tag_becomes_empty_string(self):
        wr = self._wr(tag=None)
        _, rows = work_requirement_table([wr])
        assert rows[0][3] == ""

    def test_healthy_flag_rendered(self):
        _, rows_yes = work_requirement_table([self._wr(healthy=True)])
        _, rows_no = work_requirement_table([self._wr(healthy=False)])
        assert rows_yes[0][6] == "Yes"
        assert rows_no[0][6] == "No"


class TestNoEmojiCodes:
    """
    Text such as '{{num:x:=1}}' or '{{env:smile:}}' is printed as written:
    Rich's ':name:' emoji codes are off on every console, since the CLI
    prints user text and never means one.
    """

    TEXT = "'{{num:x:=1}}' and '{{env:smile:}}' and --no-binary :all:"

    def test_every_console(self):
        consoles = [
            printing_module.CONSOLE,
            printing_module.CONSOLE_TABLE,
            printing_module.CONSOLE_ERR,
            printing_module.CONSOLE_JSON,
        ]
        for console in consoles:
            with console.capture() as capture:
                console.print(self.TEXT)
            assert capture.get().strip() == self.TEXT, console

    def test_input_prompt(self, monkeypatch):
        written = StringIO()
        # '_file', not 'file': its getter answers sys.stdout when none is set,
        # so restoring 'file' would pin the console to this test's capture
        monkeypatch.setattr(printing_module.CONSOLE, "_file", written)
        printing_module.CONSOLE.input("{{a:x:}} ? ", stream=StringIO("y\n"))
        assert "{{a:x:}}" in written.getvalue()


# ---------------------------------------------------------------------------
# Output that is not to a terminal, and terminal widths
# ---------------------------------------------------------------------------


class TestNotATerminal:
    """
    Rich's width is 80 when the output is not a terminal; every print passes
    soft_wrap=True, so lines are wrapped once, by print_string(), and a
    table row not at all.
    """

    @staticmethod
    def _args():
        return SimpleNamespace(
            quiet=False,
            json_output=False,
            count_only=False,
            no_format=False,
            print_pid=False,
        )

    def test_a_table_row_stays_one_line(self, monkeypatch):
        buffer = StringIO()
        monkeypatch.setattr(printing_module, "ARGS_PARSER", self._args())
        monkeypatch.setattr(
            printing_module, "CONSOLE_TABLE", Console(file=buffer, emoji=False)
        )
        row = "│ " + "x" * 120 + " │"
        printing_module.print_table_core(row)
        assert buffer.getvalue() == row + "\n"

    def test_a_message_is_wrapped_once(self, monkeypatch):
        buffer = StringIO()
        monkeypatch.setattr(printing_module, "ARGS_PARSER", self._args())
        monkeypatch.setattr(printing_module, "LOG_WIDTH", 120)
        monkeypatch.setattr(
            printing_module, "CONSOLE", Console(file=buffer, emoji=False)
        )
        print_info("word " * 40)
        lines = buffer.getvalue().splitlines()
        # print_string()'s lines, at 120, and not broken again at 80
        assert all(len(line) <= 120 for line in lines)
        assert all(len(line) > 80 for line in lines[:-1])

    def test_a_simple_line_stays_one_line(self, monkeypatch):
        buffer = StringIO()
        monkeypatch.setattr(printing_module, "ARGS_PARSER", self._args())
        monkeypatch.setattr(
            printing_module, "CONSOLE", Console(file=buffer, emoji=False)
        )
        path = "remote:bucket/" + "a/" * 60 + "file.txt"
        printing_module.print_simple(path)
        assert buffer.getvalue() == path + "\n"


class TestTerminalWidth:
    def test_a_terminal_reporting_no_width_gets_the_default(self, monkeypatch):
        monkeypatch.setattr(
            printing_module, "get_terminal_size", lambda: SimpleNamespace(columns=0)
        )
        assert printing_module.terminal_width() == printing_module.DEFAULT_LOG_WIDTH

    def test_no_terminal_gets_the_default(self, monkeypatch):
        def _no_terminal():
            raise OSError("not a terminal")

        monkeypatch.setattr(printing_module, "get_terminal_size", _no_terminal)
        assert printing_module.terminal_width() == printing_module.DEFAULT_LOG_WIDTH

    def test_a_terminal_width_is_used(self, monkeypatch):
        monkeypatch.setattr(
            printing_module, "get_terminal_size", lambda: SimpleNamespace(columns=97)
        )
        assert printing_module.terminal_width() == 97


def test_errors_are_highlighted_as_messages_are():
    # The stderr console resolves the highlighter's styles, as CONSOLE does
    assert printing_module.CONSOLE_ERR.get_style("pyexamples.date_time") == (
        printing_module.CONSOLE.get_style("pyexamples.date_time")
    )


# ---------------------------------------------------------------------------
# print_event()
# ---------------------------------------------------------------------------


class TestPrintEventWithNullFields:
    """
    The Platform leaves a summary null until there is something to
    summarise; an event holding one is printed, not raised on, which would
    end the stream being followed.
    """

    @staticmethod
    def _print(monkeypatch, event: dict, id_type) -> list[str]:
        import json

        printed: list[str] = []
        monkeypatch.setattr(
            printing_module, "ARGS_PARSER", SimpleNamespace(events_as_json=False)
        )
        monkeypatch.setattr(
            printing_module, "print_info", lambda msg, **k: printed.append(msg)
        )
        printing_module.print_event("data:" + json.dumps(event), id_type)
        return printed

    def test_a_compute_requirement_source_with_no_instance_summary(self, monkeypatch):
        from yellowdog_cli.utils.ydid_utils import YDIDType

        printed = self._print(
            monkeypatch,
            {
                "name": "cr",
                "status": "PROVISIONING",
                "targetInstanceCount": 2,
                "expectedInstanceCount": 0,
                "provisionStrategy": {
                    "sources": [{"name": "s1", "instanceSummary": None}]
                },
            },
            YDIDType.COMPUTE_REQUIREMENT,
        )
        assert "2 TARGET, 0 EXPECTED, 0 ALIVE" in printed[0]

    def test_a_task_group_with_no_task_summary(self, monkeypatch):
        from yellowdog_cli.utils.ydid_utils import YDIDType

        printed = self._print(
            monkeypatch,
            {
                "name": "wr",
                "status": "RUNNING",
                "taskGroups": [
                    {"name": "tg", "status": "PENDING", "taskSummary": None}
                ],
            },
            YDIDType.WORK_REQUIREMENT,
        )
        assert "Task Group 'tg': 0 Task(s)" in printed[0]

    def test_a_worker_pool_with_no_summaries(self, monkeypatch):
        from yellowdog_cli.utils.ydid_utils import YDIDType

        printed = self._print(
            monkeypatch,
            {
                "name": "wp",
                "status": "PENDING",
                "nodeSummary": None,
                "workerSummary": None,
            },
            YDIDType.WORKER_POOL,
        )
        assert printed[0].startswith("Worker Pool 'wp' is PENDING")


# ---------------------------------------------------------------------------
# sorted_objects(), nodes_table(), print_to_file()
# ---------------------------------------------------------------------------


class TestSortedObjects:
    @staticmethod
    def _args(monkeypatch, reverse=None):
        monkeypatch.setattr(
            printing_module, "ARGS_PARSER", SimpleNamespace(sort=None, reverse=reverse)
        )

    def test_a_none_name_sorts_first(self, monkeypatch):
        self._args(monkeypatch)
        objects = [
            SimpleNamespace(name="b"),
            SimpleNamespace(name=None),
            SimpleNamespace(name="a"),
        ]
        assert [o.name for o in printing_module.sorted_objects(objects)] == [
            None,
            "a",
            "b",
        ]

    def test_reverse_applies(self, monkeypatch):
        self._args(monkeypatch, reverse=True)
        objects = [SimpleNamespace(name="a"), SimpleNamespace(name="b")]
        assert [o.name for o in printing_module.sorted_objects(objects)] == ["b", "a"]

    def test_objects_without_names_sort_by_namespace(self, monkeypatch):
        self._args(monkeypatch)
        objects = [SimpleNamespace(namespace="y"), SimpleNamespace(namespace=None)]
        assert [o.namespace for o in printing_module.sorted_objects(objects)] == [
            None,
            "y",
        ]


def test_a_node_without_details_is_still_listed():
    node = SimpleNamespace(details=None, workers=[], status="RUNNING", id="ydid:node:x")
    _, rows = printing_module.nodes_table([node])
    assert rows == [[1, None, None, None, None, "", None, 0, "RUNNING", "ydid:node:x"]]


def test_an_output_file_that_cannot_be_written_keeps_its_cause(tmp_path):
    import pytest

    with pytest.raises(RuntimeError) as raised:
        printing_module.print_to_file("{}", str(tmp_path / "missing" / "out.json"))
    assert isinstance(raised.value.__cause__, OSError)
