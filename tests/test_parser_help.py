"""
How '--help' lays out a command's options: the command's own first, under
'options', and the options every command shares after them, under 'universal
options', each summarised as '[universal options]' in the usage line, so the
options that say what the command does are the first read.
"""

from yellowdog_cli.utils.command_registry import (
    COMMANDS,
    COMMON_OPTIONS,
    CommandKind,
    build_parser,
)
from yellowdog_cli.utils.noun_registry import command_named


def _help(name: str) -> str:
    command = command_named(name)
    assert command is not None
    return build_parser(command, prog=name).format_help()


def test_the_commands_own_options_come_before_the_common_ones():
    text = _help("yd wr submit")
    assert text.index("--follow") < text.index("universal options:")
    assert text.index("universal options:") < text.index("--key")


def test_the_usage_line_summarises_the_common_options():
    usage = build_parser(
        command_named("yd wr submit"), prog="yd wr submit"
    ).format_usage()
    assert "[universal options]" in usage
    assert "--follow" in usage
    for option in COMMON_OPTIONS[CommandKind.API]:
        for flag in option.flags:
            assert f"[{flag}" not in usage, flag


def test_every_common_option_is_under_common_options():
    text = _help("yd wr submit")
    common = text[text.index("universal options:") :]
    for option in COMMON_OPTIONS[CommandKind.API]:
        assert option.flags[0] in common, option.flags[0]


def test_a_data_client_command_groups_its_own_common_set():
    text = _help("yd data upload")
    common = text[text.index("universal options:") :]
    assert "--config" in common
    assert "--key" not in text


def test_a_command_with_no_common_options_has_no_such_group():
    parser = build_parser(COMMANDS["yd-version"], prog="yd version")
    assert "universal options" not in parser.format_help()
    assert "[universal options]" not in parser.format_usage()


def test_a_hidden_option_stays_out_of_the_usage_line():
    # 'yd data list' hides '--dry-run' (noun_registry.py)
    usage = build_parser(
        command_named("yd data list"), prog="yd data list"
    ).format_usage()
    assert "--dry-run" not in usage


def test_an_option_error_shows_the_short_usage(capsys):
    import pytest

    parser = build_parser(command_named("yd wr list"), prog="yd wr list")
    with pytest.raises(SystemExit):
        parser.parse_args(["--no-such-option"])
    err = capsys.readouterr().err
    assert "[universal options]" in err
    assert "--pac" not in err
