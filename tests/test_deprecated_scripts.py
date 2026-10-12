"""
The 'yd-*' scripts released before 'yd': each still runs, warning on stderr
of the 'yd' form that replaces it; 'yd <word>' and 'python -m' never warn;
'--quiet' silences the warning. The noun scripts and yd-completion, never
released, are gone.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from yellowdog_cli.utils.command_registry import COMMANDS, OTHER_COMMANDS
from yellowdog_cli.utils.noun_registry import REPLACED_BY_VERBS
from yellowdog_cli.utils.top_level import SCRIPT_FORMS, deprecation_message

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10
    import tomli as tomllib


def _scripts() -> dict[str, str]:
    with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["scripts"]


def test_every_script_but_yd_is_deprecated():
    assert set(_scripts()) - {"yd"} == set(SCRIPT_FORMS)


def test_the_forms():
    assert SCRIPT_FORMS["yd-submit"] == ["yd workrequirement submit"]
    assert SCRIPT_FORMS["yd-list"] == ["yd list"]
    assert SCRIPT_FORMS["yd-commander"] == ["yd commander"]
    assert "yd-completion" not in SCRIPT_FORMS


def test_the_unreleased_scripts_are_gone():
    scripts = _scripts()
    for gone in ("yd-wr", "yd-workrequirement", "yd-data", "yd-completion"):
        assert gone not in scripts


def test_every_registry_and_other_command_is_covered():
    for name in [*COMMANDS, *OTHER_COMMANDS]:
        assert name in SCRIPT_FORMS or name == "yd-completion", name
    assert set(REPLACED_BY_VERBS) <= set(SCRIPT_FORMS)


def test_the_message():
    assert deprecation_message("yd-list") == (
        "'yd-list' is deprecated and will be removed in a future release: use 'yd list'"
    )


def test_the_message_offers_every_form():
    assert deprecation_message("yd-terminate").endswith(
        "use 'yd computerequirement terminate', 'yd instance terminate' or"
        " 'yd node terminate'"
    )


def _run(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize(
    "argv, form",
    [
        (["yd-version", "--json"], "yd version"),
        (["yd-help", "--json"], "yd help"),
        (["yd-schema", "--list"], "yd schema"),
        (["yd-format-json", "--help"], "yd format-json"),
        (["yd-variables", "--quiet"], None),  # --quiet: silenced
    ],
)
def test_a_script_warns_of_its_replacement(argv, form):
    result = _run(*argv)
    if form is None:
        assert "deprecated" not in result.stderr
    else:
        assert f"use '{form}'" in " ".join(result.stderr.split())
    assert "will be removed" not in result.stdout


@pytest.mark.parametrize(
    "argv",
    [
        ["yd", "version", "--json"],
        ["yd", "help", "--json"],
        ["yd", "schema", "--list"],
        [sys.executable, "-m", "yellowdog_cli.version", "--json"],
    ],
)
def test_yd_and_python_m_do_not_warn(argv):
    assert "deprecated" not in _run(*argv).stderr
