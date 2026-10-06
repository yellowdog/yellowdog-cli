"""
yd-mcp's own command line: what launcher.parse_args() turns it into and what
it refuses. Needs neither the 'mcp' extra nor the SDK, like the launcher.
"""

import os

import pytest

from yellowdog_cli.mcp.launcher import main, parse_args
from yellowdog_cli.mcp.tools import ServerSettings


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text("")
    return tmp_path


def _refused(argv, capsys) -> str:
    with pytest.raises(SystemExit) as exc:
        parse_args(argv)
    assert exc.value.code == 2
    return capsys.readouterr().err


def test_no_options(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert parse_args([]) == ServerSettings(
        config_file=None, namespace=None, tag=None, variables=()
    )


def test_every_option(config):
    settings = parse_args(
        [
            "config.toml",
            "-n",
            "ns",
            "-t",
            "tag",
            "-v",
            "a=1",
            "-v",
            "b=2",
            "--transport",
            "stdio",
        ]
    )
    assert settings == ServerSettings(
        config_file=os.path.join(str(config), "config.toml"),
        namespace="ns",
        tag="tag",
        variables=("a=1", "b=2"),
        transport="stdio",
    )
    assert settings.working_dir == str(config)


def test_the_config_file_as_an_option(config):
    assert parse_args(["-c", "config.toml"]).config_file == os.path.join(
        str(config), "config.toml"
    )


def test_a_missing_config_file_is_refused(config, capsys):
    assert "nope.toml" in _refused(["nope.toml"], capsys)


def test_the_config_file_given_twice_is_refused(config, capsys):
    assert "once" in _refused(["config.toml", "-c", "config.toml"], capsys)


def test_the_config_option_given_twice_is_refused(config, capsys):
    (config / "other.toml").write_text("")
    assert "once" in _refused(["-c", "config.toml", "-c", "other.toml"], capsys)


def test_a_variable_must_be_name_equals_value(config, capsys):
    assert "name=value" in _refused(["-v", "novalue"], capsys)


def test_only_stdio_for_now(config, capsys):
    assert "streamable-http" in _refused(["--transport", "streamable-http"], capsys)


def test_help_needs_no_mcp(capsys):
    with pytest.raises(SystemExit) as exc:
        parse_args(["--help"])
    assert exc.value.code == 0
    assert "yd-mcp" in capsys.readouterr().out


def test_the_missing_extra_message(monkeypatch, capsys):
    import yellowdog_cli.mcp.launcher as launcher

    def missing():
        raise ImportError("The MCP server is not installed by default")

    monkeypatch.setattr(launcher, "check_mcp_imports", missing)
    monkeypatch.setattr("sys.argv", ["yd-mcp"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "not installed" in capsys.readouterr().err


def test_a_variable_name_the_cli_refuses_is_refused_at_launch(config, capsys):
    assert "invalid variable name '.x'" in _refused(["-v", ".x=1"], capsys)


def test_a_reserved_variable_name_is_refused_at_launch(config, capsys):
    assert "'namespace' is not a variable" in _refused(["-v", "namespace=n"], capsys)
