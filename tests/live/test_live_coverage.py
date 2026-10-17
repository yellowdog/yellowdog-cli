"""
The coverage record: each command 'yd' ran, as the user would type it, per
process, and only when it exited as expected.
"""

import pytest
from harness import coverage


@pytest.fixture
def directory(tmp_path):
    coverage.configure(tmp_path)
    yield tmp_path
    coverage.configure(None)


def test_a_noun_verb_is_recorded_by_the_noun(directory):
    coverage.record(("workrequirement", "show", "x", "--quiet"))
    assert coverage.recorded(directory) == {"yd workrequirement show"}


def test_an_alias_is_recorded_as_its_noun(directory):
    coverage.record(("wr", "show", "x"))
    coverage.record(("cr", "terminate", "x", "--yes"))
    assert coverage.recorded(directory) == {
        "yd workrequirement show",
        "yd computerequirement terminate",
    }


def test_a_top_level_command_is_recorded(directory):
    coverage.record(("list", "keyrings", "--json"))
    coverage.record(("doctor", "--json"))
    assert coverage.recorded(directory) == {"yd list", "yd doctor"}


def test_what_is_not_a_command_is_not_recorded(directory):
    coverage.record(("--version",))
    coverage.record(("nonsense", "verb"))
    coverage.record(("wr", "--help"))
    assert coverage.recorded(directory) == set()


def test_nothing_is_recorded_unconfigured(tmp_path):
    coverage.configure(None)
    coverage.record(("wr", "show", "x"))
    assert coverage.recorded(tmp_path) == set()


def test_processes_record_to_their_own_files(directory, monkeypatch):
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    coverage.record(("wr", "show", "x"))
    assert (directory / "coverage-gw3.jsonl").exists()


def test_the_expected_set_is_every_noun_verb_and_command():
    expected = coverage.expected()
    assert "yd workrequirement submit" in expected
    assert "yd cloudinfo prices" in expected
    assert "yd doctor" in expected
    assert "yd wr submit" not in expected  # nouns by their names only
    assert "yd workrequirement" not in expected


def test_only_an_expected_exit_code_is_recorded(directory, tmp_path, monkeypatch):
    import sys

    from harness import config as config_module
    from harness.config import load_live_config
    from harness.run import Run
    from harness.yd import Yd
    from live_samples import AWS, PLATFORM, write_config

    monkeypatch.setattr(config_module, "DEFAULT_PATH", tmp_path / "absent.toml")
    config = load_live_config(write_config(tmp_path, PLATFORM + AWS))
    run = Run.start(config, tmp_path / "runs")
    # Exits with the last argument before '--config <file>'
    exits_as = Yd(
        run, program=(sys.executable, "-c", "import sys; sys.exit(int(sys.argv[-3]))")
    )
    exits_as("wr", "show", "0")
    exits_as("cr", "show", "6", ok=(0, 6))
    exits_as("task", "show", "1", check=False)
    assert coverage.recorded(directory) == {
        "yd workrequirement show",
        "yd computerequirement show",
    }


def test_every_entry_not_exercised_is_a_command_with_a_reason():
    expected = coverage.expected()
    for command, reason in coverage.NOT_EXERCISED.items():
        assert command in expected, command
        assert reason.strip(), command


def test_the_permanent_entries_are_there():
    for command in (
        "yd cloudwizard",
        "yd commander",
        "yd mcp",
        "yd help",
        "yd version",
        "yd completion",
        "yd format-json",
        "yd jsonnet2json",
        "yd node stop",
        "yd node start",
    ):
        assert command in coverage.NOT_EXERCISED, command


def test_the_gate_names_each_command_not_exercised(directory):
    coverage.record(("doctor",))
    problems = coverage.gate(directory, excluded={})
    expected = coverage.expected() - set(coverage.NOT_EXERCISED) - {"yd doctor"}
    assert len(problems) == len(expected)
    assert not any("yd doctor" in p for p in problems)


def test_the_gate_passes_when_everything_was_exercised(directory, monkeypatch):
    for command in coverage.expected():
        words = command.split()[1:]
        coverage.record(tuple(words))
    assert coverage.gate(directory, excluded={}) == []


def test_unconfigurable_data_verbs_are_left_out_and_named(directory):
    for command in coverage.expected() - coverage.DATA_COMMANDS:
        coverage.record(tuple(command.split()[1:]))
    excluded = {command: "no [data] section" for command in coverage.DATA_COMMANDS}
    assert coverage.gate(directory, excluded=excluded) == []


def test_an_offline_test_records_nowhere():
    # tests/live/conftest.py turns recording off for every test not marked
    # 'live', so an offline test's Yd calls never count toward the gate
    assert coverage._DIRECTORY is None


def test_yd_schema_is_left_to_the_unit_tests():
    # It takes neither --config nor --quiet, and never reaches the Platform
    assert "yd schema" in coverage.NOT_EXERCISED


PERMANENT = {
    "yd node restart",
    "yd cloudwizard",
    "yd commander",
    "yd mcp",
    "yd help",
    "yd version",
    "yd completion",
    "yd format-json",
    "yd jsonnet2json",
    "yd schema",
    "yd node stop",
    "yd node start",
}


def test_only_permanent_entries_remain():
    assert set(coverage.NOT_EXERCISED) == PERMANENT
