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

    def test_every_command_is_registered_under_its_own_name(self):
        # No aliases: one name per command
        for name, cmd in COMMANDS.items():
            assert cmd.name == name

    def test_kinds(self):
        data_client = {
            "yd-upload",
            "yd-download",
            "yd-delete",
            "yd-ls",
            "yd-copy",
        }
        standalone = {
            "yd-help",
            "yd-version",
            "yd-format-json",
            "yd-jsonnet2json",
            "yd-schema",
        }
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
    @pytest.fixture(autouse=True)
    def _no_extras_installed(self, monkeypatch):
        # Whatever this machine has installed: each test that needs an
        # extra installed says so
        monkeypatch.setattr(help_module, "extra_installed", lambda extra: False)

    def test_lists_every_command_once_with_its_summary(self, capsys):
        help_module.main()
        out = capsys.readouterr().out
        width = help_module.column_width()
        for name, cmd in COMMANDS.items():
            assert f"{name:<{width}}  {cmd.summary}" in out
            assert out.count(f"{name:<{width}}  ") == 1

    def test_the_entry_points_outside_the_registry_are_listed(self, capsys):
        # yd-commander and yd-mcp take none of the CLI's options and so have
        # no registry entry, but they are commands a user has
        help_module.main()
        out = capsys.readouterr().out
        width = help_module.column_width()
        for name, summary in help_module.OTHER_COMMANDS.items():
            assert f"{name:<{width}}  {summary}" in out, name
        assert "yd-commander" in out and "yd-mcp" in out

    def test_the_other_commands_are_the_entry_points_the_registry_lacks(self):
        # Held both ways, so a new entry point is listed by one or the other
        assert set(help_module.OTHER_COMMANDS) == _entry_points() - set(COMMANDS)

    def test_the_listing_is_coloured(self):
        from rich.text import Text

        # The name and a note (an extra needed, a synonym) carry styles the
        # theme defines; the summary proper is plain
        lines = {t.plain.split()[0]: t for t in help_module.styled_lines()}
        assert all(isinstance(t, Text) for t in lines.values())
        cancel = lines["yd-cancel"]
        assert any(
            s.style == help_module.NAME_STYLE
            and cancel.plain[s.start : s.end].strip() == "yd-cancel"
            for s in cancel.spans
        )
        assert not any(s.style == help_module.NOTE_STYLE for s in cancel.spans)
        mcp = lines["yd-mcp"]
        assert any(
            s.style == help_module.NOTE_STYLE
            and "needs the mcp extra" in mcp.plain[s.start : s.end]
            for s in mcp.spans
        )

    def test_a_parenthesis_inside_a_summary_is_not_a_note(self):
        # 'Hold (pause) running Work Requirements': only a trailing extra
        # note is dimmed, never a parenthesis in the summary's prose
        lines = {t.plain.split()[0]: t for t in help_module.styled_lines()}
        for name in ("yd-hold", "yd-start"):
            line = lines[name]
            assert "(" in line.plain
            assert not any(s.style == help_module.NOTE_STYLE for s in line.spans), name
        cloudwizard = lines["yd-cloudwizard"]
        dimmed = [
            cloudwizard.plain[s.start : s.end]
            for s in cloudwizard.spans
            if s.style == help_module.NOTE_STYLE
        ]
        assert dimmed == [" (needs the cloudwizard extra)"]

    def test_no_format_prints_the_same_text_without_styles(self, capsys, monkeypatch):
        import sys

        monkeypatch.setattr(sys, "argv", ["yd-help"])
        help_module.main()
        styled = capsys.readouterr().out
        monkeypatch.setattr(sys, "argv", ["yd-help", "--no-format"])
        help_module.main()
        plain = capsys.readouterr().out
        # Not a terminal here, so the styled run carries no escape codes either
        assert plain == styled and "\x1b[" not in plain

    def test_the_json_lists_them_too(self, capsys, monkeypatch):
        import json
        import sys

        monkeypatch.setattr(sys, "argv", ["yd-help", "--json"])
        help_module.main()
        listed = {row["command"] for row in json.loads(capsys.readouterr().out)}
        assert {"yd-commander", "yd-mcp"} <= listed

    def test_the_json_states_extras_as_fields(self, monkeypatch):
        monkeypatch.setattr(
            help_module, "extra_installed", lambda extra: extra == "commander"
        )
        records = {r["command"]: r for r in help_module.entries()}
        assert records["yd-commander"]["extra"] == "commander"
        assert records["yd-commander"]["installed"] is True
        assert records["yd-mcp"]["installed"] is False
        # The summary itself is unchanged, and a plain command has neither
        assert records["yd-commander"]["summary"].endswith(
            "(needs the commander extra)"
        )
        assert set(records["yd-cancel"]) == {"command", "summary"}

    def test_an_installed_extra_says_so(self, monkeypatch):
        monkeypatch.setattr(
            help_module, "extra_installed", lambda extra: extra == "mcp"
        )
        lines = {t.plain.split()[0]: t for t in help_module.styled_lines()}
        assert lines["yd-mcp"].plain.endswith("(mcp extra installed)")
        assert lines["yd-commander"].plain.endswith("(needs the commander extra)")
        dimmed = [
            lines["yd-mcp"].plain[s.start : s.end]
            for s in lines["yd-mcp"].spans
            if s.style == help_module.NOTE_STYLE
        ]
        assert dimmed == [" (mcp extra installed)"]

    def test_every_extra_named_has_a_probe(self):
        named = {r["extra"] for r in help_module.entries() if "extra" in r}
        # jsonnet is an extra no command needs, so its probe is the doctor's
        assert named <= set(help_module.EXTRA_PROBES)

    def test_every_probed_extra_is_one_pyproject_offers(self):
        with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
            extras = set(tomllib.load(f)["project"]["optional-dependencies"])
        assert set(help_module.EXTRA_PROBES) <= extras

    def test_the_listing_ends_with_where_to_go_next(self, capsys, monkeypatch):
        import sys

        monkeypatch.setattr(sys, "argv", ["yd-help", "--no-format"])
        help_module.main()
        out = capsys.readouterr().out.strip()
        assert out.splitlines()[-1].startswith("Run 'yd-<command> --help'")
        assert "README.md" in out.splitlines()[-1]


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
            "yd-cloud-info",
            "yd-show",
            "yd-variables",
            "yd-doctor",
            "yd-application",
            "yd-compare",
            "yd-ls",
            "yd-version",
            "yd-schema",
        }

    def test_the_destructive_commands(self):
        assert {n for n, c in COMMANDS.items() if c.tool is ToolKind.DESTRUCTIVE} == {
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
            "yd-compute-deprovision",
            "yd-compute-reprovision",
            "yd-nodeaction",
            "yd-priority",
            "yd-token",
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


class TestCompareIds:
    WR = "ydid:workreq:000000:11111111-1111-1111-1111-111111111111"
    TG = "ydid:taskgrp:000000:11111111-1111-1111-1111-111111111111:1"
    WP = "ydid:wrkrpool:000000:11111111-1111-1111-1111-111111111111"

    def _check(self, wr_or_tg_id: str, *worker_pool_ids: str) -> None:
        from argparse import Namespace

        from yellowdog_cli.utils.command_registry import check_compare_ids

        check_compare_ids(
            Namespace(wr_or_tg_id=wr_or_tg_id, worker_pool_ids=list(worker_pool_ids)),
            build_parser(COMMANDS["yd-compare"], prog="yd-compare"),
        )

    def test_a_work_requirement_or_task_group_and_pools_pass(self):
        self._check(self.WR, self.WP)
        self._check(self.TG, self.WP, self.WP)

    @pytest.mark.parametrize(
        "ids",
        [("nonsense", WP), (WP, WP), (WR, WR), (TG, WP, "ydid:wrkrpool:bad")],
    )
    def test_anything_else_is_a_usage_error(self, ids, capsys):
        with pytest.raises(SystemExit) as raised:
            self._check(*ids)
        assert raised.value.code == 2
        assert "not a YellowDog" in capsys.readouterr().err


class TestResizeTarget:
    CR = "ydid:compreq:000000:11111111-1111-1111-1111-111111111111"
    WP = "ydid:wrkrpool:000000:11111111-1111-1111-1111-111111111111"

    @pytest.mark.parametrize(
        "argv, compute_requirement",
        [
            (["wp-a", "2"], False),
            (["-C", "cr-a", "2"], True),
            ([CR, "2"], True),  # the ID says what it is
            (["-C", CR, "2"], True),
            ([WP, "2"], False),
        ],
    )
    def test_a_compute_requirement_by_option_or_id(self, argv, compute_requirement):
        from yellowdog_cli.utils.args import CLIParser

        assert CLIParser("yd-resize", argv).compute_req_resize is compute_requirement

    def test_the_option_with_a_worker_pool_id_is_refused(self, capsys):
        from yellowdog_cli.utils.args import CLIParser

        with pytest.raises(SystemExit) as raised:
            CLIParser("yd-resize", ["-C", self.WP, "2"])
        assert raised.value.code == 2
        assert "cannot be used with a Worker Pool ID" in capsys.readouterr().err


class TestArgsProperties:
    def test_every_property_reads_an_option_some_command_registers(self):
        # A property reading a destination no option has would return None
        # under @allow_missing_attribute, silently disabling its option
        import inspect
        import re

        from yellowdog_cli.utils import args as args_module

        destinations = {
            action.dest
            for name, command in [*COMMANDS.items(), ("x", None)]
            for action in build_parser(command, prog=name)._actions
        }
        read = set(re.findall(r"self\.args\.(\w+)", inspect.getsource(args_module)))
        assert read and read <= destinations, sorted(read - destinations)

    @pytest.mark.parametrize("command", ["yd-delete", "yd-wait", "yd-copy"])
    def test_docs_is_answered_before_anything_is_checked(self, command, capsys):
        # A required argument missing, or a validator's refusal, used to stand
        # in the way of '--docs'
        from yellowdog_cli.utils.args import CLIParser

        with pytest.raises(SystemExit) as raised:
            CLIParser(command=command, argv=["--docs"])
        assert raised.value.code == 0
        assert "Online documentation" in capsys.readouterr().out


class TestRemotePathsWithParentSegments:
    """
    A '..' segment in a remote path climbs out of the prefix (or the bucket)
    past the checks that refuse deleting or syncing over the remote's root or
    the bucket, so the commands that delete or write remotely refuse it as
    parsed. yd-ls only reads, and a local path may climb as it likes.
    """

    @pytest.mark.parametrize(
        "command, argv",
        [
            ("yd-delete", ["-R", ".."]),
            ("yd-delete", ["a/../../b"]),
            ("yd-delete", ["myremote:bucket/.."]),
            ("yd-download", [".."]),
            ("yd-download", ["--sync", "x/.."]),
            ("yd-copy", ["../a", "b"]),
            ("yd-copy", ["a", "b/../.."]),
            ("yd-upload", ["f.txt", "-d", "../x"]),
        ],
    )
    def test_refused(self, command, argv, capsys):
        from yellowdog_cli.utils.args import CLIParser

        with pytest.raises(SystemExit) as raised:
            CLIParser(command, argv)
        assert raised.value.code == 2
        assert "'..'" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "command, argv",
        [
            ("yd-ls", [".."]),
            ("yd-download", ["a..b"]),
            ("yd-download", ["x", "-d", "../out"]),
            ("yd-download", ["x", "--into", "../out"]),
            ("yd-upload", ["../f.txt"]),
        ],
    )
    def test_accepted(self, command, argv):
        from yellowdog_cli.utils.args import CLIParser

        CLIParser(command, argv)
