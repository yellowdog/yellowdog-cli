"""
Shell completion: utils/completion.py's complete() over the registries, the
'yd completion --complete' protocol the stubs speak, the stubs themselves
(run in bash, zsh and fish where those are installed, parsed by PowerShell
where it is), and the registry's Completes markings held to the metavars.
"""

import re
import shutil
import subprocess
import sys

import pytest

from yellowdog_cli import completion as yd_completion
from yellowdog_cli.utils.command_registry import (
    COMMANDS,
    ENTITY_TYPES,
    Completes,
)
from yellowdog_cli.utils.completion import (
    Mode,
    complete,
    join_bash_words,
)
from yellowdog_cli.utils.noun_registry import (
    NOUN_COMMANDS,
    NOUNS,
    REPLACED_BY_VERBS,
    RESOURCE_LIST_TYPES,
)
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

    @pytest.mark.parametrize(
        "word", ["commander", "mcp", "format-json", "jsonnet2json"]
    )
    def test_a_command_the_registry_does_not_describe_completes_files(self, word):
        # Before the stubs claimed its name, the shell completed files for it
        assert complete(["yd", word], "").mode is Mode.FILES
        assert complete(["yd", word, "config.toml", "-r"], "w").mode is Mode.FILES
        assert _values(["yd", word], "-") == ["--help"]

    def test_a_described_standalone_command_is_not_left_to_the_shell(self):
        assert _values(["yd", "completion"], "z") == ["zsh"]

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

    def test_a_failure_prints_nothing(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["yd-completion", "--complete", "zsh", "x"])
        yd_completion.main()
        assert capsys.readouterr() == ("", "")

    def test_the_request_is_answered_on_stdout(self, monkeypatch, capsys):
        argv = ["yd-completion", "--complete", "bash", "2", "yd", "wr", "sub"]
        monkeypatch.setattr(sys, "argv", argv)
        yd_completion.main()
        assert capsys.readouterr().out == "values\nsubmit\n"


class TestScripts:
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
class TestBashScript:
    def test_the_script_parses(self, tmp_path):
        stub = tmp_path / "yd.bash"
        stub.write_text(yd_completion.completion_script("bash"), encoding="utf-8")
        assert subprocess.run(["bash", "-n", str(stub)]).returncode == 0

    def test_the_script_completes(self, tmp_path):
        (tmp_path / "specs").mkdir()
        (tmp_path / "specs" / "wr.json").write_text("{}", encoding="utf-8")
        script = "\n".join(
            [
                _COMPLETER,
                yd_completion.completion_script("bash"),
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
    def test_the_script_parses(self, tmp_path):
        stub = tmp_path / "yd.zsh"
        stub.write_text(yd_completion.completion_script("zsh"), encoding="utf-8")
        assert subprocess.run(["zsh", "-n", str(stub)]).returncode == 0

    def test_the_script_completes(self, tmp_path):
        # zsh's completion functions stood in for, printing what they are given
        script = "\n".join(
            [
                _COMPLETER,
                "compdef() { print -r -- compdef $1 $2 }",
                '_describe() { print -rl -- "${(@P)4}" }',
                "_files() { print -r -- files $* }",
                yd_completion.completion_script("zsh"),
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
    def test_the_script_parses(self, tmp_path):
        stub = tmp_path / "yd.fish"
        stub.write_text(yd_completion.completion_script("fish"), encoding="utf-8")
        assert subprocess.run(["fish", "-n", str(stub)]).returncode == 0

    def test_the_script_completes(self, tmp_path):
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
                yd_completion.completion_script("fish"),
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


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="needs PowerShell (pwsh)")
class TestPowerShellScript:
    def test_the_script_parses(self, tmp_path):
        stub = tmp_path / "yd.ps1"
        stub.write_text(yd_completion.completion_script("powershell"), encoding="utf-8")
        check = (
            "$errors = $null; [System.Management.Automation.Language.Parser]::"
            f"ParseFile('{stub}', [ref]$null, [ref]$errors) | Out-Null;"
            " if ($errors) { $errors; exit 1 }"
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", check], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stdout + result.stderr


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
