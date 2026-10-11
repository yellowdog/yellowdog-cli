"""
The noun commands (utils/noun_registry.py, utils/noun_dispatch.py): every
verb runs a registry command, every registry command is accounted for, the
derived commands narrow their options and targets to the object, and the
dispatcher selects the verb's command and hands it the verb's arguments.
"""

import sys
from argparse import SUPPRESS
from pathlib import Path
from types import SimpleNamespace

import pytest

from yellowdog_cli.utils import args as args_module
from yellowdog_cli.utils import noun_dispatch
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.command_registry import COMMANDS, build_parser
from yellowdog_cli.utils.exit_codes import ExitCode
from yellowdog_cli.utils.noun_registry import (
    DEPRECATED,
    GENERIC_COMMANDS,
    INSTANCE,
    NAME,
    NOUN_COMMANDS,
    NOUNS,
    NOUNS_BY_NAME,
    command_named,
    noun_forms,
    target_kind,
)
from yellowdog_cli.utils.ydid_utils import YDIDType

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10
    import tomli as tomllib

_UUID = "00000000-0000-0000-0000-000000000000"
CR_ID = f"ydid:compreq:abc123:{_UUID}"
WP_ID = f"ydid:wrkrpool:abc123:{_UUID}"
WR_ID = f"ydid:workreq:abc123:{_UUID}"
NODE_ID = f"ydid:node:abc123:{_UUID}"
INSTANCE_SPEC = f"{CR_ID}.i-0123456789"

# The registry commands no noun replaces and which are not offered under
# one: the utilities, kept as they are
UTILITIES = {
    "yd-application",
    "yd-cloudwizard",
    "yd-completion",
    "yd-doctor",
    "yd-variables",
    "yd-schema",
    "yd-format-json",
    "yd-jsonnet2json",
    "yd-help",
    "yd-version",
}


def _scripts() -> dict[str, str]:
    with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["scripts"]


@pytest.fixture(autouse=True)
def _no_selection(monkeypatch):
    # The dispatcher's selection is module state: no test leaves it behind
    monkeypatch.setattr(args_module, "_SELECTED", None)


class TestTheRegistry:
    def test_every_verb_runs_a_registry_command(self):
        for noun in NOUNS:
            for verb in noun.verbs:
                assert verb.command in COMMANDS, (noun.name, verb.name)

    def test_verb_names_are_unique_within_a_noun(self):
        for noun in NOUNS:
            names = [verb.name for verb in noun.verbs]
            assert len(names) == len(set(names)), noun.name

    def test_every_registry_command_is_accounted_for(self):
        # A new command is replaced by a noun verb, offered under the nouns
        # as a generic one, or kept as a utility: a decision either way
        for name in COMMANDS:
            assert (name in DEPRECATED) + (name in GENERIC_COMMANDS) + (
                name in UTILITIES
            ) == 1, name

    def test_the_generic_commands_are_offered_under_nouns_too(self):
        for name in GENERIC_COMMANDS:
            assert noun_forms(name), name

    def test_every_noun_and_alias_is_an_entry_point_of_its_own_module(self):
        scripts = _scripts()
        for noun in NOUNS:
            module = f"yellowdog_cli.nouns.{noun.name.removeprefix('yd-')}:main"
            for invoked in noun.invoked_names():
                assert scripts.get(invoked) == module, invoked

    def test_the_aliases(self):
        aliases = {noun.alias: noun.name for noun in NOUNS if noun.alias}
        assert aliases == {
            "yd-wr": "yd-workrequirement",
            "yd-tg": "yd-taskgroup",
            "yd-wp": "yd-workerpool",
            "yd-cr": "yd-computerequirement",
        }

    def test_no_noun_or_alias_is_a_registry_command(self):
        assert not set(NOUNS_BY_NAME) & set(COMMANDS)

    def test_deprecated_names_map_to_their_noun_forms(self):
        assert DEPRECATED["yd-submit"] == ["yd-workrequirement submit"]
        assert set(DEPRECATED["yd-terminate"]) == {
            "yd-computerequirement terminate",
            "yd-instance terminate",
            "yd-node terminate",
        }
        assert "yd-list" not in DEPRECATED


class TestDerivedCommands:
    def test_named_for_the_noun_form_and_running_the_registry_command(self):
        command = NOUN_COMMANDS["yd-instance terminate"]
        assert command.name == "yd-instance terminate"
        assert command.internal_name == "yd-terminate"
        assert command_named("yd-instance terminate") is command
        assert command_named("yd-terminate") is COMMANDS["yd-terminate"]

    def test_a_registry_command_runs_itself(self):
        assert COMMANDS["yd-submit"].internal_name == "yd-submit"

    def test_hidden_options_keep_their_identity_but_not_their_help(self):
        command = NOUN_COMMANDS["yd-instance terminate"]
        namespace = command.option_named("--namespace")
        assert namespace is not None
        assert namespace.kwargs["help"] == SUPPRESS
        assert "--namespace" not in build_parser(command).format_help()

    def test_a_fixed_positional_is_hidden(self):
        help_text = build_parser(NOUN_COMMANDS["yd-workrequirement list"]).format_help()
        assert "ENTITY_TYPE" not in help_text
        # Filters that do not apply to the type are hidden; those that do
        # are offered
        assert "--status" in help_text
        assert "--public-ips-only" not in help_text

    def test_an_id_only_verb_needs_a_target(self):
        option = NOUN_COMMANDS["yd-instance terminate"].option_named(
            "compute_reqs_instances_or_nodes"
        )
        assert option is not None and option.kwargs["nargs"] == "+"


def _parse(command: str, *argv: str) -> CLIParser:
    return CLIParser(command=command, argv=list(argv))


def _refusal(capsys, command: str, *argv: str) -> str:
    with pytest.raises(SystemExit) as exit_:
        _parse(command, *argv)
    assert exit_.value.code == ExitCode.USAGE
    return capsys.readouterr().err


class TestParsing:
    def test_the_parser_reports_the_registry_command_it_runs(self):
        parser = _parse("yd-instance terminate", INSTANCE_SPEC)
        assert parser.command_name == "yd-terminate"
        assert parser.parser.prog == "yd-instance terminate"
        assert parser.args.compute_reqs_instances_or_nodes == [INSTANCE_SPEC]

    def test_a_target_of_another_kind_is_refused(self, capsys):
        err = _refusal(capsys, "yd-instance terminate", WP_ID)
        assert "is a Worker Pool ID" in err
        assert "<cr-id.instance-id>" in err

    def test_a_name_is_refused_where_only_ids_are_taken(self, capsys):
        assert "is a name" in _refusal(capsys, "yd-node shutdown", "pool-1")

    def test_names_and_ids_are_taken_where_names_are(self):
        parser = _parse("yd-computerequirement terminate", "cr-1", CR_ID)
        assert parser.args.compute_reqs_instances_or_nodes == ["cr-1", CR_ID]

    def test_a_hidden_option_given_is_refused(self, capsys):
        err = _refusal(
            capsys, "yd-instance terminate", "--namespace", "x", INSTANCE_SPEC
        )
        assert "--namespace does not apply to yd-instance terminate" in err

    def test_a_hidden_option_left_alone_is_not_refused(self):
        # --sort's default is a string its type converts: still a default
        _parse("yd-instance stop", INSTANCE_SPEC)

    def test_show_restricted_to_the_object(self, capsys):
        _parse("yd-workrequirement show", WR_ID)
        assert "is a Worker Pool ID" in _refusal(
            capsys, "yd-workrequirement show", WP_ID
        )

    def test_resource_list_takes_resource_types_only(self, capsys):
        assert _parse("yd-resource list", "keyr").args.entity_type == "keyrings"
        assert "not a resource type" in _refusal(
            capsys, "yd-resource list", "work-requirements"
        )

    def test_a_single_target_is_checked(self, capsys):
        assert "is a Compute Requirement ID" in _refusal(
            capsys, "yd-workerpool resize", CR_ID, "2"
        )

    def test_follow_json_prints_events_under_a_noun_too(self):
        assert _parse("yd-workrequirement follow", "--json", WR_ID).events_as_json


class TestTargetKind:
    @pytest.mark.parametrize(
        "target,kind",
        [
            (INSTANCE_SPEC, INSTANCE),
            (CR_ID, YDIDType.COMPUTE_REQUIREMENT),
            (NODE_ID, YDIDType.NODE),
            ("my.pool", NAME),
            ("pool-*", NAME),
        ],
    )
    def test_kinds(self, target, kind):
        assert target_kind(target) == kind


class TestDispatch:
    @pytest.fixture
    def ran(self, monkeypatch):
        """
        The dispatcher run with a stand-in for the command module: what it
        selected and the command line it handed on.
        """
        record = SimpleNamespace(module=None, argv=None, selected=None)

        def main():
            record.argv = list(sys.argv)
            record.selected = args_module._SELECTED

        def import_module(name):
            record.module = name
            return SimpleNamespace(main=main)

        monkeypatch.setattr(noun_dispatch, "import_module", import_module)
        return record

    def _run(self, monkeypatch, *argv: str, noun: str = "yd-workrequirement"):
        monkeypatch.setattr(sys, "argv", list(argv))
        noun_dispatch.run_noun(noun)

    def test_runs_the_verbs_command_with_its_parser_selected(self, monkeypatch, ran):
        self._run(monkeypatch, "/bin/yd-wr", "submit", "-y", "wr.json")
        assert ran.module == "yellowdog_cli.submit"
        assert ran.selected == ("yd-workrequirement submit", "yd-wr submit")
        assert ran.argv == ["/bin/yd-wr", "-y", "wr.json"]

    def test_fixed_arguments_come_first(self, monkeypatch, ran):
        self._run(monkeypatch, "yd-workrequirement", "list", "--active-only")
        assert ran.module == "yellowdog_cli.list"
        assert ran.argv == ["yd-workrequirement", "work-requirements", "--active-only"]

    def test_python_m_shows_the_full_noun(self, monkeypatch, ran):
        self._run(monkeypatch, "/x/nouns/workrequirement.py", "cancel")
        assert ran.selected == (
            "yd-workrequirement cancel",
            "yd-workrequirement cancel",
        )

    def test_help(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exit_:
            self._run(monkeypatch, "yd-wr", "--help")
        assert exit_.value.code == ExitCode.SUCCESS
        out = capsys.readouterr().out
        assert "usage: yd-wr <verb>" in out
        assert "submit    Submit a Work Requirement" in out
        assert "'yd-wr' is short for 'yd-workrequirement'" in out

    def test_no_verb_is_a_usage_error(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exit_:
            self._run(monkeypatch, "yd-wr")
        assert exit_.value.code == ExitCode.USAGE
        assert "verbs:" in capsys.readouterr().err

    def test_an_unknown_verb_is_a_usage_error(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exit_:
            self._run(monkeypatch, "yd-wr", "frob")
        assert exit_.value.code == ExitCode.USAGE
        err = capsys.readouterr().err
        assert "unknown verb 'frob'" in err and "submit, cancel" in err

    def test_an_option_before_the_verb_is_a_usage_error(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exit_:
            self._run(monkeypatch, "yd-wr", "-y", "submit")
        assert exit_.value.code == ExitCode.USAGE
        assert "a verb must come before '-y'" in capsys.readouterr().err

    def test_the_selection_builds_the_verbs_parser(self, monkeypatch):
        args_module.select_command("yd-instance terminate", "yd-instance terminate")
        monkeypatch.setattr(sys, "argv", ["yd-instance", INSTANCE_SPEC])
        parser = CLIParser()
        assert parser.command is NOUN_COMMANDS["yd-instance terminate"]
        assert parser.parser.prog == "yd-instance terminate"
        assert parser.replaced_by == []


class TestDeprecatedNames:
    @pytest.mark.parametrize(
        "argv0", ["yd-submit", "/usr/bin/yd-submit", r"C:\bin\yd-submit.exe"]
    )
    def test_an_old_name_typed_is_replaced(self, monkeypatch, argv0):
        monkeypatch.setattr(sys, "argv", [argv0, "--dry-run"])
        assert CLIParser().replaced_by == ["yd-workrequirement submit"]

    def test_python_m_is_not_deprecated(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["/x/yellowdog_cli/submit.py", "--dry-run"])
        assert CLIParser().replaced_by == []

    def test_a_generic_command_is_not_deprecated(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["yd-list", "work-requirements"])
        assert CLIParser().replaced_by == []


class TestDeprecationWarning:
    def _warned(self, monkeypatch, capsys, *argv: str) -> tuple[str, str]:
        from yellowdog_cli.utils import output_settings
        from yellowdog_cli.utils.command_runner import warn_if_deprecated

        monkeypatch.setattr(sys, "argv", list(argv))
        parser = CLIParser()
        with output_settings.configured(parser):
            warn_if_deprecated(parser)
        captured = capsys.readouterr()
        return captured.out, captured.err

    def test_an_old_name_is_warned_of_on_stderr(self, monkeypatch, capsys):
        out, err = self._warned(monkeypatch, capsys, "yd-submit", "--no-format")
        assert out == ""
        assert "'yd-submit' is deprecated" in err
        assert "use 'yd-workrequirement submit'" in err

    def test_every_noun_form_is_offered(self, monkeypatch, capsys):
        _, err = self._warned(monkeypatch, capsys, "yd-terminate", "--no-format")
        assert (
            "'yd-computerequirement terminate', 'yd-instance terminate' or"
            " 'yd-node terminate'" in " ".join(err.split())
        )

    def test_quiet_suppresses_it(self, monkeypatch, capsys):
        assert self._warned(monkeypatch, capsys, "yd-submit", "-q") == ("", "")

    def test_a_noun_form_is_not_warned_of(self, monkeypatch, capsys):
        args_module.select_command("yd-workrequirement submit", "yd-wr submit")
        assert self._warned(monkeypatch, capsys, "yd-wr", "--no-format") == ("", "")
