"""
The configuration/startup preamble is the start of the '--debug' trace: on
stderr, and only when '--debug' is set.

Most of these messages are emitted while the configuration is loaded, before
any command runs: as the wrapper prepares the run, or on the first use of what
it loads (see utils/lazy.py). They are exercised here in a subprocess with a
configuration of the test's own, by importing 'wrapper.py' and calling
set_proxy(), whose use of CONFIG_COMMON loads it. The proxy messages come from
set_proxy() itself, and are also exercised directly at the foot of this file.
Nothing here contacts the platform, and the PAC lookup itself is never
performed.

Each scenario provokes a different part of the preamble, and is checked in
both directions: silence by default, and — under '--debug' — nothing on
stdout and a trace in which every line is a trace line. The second half is
what catches a message left as print_info(), whether or not this file names
it.
"""

import os
import re
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import yellowdog_cli.utils.wrapper as wrapper
from yellowdog_cli.utils import output_settings
from yellowdog_cli.utils.output_style import DEBUG_MARKER

# A trace line: the timestamp, the marker, the time since the start, the
# module, the message
TRACE_LINE = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?: \(\d+\))? : "
    rf"{re.escape(DEBUG_MARKER)}\[\+\d+\.\d{{3}}s\] \w+: "
)


def _traced(message: str, trace: str) -> bool:
    """
    Whether 'message' begins a line of the trace.
    """
    return any(
        (match := TRACE_LINE.match(line)) is not None
        and line[match.end() :].startswith(message)
        for line in trace.splitlines()
    )


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
) -> tuple[str, str]:
    """
    Import wrapper.py in a subprocess, configure the output settings and call
    set_proxy(), which loads the configuration, as a command with the given
    arguments and environment would, and return everything it printed to
    stdout and to stderr. The data client configuration is loaded explicitly afterwards,
    since it is loaded by the data client commands rather than by the
    wrapper.
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
            # As a command run does (prepare_run()): output configured from
            # the command line before the configuration loads
            "from yellowdog_cli.utils.output_settings import configure_output; "
            "configure_output(wrapper.ARGS_PARSER); "
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
    return result.stdout, result.stderr


@pytest.mark.parametrize("_name,args,env", SCENARIOS, ids=SCENARIO_IDS)
def test_preamble_is_silent_by_default(config_dir, _name, args, env):
    assert _import_wrapper(config_dir, args, env) == ("", "")


@pytest.mark.parametrize("_name,args,env", SCENARIOS, ids=SCENARIO_IDS)
def test_whole_preamble_is_traced_under_debug(config_dir, _name, args, env):
    stdout, stderr = _import_wrapper(config_dir, ["--debug", *args], env)
    assert stdout == ""
    lines = [line for line in stderr.splitlines() if line.strip()]
    assert lines, "expected the preamble to be traced under '--debug'"
    # A message left as print_info() or print_warning() would appear here
    # without the trace's form
    assert all(TRACE_LINE.match(line) for line in lines), stderr


@pytest.mark.parametrize("extra", [["--json"], ["--quiet"]], ids=["json", "quiet"])
def test_the_preamble_is_traced_under_json_and_quiet(config_dir, extra):
    """
    The trace is on stderr, so neither '--json' nor '--quiet' silences it.
    """
    stdout, stderr = _import_wrapper(config_dir, ["--debug", *extra], {})
    assert stdout == ""
    assert _traced("Loading configuration data from:", stderr)


def test_the_messages_themselves_are_unchanged(config_dir):
    """
    The messages' wording is their own: '--debug' decides only whether they
    are traced.
    """
    # '--tag' given, for its message: yd-list does not default it to ''
    _, trace = _import_wrapper(
        config_dir, ["--debug", "--tag", "t"], {"YD_DATA_CLIENT": "myprofile"}
    )
    for message in [
        "Loading environment variables from",
        "Adding 'YD' environment variable(s):",
        "Adding environment-defined variable substitution(s) for:",
        "Loading configuration data from:",
        "Loading imported common configuration data from:",
        "Using 'tag' provided on command line",
        "Using data client profile:",
    ]:
        assert _traced(message, trace), trace


def test_each_line_names_the_module_it_came_from(config_dir):
    _, trace = _import_wrapper(config_dir, ["--debug"], {})
    assert "s] load_config: Loading configuration data from:" in trace


# ---------------------------------------------------------------------------
# Without '--no-format': the trace is plain text either way
# ---------------------------------------------------------------------------


def test_formatted_preamble_is_silent_by_default(config_dir):
    assert _import_wrapper(config_dir, [], {}, no_format=False) == ("", "")


def test_the_trace_is_unformatted_without_no_format(config_dir):
    stdout, stderr = _import_wrapper(config_dir, ["--debug"], {}, no_format=False)
    assert stdout == ""
    assert "\x1b[" not in stderr
    assert _traced("Loading configuration data from:", stderr)


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
            output_settings.configured(args),
            patch.object(
                wrapper,
                "CONFIG_COMMON",
                SimpleNamespace(use_pac=use_pac, url="https://api.yellowdog.ai"),
            ),
            # set_proxy() imports it where it uses it, from pypac
            patch("pypac.pac_context_for_url", nullcontext),
            patch.dict(os.environ, environment, clear=True),
        ):
            wrapper.set_proxy()
        captured = capsys.readouterr()
        assert captured.out == ""
        return captured.err

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
        assert _traced("Using Proxy Auto-Configuration (PAC)", output)
        assert _traced("No PAC proxy settings found", output)

    def test_the_proxy_in_use_is_reported_under_debug(self, capsys):
        output = self._output(
            capsys, debug=True, use_pac=False, proxy="http://proxy.example.com:8080"
        )
        assert _traced("Using HTTPS_PROXY=http://proxy.example.com:8080", output)

    def test_every_proxy_message_is_a_trace_line(self, capsys):
        output = self._output(
            capsys, debug=True, use_pac=True, proxy="http://proxy.example.com:8080"
        )
        lines = [line for line in output.splitlines() if line.strip()]
        assert lines
        assert all(TRACE_LINE.match(line) for line in lines), output
