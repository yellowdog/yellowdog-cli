"""
The command registry: the data model every yd-* command's options are
defined in, the parser built from it, and the resolution of a command
name from sys.argv[0].
"""

import sys
from argparse import ArgumentParser
from pathlib import Path

import pytest

from yellowdog_cli import help as help_module
from yellowdog_cli.utils.command_registry import (
    COMMANDS,
    COMMON_OPTIONS,
    DESCRIPTION_PREFIX,
    MCP_EXCLUDED_OPTIONS,
    Command,
    CommandKind,
    Exclusive,
    ToolKind,
    build_parser,
    command_from_argv0,
    option,
)

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10: tomli, which the CLI already depends on
    import tomli as tomllib


class TestOption:
    def test_name_is_first_long_flag(self):
        assert option("--namespace", "-n", help="x").name == "--namespace"

    def test_name_of_positional_is_its_dest(self):
        o = option("work_requirements", nargs="*", help="x")
        assert o.name == "work_requirements"
        assert o.positional

    def test_flag_option_is_not_positional(self):
        assert not option("--yes", "-y", action="store_true").positional

    def test_aliases_are_every_other_flag(self):
        o = option("--no-format", "--nf", action="store_true")
        assert o.aliases == ("--nf",)
        assert option("--sort", type=str).aliases == ()

    def test_variant_keeps_identity_and_overrides_kwargs(self):
        base = option("--follow", "-f", action="store_true", help="base help")
        v = base.variant(help="other help")
        assert v.name == base.name
        assert v.flags == base.flags
        assert v.kwargs == {"action": "store_true", "help": "other help"}
        assert base.kwargs["help"] == "base help"  # the original is untouched

    def test_name_of_short_flag_only_option_raises_value_error(self):
        with pytest.raises(ValueError):
            option("-y", action="store_true").name

    def test_register_adds_the_argument_verbatim(self):
        parser = ArgumentParser()
        action = option(
            "--tag", "-t", type=str, nargs="?", const="", metavar="<tag>"
        ).register(parser)
        assert action.option_strings == ["--tag", "-t"]
        assert action.nargs == "?"
        assert action.const == ""
        assert parser.parse_args(["--tag"]).tag == ""


class TestCommand:
    def _command(self, kind=CommandKind.API, **kwargs) -> Command:
        kwargs.setdefault("tool", ToolKind.READ_ONLY)
        return Command(
            name="yd-x", purpose="doing x", summary="Do x", kind=kind, **kwargs
        )

    def test_all_options_prepends_the_kinds_common_set(self, monkeypatch):
        common = option("--debug", action="store_true")
        own = option("--yes", "-y", action="store_true")
        monkeypatch.setitem(COMMON_OPTIONS, CommandKind.API, (common,))
        assert self._command(options=(own,)).all_options() == (common, own)

    def test_flat_options_expands_exclusive_groups(self, monkeypatch):
        monkeypatch.setitem(COMMON_OPTIONS, CommandKind.API, ())
        a, b, c = (option(f"--{n}", action="store_true") for n in "abc")
        cmd = self._command(options=(a, Exclusive((b, c))))
        assert [o.name for o in cmd.flat_options()] == ["--a", "--b", "--c"]

    def test_has_compares_by_identity_not_object(self):
        follow = option("--follow", "-f", action="store_true", help="a")
        cmd = self._command(options=(follow.variant(help="b"),))
        assert cmd.has(follow)
        assert not cmd.has(option("--yes", action="store_true"))

    def test_option_named(self):
        yes = option("--yes", "-y", action="store_true")
        cmd = self._command(options=(yes,))
        assert cmd.option_named("--yes") is yes
        assert cmd.option_named("--no") is None

    def test_requires_namespace_and_tag_defaults_false(self):
        assert self._command().requires_namespace_and_tag is False


class TestCommandFromArgv0:
    @pytest.mark.parametrize(
        "argv0, expected",
        [
            ("yd-submit", "yd-submit"),
            ("/usr/local/bin/yd-submit", "yd-submit"),
            ("/home/user/Downloads/tools/yd-version", "yd-version"),
            ("/home/user/submit/yd-version", "yd-version"),
            ("/x/yellowdog_cli/submit.py", "yd-submit"),
            ("/x/yellowdog_cli/compute_stop.py", "yd-compute-stop"),
            (r"C:\Python\Scripts\yd-submit.exe", "yd-submit"),
            (r"C:\Python\Scripts\yd-submit-script.py", "yd-submit"),
            ("pytest", "yd-pytest"),
        ],
    )
    def test_resolution(self, argv0, expected):
        assert command_from_argv0(argv0) == expected


class TestBuildParser:
    def test_unknown_command_gets_the_api_common_set_and_no_description(
        self, monkeypatch
    ):
        common = option("--debug", action="store_true")
        monkeypatch.setitem(COMMON_OPTIONS, CommandKind.API, (common,))
        parser = build_parser(None)
        assert parser.description is None
        assert parser.parse_args(["--debug"]).debug is True

    def test_command_parser_has_prog_description_and_options_in_order(
        self, monkeypatch
    ):
        monkeypatch.setitem(
            COMMON_OPTIONS, CommandKind.API, (option("--debug", action="store_true"),)
        )
        cmd = Command(
            name="yd-x",
            purpose="doing x",
            summary="Do x",
            kind=CommandKind.API,
            options=(
                option("--yes", "-y", action="store_true"),
                Exclusive(
                    (
                        option("--ids-only", action="store_true"),
                        option("--json", action="store_true"),
                    )
                ),
            ),
            tool=ToolKind.READ_ONLY,
        )
        parser = build_parser(cmd, prog="yd-x")
        assert parser.prog == "yd-x"
        assert parser.description == DESCRIPTION_PREFIX + "doing x"
        names = [a.option_strings[0] for a in parser._actions if a.option_strings]
        assert names == ["-h", "--debug", "--yes", "--ids-only", "--json"]
        with pytest.raises(SystemExit):
            parser.parse_args(["--ids-only", "--json"])  # mutually exclusive


def _entry_points() -> set[str]:
    with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
        return set(tomllib.load(f)["project"]["scripts"])


class TestRegistryMatchesEntryPoints:
    def test_every_entry_point_is_registered_and_vice_versa(self):
        assert set(COMMANDS) == _entry_points() - {"yd-commander", "yd-mcp"}

    def test_rm_is_an_alias_of_delete(self):
        assert COMMANDS["yd-rm"] is COMMANDS["yd-delete"]

    def test_kinds(self):
        data_client = {
            "yd-upload",
            "yd-download",
            "yd-delete",
            "yd-rm",
            "yd-ls",
            "yd-copy",
        }
        standalone = {"yd-help", "yd-version", "yd-format-json", "yd-jsonnet2json"}
        for name, cmd in COMMANDS.items():
            expected = (
                CommandKind.DATA_CLIENT
                if name in data_client
                else CommandKind.STANDALONE
                if name in standalone
                else CommandKind.API
            )
            assert cmd.kind is expected, name

    def test_no_command_registers_a_flag_twice(self):
        for name, cmd in COMMANDS.items():
            flags = [f for o in cmd.flat_options() for f in o.flags]
            assert len(flags) == len(set(flags)), name


class TestHelpCommand:
    def test_lists_every_command_once_with_its_summary(self, capsys):
        help_module.main()
        out = capsys.readouterr().out
        # COMMANDS.items() includes the "yd-rm" alias key, whose Command is
        # yd-delete's own (same object, same .name); format on cmd.name, not
        # the dict key, or the alias entry looks for a "yd-rm" line that was
        # never printed.
        for _, cmd in COMMANDS.items():
            assert f"{cmd.name:<{help_module.column_width()}}  {cmd.summary}" in out
        assert (
            out.count("yd-delete") == 1
        )  # yd-rm is mentioned in yd-delete's summary, not listed again

    def test_commander_is_not_listed(self, capsys):
        help_module.main()
        assert "yd-commander" not in capsys.readouterr().out


class TestToolKinds:
    def test_every_command_states_its_kind(self):
        for command in COMMANDS.values():
            assert isinstance(command.tool, ToolKind), command.name

    def test_the_commands_that_are_not_tools(self):
        # Interactive, or file formatters, or the tool list itself
        assert {n for n, c in COMMANDS.items() if c.tool is ToolKind.NONE} == {
            "yd-cloudwizard",
            "yd-format-json",
            "yd-jsonnet2json",
            "yd-help",
        }

    def test_the_read_only_commands(self):
        assert {n for n, c in COMMANDS.items() if c.tool is ToolKind.READ_ONLY} == {
            "yd-list",
            "yd-show",
            "yd-variables",
            "yd-doctor",
            "yd-application",
            "yd-compare",
            "yd-ls",
            "yd-version",
        }

    def test_the_destructive_commands(self):
        assert {
            n
            for n, c in COMMANDS.items()
            if c.tool is ToolKind.DESTRUCTIVE and n != "yd-rm"
        } == {
            "yd-cancel",
            "yd-abort",
            "yd-shutdown",
            "yd-terminate",
            "yd-remove",
            "yd-delete",
            "yd-hold",
            "yd-start",
            "yd-finish",
            "yd-resize",
            "yd-boost",
            "yd-compute-stop",
            "yd-compute-start",
            "yd-compute-restart",
            "yd-nodeaction",
        }

    def test_the_acting_commands(self):
        assert {n for n, c in COMMANDS.items() if c.tool is ToolKind.ACTING} == {
            "yd-submit",
            "yd-provision",
            "yd-instantiate",
            "yd-create",
            "yd-upload",
            "yd-download",
            "yd-copy",
            "yd-wait",
            "yd-follow",
        }

    def test_a_command_must_state_its_kind(self):
        with pytest.raises(TypeError):
            Command(name="yd-x", purpose="p", summary="s", kind=CommandKind.API)  # type: ignore[call-arg]


class TestExcludedOptions:
    def test_every_excluded_name_is_an_option_of_some_command(self):
        names = {o.name for c in COMMANDS.values() for o in c.flat_options()}
        assert MCP_EXCLUDED_OPTIONS <= names, MCP_EXCLUDED_OPTIONS - names

    def test_the_options_the_server_supplies_itself_are_excluded(self):
        assert {
            "--json",
            "--yes",
            "--config",
            "--no-config",
            "--no-format",
        } <= MCP_EXCLUDED_OPTIONS

    def test_credentials_and_secrets_are_excluded(self):
        assert {
            "--key",
            "--secret",
            "--show-keyring-passwords",
            "--show-secrets",
        } <= MCP_EXCLUDED_OPTIONS
