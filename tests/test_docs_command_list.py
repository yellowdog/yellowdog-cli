"""
The Command List (docs/commands.md, which the README points to) agrees
with the command registry: the Universal
and Shared option tables list real options with the right short forms and
the right reach, and every option bullet (or option-table row) in a command's
section names an option that command takes. Wording is never checked.
"""

import re
from pathlib import Path

import pytest

from yellowdog_cli.utils.command_registry import COMMANDS, CommandKind

COMMAND_LIST = Path(__file__).parent.parent / "docs" / "commands.md"

FLAG = re.compile(r"`(-{1,2}[A-Za-z][\w-]*)")  # the flag inside a backticked form
# A table row's first cell; `\|` is an escaped pipe inside it, as in `--sort`'s.
TABLE_ROW = re.compile(r"^\| (`(?:\\\||[^|])*`) \|")


def _outside_fences(text: str) -> str:
    """
    The text with every line inside a fenced code block (the fences included)
    blanked, keeping its length and line breaks so that offsets still index
    the original. A shell comment in an example is not a heading, nor a line
    of one a bullet.
    """
    lines = text.splitlines(keepends=True)
    in_fence = False
    for i, line in enumerate(lines):
        fence = line.lstrip().startswith("```")
        if fence or in_fence:
            lines[i] = re.sub(r"[^\n]", " ", line)
        if fence:
            in_fence = not in_fence
    return "".join(lines)


def _command_list() -> str:
    return COMMAND_LIST.read_text(encoding="utf-8")


def _heading(text: str, heading: str) -> re.Match[str] | None:
    """
    The heading's line: '### yd-delete'.
    """
    return re.search(rf"^{re.escape(heading)}$", _outside_fences(text), re.M)


def _section(text: str, heading: str) -> str:
    """
    The text under a heading, up to the next heading of the same or higher level.
    """
    level = heading.split(" ")[0]
    found = _heading(text, heading)
    assert found is not None, f"no heading {heading!r}"
    rest = text[found.start() :]
    body = rest.index("\n") + 1  # search for the next heading after this one's own line
    match = re.search(rf"^#{{1,{len(level)}}} ", _outside_fences(rest)[body:], re.M)
    return rest if match is None else rest[: body + match.start()]


def _table_options(section: str) -> list[tuple[str, tuple[str, ...]]]:
    """
    (long flag, aliases) for each row of the section's table.
    """
    rows = []
    for line in _outside_fences(section).splitlines():
        m = TABLE_ROW.match(line)
        if m and not m.group(1).startswith("`Option"):
            flags = FLAG.findall(m.group(1))
            rows.append((flags[0], tuple(flags[1:])))
    return rows


def _bullet_flags(section: str) -> list[str]:
    """
    The flags each option bullet, or option-table row, names before its description.
    """
    flags = []
    for line in _outside_fences(section).splitlines():
        if line.startswith("- `--"):
            flags += FLAG.findall(line.split(" — ")[0])
        elif line.startswith("| `-") and (m := TABLE_ROW.match(line)):
            # yd-list documents its options as a table rather than as bullets
            flags += FLAG.findall(m.group(1))
    return flags


CLI_COMMANDS = {
    n: c for n, c in COMMANDS.items() if c.kind is not CommandKind.STANDALONE
}
API_COMMANDS = {n: c for n, c in CLI_COMMANDS.items() if c.kind is CommandKind.API}
DATA_CLIENT_COMMANDS = {
    n: c for n, c in CLI_COMMANDS.items() if c.kind is CommandKind.DATA_CLIENT
}
WITHHELD_FROM_DATA_CLIENT = {"--key", "--secret", "--url", "--pac"}


def _commands_with(flag: str) -> set[str]:
    return {n for n, c in CLI_COMMANDS.items() if c.option_named(flag) is not None}


class TestUniversalOptions:
    section = _section(_command_list(), "## Universal Options")
    rows = _table_options(section)

    def test_table_is_not_empty(self):
        assert len(self.rows) >= 10

    @pytest.mark.parametrize("flag, aliases", rows, ids=[r[0] for r in rows])
    def test_option_is_on_every_command_it_should_be(self, flag, aliases):
        expected = set(API_COMMANDS)
        if flag not in WITHHELD_FROM_DATA_CLIENT:
            expected |= set(DATA_CLIENT_COMMANDS)
        assert _commands_with(flag) == expected

    @pytest.mark.parametrize("flag, aliases", rows, ids=[r[0] for r in rows])
    def test_aliases_match_the_registry(self, flag, aliases):
        registered = next(iter(API_COMMANDS.values())).option_named(flag)
        assert registered is not None
        assert set(aliases) == set(registered.aliases)

    def test_nothing_universal_is_missing_from_the_table(self):
        on_every_api_command = set.intersection(
            *({o.name for o in c.flat_options()} for c in API_COMMANDS.values())
        )
        assert on_every_api_command == {flag for flag, _ in self.rows}

    def test_preamble_names_the_standalone_commands(self):
        standalone = {
            n for n, c in COMMANDS.items() if c.kind is CommandKind.STANDALONE
        }
        named = set(re.findall(r"`(yd-[\w-]+)`", self.section.split("\n\n")[1]))
        assert named == standalone | {"yd-commander", "yd-mcp"}

    def test_preamble_names_the_withheld_options(self):
        assert (
            set(FLAG.findall(self.section.split("\n\n")[2]))
            == WITHHELD_FROM_DATA_CLIENT
        )


class TestSharedOptions:
    rows = _table_options(_section(_command_list(), "## Shared Options"))

    def test_table_is_not_empty(self):
        assert len(self.rows) >= 5

    @pytest.mark.parametrize("flag, aliases", rows, ids=[r[0] for r in rows])
    def test_on_some_but_not_all_commands(self, flag, aliases):
        holders = _commands_with(flag)
        assert 2 <= len(holders) < len(CLI_COMMANDS), flag

    @pytest.mark.parametrize("flag, aliases", rows, ids=[r[0] for r in rows])
    def test_aliases_match_the_registry(self, flag, aliases):
        holders = sorted(_commands_with(flag))
        assert holders, f"{flag} is an option of no command"
        for name in holders:
            registered = CLI_COMMANDS[name].option_named(flag)
            assert registered is not None
            assert set(aliases) == set(registered.aliases), name


DOCUMENTED = sorted(n for n in CLI_COMMANDS if n != "yd-cloudwizard")


STANDALONE_DOCUMENTED = sorted(
    n for n, c in COMMANDS.items() if c.kind is CommandKind.STANDALONE
)


class TestCommandSections:
    text = _command_list()

    @pytest.mark.parametrize("name", DOCUMENTED)
    def test_every_command_has_a_section(self, name):
        assert _heading(self.text, f"### {name}") is not None

    @pytest.mark.parametrize("name", STANDALONE_DOCUMENTED)
    def test_every_standalone_command_has_a_section(self, name):
        assert _heading(self.text, f"### {name}") is not None

    @pytest.mark.parametrize("name", DOCUMENTED)
    def test_every_option_bullet_names_an_option_of_the_command(self, name):
        section = _section(self.text, f"### {name}")
        command = CLI_COMMANDS[name]
        known = {f for o in command.flat_options() for f in o.flags}
        unknown = [f for f in _bullet_flags(section) if f not in known]
        assert unknown == [], f"{name} bullets name options it does not take: {unknown}"
