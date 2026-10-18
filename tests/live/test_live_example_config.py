"""
tests/live/system-tests.example.toml, the live system tests' configuration
to copy: held to the schema (harness/config.py's SCHEMA), so that it names
every key, in its own section, set or commented out, and nothing else; marks
a key 'required' exactly when the schema does; and loads as it is.
"""

import re
from pathlib import Path

import pytest
from harness import config
from harness.config import SCHEMA, load_live_config

EXAMPLE = Path(__file__).with_name("system-tests.example.toml")
_SECTION = re.compile(r"^#?\s*\[(\w+)\]")
_KEY = re.compile(r"^#?\s*([a-z_]+)\s*=")


@pytest.fixture(autouse=True)
def _no_default_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DEFAULT_PATH", tmp_path / "absent.toml")


def _named() -> dict[str, dict[str, str]]:
    """
    Each section's keys as the example names them, set or commented out,
    with the line naming each.
    """
    named: dict[str, dict[str, str]] = {}
    section = None
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        if match := _SECTION.match(line):
            section = match.group(1)
            named.setdefault(section, {})
        elif (match := _KEY.match(line)) and section is not None:
            named[section][match.group(1)] = line
    return named


def test_the_example_names_every_section_and_key_of_the_schema():
    named = _named()
    assert set(named) == set(SCHEMA)
    for section, keys in SCHEMA.items():
        assert set(named[section]) == set(keys), section


def test_a_key_is_marked_required_exactly_when_it_is():
    for section, keys in _named().items():
        for key, line in keys.items():
            marked = "# required" in line
            assert marked == SCHEMA[section][key].required, f"[{section}] {key}"


def test_the_example_loads_as_it_is():
    loaded = load_live_config({"YDST_CONFIG": str(EXAMPLE)})
    assert loaded.primary == "aws"
    assert list(loaded.providers) == ["aws"]
    assert loaded.warnings == ()
