#!/usr/bin/env python3

"""
Check the installation, configuration and platform connection, and report
each check as OK, WARN, FAIL or SKIP with a remedy for anything wrong.

Built on neither wrapper: both exit on a missing key before main() runs,
which is the state this command exists to diagnose.
"""

import logging
import textwrap
from sys import exit, stderr

from rich.markup import escape

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.doctor_checks import Check, Context, Result, Status, run_checks
from yellowdog_cli.utils.printing import (
    CONSOLE_TABLE,
    print_json,
    print_simple,
)

Row = tuple[Check, Result]

_COLOUR = {
    Status.OK: "green",
    Status.WARN: "yellow",
    Status.FAIL: "red",
    Status.SKIP: "dim",
}


def exit_code(rows: list[Row]) -> int:
    return 1 if any(result.status is Status.FAIL for _, result in rows) else 0


def render_json(rows: list[Row]) -> list[dict]:
    return [
        {
            "group": check.group,
            "check": check.name,
            "status": result.status.value,
            "detail": result.detail,
            "remedy": result.remedy,
        }
        for check, result in rows
    ]


def _summary(rows: list[Row]) -> str:
    counts = {
        status: sum(1 for _, r in rows if r.status is status) for status in Status
    }
    return (
        f"{len(rows)} checks: {counts[Status.OK]} OK, {counts[Status.WARN]} WARN, "
        f"{counts[Status.FAIL]} FAIL, {counts[Status.SKIP]} SKIP"
    )


def _print_line(plain_prefix: str, markup_prefix: str, text: str) -> None:
    """
    One row, or one remedy, of the report on stdout: a prefix (the check
    and status columns, or the status word) then its text.

    Under --no-format, one line whatever its length, for grep and pasting.
    Formatted, the text wraps at the console's width, on whitespace only so
    that no YDID, URL or path is split, and every continuation line is
    indented to where the text began, leaving the columns to its left clear.
    The wrapping is done here, on the plain text, rather than by the
    console, which would carry the text on at column 0; 'soft_wrap=True'
    then stops the console wrapping a line again, one too long only for a
    word it could not break.
    """
    if ARGS_PARSER.no_format:
        print_simple(f"{plain_prefix}{text}".rstrip(), override_quiet=True)
        return
    offset = len(plain_prefix)
    pieces = textwrap.wrap(
        text,
        width=max(20, CONSOLE_TABLE.width - offset),
        break_long_words=False,
        break_on_hyphens=False,
    ) or [""]
    CONSOLE_TABLE.print(f"{markup_prefix}{escape(pieces[0])}".rstrip(), soft_wrap=True)
    for piece in pieces[1:]:
        CONSOLE_TABLE.print(" " * offset + escape(piece), soft_wrap=True)


def _print_remedies(rows: list[Row]) -> None:
    """
    '<STATUS> <check>: <remedy>' for each FAIL and WARN, on stdout with the
    rest of the report, so that a redirected or pasted report keeps them.
    """
    for check, result in rows:
        if result.status in (Status.FAIL, Status.WARN):
            status = result.status.value
            colour = _COLOUR[result.status]
            _print_line(
                f"{status} ",
                f"[{colour}]{status}[/{colour}] ",
                f"{check.name}: {result.remedy or result.detail}",
            )


def render_table(rows: list[Row]) -> None:
    """
    The checks under their group headings, in columns shared by every group.
    The columns are laid out from the visible text and the status coloured
    afterwards: laid out with the markup in place, each status would be
    padded by the length of its colour's name.
    """
    name_width = max((len(check.name) for check, _ in rows), default=0)
    status_width = max(len(status.value) for status in Status)
    groups: dict[str, list[Row]] = {}
    for check, result in rows:
        groups.setdefault(check.group, []).append((check, result))
    for group, group_rows in groups.items():
        print_simple(f"\n{group}", override_quiet=True)
        for check, result in group_rows:
            name = check.name.ljust(name_width)
            status = result.status.value.ljust(status_width)
            colour = _COLOUR[result.status]
            _print_line(
                f"{name}  {status}  ",
                f"{escape(name)}  [{colour}]{status}[/{colour}]  ",
                result.detail,
            )
    print_simple("", override_quiet=True)
    _print_remedies(rows)
    print_simple(_summary(rows), override_quiet=True)


def _keep_logging_off_stdout() -> None:
    """
    Give the root logger a handler before anything imports rclone_api, which
    otherwise installs one writing to stdout, where urllib3's retry warnings
    for an unanswering platform would land in the table and break --json.
    Under --debug the log goes to stderr; otherwise nowhere, since the rows
    report what it would say.
    """
    if logging.root.handlers:
        return
    handler = (
        logging.StreamHandler(stderr) if ARGS_PARSER.debug else logging.NullHandler()
    )
    logging.root.addHandler(handler)


def main() -> None:
    _keep_logging_off_stdout()
    timeout = ARGS_PARSER.timeout
    assert timeout is not None  # the option has a default; argparse refuses < 1
    ctx = Context(
        offline=bool(ARGS_PARSER.offline),
        timeout=timeout,
        debug=bool(ARGS_PARSER.debug),
    )
    rows = run_checks(ctx)
    if ARGS_PARSER.json_output:
        print_json(render_json(rows))
    elif ARGS_PARSER.quiet:
        _print_remedies(rows)
        print_simple(_summary(rows), override_quiet=True)
    else:
        render_table(rows)
    exit(exit_code(rows))


if __name__ == "__main__":
    main()
