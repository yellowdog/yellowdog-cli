#!/usr/bin/env python3

"""
List the yd commands: the nouns with their verbs, the other commands, and
(--deprecated) the yd-* scripts 'yd' replaces.
"""

import json
import re
import sys
from importlib.util import find_spec

from rich.console import Console
from rich.text import Text
from rich.theme import Theme

from yellowdog_cli._version import __version__
from yellowdog_cli.utils.check_imports import EXTRA_PROBES
from yellowdog_cli.utils.command_registry import COMMANDS, OTHER_COMMANDS, build_parser
from yellowdog_cli.utils.compact_json import CompactJSONEncoder
from yellowdog_cli.utils.invocation import selected_prog
from yellowdog_cli.utils.noun_registry import NOUNS, REPLACED_BY_VERBS, Noun
from yellowdog_cli.utils.output_encoding import use_utf8_output
from yellowdog_cli.utils.output_settings import configure_output
from yellowdog_cli.utils.output_style import DEFAULT_THEME, JSON_INDENT
from yellowdog_cli.utils.printing import print_json_text
from yellowdog_cli.utils.top_level import (
    SCRIPT_FORMS,
    warn_if_deprecated_script,
    word_of,
    yd_form,
)
from yellowdog_cli.utils.version_info import docs_url

# The CLI's theme, as printing.py uses it: a command name in the style of a
# table's content, and a note -- the extra a command needs -- dimmed so the
# summaries proper stand out.
NAME_STYLE = "pyexamples.table_content"
NOTE_STYLE = "dim"
HEADING_STYLE = "bold"
# The notes dimmed: a trailing '(needs the <extra> extra)', '(<extra> extra
# installed)' or a noun's '(short: yd wr)' -- never a parenthesis inside the
# summary's own prose ('Hold (pause) ...')
NOTE = re.compile(r" \((needs the \w+ extra|\w+ extra installed|short: yd \w+)\)$")
# A summary's extra, as the registry and OTHER_COMMANDS write it
EXTRA = re.compile(r" \(needs the (\w+) extra\)$")


def _other_commands() -> list[tuple[str, str]]:
    """
    The commands that are not nouns, by their 'yd-*' names: the registry
    commands no noun replaces (yd-list, the utilities), and the other entry
    points.
    """
    return sorted(
        [
            (name, cmd.summary)
            for name, cmd in COMMANDS.items()
            if name not in REPLACED_BY_VERBS
        ]
        + list(OTHER_COMMANDS.items())
    )


def _listing() -> list[tuple[str, str]]:
    """
    The other commands as typed: 'yd list'.
    """
    return [(yd_form(name), summary) for name, summary in _other_commands()]


def _nouns() -> list[Noun]:
    return sorted(NOUNS, key=lambda noun: noun.name)


def _noun_summary(noun: Noun) -> str:
    """
    A noun's line in the listing: what it does, and its short form.
    """
    if noun.alias is None:
        return noun.summary
    return f"{noun.summary} (short: yd {noun.alias})"


def _verbs(noun: Noun) -> str:
    return ", ".join(verb.name for verb in noun.verbs)


def _deprecated_listing() -> list[tuple[str, str]]:
    return sorted((name, ", ".join(forms)) for name, forms in SCRIPT_FORMS.items())


def column_width() -> int:
    return max(
        len(name)
        for name in [f"yd {noun.name}" for noun in NOUNS]
        + [name for name, _ in _listing()]
        + list(SCRIPT_FORMS)
    )


def extra_installed(extra: str) -> bool:
    """
    Whether an optional extra is installed: its probe package can be found.
    """
    return find_spec(EXTRA_PROBES[extra]) is not None


def _command_record(name: str, summary: str) -> dict:
    record: dict = {"command": name, "summary": summary}
    if (match := EXTRA.search(summary)) is not None:
        record["extra"] = match.group(1)
        record["installed"] = extra_installed(match.group(1))
    return record


def entries() -> list[dict]:
    """
    The listing as '--json' gives it: each noun with its alias and verbs,
    each other command's word and summary, with the extra it needs and
    whether that is installed as fields of their own, so that no script has
    to pick them out of the summary; and each deprecated 'yd-*' script, with
    the 'yd' forms that replace it.
    """
    records: list[dict] = []
    for noun in _nouns():
        records.append(
            {
                "command": noun.name,
                "alias": noun.alias,
                "summary": noun.summary,
                "verbs": [
                    {
                        "verb": verb.name,
                        "summary": verb.summary,
                        **(
                            {"replaces": verb.command}
                            if verb.command in REPLACED_BY_VERBS
                            else {}
                        ),
                    }
                    for verb in noun.verbs
                ],
            }
        )
    records += [
        _command_record(word_of(name), summary) for name, summary in _other_commands()
    ]
    for name, forms in sorted(SCRIPT_FORMS.items()):
        summary = COMMANDS[name].summary if name in COMMANDS else OTHER_COMMANDS[name]
        records.append(
            {
                **_command_record(name, summary),
                "deprecated": True,
                "replacedBy": forms,
            }
        )
    return records


def shown_summary(summary: str) -> str:
    """
    A summary as the listing shows it: an extra that is installed says so,
    rather than that it is needed.
    """
    match = EXTRA.search(summary)
    if match is None or not extra_installed(match.group(1)):
        return summary
    return f"{summary[: match.start()]} ({match.group(1)} extra installed)"


def _footer() -> str:
    return (
        "Run 'yd <noun> --help' for a noun's verbs, and 'yd <noun> <verb>"
        " --help' or 'yd <command> --help' for the options; documentation:"
        f" {docs_url()}"
    )


def _deprecation_note() -> str:
    return (
        "The yd-* commands (yd-submit, yd-list and the rest) still run, with"
        " a warning, until a future release; 'yd help --deprecated' lists"
        " them."
    )


def main():
    use_utf8_output()
    warn_if_deprecated_script("yd-help")
    parser = build_parser(COMMANDS["yd-help"], prog=selected_prog("yd-help"))
    args = parser.parse_args()

    if args.json:
        # Coloured on a terminal, unless --no-format; otherwise the text alone
        configure_output(args)
        print_json_text(
            json.dumps(entries(), indent=JSON_INDENT, cls=CompactJSONEncoder)
        )
        return

    print_listing(deprecated=args.deprecated, no_format=args.no_format)


def print_listing(
    stderr: bool = False, deprecated: bool = False, no_format: bool = False
) -> None:
    """
    The listing, on stdout or (for 'yd' with no command) stderr.
    """
    lines = [
        Text(_heading(), style=HEADING_STYLE),
        Text(),
        *styled_lines(deprecated=deprecated),
        Text(),
        Text(_footer(), style=NOTE_STYLE),
    ]
    if not deprecated:
        lines += [Text(), Text(_deprecation_note(), style=NOTE_STYLE)]

    if no_format:
        out = sys.stderr if stderr else sys.stdout
        print(file=out)
        for line in lines:
            print(line.plain, file=out)
        print(file=out)
        return

    # Rich drops the styles by itself where the stream is not a terminal, or
    # NO_COLOR is set; soft_wrap keeps a long summary on its one line
    console = Console(
        theme=Theme(DEFAULT_THEME), highlight=False, emoji=False, stderr=stderr
    )
    console.print()
    for line in lines:
        console.print(line, soft_wrap=True)
    console.print()


def _heading() -> str:
    return f"YellowDog CLI v{__version__} — available commands:"


def _row(name: str, summary: str, width: int) -> Text:
    """
    A command's line: the padded name in NAME_STYLE, then the summary, with
    a trailing note in NOTE_STYLE.
    """
    line = Text("  ")
    line.append(f"{name:<{width}}", style=NAME_STYLE)
    line.append("  ")
    match = NOTE.search(summary)
    if match:
        line.append(summary[: match.start()])
        line.append(match.group(0), style=NOTE_STYLE)
    else:
        line.append(summary)
    return line


def styled_lines(deprecated: bool = False) -> list[Text]:
    """
    The listing's lines: each noun with its verbs, then the other commands;
    or, if 'deprecated', each deprecated command and its noun forms.
    """
    width = column_width()
    if deprecated:
        return [
            Text("Deprecated commands, and what replaces them:", style=HEADING_STYLE),
            *(_row(name, forms, width) for name, forms in _deprecated_listing()),
        ]
    lines = [Text("Commands by object:", style=HEADING_STYLE)]
    for noun in _nouns():
        lines.append(_row(f"yd {noun.name}", _noun_summary(noun), width))
        lines.append(Text(" " * (width + 4) + _verbs(noun), style=NOTE_STYLE))
    lines += [Text(), Text("Other commands:", style=HEADING_STYLE)]
    lines += [_row(name, shown_summary(summary), width) for name, summary in _listing()]
    return lines


if __name__ == "__main__":
    main()
