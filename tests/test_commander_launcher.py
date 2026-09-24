"""
Tests for yd-commander's command-line options: what launcher.parse_args() turns
them into, and what it refuses. Deliberately Qt-free, like the launcher itself,
so these run where PyQt6 is not installed.
"""

from os.path import join

import pytest

from yellowdog_cli.commander.launcher import parse_args
from yellowdog_cli.commander.startup import StartupSettings


@pytest.fixture
def files(tmp_path, monkeypatch):
    """A launch directory holding a config file and both definition files."""
    monkeypatch.chdir(tmp_path)
    for name in ("config.toml", "wr.json", "wp.jsonnet"):
        (tmp_path / name).write_text("")
    return tmp_path


def refused(argv: list[str], capsys) -> str:
    """Parse, expecting argparse to refuse; return what it said."""
    with pytest.raises(SystemExit) as exc:
        parse_args(argv)
    assert exc.value.code == 2
    return capsys.readouterr().err


def test_no_options_is_the_default_state():
    assert parse_args([]) == StartupSettings()


def test_every_option_reaches_the_settings(files):
    settings = parse_args(
        [
            "config.toml",
            "-y",
            "-n",
            "ns",
            "-t",
            "tag",
            "--name",
            "proj-*",
            "-P",
            "tag/results*",
            "-v",
            "a=1",
            "-v",
            "b=",
            "-r",
            "wr.json",
            "-p",
            "wp.jsonnet",
        ]
    )
    assert settings == StartupSettings(
        config_file=join(files, "config.toml"),
        disable_confirmations=True,
        namespace="ns",
        tag="tag",
        name_glob="proj-*",
        object_path="tag/results*",
        variables=("a=1", "b="),
        wr_file=join(files, "wr.json"),
        wp_file=join(files, "wp.jsonnet"),
    )


def test_long_forms(files):
    settings = parse_args(
        [
            "--config",
            "config.toml",
            "--namespace",
            "ns",
            "--tag",
            "tag",
            "--path",
            "p*",
            "--variable",
            "a=1",
            "--work-requirement",
            "wr.json",
            "--worker-pool",
            "wp.jsonnet",
        ]
    )
    assert settings.config_file == join(files, "config.toml")
    assert (settings.namespace, settings.tag, settings.object_path) == (
        "ns",
        "tag",
        "p*",
    )
    assert settings.variables == ("a=1",)
    assert settings.wr_file == join(files, "wr.json")
    assert settings.wp_file == join(files, "wp.jsonnet")


def test_relative_definition_paths_resolve_against_the_launch_directory(files):
    # Not against the config file's directory: a path typed in a shell means
    # the shell's directory.
    (files / "defs").mkdir()
    (files / "defs" / "wr.json").write_text("")
    (files / "configs").mkdir()
    (files / "configs" / "config.toml").write_text("")
    settings = parse_args(["-c", "configs/config.toml", "-r", "defs/wr.json"])
    assert settings.wr_file == join(files, "defs", "wr.json")


def test_the_config_file_cannot_be_given_twice(files, capsys):
    assert "once" in refused(["config.toml", "-c", "config.toml"], capsys)


@pytest.mark.parametrize("option", ["-c", "-r", "-p"])
def test_a_missing_file_fails_the_launch(files, capsys, option):
    assert "does not exist" in refused([option, "missing.json"], capsys)


def test_a_missing_positional_config_file_fails_the_launch(files, capsys):
    assert "does not exist" in refused(["missing.toml"], capsys)


def test_a_directory_is_not_a_file(files, capsys):
    (files / "defs").mkdir()
    assert "does not exist" in refused(["-r", "defs"], capsys)


@pytest.mark.parametrize("variable", ["a", "=1", ""])
def test_a_variable_must_be_name_equals_value(capsys, variable):
    assert "name=value" in refused(["-v", variable], capsys)


@pytest.mark.parametrize("variable", ["title=my run", "a=1\tb=2", "a=1\nb=2"])
def test_a_variable_cannot_contain_whitespace(capsys, variable):
    # The User Variables field is split on whitespace when a command is built,
    # so 'title=my run' would reach the CLI as 'title=my' and 'run'
    assert "whitespace" in refused(["-v", variable], capsys)


@pytest.mark.parametrize("option", ["-n", "-t", "--name", "-P"])
@pytest.mark.parametrize("value", ["two\nlines", "a\ttab", "cr\r"])
def test_a_field_value_must_survive_the_field(capsys, option, value):
    # The edit-box handler deletes tabs and newlines
    assert "single line" in refused([option, value], capsys)


@pytest.mark.parametrize("option", ["-n", "-t", "--name", "-P"])
def test_a_field_value_cannot_be_empty(capsys, option):
    assert "must not be empty" in refused([option, ""], capsys)


def test_a_path_may_contain_spaces():
    # Unlike a variable, the Path field is taken whole
    assert parse_args(["-P", "my results/*"]).object_path == "my results/*"
