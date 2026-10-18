"""
commander/host.py's child-process helpers, without Qt: a 'yd-*' console
script of this installation is run under this interpreter, by the module its
entry point names, so that the PATH Commander was started with does not
decide which CLI runs; and every console-script module can be run that way.
"""

import pathlib
import subprocess
import sys
from importlib.metadata import entry_points
from importlib.util import find_spec

import pytest

from yellowdog_cli.commander.host import CHILD_ENVIRONMENT, cli_program


@pytest.mark.parametrize(
    "command, module",
    [
        ("yd-submit", "yellowdog_cli.submit"),
        ("yd-commander", "yellowdog_cli.commander.launcher"),  # No rule gives this
        ("yd-variables", "yellowdog_cli.variables"),
    ],
)
def test_a_console_script_runs_under_this_interpreter(command, module):
    assert cli_program(command, ["-q"]) == (sys.executable, ["-m", module, "-q"])


@pytest.mark.parametrize("noun", ["workrequirement", "wr"])
def test_a_yd_command_runs_the_dispatcher(noun):
    # The verb ahead of the arguments Commander adds, which follow it
    assert cli_program(f"yd {noun} submit", ["-q"]) == (
        sys.executable,
        ["-m", "yellowdog_cli.yd", noun, "submit", "-q"],
    )


def test_a_yd_command_shows_the_form_typed(tmp_path):
    # Run as its own module, yd list called itself yd-list
    program, args = cli_program("yd list", ["--help"])
    result = subprocess.run(
        [program, *args], capture_output=True, text=True, timeout=60, cwd=tmp_path
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("usage: yd list ")


def test_an_unknown_yd_script_name_runs_the_dispatcher():
    # Not another installation's script on the PATH
    assert cli_program("yd-no-such-command", []) == (
        sys.executable,
        ["-m", "yellowdog_cli.yd", "yd-no-such-command"],
    )


def test_anything_else_runs_as_it_is():
    assert cli_program("ls", ["-l"]) == ("ls", ["-l"])


def test_children_write_utf8():
    assert CHILD_ENVIRONMENT["PYTHONIOENCODING"] == "utf-8"


def _console_script_modules() -> list[tuple[str, str]]:
    return sorted(
        (point.name, point.value.split(":")[0])
        for point in entry_points(group="console_scripts")
        if point.value.startswith("yellowdog_cli.")
    )


@pytest.mark.parametrize("name, module", _console_script_modules())
def test_every_console_script_module_runs_under_python_m(name, module):
    """
    Commander and the MCP server run a command as 'python -m <module>', which
    runs main() only from the module's '__main__' guard: yd workrequirement
    cancel and yd-application had none, so run that way they parsed and did
    nothing.
    """
    spec = find_spec(module)
    assert spec is not None and spec.origin is not None, module
    source = pathlib.Path(spec.origin).read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in source, name
