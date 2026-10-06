"""
yd-submit's option combinations that cannot apply together are refused as
the command line is parsed (check_submit_combinations in the registry),
rather than silently ignored.
"""

import pytest

from yellowdog_cli.utils.args import CLIParser


def _parse(*argv: str) -> CLIParser:
    return CLIParser(command="yd-submit", argv=list(argv))


@pytest.mark.parametrize(
    "argv, message",
    [
        (["-j", "raw.json", "wr.json"], "--json-raw cannot be used with a Work"),
        (["-j", "raw.json", "-r", "wr.json"], "--json-raw cannot be used with --work"),
        (["-j", "raw.json", "-A", "wr"], "--json-raw cannot be used with --add-to"),
        (
            ["-j", "raw.json", "-V", "a.csv"],
            "--json-raw cannot be used with --csv-file",
        ),
        (["-j", "raw.json", "-p"], "--json-raw cannot be used with --process-csv"),
        (["-j", "raw.json", "-C", "3"], "--json-raw cannot be used with --task-count"),
        (["-j", "raw.json", "-G", "3"], "--json-raw cannot be used with --task-group"),
        (["-j", "raw.json", "-e"], "--json-raw cannot be used with --empty"),
        (["-j", "raw.json", "--validate"], "--json-raw cannot be used with --validate"),
        (["-A", "wr", "-H"], "--add-to cannot be used with --hold"),
        (["-A", "wr", "-e"], "--add-to cannot be used with --empty"),
        (["-E"], "--exit-on-failure needs --follow or --progress"),
    ],
)
def test_refused(argv, message, capsys):
    with pytest.raises(SystemExit) as raised:
        _parse(*argv)
    assert raised.value.code == 2
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["-j", "raw.json", "-H", "-f"],
        ["-A", "wr", "wr.json", "-V", "a.csv"],
        ["-E", "-f"],
        ["-E", "--progress"],
        ["wr.json", "-C", "3", "-G", "2", "-e", "-H"],
    ],
)
def test_allowed(argv):
    _parse(*argv)
