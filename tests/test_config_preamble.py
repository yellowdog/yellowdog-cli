"""
The configuration/startup preamble is printed only when '--debug' is set.

Most of these messages are emitted while 'wrapper.py' and the modules it
imports are themselves being imported, before any command runs, so they are
exercised here by importing that module in a subprocess with a configuration of
the test's own. The proxy messages come later, from set_proxy() at command time,
and are exercised directly at the foot of this file. Nothing here contacts the
platform, and the PAC lookup itself is never performed.

Each scenario provokes a different part of the preamble, and is checked in
both directions: silence by default, and — under '--debug' — output in which
every line carries the DEBUG marker. The second half is what catches a message
that was left as print_info(), whether or not this file names it.
"""

import os
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import yellowdog_cli.utils.wrapper as wrapper
from yellowdog_cli.utils.settings import DEBUG_MARKER

CONFIG_TOML = """
[common]
importCommon = "common.toml"
key = "{{TESTVAR}}"

[dataClient]
bucket = "default-bucket"

[dataClient.myprofile]
bucket = "profile-bucket"
"""

COMMON_TOML = """
[common]
secret = "not-a-real-secret"
"""

DOTENV = "YD_SOME_VARIABLE=some-value\n"

# Each scenario is (name, extra arguments, extra environment variables), and
# provokes a different part of the preamble
SCENARIOS = [
    # '.env' loading, environment-defined substitutions, the config file and
    # the common section it imports, and the default namespace and tag
    ("defaults", [], {}),
    # Command-line-defined substitutions, a property override, and a value
    # supplied on the command line
    ("command-line", ["-v", "cli_var=1", "--property", "common.tag=t", "-n", "ns"], {}),
    # A value supplied via the environment
    ("environment", [], {"YD_TAG": "env-tag"}),
    # The configuration file explicitly ignored
    ("no-config", ["--no-config"], {"YD_KEY": "k", "YD_SECRET": "s"}),
    # A named data client profile
    ("data-client-profile", [], {"YD_DATA_CLIENT": "myprofile"}),
    # A Platform URL other than the default
    ("non-default-url", [], {"YD_URL": "https://api.example.com"}),
    # An HTTPS proxy taken from the environment, reported by set_proxy()
    ("https-proxy", [], {"HTTPS_PROXY": "http://proxy.example.com:8080"}),
    # A certificates bundle, which is reported as it is put in the environment
    ("certificates", ["--property", "common.certificates=ca.pem"], {}),
]
SCENARIO_IDS = [scenario[0] for scenario in SCENARIOS]


@pytest.fixture(scope="module")
def config_dir(tmp_path_factory) -> Path:
    """
    A directory holding a config file, the common section it imports, and a
    '.env' file.
    """
    directory = tmp_path_factory.mktemp("config")
    (directory / "config.toml").write_text(CONFIG_TOML)
    (directory / "common.toml").write_text(COMMON_TOML)
    (directory / ".env").write_text(DOTENV)
    return directory


def _import_wrapper(
    config_dir: Path, args: list, env: dict, no_format: bool = True
) -> str:
    """
    Import wrapper.py in a subprocess, as a command with the given arguments
    and environment would, and return everything it printed to stdout. The
    data client configuration is loaded explicitly afterwards, since it is
    loaded by the data client commands rather than by the wrapper.
    """
    # '--no-format' keeps each message on one line, so the assertions read the
    # message text rather than the terminal's wrapping of it. Passing it also
    # takes the plain print() branch rather than the Rich console, so the
    # formatted branch is covered separately below.
    argv = ["yd-list", "applications", *(["--no-format"] if no_format else []), *args]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys; sys.argv = {argv!r}; "
            "import yellowdog_cli.utils.wrapper as wrapper; "
            "wrapper.set_proxy(); "
            "from yellowdog_cli.utils.load_config import load_config_data_client; "
            "load_config_data_client()",
        ],
        cwd=config_dir,
        env={
            "PATH": "",
            "HOME": str(config_dir),
            "YD_VAR_TESTVAR": "a-key",
            **env,
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("_name,args,env", SCENARIOS, ids=SCENARIO_IDS)
def test_preamble_is_silent_by_default(config_dir, _name, args, env):
    assert _import_wrapper(config_dir, args, env) == ""


@pytest.mark.parametrize("_name,args,env", SCENARIOS, ids=SCENARIO_IDS)
def test_whole_preamble_is_marked_and_shown_under_debug(config_dir, _name, args, env):
    output = _import_wrapper(config_dir, ["--debug", *args], env)
    lines = [line for line in output.splitlines() if line.strip()]
    assert lines, "expected the preamble to be printed under '--debug'"
    # A message left as print_info() would appear here without the marker
    assert all(DEBUG_MARKER in line for line in lines), output


def test_the_messages_themselves_are_unchanged(config_dir):
    """
    The wording is carried over intact: only the gating changed.
    """
    output = _import_wrapper(config_dir, ["--debug"], {"YD_DATA_CLIENT": "myprofile"})
    for message in [
        "Loading environment variables from",
        "Adding 'YD' environment variable(s):",
        "Adding environment-defined variable substitution(s) for:",
        "Loading configuration data from:",
        "Loading imported common configuration data from:",
        "Using 'tag' provided on command line",
        "Using data client profile:",
    ]:
        assert f"{DEBUG_MARKER}{message}" in output


# ---------------------------------------------------------------------------
# The formatted (Rich console) branch, i.e. without '--no-format'
# ---------------------------------------------------------------------------


def test_formatted_preamble_is_silent_by_default(config_dir):
    assert _import_wrapper(config_dir, [], {}, no_format=False) == ""


def test_formatted_preamble_is_shown_under_debug(config_dir):
    # Wrapping breaks a message over several lines, so the marker is asserted
    # for the output rather than for every line of it
    output = _import_wrapper(config_dir, ["--debug"], {}, no_format=False)
    assert DEBUG_MARKER in output
    assert "Loading configuration data from:" in output


# ---------------------------------------------------------------------------
# set_proxy(): runs at command time, so it is exercised directly
# ---------------------------------------------------------------------------


class TestProxyMessages:
    """
    The PAC branch, with the lookup itself stubbed out: what is under test is
    which messages are printed, not pypac's discovery.
    """

    @staticmethod
    def _args(debug: bool):
        return SimpleNamespace(
            debug=debug,
            quiet=False,
            json_output=False,
            count_only=False,
            no_format=True,
            print_pid=False,
            dry_run=False,
            process_csv_only=False,
        )

    def _output(self, capsys, debug: bool, use_pac: bool, proxy: str | None) -> str:
        environment = {"HTTPS_PROXY": proxy} if proxy else {}
        args = self._args(debug)
        with (
            patch.object(wrapper, "ARGS_PARSER", args),
            patch("yellowdog_cli.utils.printing.ARGS_PARSER", args),
            patch.object(
                wrapper,
                "CONFIG_COMMON",
                SimpleNamespace(use_pac=use_pac, url="https://api.yellowdog.ai"),
            ),
            patch.object(wrapper, "pac_context_for_url", nullcontext),
            patch.dict(os.environ, environment, clear=True),
        ):
            wrapper.set_proxy()
        return capsys.readouterr().out

    @pytest.mark.parametrize(
        "use_pac,proxy",
        [
            (True, None),  # PAC enabled, nothing discovered
            (True, "http://proxy.example.com:8080"),  # PAC enabled, proxy found
            (False, "http://proxy.example.com:8080"),  # proxy from the environment
        ],
    )
    def test_silent_by_default(self, capsys, use_pac, proxy):
        assert self._output(capsys, debug=False, use_pac=use_pac, proxy=proxy) == ""

    def test_pac_enabled_with_nothing_found_is_reported_under_debug(self, capsys):
        output = self._output(capsys, debug=True, use_pac=True, proxy=None)
        assert f"{DEBUG_MARKER}Using Proxy Auto-Configuration (PAC)" in output
        assert f"{DEBUG_MARKER}No PAC proxy settings found" in output

    def test_the_proxy_in_use_is_reported_under_debug(self, capsys):
        output = self._output(
            capsys, debug=True, use_pac=False, proxy="http://proxy.example.com:8080"
        )
        assert (
            f"{DEBUG_MARKER}Using HTTPS_PROXY=http://proxy.example.com:8080" in output
        )

    def test_every_proxy_message_carries_the_marker(self, capsys):
        output = self._output(
            capsys, debug=True, use_pac=True, proxy="http://proxy.example.com:8080"
        )
        lines = [line for line in output.splitlines() if line.strip()]
        assert lines
        assert all(DEBUG_MARKER in line for line in lines), output
