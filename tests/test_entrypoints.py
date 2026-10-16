"""
Basic check that all the entrypoints are present, and can be invoked: 'yd'
and the words after it, and every deprecated yd-* script pyproject.toml
declares.
"""

import sys
from pathlib import Path

import pytest
from cli_test_helpers import shell

from yellowdog_cli.utils.top_level import TOP_LEVEL

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10: tomli, which the CLI already depends on
    import tomli as tomllib

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
# Every deprecated yd-* script, from pyproject.toml, so none can be missed
SCRIPTS = sorted(
    name
    for name in tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"][
        "scripts"
    ]
    if name.startswith("yd-")
)
# Those that print a document rather than a usage and take no '--help' of note
_BARE = {"yd-help", "yd-version"}


def test_every_script_is_checked():
    assert len(SCRIPTS) > 40  # The table was read, not an empty one


@pytest.mark.parametrize(
    "cmd,expected",
    [
        *((script if script in _BARE else f"{script} --help", 0) for script in SCRIPTS),
        # 'yd': every word after it, a verb's help, and the usage errors
        ("yd --help", 0),
        *((f"yd {word} --help", 0) for word in sorted(TOP_LEVEL)),
        ("yd workrequirement submit --help", 0),
        ("yd wr", 2),  # no verb
        ("yd", 2),  # no command
    ],
)
def test_entrypoint(cmd, expected):
    assert shell(cmd).exit_code == expected
