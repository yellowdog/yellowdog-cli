"""
Tests for variables.py — the 'yd-variables' command.

report_variables() is exercised directly against a substituted variable table;
the JSON-only output is exercised through a real child process, because that is
the property Commander depends on: it parses stdout, so a status message or the
wrapper's trailing 'Done' appearing there would break it.
"""

import os
import subprocess
from json import loads

import pytest

import yellowdog_cli.utils.variables as variables_module
from yellowdog_cli.utils.settings import REDACTED_VALUE
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
    def test_stdout_is_json_and_nothing_else(self, tmp_path):
        # No '--quiet' is passed: the command suppresses the status messages and
        # the wrapper's 'Done' itself, which is what lets Commander parse stdout
        result = _run("namespace", "tag", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert loads(result.stdout) == {
            "namespace": "my-namespace",
            "tag": "my-tag",
        }

    def test_a_command_line_variable_is_reported(self, tmp_path):
        result = _run("-v", "instances=5", "instances", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert loads(result.stdout) == {"instances": "5"}

    def test_names_are_accepted_ahead_of_the_options(self, tmp_path):
        # The shape Commander builds in _yd_variables_command(): the names sit
        # between the configuration-source options and the namespace/tag/user
        # variable overrides. argparse has to end the '*' positional at the
        # first option that follows it
        result = _run(
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
        result = _run(cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        reported = loads(result.stdout)
        assert reported["key"] == REDACTED_VALUE
        assert reported["secret"] == REDACTED_VALUE

    def test_show_secrets_reveals_them(self, tmp_path):
        result = _run("--show-secrets", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        reported = loads(result.stdout)
        assert reported["key"] == "a-key"
        assert reported["secret"] == "a-secret"

    def test_naming_them_reveals_them(self, tmp_path):
        result = _run("key", "secret", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert loads(result.stdout) == {"key": "a-key", "secret": "a-secret"}

    def test_every_variable_includes_the_configured_ones(self, tmp_path):
        result = _run(cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        reported = loads(result.stdout)
        assert reported["namespace"] == "my-namespace"
        assert reported["tag"] == "my-tag"
        assert list(reported) == sorted(reported)


class TestUndefinedVariableWarnings:
    # The warnings go to stderr, so the JSON on stdout stays parseable: before
    # they did, the one main_wrapper prints for the '[common]' values landed on
    # stdout ahead of the JSON, and the table's own variables went unchecked

    def test_a_reported_variable_is_checked(self, tmp_path):
        result = _run("-v", "a=x-{{missing}}", "a", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert loads(result.stdout) == {"a": "x-{{missing}}"}
        assert "'{{missing}}' is not defined" in result.stderr

    def test_every_variable_is_checked_in_the_full_report(self, tmp_path):
        result = _run("-v", "a=x-{{missing}}", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert loads(result.stdout)["a"] == "x-{{missing}}"
        assert "'{{missing}}' is not defined" in result.stderr

    def test_a_variable_not_asked_for_is_not_checked(self, tmp_path):
        result = _run("-v", "a=x-{{missing}}", "tag", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert "{{missing}}" not in result.stderr

    def test_a_configuration_value_warning_does_not_reach_stdout(self, tmp_path):
        result = _run("-n", "ns-{{nope}}", "namespace", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert loads(result.stdout) == {"namespace": "ns-{{nope}}"}
        assert "'{{nope}}' is not defined" in result.stderr

    def test_quiet_suppresses_them(self, tmp_path):
        result = _run("-q", "-v", "a=x-{{missing}}", "a", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert "Warning" not in result.stderr

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
        assert "{{missing}}" not in result.stderr
