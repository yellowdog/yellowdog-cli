"""
Shell completion: utils/completion.py's complete() over the registries, the
'yd completion --complete' protocol the stubs speak, the stubs themselves
(run in bash, zsh, fish and PowerShell where those are installed: fish's
'complete -C' and PowerShell's TabExpansion2 completing a command line as a
Tab would), and the registry's Completes markings held to the metavars.
"""

import os
import re
import shutil
import subprocess
import sys
import time

import pytest

from yellowdog_cli import completion as yd_completion
from yellowdog_cli.utils import completion_lookups
from yellowdog_cli.utils.command_registry import (
    COMMANDS,
    ENTITY_TYPES,
    Completes,
)
from yellowdog_cli.utils.completion import (
    Candidate,
    Mode,
    complete,
    join_bash_words,
)
from yellowdog_cli.utils.entity_names import ET_WORK_REQUIREMENTS
from yellowdog_cli.utils.limits import LOOKUP_TIMEOUT_SECONDS
from yellowdog_cli.utils.noun_registry import (
    NOUN_COMMANDS,
    NOUNS,
    REPLACED_BY_VERBS,
    RESOURCE_LIST_TYPES,
)
from yellowdog_cli.utils.settings import YD_COMPLETION_LOOKUPS
from yellowdog_cli.utils.top_level import TOP_LEVEL


def _values(words: list[str], current: str = "") -> list[str]:
    result = complete(words, current)
    assert result.mode is Mode.VALUES
    return [candidate.value for candidate in result.candidates]


class TestNounsAndVerbs:
    def test_a_noun_offers_its_verbs_with_their_summaries(self):
        result = complete(["yd", "workrequirement"], "")
        noun = next(n for n in NOUNS if n.name == "workrequirement")
        assert [c.value for c in result.candidates] == [v.name for v in noun.verbs]
        assert result.candidates[0].description == noun.verbs[0].summary

    def test_the_short_form_offers_the_same(self):
        assert _values(["yd", "wr"]) == _values(["yd", "workrequirement"])

    def test_the_verbs_are_filtered_by_what_is_typed(self):
        assert _values(["yd", "wr"], "s") == ["submit", "start", "show"]

    def test_a_dash_at_the_verb_offers_help(self):
        assert _values(["yd", "wr"], "-") == ["--help"]

    def test_an_unknown_verb_offers_nothing(self):
        assert _values(["yd", "wr", "nonesuch"], "-") == []

    def test_a_deprecated_command_offers_nothing(self):
        assert _values(["yd-submit"], "--") == []

    def test_an_unknown_command_offers_nothing(self):
        assert _values(["yd", "nonesuch"], "--") == []
        assert _values([], "") == []

    @pytest.mark.parametrize("word", ["commander", "mcp"])
    def test_a_command_the_registry_does_not_describe_completes_files(self, word):
        # Before the stubs claimed its name, the shell completed files for it
        assert complete(["yd", word], "").mode is Mode.FILES
        assert complete(["yd", word, "config.toml", "-r"], "w").mode is Mode.FILES
        assert _values(["yd", word], "-") == ["--help"]

    def test_a_described_standalone_command_is_not_left_to_the_shell(self):
        assert _values(["yd", "completion"], "z") == ["zsh"]

    @pytest.mark.parametrize(
        "word, options",
        [
            ("format-json", ["--check", "--help"]),
            ("jsonnet2json", ["--no-format", "--yes", "--help"]),
        ],
    )
    def test_a_standalone_command_completes_its_files_and_options(self, word, options):
        # Its files positional is marked as files, so the shell completes them
        assert complete(["yd", word], "").mode is Mode.FILES
        assert sorted(_values(["yd", word], "-")) == sorted(options)

    def test_yd_versions_options_complete(self):
        assert _values(["yd", "version"], "--j") == ["--jsonnet", "--json"]

    def test_the_command_may_be_a_path_or_an_exe(self):
        assert _values(["/usr/local/bin/yd", "wr"], "s") == ["submit", "start", "show"]
        assert _values(["C:\\bin\\yd.exe", "wr"], "s") == ["submit", "start", "show"]


class TestOptions:
    def test_a_verb_offers_its_options_with_their_help(self):
        result = complete(["yd", "wr", "submit"], "--fol")
        assert [c.value for c in result.candidates] == ["--follow"]
        assert result.candidates[0].description

    def test_a_hidden_option_is_never_offered(self):
        # yd instance takes Instances by ID: no namespace or tag selection
        offered = _values(["yd", "instance", "terminate"], "--")
        assert "--namespace" not in offered
        assert "--tag" not in offered
        assert "--yes" in offered

    def test_a_given_option_is_not_offered_again(self):
        assert "--follow" not in _values(["yd", "wr", "submit", "--follow"], "--")

    def test_a_given_option_is_not_offered_again_by_its_short_flag(self):
        assert "--follow" not in _values(["yd", "wr", "submit", "-f"], "--")

    def test_a_repeatable_option_is_offered_again(self):
        words = ["yd", "wr", "submit", "--variable", "a=1"]
        assert "--variable" in _values(words, "--")

    def test_an_exclusive_group_with_a_member_given_is_not_offered(self):
        words = ["yd", "data", "download", "x", "--into", "out"]
        assert "--destination" not in _values(words, "--")

    def test_a_short_flag_typed_in_full_completes_to_itself(self):
        assert _values(["yd", "wr", "submit"], "-f") == ["-f"]

    def test_help_is_offered(self):
        assert "--help" in _values(["yd", "wr", "submit"], "--")

    def test_an_empty_word_with_no_positional_values_offers_options(self):
        assert "--yes" in _values(["yd", "wr", "cancel"], "")

    def test_a_double_dash_ends_options(self):
        assert _values(["yd", "wr", "cancel", "--"], "--") == []

    def test_an_optional_value_may_be_left_out(self):
        # '--namespace' takes a value or none: a dash after it is an option
        assert "--follow" in _values(["yd", "wr", "cancel", "--namespace"], "--f")

    def test_the_value_of_an_optional_value_option_is_not_a_positional(self):
        words = ["yd", "workerpool", "resize", "--namespace", "ns"]
        # The next word is the first positional, which offers nothing
        assert _values(words, "x") == []


class TestValues:
    def test_choices(self):
        words = ["yd", "cloudinfo", "prices", "--provider"]
        assert _values(words) == ["aws", "azure", "google", "oci"]

    def test_choices_after_an_equals(self):
        words = ["yd", "cloudinfo", "prices"]
        assert _values(words, "--provider=a") == ["--provider=aws", "--provider=azure"]

    @pytest.mark.parametrize(
        "current, offered",
        [
            # Matched in any case, as the CLI reads the type, and offered in
            # the case typed, so that a shell matching case keeps them
            ("k", ["keyring"]),
            ("K", ["Keyring"]),
            ("KEY", ["Keyring"]),
            ("namespacep", ["namespacepolicy"]),
            ("Name", ["Namespace", "NamespacePolicy"]),
        ],
    )
    def test_a_resource_type_in_any_case(self, current, offered):
        assert _values(["yd", "resource", "remove", "--type"], current) == offered

    def test_a_resource_type_with_nothing_typed_is_offered_as_written(self):
        offered = _values(["yd", "resource", "create", "--type"])
        assert "ComputeSourceTemplate" in offered and len(offered) == 15

    def test_a_resource_type_after_an_equals(self):
        assert _values(["yd", "resource", "create"], "--type=keyr") == [
            "--type=keyring"
        ]

    def test_other_choices_still_match_their_case(self):
        assert _values(["yd", "cloudinfo", "prices", "--provider"], "A") == []

    def test_an_unknown_option_after_an_equals_offers_nothing(self):
        assert _values(["yd", "wr", "cancel"], "--nonesuch=") == []

    def test_sort_keys_after_a_comma_each_once(self):
        words = ["yd", "wr", "cancel", "--sort"]
        assert _values(words, "name,") == [
            "name,created",
            "name,status",
            "name,namespace",
        ]

    def test_entity_types(self):
        assert _values(["yd", "list"], "work") == [
            t for t in ENTITY_TYPES if t.startswith("work")
        ]

    def test_a_verb_narrows_the_entity_types(self):
        assert _values(["yd", "resource", "list"]) == sorted(RESOURCE_LIST_TYPES)

    def test_a_fixed_positional_is_not_offered(self):
        # 'yd wr list' supplies the entity type itself
        assert "work-requirements" not in _values(["yd", "wr", "list"])

    def test_a_value_the_cli_does_not_know_offers_nothing(self):
        assert _values(["yd", "wr", "cancel", "--namespace"]) == []

    @pytest.mark.parametrize(
        "words, mode",
        [
            (["yd", "wr", "submit", "--config"], Mode.FILES),
            (["yd", "wr", "submit"], Mode.FILES),  # the specification positional
            (["yd", "resource", "create"], Mode.FILES),
            (["yd", "data", "upload"], Mode.FILES),
            (["yd", "schema", "--write"], Mode.DIRS),
            (["yd", "data", "download", "x", "--into"], Mode.DIRS),
        ],
    )
    def test_files_and_directories(self, words, mode):
        assert complete(words, "").mode is mode

    def test_a_file_after_an_equals(self):
        assert complete(["yd", "wr", "submit"], "--config=c").mode is Mode.FILES

    def test_positionals_are_counted(self):
        # yd workerpool resize <pool> <size>: both given, so options
        words = ["yd", "workerpool", "resize", "pool", "3"]
        assert "--yes" in _values(words)


class TestLookups:
    """
    An entity argument is completed from the Platform: complete() names the
    lookup and the configuration options typed, and the command makes it.
    """

    @pytest.mark.parametrize(
        "words, entity, task_groups",
        [
            (["yd", "task", "list", "--within"], ET_WORK_REQUIREMENTS, True),
            (["yd", "tg", "list", "--within"], ET_WORK_REQUIREMENTS, True),
            (["yd", "instance", "list", "--within"], "compute-requirements", False),
            (["yd", "node", "list", "--within"], "worker-pools", False),
            (["yd", "worker", "list", "--within"], "worker-pools", False),
            (["yd", "list", "tasks", "--within"], ET_WORK_REQUIREMENTS, True),
            (["yd", "list", "inst", "--within"], "compute-requirements", False),
            (["yd", "list", "W", "--sort", "name", "--within"], None, False),
        ],
    )
    def test_within_looks_up_its_parent(self, words, entity, task_groups):
        result = complete(words, "my")
        if entity is None:
            # Work Requirements have no parent to list within
            assert result.lookup is None
            return
        assert result.lookup is not None
        assert result.lookup.lookup.entity == entity
        assert result.lookup.lookup.ids is False
        assert result.lookup.lookup.tagged is False
        assert result.lookup.lookup.task_groups is task_groups
        assert result.lookup.current == "my"

    @pytest.mark.parametrize(
        "words, resource",
        [
            (["yd", "resource", "remove", "--type", "Keyring"], "Keyring"),
            (["yd", "resource", "remove", "--type", "keyring"], "Keyring"),
            (["yd", "resource", "remove", "--type=Group"], "Group"),
            (["yd", "resource", "show", "--type", "Namespace", "dev"], "Namespace"),
            (["yd", "show", "--type", "Credential"], "Credential"),
        ],
    )
    def test_a_resource_type_looks_up_its_names(self, words, resource):
        result = complete(words, "te")
        assert result.lookup is not None
        assert result.lookup.lookup.resource == resource
        assert result.lookup.current == "te"

    @pytest.mark.parametrize(
        "words",
        [
            ["yd", "resource", "remove"],  # files, with no --type
            ["yd", "resource", "remove", "--type", "Keyrings"],  # no such type
            ["yd", "resource", "create", "--type", "Keyring"],  # files to create
        ],
    )
    def test_no_resource_lookup_without_a_type_to_remove_or_show(self, words):
        assert complete(words, "x").lookup is None

    def test_an_ambiguous_type_looks_nothing_up_for_within(self):
        assert complete(["yd", "list", "t", "--within"], "").lookup is None

    def test_an_action_verb_looks_up_names(self):
        result = complete(["yd", "wr", "cancel"], "")
        assert result.lookup is not None
        assert result.lookup.lookup.entity == ET_WORK_REQUIREMENTS
        assert result.lookup.lookup.ids is False

    def test_with_nothing_typed_the_options_are_the_fallback(self):
        result = complete(["yd", "wr", "cancel"], "")
        assert "--yes" in [candidate.value for candidate in result.candidates]

    def test_with_a_word_begun_only_the_lookup_answers(self):
        result = complete(["yd", "wr", "cancel"], "my")
        assert result.lookup is not None
        assert result.lookup.current == "my"
        assert result.candidates == ()

    def test_a_show_verb_looks_up_names(self):
        # Its noun gives a name its type, so names are offered, as an action's are
        result = complete(["yd", "wr", "show"], "")
        assert result.lookup is not None
        assert result.lookup.lookup.ids is False

    def test_a_task_groups_show_looks_up_wr_slash_tg(self):
        result = complete(["yd", "tg", "show"], "")
        assert result.lookup is not None
        assert result.lookup.lookup.task_groups is True

    def test_token_looks_up_configured_worker_pools(self):
        result = complete(["yd", "wp", "token"], "")
        assert result.lookup is not None
        assert result.lookup.lookup.configured_only is True

    def test_a_later_target_is_looked_up_too(self):
        result = complete(["yd", "cr", "terminate", "first"], "")
        assert result.lookup is not None

    def test_the_configuration_options_typed_are_carried(self):
        words = ["yd", "wr", "cancel", "-n", "prod", "-t", "x", "-c", "cfg.toml"]
        result = complete(words, "a")
        assert result.lookup is not None
        settings = result.lookup.settings
        assert settings["namespace"] == "prod"
        assert settings["tag"] == "x"
        assert settings["config_file"] == "cfg.toml"

    def test_the_equals_form_is_carried(self):
        result = complete(["yd", "wr", "cancel", "--namespace=prod", "--tag="], "")
        assert result.lookup is not None
        assert result.lookup.settings["namespace"] == "prod"
        assert result.lookup.settings["tag"] == ""

    def test_repeated_options_and_flags_are_carried(self):
        words = [
            "yd",
            "wr",
            "cancel",
            "-v",
            "a=1",
            "-v",
            "b=2",
            "--property",
            "common.tag=t",
            "--env-override",
            "--no-config",
            "--pac",
        ]
        result = complete(words, "")
        assert result.lookup is not None
        settings = result.lookup.settings
        assert settings["variables"] == ["a=1", "b=2"]
        assert settings["property_overrides"] == ["common.tag=t"]
        assert settings["env_override"] is True
        assert settings["no_config"] is True
        assert settings["use_pac"] is True

    @pytest.mark.parametrize(
        "words",
        [
            ["yd", "wp", "shutdown", "-n", "-t", "--yes"],
            ["yd", "wp", "shutdown", "-n", "--yes", "-t", "--dry-run"],
            ["yd", "wp", "shutdown", "--namespace", "--tag", "-y"],
        ],
    )
    def test_an_option_given_no_value_is_its_empty_default(self, words):
        # '-n' and '-t' without a value mean '', as they do to the command
        result = complete(words, "")
        assert result.lookup is not None
        assert result.lookup.settings["namespace"] == ""
        assert result.lookup.settings["tag"] == ""

    def test_after_an_option_taking_an_optional_value_its_value_is_completed(self):
        # The command would take the word as the tag, not as a Worker Pool
        assert complete(["yd", "wp", "shutdown", "-n", "-t"], "").lookup is None

    @pytest.mark.parametrize(
        "words",
        [
            ["yd", "wr", "cancel", "-nprod", "-tdev", "-ccfg.toml"],
            [
                "yd",
                "wr",
                "cancel",
                "--names",
                "prod",
                "--ta",
                "dev",
                "--conf",
                "cfg.toml",
            ],
            ["yd", "wr", "cancel", "--names=prod", "--ta=dev", "--conf=cfg.toml"],
        ],
    )
    def test_attached_and_abbreviated_options_are_read_as_argparse_reads_them(
        self, words
    ):
        result = complete(words, "")
        assert result.lookup is not None
        settings = result.lookup.settings
        assert (settings["namespace"], settings["tag"], settings["config_file"]) == (
            "prod",
            "dev",
            "cfg.toml",
        )

    def test_an_ambiguous_abbreviation_is_not_read(self):
        # '--n' could be '--namespace' or '--no-config' (or '--no-format')
        result = complete(["yd", "wr", "cancel", "--n", "x"], "")
        assert result.lookup is not None
        assert result.lookup.settings["namespace"] is None

    def test_an_abbreviated_option_is_not_offered_again(self):
        assert "--namespace" not in _values(
            ["yd", "wr", "cancel", "--names", "p"], "--"
        )

    def test_the_names_typed_already_are_carried(self):
        result = complete(["yd", "wr", "cancel", "one", "-n", "ns", "two"], "")
        assert result.lookup is not None
        assert result.lookup.given == ("one", "two")

    def test_nothing_typed_leaves_the_settings_unset(self):
        result = complete(["yd", "wr", "cancel"], "")
        assert result.lookup is not None
        settings = result.lookup.settings
        assert settings["namespace"] is None
        assert settings["variables"] is None
        assert settings["use_pac"] is False

    def test_an_option_value_is_not_looked_up(self):
        assert complete(["yd", "wr", "cancel", "--namespace"], "").lookup is None

    def test_an_option_name_is_not_looked_up(self):
        assert complete(["yd", "wr", "cancel"], "-").lookup is None

    def test_a_specification_file_is_not_looked_up(self):
        assert complete(["yd", "wr", "submit"], "").lookup is None

    def test_a_generic_command_is_not_looked_up(self):
        # Its type is not known until an ID is typed
        assert complete(["yd", "show"], "").lookup is None

    def test_a_deprecated_command_is_not_looked_up(self):
        assert complete(["yd-cancel"], "").lookup is None


class TestEveryCommand:
    @pytest.mark.parametrize("name", sorted(NOUN_COMMANDS))
    def test_every_verb_completes(self, name):
        words = name.split()
        complete(words, "")
        complete(words, "-")
        assert complete(words, "--help").candidates

    @pytest.mark.parametrize("word", sorted(TOP_LEVEL))
    def test_every_word_completes(self, word):
        complete(["yd", word], "")
        complete(["yd", word], "-")


class TestTheFirstWord:
    def test_offers_the_words_with_their_summaries(self):
        values = {c.value: c.description for c in complete(["yd"], "w").candidates}
        assert {"wr", "workrequirement", "workerpool", "wp", "wait", "worker"} <= set(
            values
        )
        assert values["wr"] == "short for 'yd workrequirement'"

    def test_offers_every_word_and_no_deprecated_command(self):
        values = {c.value for c in complete(["yd"], "").candidates}
        assert values == set(TOP_LEVEL)
        assert not values & set(REPLACED_BY_VERBS)
        assert "submit" not in values

    def test_help_after_a_dash(self):
        assert _values(["yd"], "-") == ["--help"]

    @pytest.mark.parametrize("argv0", ["yd", "/usr/local/bin/yd", r"C:\bin\yd.exe"])
    def test_yd_by_any_path(self, argv0):
        assert _values([argv0, "wr"], "sub") == ["submit"]

    def test_a_deprecated_script_completes_nothing(self):
        assert _values(["yd-list"], "") == []
        assert _values(["yd-submit"], "-") == []

    def test_an_unknown_word_completes_nothing(self):
        assert _values(["yd", "frob"], "") == []


class TestBashWords:
    def test_an_option_and_its_value_are_rejoined(self):
        assert join_bash_words(["yd", "wr", "cancel", "--sort", "="], "na") == (
            ["yd", "wr", "cancel"],
            "--sort=na",
            "--sort=",
        )

    def test_a_bare_equals_is_the_value_start(self):
        assert join_bash_words(["yd", "wr", "cancel", "--sort"], "=") == (
            ["yd", "wr", "cancel"],
            "--sort=",
            "--sort=",
        )

    def test_a_ydid_is_rejoined(self):
        words = ["yd", "show", "ydid", ":", "wrkreq", ":", "000", ":", "x"]
        assert join_bash_words(words, "") == (
            ["yd", "show", "ydid:wrkreq:000:x"],
            "",
            "",
        )

    def test_nothing_to_join(self):
        assert join_bash_words(["yd", "wr"], "s") == (["yd", "wr"], "s", "")


class TestReply:
    def test_bash_gets_values_without_the_prefix_it_keeps(self):
        words = ["yd", "wr", "cancel", "--sort", "=", "cr"]
        assert yd_completion.completion_reply("bash", 5, words) == [
            "values",
            "created",
        ]

    def test_zsh_gets_descriptions(self):
        lines = yd_completion.completion_reply("zsh", 2, ["yd", "wr", "sub"])
        assert lines == ["values", "submit\tSubmit a Work Requirement"]

    def test_an_index_past_the_words_is_an_empty_current_word(self):
        # PowerShell 5.1 drops an empty argument, so it never sends one
        lines = yd_completion.completion_reply("powershell", 2, ["yd", "wr"])
        assert "submit\tSubmit a Work Requirement" in lines

    def test_a_mode_without_candidates(self):
        assert yd_completion.completion_reply("zsh", 3, ["yd", "wr", "submit"]) == [
            "files"
        ]

    def test_a_failure_prints_nothing(self, monkeypatch, capfd):
        monkeypatch.setattr(sys, "argv", ["yd-completion", "--complete", "zsh", "x"])
        yd_completion.main()
        assert capfd.readouterr() == ("", "")

    def test_the_request_is_answered_on_stdout(self, monkeypatch, capfd):
        argv = ["yd-completion", "--complete", "bash", "2", "yd", "wr", "sub"]
        monkeypatch.setattr(sys, "argv", argv)
        yd_completion.main()
        assert capfd.readouterr().out == "values\nsubmit\n"


FOUND = (
    Candidate("ydid:wrkreq:000000:a", "first (RUNNING)"),
    Candidate("ydid:wrkreq:000000:b", "second (HELD)"),
)


class TestLookupReply:
    """
    The command makes the lookup complete() asks for, within its time limit,
    and nothing it or the configuration prints reaches the answer.
    """

    @pytest.fixture
    def found(self, monkeypatch):
        """
        The lookup's answer, recording the requests made.
        """
        requests = []

        def candidates(request):
            requests.append(request)
            return FOUND

        monkeypatch.delenv(YD_COMPLETION_LOOKUPS, raising=False)
        monkeypatch.setattr(completion_lookups, "candidates", candidates)
        return requests

    def test_zsh_gets_the_ids_described(self, found):
        lines = yd_completion.completion_reply(
            "zsh", 3, ["yd", "wr", "show", "ydid:"], names=True
        )
        assert lines == [
            "values",
            "ydid:wrkreq:000000:a\tfirst (RUNNING)",
            "ydid:wrkreq:000000:b\tsecond (HELD)",
        ]
        assert found[0].current == "ydid:"

    def test_bash_gets_an_id_without_the_part_before_its_last_colon(self, found):
        # bash split 'ydid:wrkreq:' at its colons, and keeps what precedes the
        # last one, so it is taken off each candidate
        words = ["yd", "wr", "show", "ydid", ":", "wrkreq", ":"]
        lines = yd_completion.completion_reply("bash", 6, words, names=True)
        assert lines == ["values", "000000:a", "000000:b"]
        assert found[0].current == "ydid:wrkreq:"

    def test_what_is_found_replaces_the_options(self, found):
        lines = yd_completion.completion_reply(
            "zsh", 3, ["yd", "wr", "cancel"], names=True
        )
        assert lines[1:] == [f"{c.value}\t{c.description}" for c in FOUND]

    def test_with_nothing_found_the_options_are_offered(self, monkeypatch):
        monkeypatch.delenv(YD_COMPLETION_LOOKUPS, raising=False)
        monkeypatch.setattr(completion_lookups, "candidates", lambda request: ())
        lines = yd_completion.completion_reply(
            "bash", 3, ["yd", "wr", "cancel"], names=True
        )
        assert "--yes" in lines

    @pytest.mark.parametrize("value", ["on", "1", ""])
    def test_without_names_no_lookup_is_made(self, found, monkeypatch, value):
        # The default: the variable cannot turn lookups on
        monkeypatch.setenv(YD_COMPLETION_LOOKUPS, value)
        lines = yd_completion.completion_reply("bash", 3, ["yd", "wr", "cancel"])
        assert found == []
        assert "--yes" in lines

    @pytest.mark.parametrize("value", ["off", "0", "false", "NO", "Off"])
    def test_the_variable_switches_names_off(self, found, monkeypatch, value):
        monkeypatch.setenv(YD_COMPLETION_LOOKUPS, value)
        lines = yd_completion.completion_reply(
            "bash", 3, ["yd", "wr", "cancel"], names=True
        )
        assert found == []
        assert "--yes" in lines

    @pytest.mark.parametrize("value", ["on", "1", ""])
    def test_any_other_value_leaves_names_on(self, found, monkeypatch, value):
        monkeypatch.setenv(YD_COMPLETION_LOOKUPS, value)
        yd_completion.completion_reply("bash", 3, ["yd", "wr", "cancel"], names=True)
        assert len(found) == 1

    def test_names_reach_the_answer_from_the_command_line(
        self, found, monkeypatch, capfd
    ):
        argv = ["yd-completion", "--complete", "--names", "bash", "3"]
        monkeypatch.setattr(sys, "argv", [*argv, "yd", "wr", "cancel", "x"])
        yd_completion.main()
        assert capfd.readouterr().out.splitlines()[1:] == [c.value for c in FOUND]
        assert len(found) == 1

    def test_a_local_answer_makes_no_lookup(self, found):
        yd_completion.completion_reply("zsh", 2, ["yd", "wr", "sub"], names=True)
        assert found == []

    def test_what_a_lookup_prints_is_not_in_the_answer(self, monkeypatch, capfd):
        def noisy(request):
            print("noise on stdout")
            sys.stderr.write("noise on stderr\n")
            os.write(1, b"noise on fd 1\n")
            return FOUND

        monkeypatch.delenv(YD_COMPLETION_LOOKUPS, raising=False)
        monkeypatch.setattr(completion_lookups, "candidates", noisy)
        argv = ["yd-completion", "--complete", "--names", "bash", "3"]
        monkeypatch.setattr(sys, "argv", [*argv, "yd", "wr", "cancel", "x"])

        yd_completion.main()

        out, err = capfd.readouterr()
        assert out == "values\n" + "".join(f"{c.value}\n" for c in FOUND)
        assert err == ""
        print("after")  # the descriptors are back
        assert capfd.readouterr().out == "after\n"

    def test_a_lookup_that_hangs_is_abandoned_in_time(self, tmp_path):
        # In a process of its own, since an abandoned lookup ends the process
        script = tmp_path / "hang.py"
        script.write_text(
            "import sys, time\n"
            "from yellowdog_cli import completion\n"
            "from yellowdog_cli.utils import completion_lookups\n"
            "def hang(request):\n"
            "    print('noise')\n"
            "    time.sleep(60)\n"
            "completion_lookups.candidates = hang\n"
            "sys.argv = ['yd-completion', '--complete', '--names', 'zsh', '3',"
            " 'yd', 'wr', 'cancel', 'x']\n"
            "completion.main()\n"
            "print('not reached')\n",
            encoding="utf-8",
        )
        env = {k: v for k, v in os.environ.items() if k != YD_COMPLETION_LOOKUPS}
        started = time.monotonic()

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )

        assert time.monotonic() - started < LOOKUP_TIMEOUT_SECONDS + 8
        assert result.returncode == 0
        assert result.stdout == "values\n"
        assert result.stderr == ""


class TestScripts:
    @pytest.mark.parametrize("shell", ["bash", "zsh", "fish", "powershell"])
    def test_names_are_asked_for_by_the_script_given_names(self, shell):
        plain = yd_completion.completion_script(shell)
        named = yd_completion.completion_script(shell, names=True)
        assert f"yd completion --complete {shell}" in plain
        assert f"yd completion --complete --names {shell}" not in plain
        assert f"yd completion --complete --names {shell}" in named
        assert f"yd completion --complete {shell}" not in named
        # Each says how to load it with names
        assert "--names" in plain.split("\n\n")[0]

    def test_the_command_prints_the_script_with_names(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["yd-completion", "zsh", "--names"])
        yd_completion.main()
        assert capsys.readouterr().out == yd_completion.completion_script(
            "zsh", names=True
        )

    @pytest.mark.parametrize("shell", ["bash", "zsh", "fish", "powershell"])
    def test_a_script_is_registered_for_yd_alone(self, shell):
        script = yd_completion.completion_script(shell)
        assert "@NAMES@" not in script
        assert "yd completion --complete" in script
        assert "yd-completion" not in script

    def test_the_command_prints_the_script(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["yd-completion", "bash"])
        yd_completion.main()
        assert capsys.readouterr().out == yd_completion.completion_script("bash")

    def test_an_unknown_shell_is_refused(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["yd-completion", "tcsh"])
        with pytest.raises(SystemExit) as raised:
            yd_completion.main()
        assert raised.value.code == 2


# Stand-ins the stubs run under: 'yd' as this interpreter's module, so the
# checkout's code answers whatever is installed
_COMPLETER = f'yd() {{ "{sys.executable}" -m yellowdog_cli.yd "$@"; }}'


def _run_shell(shell: str, script: str, tmp_path) -> str:
    path = tmp_path / "check"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [shell, *(["-f"] if shell == "zsh" else []), str(path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="on Windows 'bash' may be WSL's launcher with no Linux installed",
)
class TestBashScript:
    @pytest.mark.parametrize("names", [False, True])
    def test_the_script_parses(self, tmp_path, names):
        stub = tmp_path / "yd.bash"
        stub.write_text(
            yd_completion.completion_script("bash", names=names), encoding="utf-8"
        )
        assert subprocess.run(["bash", "-n", str(stub)]).returncode == 0

    @pytest.mark.parametrize("names", [False, True])
    def test_the_script_completes(self, tmp_path, names):
        (tmp_path / "specs").mkdir()
        (tmp_path / "specs" / "wr.json").write_text("{}", encoding="utf-8")
        script = "\n".join(
            [
                _COMPLETER,
                yd_completion.completion_script("bash", names=names),
                't() { COMP_WORDS=("$@"); COMP_CWORD=$(( ${#COMP_WORDS[@]} - 1 ));'
                ' _yd_completion; echo "${COMPREPLY[*]}"; }',
                "t yd wr s",
                "t yd wr cancel --sort = cr",
                "t yd wr submit specs/w",
                "t yd schema --write sp",
                "complete -p yd",
            ]
        )
        assert _run_shell("bash", script, tmp_path).splitlines() == [
            "submit start show",
            "created",
            "specs/wr.json",
            "specs",
            "complete -F _yd_completion yd",
        ]


@pytest.mark.skipif(shutil.which("zsh") is None, reason="needs zsh")
class TestZshScript:
    @pytest.mark.parametrize("names", [False, True])
    def test_the_script_parses(self, tmp_path, names):
        stub = tmp_path / "yd.zsh"
        stub.write_text(
            yd_completion.completion_script("zsh", names=names), encoding="utf-8"
        )
        assert subprocess.run(["zsh", "-n", str(stub)]).returncode == 0

    @pytest.mark.parametrize("names", [False, True])
    def test_the_script_completes(self, tmp_path, names):
        # zsh's completion functions stood in for, printing what they are given
        script = "\n".join(
            [
                _COMPLETER,
                "compdef() { print -r -- compdef $1 $2 }",
                '_describe() { print -rl -- "${(@P)4}" }',
                "_files() { print -r -- files $* }",
                yd_completion.completion_script("zsh", names=names),
                't() { words=("$@"); CURRENT=${#words}; _yd_completion }',
                "t yd wr su",
                "t yd wr cancel --sort=cr",
                "t yd wr submit ''",
                "t yd schema --write ''",
            ]
        )
        assert _run_shell("zsh", script, tmp_path).splitlines() == [
            "compdef _yd_completion yd",
            "submit:Submit a Work Requirement",
            "--sort=created",
            "files",
            "files -/",
        ]


@pytest.mark.skipif(shutil.which("fish") is None, reason="needs fish")
class TestFishScript:
    @pytest.mark.parametrize("names", [False, True])
    def test_the_script_parses(self, tmp_path, names):
        stub = tmp_path / "yd.fish"
        stub.write_text(
            yd_completion.completion_script("fish", names=names), encoding="utf-8"
        )
        assert subprocess.run(["fish", "-n", str(stub)]).returncode == 0

    @pytest.mark.parametrize("names", [False, True])
    def test_the_script_completes(self, tmp_path, names):
        # fish's own completion of a command line ('complete -C'), so its
        # tokenising and path completion are the real ones
        (tmp_path / "specs").mkdir()
        (tmp_path / "specs" / "wr.json").write_text("{}", encoding="utf-8")
        lines = [
            "yd wr s",
            "yd wr cancel --sort=cr",
            "yd wr submit specs/w",
            "yd schema --write sp",
            "yd-submit --f",
        ]
        script = "\n".join(
            [
                f'function yd; "{sys.executable}" -m yellowdog_cli.yd $argv; end',
                yd_completion.completion_script("fish", names=names),
                *(f"echo '[{line}]'; complete -C '{line}'" for line in lines),
                "echo '[yd wr ]'; complete -C 'yd wr ' | count",
            ]
        )
        assert _run_shell("fish", script, tmp_path).splitlines() == [
            "[yd wr s]",
            "show\tShow the details of Work Requirements",
            "start\tStart held (paused) Work Requirements",
            "submit\tSubmit a Work Requirement",
            "[yd wr cancel --sort=cr]",
            "--sort=created",
            "[yd wr submit specs/w]",
            "specs/wr.json",
            "[yd schema --write sp]",
            "specs/\tDirectory",
            # A deprecated command has no completion
            "[yd-submit --f]",
            "[yd wr ]",
            str(len(next(n for n in NOUNS if n.name == "workrequirement").verbs)),
        ]


# Each PowerShell present: PowerShell 7 ('pwsh', anywhere) and Windows
# PowerShell 5.1 ('powershell', Windows alone), which drops an empty argument
# passed to a program; the Windows workflow (.github/workflows) runs both
POWERSHELLS = [shell for shell in ("pwsh", "powershell") if shutil.which(shell)]


@pytest.mark.skipif(not POWERSHELLS, reason="needs PowerShell (pwsh or powershell)")
@pytest.mark.parametrize("powershell", POWERSHELLS)
class TestPowerShellScript:
    @pytest.mark.parametrize("names", [False, True])
    def test_the_script_parses(self, tmp_path, powershell, names):
        stub = tmp_path / "yd.ps1"
        stub.write_text(
            yd_completion.completion_script("powershell", names=names), encoding="utf-8"
        )
        check = (
            "$errors = $null; [System.Management.Automation.Language.Parser]::"
            f"ParseFile('{stub}', [ref]$null, [ref]$errors) | Out-Null;"
            " if ($errors) { $errors; exit 1 }"
        )
        result = subprocess.run(
            [powershell, "-NoProfile", "-Command", check],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    @pytest.mark.parametrize("names", [False, True])
    def test_the_script_completes(self, tmp_path, powershell, names):
        # PowerShell's own completion of a command line (TabExpansion2), so
        # its tokenising and path completion are the real ones; each match
        # with its tooltip where that says more than the match itself
        (tmp_path / "specs").mkdir()
        (tmp_path / "specs" / "wr.json").write_text("{}", encoding="utf-8")
        lines = [
            "yd wr s",
            "yd wr cancel --sort=cr",
            "yd wr submit specs/w",
            "yd schema --write sp",
            "yd-submit --f",
        ]
        quoted = ", ".join(f"'{line}'" for line in lines)
        script = "\n".join(
            [
                f"function yd {{ & '{sys.executable}' -m yellowdog_cli.yd @args }}",
                yd_completion.completion_script("powershell", names=names),
                f"foreach ($line in @({quoted})) {{",
                "    '[' + $line + ']'",
                "    $found = TabExpansion2 -inputScript $line"
                " -cursorColumn $line.Length",
                "    foreach ($match in $found.CompletionMatches) {",
                "        $text = $match.CompletionText -replace '\\\\', '/'",
                "        if ($match.ResultType -like 'Parameter*' -and"
                " $match.ToolTip -ne $match.CompletionText) {",
                '            $text + "`t" + $match.ToolTip',
                "        } else { $text }",
                "    }",
                "}",
                "'[yd wr ]'",
                "(TabExpansion2 -inputScript 'yd wr ' -cursorColumn 6)"
                ".CompletionMatches.Count",
            ]
        )
        path = tmp_path / "check.ps1"
        path.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-File", str(path)],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.splitlines() == [
            "[yd wr s]",
            "submit\tSubmit a Work Requirement",
            "start\tStart held (paused) Work Requirements",
            "show\tShow the details of Work Requirements",
            "[yd wr cancel --sort=cr]",
            "--sort=created",
            "[yd wr submit specs/w]",
            "./specs/wr.json",
            "[yd schema --write sp]",
            "./specs",
            # A deprecated command has no completion
            "[yd-submit --f]",
            # An empty current word, which PowerShell 5.1 would drop
            "[yd wr ]",
            str(len(next(n for n in NOUNS if n.name == "workrequirement").verbs)),
        ]


class TestMarkings:
    # A metavar naming a local file, a specification or a directory
    FILE_OR_DIRECTORY = re.compile(
        r"file|specification|\.json|\.toml|\.csv|dir|local-path", re.IGNORECASE
    )

    def _options(self):
        return {
            (command.name, option.name): option
            for command in COMMANDS.values()
            for option in command.flat_options()
        }

    def test_every_file_or_directory_option_is_marked(self):
        assert [
            key
            for key, option in self._options().items()
            if self.FILE_OR_DIRECTORY.search(str(option.kwargs.get("metavar", "")))
            and option.completes is Completes.NONE
        ] == []

    def test_every_marked_option_names_a_file_or_directory(self):
        assert [
            key
            for key, option in self._options().items()
            if option.completes is not Completes.NONE
            and not self.FILE_OR_DIRECTORY.search(str(option.kwargs.get("metavar", "")))
        ] == []

    def test_a_variant_keeps_its_marking(self):
        option = COMMANDS["yd-submit"].option_named("--config")
        assert option is not None
        assert option.variant(help="x").completes is Completes.FILE
