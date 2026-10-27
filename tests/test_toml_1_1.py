"""
TOML 1.1, which the configuration documentation promises, read by both
of the CLI's TOML loaders: the configuration file's and a TOML
specification's (load_toml_file_with_variable_substitutions()) and a
CSV-expanded TOML Work Requirement's (load_toml_file_with_csv_task_expansion()).

The standard library's 'tomllib' reads TOML 1.1 only from Python 3.15, so
these fail on an earlier Python if either loader stops using 'tomli'.
"""

from datetime import datetime, time

import pytest

from yellowdog_cli.utils.csv_data import load_toml_file_with_csv_task_expansion
from yellowdog_cli.utils.file_substitution import (
    load_toml_file_with_variable_substitutions,
)

# Each construct new in TOML 1.1, none of which TOML 1.0 accepts
TOML_1_1 = """\
inline = {
    a = 1,
    b = "{{env:YD_TOML_1_1_TEST}}",
}
escape = "\\e"
hex_escape = "\\x41"
no_seconds_time = 07:30
no_seconds_datetime = 2026-10-27T07:30
"""


@pytest.fixture(autouse=True)
def _variable(monkeypatch):
    monkeypatch.setenv("YD_TOML_1_1_TEST", "substituted")


def test_the_toml_loader_reads_toml_1_1(tmp_path):
    toml_file = tmp_path / "spec.toml"
    toml_file.write_text(TOML_1_1, encoding="utf-8")

    data = load_toml_file_with_variable_substitutions(str(toml_file))

    assert data == {
        "inline": {"a": 1, "b": "substituted"},
        "escape": "\x1b",
        "hex_escape": "A",
        "no_seconds_time": time(7, 30),
        "no_seconds_datetime": datetime(2026, 10, 27, 7, 30),
    }


def test_the_csv_loader_reads_toml_1_1(tmp_path):
    toml_file = tmp_path / "wr.toml"
    toml_file.write_text(
        """\
[[taskGroups]]
tasks = [
    {
        name = "task_<<x>>",
        environment = {
            X = "<<x>>",
        },
    },
]
""",
        encoding="utf-8",
    )
    (tmp_path / "data.csv").write_text("x\n1\n2\n", encoding="utf-8")

    data = load_toml_file_with_csv_task_expansion(
        str(toml_file), ["data.csv"], files_directory=str(tmp_path)
    )

    assert data["taskGroups"][0]["tasks"] == [
        {"name": "task_1", "environment": {"X": "1"}},
        {"name": "task_2", "environment": {"X": "2"}},
    ]
