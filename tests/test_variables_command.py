"""
Tests for variables.py — the 'yd-variables' command.

report_variables() is exercised directly against a substituted variable table;
the output through a real child process. Like yd-show's, it is JSON with the
warnings ahead of it and the wrapper's 'Done' after it, and only JSON under
'--quiet', which is what Commander depends on: it parses stdout.
"""

import os
import subprocess
from json import loads

import pytest

import yellowdog_cli.utils.variables as variables_module
from yellowdog_cli.utils.settings import REDACTED_VALUE, WARNING_MARKER
from yellowdog_cli.variables import report_variables

SUBSTITUTIONS = {
    "tag": "my-tag",
    "namespace": "my-namespace",
    "username": "someone",
    "all": "a variable that happens to be called 'all'",
    "key": "an-application-key",
    "secret": "an-application-secret",
    # A user-defined variable that holds a credential and says so in its name.
    # Deliberately NOT redacted: see TestRedaction below
    "APP_SECRET_MINE": "a-user-defined-secret",
}


@pytest.fixture
def substitutions(monkeypatch):
    monkeypatch.setattr(variables_module, "VARIABLE_SUBSTITUTIONS", dict(SUBSTITUTIONS))


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


class TestSelection:
    def test_no_names_reports_every_variable(self, substitutions):
        assert report_variables([], show_secrets=True) == SUBSTITUTIONS

    def test_names_report_only_those_variables(self, substitutions):
        assert report_variables(["tag", "namespace"]) == {
            "namespace": "my-namespace",
            "tag": "my-tag",
        }

    def test_a_name_that_is_not_a_variable_reports_null(self, substitutions):
        # Not an error and not omitted: 'is this variable set?' is one of the
        # questions the command exists to answer
        assert report_variables(["tag", "nonexistent"]) == {
            "nonexistent": None,
            "tag": "my-tag",
        }

    def test_a_repeated_name_is_reported_once(self, substitutions):
        assert report_variables(["tag", "tag"]) == {"tag": "my-tag"}

    def test_all_is_not_a_keyword(self, substitutions):
        # Under 'yd-show -r', 'all' meant every variable. Empty now means that,
        # so the name is an ordinary one and may be used as a variable name
        assert report_variables(["all"]) == {"all": SUBSTITUTIONS["all"]}

    def test_all_is_not_a_keyword_when_undefined(self, monkeypatch):
        monkeypatch.setattr(
            variables_module, "VARIABLE_SUBSTITUTIONS", {"tag": "my-tag"}
        )
        assert report_variables(["all"]) == {"all": None}


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


class TestOrdering:
    def test_every_variable_is_reported_in_alphabetical_order(self, substitutions):
        assert list(report_variables([])) == [
            "APP_SECRET_MINE",
            "all",
            "key",
            "namespace",
            "secret",
            "tag",
            "username",
        ]

    def test_named_variables_are_reported_in_alphabetical_order(self, substitutions):
        # Not in the order they were asked for
        assert list(report_variables(["username", "namespace", "tag"])) == [
            "namespace",
            "tag",
            "username",
        ]


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


class TestRedaction:
    def test_reporting_every_variable_redacts_the_credentials(self, substitutions):
        reported = report_variables([])
        assert reported["key"] == REDACTED_VALUE
        assert reported["secret"] == REDACTED_VALUE

    def test_show_secrets_reports_the_credentials(self, substitutions):
        reported = report_variables([], show_secrets=True)
        assert reported["key"] == SUBSTITUTIONS["key"]
        assert reported["secret"] == SUBSTITUTIONS["secret"]

    @pytest.mark.parametrize("name", ["key", "secret"])
    def test_naming_a_credential_reports_it_without_show_secrets(
        self, substitutions, name
    ):
        # Naming a variable is an explicit request for it
        assert report_variables([name]) == {name: SUBSTITUTIONS[name]}

    def test_naming_a_credential_alongside_others_reports_it(self, substitutions):
        assert report_variables(["secret", "tag"]) == {
            "secret": SUBSTITUTIONS["secret"],
            "tag": SUBSTITUTIONS["tag"],
        }

    def test_no_other_variable_is_redacted(self, substitutions):
        # The deliberate limit: only the two variables the CLI injects itself
        # can be known to be credentials. A user-defined variable holding one --
        # named 'APP_SECRET_MINE' here -- is reported in full, because guessing
        # from the name would be a guarantee the command cannot keep
        reported = report_variables([])
        assert reported["APP_SECRET_MINE"] == SUBSTITUTIONS["APP_SECRET_MINE"]
        assert REDACTED_VALUE not in [
            value for name, value in reported.items() if name not in ("key", "secret")
        ]

    def test_redaction_does_not_alter_the_variable_table(self, substitutions):
        report_variables([])
        # get_all_user_variables() copies, but a regression there would leave
        # the process running on '<REDACTED>' as its actual credentials
        assert variables_module.VARIABLE_SUBSTITUTIONS["key"] == SUBSTITUTIONS["key"]


# ---------------------------------------------------------------------------
# The output of the command itself
# ---------------------------------------------------------------------------


def _run(*args: str, cwd) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(
        {
            "YD_KEY": "a-key",
            "YD_SECRET": "a-secret",
            "YD_NAMESPACE": "my-namespace",
            "YD_TAG": "my-tag",
        }
    )
    return subprocess.run(
        ["yd-variables", "--nc", *args],
        capture_output=True,
        text=True,
        env=env,
        # Run away from the repository, so neither its config.toml nor its
        # '.env' file contributes variables of its own
        cwd=cwd,
        timeout=120,
    )


class TestCommandOutput:
    def test_without_quiet_the_json_is_followed_by_done(self, tmp_path):
        # As yd-show's is: the command does not select JSON output to hide it
        result = _run("namespace", "tag", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert _stdout(result).startswith(
            '{"namespace": "my-namespace", "tag": "my-tag"}'
        )
        assert _stdout(result).endswith("Done")

    def test_quiet_leaves_only_the_json(self, tmp_path):
        result = _run("-q", "namespace", "tag", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert loads(result.stdout) == {
            "namespace": "my-namespace",
            "tag": "my-tag",
        }

    def test_a_command_line_variable_is_reported(self, tmp_path):
        result = _run("-q", "-v", "instances=5", "instances", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert loads(result.stdout) == {"instances": "5"}

    def test_names_are_accepted_ahead_of_the_options(self, tmp_path):
        # The shape Commander builds in _yd_variables_command(): the names sit
        # between the configuration-source options and the namespace/tag/user
        # variable overrides. argparse has to end the '*' positional at the
        # first option that follows it
        result = _run(
            "-q",
            "--nf",
            "namespace",
            "tag",
            "-n",
            "another-namespace",
            "-t",
            "another-tag",
            "-v",
            "unused=1",
            cwd=tmp_path,
        )

        assert result.returncode == 0, result.stderr
        assert loads(result.stdout) == {
            "namespace": "another-namespace",
            "tag": "another-tag",
        }

    def test_the_credentials_are_redacted_in_the_full_report(self, tmp_path):
        result = _run("-q", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        reported = loads(result.stdout)
        assert reported["key"] == REDACTED_VALUE
        assert reported["secret"] == REDACTED_VALUE

    def test_show_secrets_reveals_them(self, tmp_path):
        result = _run("-q", "--show-secrets", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        reported = loads(result.stdout)
        assert reported["key"] == "a-key"
        assert reported["secret"] == "a-secret"

    def test_naming_them_reveals_them(self, tmp_path):
        result = _run("-q", "key", "secret", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert loads(result.stdout) == {"key": "a-key", "secret": "a-secret"}

    def test_every_variable_includes_the_configured_ones(self, tmp_path):
        result = _run("-q", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        reported = loads(result.stdout)
        assert reported["namespace"] == "my-namespace"
        assert reported["tag"] == "my-tag"
        assert list(reported) == sorted(reported)


def _stdout(result: subprocess.CompletedProcess) -> str:
    """
    Stdout with its whitespace collapsed, since the warnings are wrapped to
    the terminal's width and a phrase may be split over two lines.
    """
    return " ".join(result.stdout.split())


class TestUndefinedVariableWarnings:
    # The warnings go to stdout, ahead of the JSON, as every command's do;
    # '--quiet' leaves the JSON alone, and is what Commander passes

    def test_a_reported_variable_is_checked(self, tmp_path):
        result = _run("-v", "a=x-{{missing}}", "a", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert "'{{missing}}' is not defined" in _stdout(result)

    def test_every_variable_is_checked_in_the_full_report(self, tmp_path):
        result = _run("-v", "a=x-{{missing}}", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert "'{{missing}}' is not defined" in _stdout(result)

    def test_a_variable_not_asked_for_is_not_checked(self, tmp_path):
        result = _run("-v", "a=x-{{missing}}", "tag", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert "{{missing}}" not in _stdout(result)

    def test_a_configuration_value_is_checked(self, tmp_path):
        # Printed by main_wrapper, before the command itself runs
        result = _run("-n", "ns-{{nope}}", "namespace", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert "'{{nope}}' is not defined" in _stdout(result)

    def test_quiet_suppresses_them(self, tmp_path):
        result = _run(
            "-q",
            "-n",
            "ns-{{nope}}",
            "-v",
            "a=x-{{missing}}",
            "namespace",
            "a",
            cwd=tmp_path,
        )

        assert result.returncode == 0, result.stderr
        assert loads(result.stdout) == {
            "a": "x-{{missing}}",
            "namespace": "ns-{{nope}}",
        }

    def test_commanders_invocation_parses_despite_a_warning(self, tmp_path):
        # The shape _yd_variables_command() builds, '--quiet' included (which
        # test_commander_config_discovery.py holds it to), with a warning due
        result = _run(
            "--quiet",
            "--nf",
            "namespace",
            "tag",
            "-n",
            "ns-{{nope}}",
            cwd=tmp_path,
        )

        assert result.returncode == 0, result.stderr
        assert loads(result.stdout) == {"namespace": "ns-{{nope}}", "tag": "my-tag"}

    def test_the_credentials_are_not_checked(self, tmp_path):
        # Their text is not for a warning, as for the configuration values
        env_secret = "s-{{missing}}"
        result = subprocess.run(
            ["yd-variables", "--nc", "secret"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "YD_KEY": "a-key",
                "YD_SECRET": env_secret,
                "YD_NAMESPACE": "my-namespace",
                "YD_TAG": "my-tag",
            },
            cwd=tmp_path,
            timeout=120,
        )

        assert result.returncode == 0, result.stderr
        assert WARNING_MARKER not in result.stdout


# ---------------------------------------------------------------------------
# Explaining unset variables
# ---------------------------------------------------------------------------


@pytest.fixture
def definitions(monkeypatch):
    """
    An empty table and record of definitions, filled through the real
    definition path so that the record is kept the way the CLI keeps it.
    Two sweeps, as every command makes several, so that a test cannot pass
    only because the effect of an unset takes a second one to show.
    """
    monkeypatch.setattr(variables_module, "VARIABLE_SUBSTITUTIONS", {})
    monkeypatch.setattr(variables_module, "_DEFINITIONS", {})

    def define(**subs):
        variables_module.add_substitutions_without_overwriting(subs)
        variables_module.add_substitutions_without_overwriting({})

    return define


class TestExplainUnsetVariable:
    def test_bare_unset(self, definitions):
        definitions(site="{{::}}")

        assert variables_module.explain_unset_variable("site") == (
            "Variable 'site' is unset: 'site' is '{{::}}', which always unsets it"
        )

    def test_bare_unset_inside_a_longer_value(self, definitions):
        definitions(site="a-{{::}}")

        assert "'site' contains '{{::}}'" in variables_module.explain_unset_variable(
            "site"
        )

    def test_an_unset_suffix_chain_is_followed_to_its_end(self, definitions):
        definitions(site="{{::}}", pool="{{site::}}-p", summary="{{pool::}} s")

        assert variables_module.explain_unset_variable("summary") == (
            "Variable 'summary' is unset: 'summary' refers to '{{pool::}}', and"
            " 'pool' is unset; 'pool' refers to '{{site::}}', and 'site' is"
            " unset; 'site' is '{{::}}', which always unsets it"
        )

    def test_an_undefined_variable_with_the_unset_suffix(self, definitions):
        definitions(site="a-{{nope::}}")

        assert variables_module.explain_unset_variable("site") == (
            "Variable 'site' is unset: 'site' refers to '{{nope::}}', and 'nope'"
            " is not defined"
        )

    def test_a_type_tag_is_seen_through(self, definitions):
        definitions(count="{{num:nope::}}")

        assert "'nope' is not defined" in variables_module.explain_unset_variable(
            "count"
        )

    def test_an_unset_environment_variable(self, definitions, monkeypatch):
        monkeypatch.delenv("YD_TEST_NOT_SET", raising=False)
        definitions(home="{{env:YD_TEST_NOT_SET::}}")

        assert (
            "the environment variable 'YD_TEST_NOT_SET' is not set"
            in variables_module.explain_unset_variable("home")
        )

    def test_a_reference_inside_a_nested_expression(self, definitions):
        definitions(site="{{::}}", name="{{prefix_{{site::}}}}")

        assert "'name' refers to '{{site::}}', and 'site' is unset" in (
            variables_module.explain_unset_variable("name")
        )

    def test_a_variable_with_a_value_has_no_explanation(self, definitions):
        definitions(site="x", pool="{{site}}-p")

        assert variables_module.explain_unset_variable("pool") is None

    def test_a_variable_never_defined_has_no_explanation(self, definitions):
        definitions(site="x")

        assert variables_module.explain_unset_variable("nonexistent") is None

    def test_the_unset_variables_are_listed(self, definitions):
        definitions(site="{{::}}", pool="{{site::}}-p", other="x")

        assert variables_module.get_unset_variable_names() == ["pool", "site"]

    def test_a_redefinition_replaces_the_recorded_definition(self, definitions):
        definitions(site="{{::}}")
        variables_module.add_or_update_substitution("site", "x")

        assert variables_module.explain_unset_variable("site") is None


class TestUnsetIsNotTransitive:
    # A plain reference to an unset variable is left unsubstituted, as one to
    # any undefined variable is. It once unset the referring variable too,
    # but only one resolved in the same sweep as the unset one, which took in
    # its '{{::}}' as text before it was removed: a '[common]' value referring
    # to it, or a specification property, was left unsubstituted instead

    def test_a_plain_reference_is_left_unsubstituted(self, definitions):
        definitions(site="{{::}}", pool="{{site}}-p", summary="{{pool}} s")

        assert variables_module.get_user_variable("pool") == "{{site}}-p"
        assert variables_module.get_user_variable("summary") == "{{site}}-p s"
        assert variables_module.get_unset_variable_names() == ["site"]

    def test_whatever_the_order_of_definition(self, definitions):
        definitions(pool="{{site}}-p", site="{{::}}")

        assert variables_module.get_user_variable("pool") == "{{site}}-p"

    def test_an_unset_suffix_reference_still_unsets(self, definitions):
        definitions(site="{{::}}", pool="{{site::}}-p", summary="{{pool::}} s")

        assert variables_module.get_unset_variable_names() == [
            "pool",
            "site",
            "summary",
        ]

    def test_the_referring_variable_has_no_explanation(self, definitions):
        definitions(site="{{::}}", pool="{{site}}-p")

        assert variables_module.explain_unset_variable("pool") is None


class TestUnsetExplanationsInTheCommand:
    def test_a_named_unset_variable_is_explained(self, tmp_path):
        result = _run(
            "-v", "site={{::}}", "-v", "pool={{site::}}-p", "pool", cwd=tmp_path
        )

        assert result.returncode == 0, result.stderr
        assert '{"pool": null}' in _stdout(result)
        assert "Variable 'pool' is unset" in _stdout(result)
        assert "'site' is '{{::}}'" in _stdout(result)

    def test_every_unset_variable_is_explained_in_the_full_report(self, tmp_path):
        result = _run("-v", "site={{::}}", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert '"site":' not in result.stdout
        assert "Variable 'site' is unset" in _stdout(result)

    def test_a_name_never_defined_is_not_explained(self, tmp_path):
        result = _run("nonexistent", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert "unset" not in _stdout(result)

    def test_quiet_suppresses_them(self, tmp_path):
        result = _run("-q", "-v", "site={{::}}", "site", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert "unset" not in _stdout(result)

    def test_a_reference_to_an_unset_variable_is_warned_of_as_unset(self, tmp_path):
        result = _run(
            "-v", "site={{::}}", "-v", "pool={{site}}-p", "pool", cwd=tmp_path
        )

        assert result.returncode == 0, result.stderr
        assert '{"pool": "{{site}}-p"}' in _stdout(result)
        assert "'{{site}}' is unset, and has been left unsubstituted" in _stdout(result)
        assert "'site' is '{{::}}'" in _stdout(result)
        assert "not defined" not in _stdout(result)
