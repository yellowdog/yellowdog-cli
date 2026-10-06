"""
The CLI's output: the Rich consoles, the message functions (print_info(),
print_warning(), print_error(), print_debug(), print_dry_run()), JSON output
(print_json() and the other JSON printers) and SDK object printing, with
'--output-file'. Tables are tables.py's, and events event_printing.py's.
"""

from __future__ import annotations

import re
import sys
from bisect import bisect_left
from datetime import datetime
from json import dumps as json_dumps
from os import get_terminal_size, getpid
from textwrap import fill
from textwrap import indent as text_indent
from threading import Lock
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.highlighter import JSONHighlighter, RegexHighlighter
from rich.markup import escape
from rich.theme import Theme

from yellowdog_cli.utils.compact_json import CompactJSONEncoder
from yellowdog_cli.utils.output_settings import OUTPUT
from yellowdog_cli.utils.output_style import (
    DEBUG_MARKER,
    DEBUG_STYLE,
    DEFAULT_LOG_WIDTH,
    DEFAULT_THEME,
    DRY_RUN_MARKER,
    ERROR_MARKER,
    ERROR_STYLE,
    HIGHLIGHTED_STATES,
    JSON_INDENT,
    MAX_LINES_COLOURED_FORMATTING,
    WARNING_MARKER,
    WARNING_STYLE,
)
from yellowdog_cli.utils.property_names import (
    NAME,
    PROP_ACCESS_DELEGATES,
    PROP_ADMIN_GROUP,
    PROP_CREATED_BY_ID,
    PROP_CREATED_BY_USER_ID,
    PROP_CREATED_TIME,
    PROP_DELETABLE,
    PROP_ID,
    PROP_INSTANCE_PRICING,
    PROP_PROVIDER,
    PROP_REMAINING_HOURS,
    PROP_SOURCE,
    PROP_SUPPORTING_RESOURCE_CREATED,
    PROP_TRAITS,
    TASK_GROUPS,
    TASKS,
    USERDATA,
)
from yellowdog_cli.utils.rich_console_input_fixed import ConsoleWithInputBackspaceFixed
from yellowdog_cli.utils.ydid_utils import YDID_HIGHLIGHT_RE

if TYPE_CHECKING:
    from yellowdog_client.model import (
        ComputeRequirementTemplateUsage,
        ProvisionedWorkerPoolProperties,
        Task,
        WorkRequirement,
    )


def terminal_width() -> int:
    """
    The width messages are wrapped to: the terminal's, or DEFAULT_LOG_WIDTH
    where there is no terminal or it reports no width (some pseudo-terminals,
    containers started without a size), for which fill() would raise.
    """
    try:
        columns = get_terminal_size().columns
    except OSError:
        return DEFAULT_LOG_WIDTH
    return columns if columns > 0 else DEFAULT_LOG_WIDTH


LOG_WIDTH = terminal_width()


# Set up Rich formatting for coloured output
class PrintLogHighlighter(RegexHighlighter):
    """
    Apply styles for print_info() lines.
    """

    base_style = "pyexamples."
    highlights = [  # type: ignore[assignment]  # noqa: RUF012
        re.compile(
            r"(?P<date_time>[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"
            r" [0-9][0-9]:[0-9][0-9]:[0-9][0-9])"
        ),
        re.compile(r"(?P<quoted>'[a-zA-Z0-9-._=;,:/\\\[\]{}+#@$£%^&*()~`<>?]*')"),
        YDID_HIGHLIGHT_RE,
        re.compile(r"(?P<url>(https?):((//)|(\\\\))+[\w:#@%/;$~_?+=\\.&]*)"),
        *HIGHLIGHTED_STATES,
    ]


class PrintTableHighlighter(RegexHighlighter):
    """
    Apply styles for table printing.
    """

    base_style = "pyexamples."
    table_outline_chars = "┌─┬│┼┐┤└┴┘├"
    highlights = [  # type: ignore[assignment]  # noqa: RUF012
        re.compile(rf"(?P<table_outline>[{table_outline_chars}]*)"),
        re.compile(rf"(?P<table_content>[^{table_outline_chars}]*)"),
        YDID_HIGHLIGHT_RE,
        *HIGHLIGHTED_STATES,
    ]


pyexamples_theme = Theme(DEFAULT_THEME)


# Emoji codes are off: the CLI prints user text -- '{{num:x:=1}}' -- and never
# means one, and Rich would print that as '{{num❌=1}}'. Every print passes
# soft_wrap=True: a message is wrapped by print_string() and a table not at
# all, and Rich, whose width is 80 when stdout is not a terminal, would wrap
# each line again, breaking tables and paths written to a pipe or a file
CONSOLE = ConsoleWithInputBackspaceFixed(
    highlighter=PrintLogHighlighter(), theme=pyexamples_theme, emoji=False
)
CONSOLE_TABLE = Console(
    highlighter=PrintTableHighlighter(), theme=pyexamples_theme, emoji=False
)
CONSOLE_ERR = Console(
    stderr=True, highlighter=PrintLogHighlighter(), theme=pyexamples_theme, emoji=False
)
CONSOLE_JSON = Console(highlighter=JSONHighlighter(), emoji=False)

PREFIX_LEN = 0
SUBSEQUENT_INDENT = ""


def print_string(msg: str = "", no_fill: bool = False) -> str:
    """
    Message output format, with tidy line-wrapping calibrated
    for the terminal width.
    """
    global PREFIX_LEN, SUBSEQUENT_INDENT

    prefix = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Optionally add the PID to the prefix to disambiguate interleaved
    # log messages
    if OUTPUT.print_pid:
        prefix += f" ({getpid():06d}) : "
    else:
        prefix += " : "

    if PREFIX_LEN == 0:
        PREFIX_LEN = len(prefix)
        SUBSEQUENT_INDENT = " " * PREFIX_LEN

    if no_fill or msg == "" or msg.isspace() or OUTPUT.no_format:
        return prefix + msg

    return fill(
        msg,
        width=LOG_WIDTH,
        initial_indent=prefix,
        subsequent_indent=SUBSEQUENT_INDENT,
        drop_whitespace=True,
        break_long_words=False,  # Preserve URLs
        break_on_hyphens=False,  # Preserve names
    )


def prefix_width() -> int:
    """
    The width of a message's timestamp prefix, once one has been printed (0
    before), for output that lines up under a message's text.
    """
    return PREFIX_LEN


def print_simple(
    log_message: str = "",
    override_quiet: bool = False,
):
    """
    Simple print function without timestamp.
    Set 'override_quiet' to print when '-q' is set.
    """
    if OUTPUT.quiet and override_quiet is False:
        return

    if OUTPUT.no_format:
        print(log_message)
    else:
        CONSOLE.print(escape(log_message), soft_wrap=True)


def print_info(
    log_message: str = "",
    override_quiet: bool = False,
    no_fill: bool = False,
    style: str | None = None,
):
    """
    Placeholder for logging.
    Set 'override_quiet' to print when '-q' is set.
    A 'style' is a Rich base style for the line; the highlighter's own colours
    still apply on top of it, and '--no-format' ignores it along with all
    other colouring.
    """
    if (
        OUTPUT.quiet or OUTPUT.json_output or OUTPUT.count_only
    ) and override_quiet is False:
        return

    if OUTPUT.no_format:
        print(print_string(log_message, no_fill=no_fill), flush=True)
        return

    CONSOLE.print(
        escape(print_string(log_message, no_fill=no_fill)), style=style, soft_wrap=True
    )


def print_quiet_result(result: object) -> None:
    """
    Print a command's bare result -- a created entity's ID, say -- when
    '--quiet' is set, for a shell to capture. Not under '--json', whose
    document is then all that stdout holds.
    """
    if OUTPUT.quiet and not OUTPUT.json_output:
        print(result, flush=True)


def print_debug(
    log_message: str = "",
    no_fill: bool = False,
):
    """
    An informational message that's printed only when '--debug' is set:
    used for the configuration/startup preamble, which is noise unless
    it's what one is looking at. Marked 'DEBUG' and coloured to set it
    apart from the command's own output; otherwise formatted, and
    suppressed by '--quiet' and the JSON output modes, exactly as
    print_info() is.
    """
    if not OUTPUT.debug:
        return

    print_info(f"{DEBUG_MARKER}{log_message}", no_fill=no_fill, style=DEBUG_STYLE)


def print_dry_run(
    log_message: str = "",
    no_fill: bool = False,
):
    """
    A message reporting what a '--dry-run' would have done. Formatted and
    suppressed exactly as print_info() is; it does no gating of its own,
    because every caller is already inside a dry-run branch.
    """
    print_info(f"{DRY_RUN_MARKER}{log_message}", no_fill=no_fill)


def print_error(error_obj: Exception | str):
    """
    Print an error message to stderr.
    """
    if OUTPUT.no_format:
        # sys.stderr looked up at the call, so that a redirect (yd-doctor's
        # capture of a configuration error) reaches it
        print(print_string(f"{ERROR_MARKER}{error_obj}"), flush=True, file=sys.stderr)
        return

    CONSOLE_ERR.print(
        escape(print_string(f"{ERROR_MARKER}{error_obj}")),
        style=ERROR_STYLE,
        soft_wrap=True,
    )


def warnings_suppressed() -> bool:
    """
    True if print_warning() prints nothing unless told to override: under
    '--quiet' or '--count-only'. A check that only warns can be skipped.
    """
    return bool(OUTPUT.quiet or OUTPUT.count_only)


def print_warning(
    warning: str,
    override_quiet: bool = False,
    no_fill: bool = False,
):
    """
    Print a warning: to stdout, or to stderr under '--json'.
    """
    if warnings_suppressed() and override_quiet is False:
        return

    # Under '--json' stdout is the result document alone, so a warning goes
    # to stderr rather than being dropped
    to_stderr = bool(OUTPUT.json_output)

    if OUTPUT.no_format:
        print(
            print_string(f"{WARNING_MARKER}{warning}", no_fill=no_fill),
            flush=True,
            file=sys.stderr if to_stderr else sys.stdout,
        )
        return

    (CONSOLE_ERR if to_stderr else CONSOLE).print(
        escape(print_string(f"{WARNING_MARKER}{warning}", no_fill=no_fill)),
        style=WARNING_STYLE,
        soft_wrap=True,
    )


def indent(txt: str, indent_width: int = 4) -> str:
    """
    Indent lines of text.
    """
    return text_indent(txt, prefix=" " * indent_width)


def user_data_hidden(data: Any) -> Any:
    """
    A copy of JSON-shaped data with every 'userData' string, at any depth,
    replaced by a one-line summary of its size: '--hide-user-data', for
    output a long boot script would otherwise swamp. A value that is not a
    string (null, as the Platform returns it unset) is left as it is.
    """
    if isinstance(data, dict):
        return {
            key: (
                _user_data_summary(value)
                if key == USERDATA and isinstance(value, str)
                else user_data_hidden(value)
            )
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [user_data_hidden(item) for item in data]
    return data


def _user_data_summary(user_data: str) -> str:
    """
    What '--hide-user-data' shows in place of a User Data script.
    """
    lines = len(user_data.splitlines())
    return (
        f"<user data: {len(user_data):,d} characters,"
        f" {lines:,d} line{'' if lines == 1 else 's'}>"
    )


def user_data_as_shown(data: Any) -> Any:
    """
    JSON-shaped data as it is to be shown: with its User Data summarised
    under '--hide-user-data', else unchanged. Only ever applied to what is
    printed or recorded, never to what is sent.
    """
    return user_data_hidden(data) if OUTPUT.hide_user_data else data


def _strip_id_props(d):
    """
    Remove ID and read-only metadata fields from a deserialized dict, recursively.
    Shared by print_yd_object (--strip-ids path) and print_objects_as_json.
    """
    if isinstance(d, dict):
        return {
            k: _strip_id_props(v)
            for k, v in d.items()
            if k
            not in [
                PROP_ID,
                PROP_ACCESS_DELEGATES,
                PROP_ADMIN_GROUP,
                PROP_CREATED_BY_ID,
                PROP_CREATED_BY_USER_ID,
                PROP_CREATED_TIME,
                PROP_DELETABLE,
                PROP_INSTANCE_PRICING,
                PROP_REMAINING_HOURS,
                PROP_SUPPORTING_RESOURCE_CREATED,
                PROP_TRAITS,
            ]
        }
    elif isinstance(d, list):
        return [_strip_id_props(item) for item in d]
    return d


def _sdk_json(yd_object: object) -> Any:
    """
    An SDK object as JSON data. Json is imported here, for an SDK object
    only: a list of plain dicts -- every data client command's '--json'
    result -- is printed without loading the SDK.
    """
    from yellowdog_client.common.json import Json

    return Json.dump(yd_object)


def print_objects_as_json(objects: list) -> None:
    """
    Serialise a list of SDK model objects (or plain dicts) as a JSON array
    and print to stdout with no Rich formatting.  Used by --json mode.
    """
    data = [obj if isinstance(obj, dict) else _sdk_json(obj) for obj in objects]
    if OUTPUT.strip_ids:
        stripped = []
        for item in data:
            item = _strip_id_props(item)
            try:
                item.get(PROP_SOURCE).pop(PROP_PROVIDER)  # type: ignore[union-attr]
            except (AttributeError, KeyError):
                pass
            stripped.append(item)
        data = stripped
    print_json(user_data_as_shown(data))


# Set once a JSON document has been printed to stdout, so the '--json' result
# flush (results.py) does not add a second one after a command that printed
# its own
_JSON_DOCUMENT_PRINTED = False


def json_document_printed() -> bool:
    """
    Has print_json() printed anything to stdout in this process?
    """
    return _JSON_DOCUMENT_PRINTED


def reset_json_document_printed() -> None:
    """
    Forget that a JSON document was printed (for tests, via reset_results()).
    """
    global _JSON_DOCUMENT_PRINTED
    _JSON_DOCUMENT_PRINTED = False


def print_json_text(json_text: str) -> None:
    """
    Print a JSON document's text exactly as given: no colouring and no
    wrapping, so that what is printed is byte for byte what a file holding
    it would hold (yd-schema prints a schema as --write writes it).
    """
    global _JSON_DOCUMENT_PRINTED
    _JSON_DOCUMENT_PRINTED = True
    print(json_text, end="" if json_text.endswith("\n") else "\n", flush=True)


def print_json(
    data: Any,
    initial_indent: int = 0,
    with_final_comma: bool = False,
):
    """
    Print a dictionary as a JSON data structure, using the compact JSON
    encoder.
    """
    global _JSON_DOCUMENT_PRINTED
    _JSON_DOCUMENT_PRINTED = True
    json_string = indent(
        json_dumps(data, indent=JSON_INDENT, cls=CompactJSONEncoder), initial_indent
    )
    # Coloured formatting of JSON console output is expensive
    if json_string.count("\n") > MAX_LINES_COLOURED_FORMATTING or OUTPUT.no_format:
        if with_final_comma:
            print(json_string, end=",\n", flush=True)
        else:
            print(json_string, flush=True)

    else:
        if with_final_comma:
            CONSOLE_JSON.print(escape(json_string), end=",\n", soft_wrap=True)
        else:
            CONSOLE_JSON.print(escape(json_string), soft_wrap=True)

    if OUTPUT.output_file is not None:  # Also output to a nominated file
        print_to_file(
            json_string=json_string,
            output_file=OUTPUT.output_file,
            with_final_comma=with_final_comma,
        )


def print_yd_object(
    yd_object: object,
    initial_indent: int = 0,
    with_final_comma: bool = False,
    add_fields: dict | None = None,
):
    """
    Print a YellowDog object as a JSON data structure,
    using the compact JSON encoder.
    """
    from yellowdog_client.common.json import Json

    object_data: Any = Json.dump(yd_object)

    if OUTPUT.strip_ids:
        object_data = _strip_id_props(object_data)
        # Remove the 'provider' property from CST/source data only
        # 'object_data' is always a dict in practice
        try:
            object_data.get(PROP_SOURCE).pop(PROP_PROVIDER)
        except (AttributeError, KeyError):
            pass

    if add_fields is not None:
        # Requires a copy of the 'object' datatype to be made,
        # in order to insert additional fields
        object_data_new = {}
        for key, value in object_data.items():
            object_data_new[key] = value
        for key, value in add_fields.items():
            object_data_new[key] = value
        object_data = object_data_new

    print_json(user_data_as_shown(object_data), initial_indent, with_final_comma)


def print_yd_object_list(
    objects: list[tuple[Any, dict | None]],
):
    """
    Print a JSON list of objects.
    """

    if OUTPUT.output_file is not None:
        print_info(f"Copying detailed resource list to '{OUTPUT.output_file}'")

    if len(objects) > 1:
        print("[")
        if OUTPUT.output_file is not None:
            print_to_file("[", OUTPUT.output_file)

    for index, (object_, add_fields) in enumerate(objects):
        print_yd_object(
            object_,
            initial_indent=2 if len(objects) > 1 else 0,
            with_final_comma=(True if index < len(objects) - 1 else False),
            add_fields=add_fields,
        )

    if len(objects) > 1:
        print("]")
        if OUTPUT.output_file is not None:
            print_to_file("]", OUTPUT.output_file)


def print_worker_pool(
    crtu: ComputeRequirementTemplateUsage, pwpp: ProvisionedWorkerPoolProperties
):
    """
    Reconstruct and print the JSON-formatted Worker Pool specification.
    """
    print_dry_run("Printing JSON Worker Pool specification")
    print_json(user_data_as_shown(worker_pool_specification(crtu, pwpp)))


def worker_pool_specification(
    crtu: ComputeRequirementTemplateUsage, pwpp: ProvisionedWorkerPoolProperties
) -> dict:
    """
    Reconstruct the JSON Worker Pool specification.
    """
    from yellowdog_client.common.json import Json

    return {
        "provisionedProperties": Json.dump(pwpp),
        "requirementTemplateUsage": Json.dump(crtu),
    }


class WorkRequirementSnapshot:
    """
    Represent a complete Work Requirement, with Tasks included within
    Task Group definitions. Note, this is not an 'official' representation
    of a Work Requirement.
    """

    def __init__(self):
        self.wr_data: dict = {}
        # Per Task Group, each batch added as (first Task, count), in Task
        # order: batches submitted in parallel arrive in any order
        self._batches: dict[str, list[tuple[int, int]]] = {}
        self._lock = Lock()

    def set_work_requirement(self, wr: WorkRequirement):
        """
        Set the Work Requirement to be represented, processed to
        comply with the API.
        """
        from yellowdog_client.common.json import Json

        self.wr_data = Json.dump(wr)  # type: ignore[assignment]  # Dictionary holding the complete WR

    def add_tasks(self, task_group_name: str, tasks: list[Task], first_task: int = 0):
        """
        Add a batch of Tasks to a named Task Group within the Work
        Requirement, placed by 'first_task', the number of its first Task
        within the Task Group, so that batches added in any order, from
        any thread, are shown in Task order. Cumulative.
        """
        from yellowdog_client.common.json import Json

        dumped = [Json.dump(task) for task in tasks]
        with self._lock:
            for task_group in self.wr_data[TASK_GROUPS]:
                if task_group[NAME] == task_group_name:
                    # The batches already added, as (first Task, count);
                    # this one's Tasks go after those that start before it
                    batches = self._batches.setdefault(task_group_name, [])
                    position = bisect_left(batches, (first_task, 0))
                    offset = sum(count for _, count in batches[:position])
                    batches.insert(position, (first_task, len(dumped)))
                    task_list = task_group.setdefault(TASKS, [])
                    task_list[offset:offset] = dumped
                    return

    def print(self):
        """
        Print the JSON representation.
        """
        print_dry_run("Printing JSON Work Requirement specification:")
        print_json(self.wr_data)
        print_dry_run("Complete")


FIRST_OUTPUT_TO_FILE = True  # Determine whether to 'write' or 'append'


def print_to_file(json_string: str, output_file: str, with_final_comma: bool = False):
    """
    Dump details output to a file.
    """
    global FIRST_OUTPUT_TO_FILE

    try:
        with open(
            output_file, "w" if FIRST_OUTPUT_TO_FILE else "a", encoding="utf-8"
        ) as f:
            f.write(json_string + (",\n" if with_final_comma else "\n"))
    except OSError as e:
        raise RuntimeError(f"Cannot open output file for writing: {e}") from e

    FIRST_OUTPUT_TO_FILE = False
