"""
yd-version (version.py): a single-version flag prints the version alone, or
nothing and exit 1 when it is not installed or could not be read, every
flag alike; under --json such a version is null; --debug is refused with a
single-version flag; the docs link is the release tag's, or main's for a
version that is no release; and the full report is a table of the versions
with the author, licence and docs link beneath, plus a table of where the
CLI runs from under --debug; --json is coloured on a terminal, unless
--no-format is given.
"""

import json
import sys

import pytest

import yellowdog_cli.version as yd_version
from yellowdog_cli.utils import version_info
from yellowdog_cli.utils.dataclient.rclone_version import NOT_INSTALLED, UNKNOWN


def _run(monkeypatch, capsys, *argv: str) -> tuple[str, int]:
    monkeypatch.setattr(sys, "argv", ["yd-version", *argv])
    code = 0
    try:
        yd_version.main()
    except SystemExit as e:
        code = int(e.code or 0)
    return capsys.readouterr().out, code


@pytest.mark.parametrize(
    "flag, getter",
    [
        ("--sdk", "sdk_version"),
        ("--jsonnet", "_jsonnet_version"),
        ("--rclone", "_rclone_version"),
        ("--mcp", "_mcp_version"),
    ],
)
@pytest.mark.parametrize("missing", [NOT_INSTALLED, UNKNOWN])
def test_a_version_not_to_be_had_prints_nothing_and_exits_1(
    monkeypatch, capsys, flag, getter, missing
):
    monkeypatch.setattr(yd_version, getter, lambda: missing)
    out, code = _run(monkeypatch, capsys, flag)
    assert (out, code) == ("", 1)


def test_a_version_is_printed_alone(monkeypatch, capsys):
    monkeypatch.setattr(yd_version, "_rclone_version", lambda: "1.75.1")
    assert _run(monkeypatch, capsys, "--rclone") == ("1.75.1\n", 0)


def test_json_has_null_for_a_version_not_to_be_had(monkeypatch, capsys):
    monkeypatch.setattr(yd_version, "_rclone_version", lambda: UNKNOWN)
    monkeypatch.setattr(yd_version, "sdk_version", lambda: NOT_INSTALLED)
    out, code = _run(monkeypatch, capsys, "--json")
    document = json.loads(out)
    assert code == 0
    assert document["rclone"] is None and document["sdk"] is None


def test_debug_with_a_single_version_flag_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["yd-version", "--cli", "--debug"])
    with pytest.raises(SystemExit) as raised:
        yd_version.main()
    assert raised.value.code == 2
    assert "--debug cannot be used with --cli" in capsys.readouterr().err


@pytest.mark.parametrize(
    "version, ref",
    [("1.2.3", "v1.2.3"), ("1.2.3.dev4", "main"), ("1.2.3rc1", "main")],
)
def test_the_docs_link(version, ref):
    assert version_info.docs_url(version) == (
        f"https://github.com/yellowdog/yellowdog-cli/blob/{ref}/README.md"
    )


def _stub_versions(monkeypatch) -> None:
    monkeypatch.setattr(yd_version, "sdk_version", lambda: "15.6.0")
    monkeypatch.setattr(yd_version, "_jsonnet_version", lambda: NOT_INSTALLED)
    monkeypatch.setattr(yd_version, "_rclone_version", lambda: "1.75.1")
    monkeypatch.setattr(yd_version, "_mcp_version", lambda: "2.3.0")


def _row(out: str, label: str) -> list[str]:
    """
    The cells of the table row whose first cell is 'label'.
    """
    for line in out.splitlines():
        cells = [cell.strip() for cell in line.split("│")[1:-1]]
        if cells and cells[0] == label:
            return cells
    raise AssertionError(f"no row {label!r} in:\n{out}")


@pytest.mark.parametrize("argv", [(), ("--nf",)])
def test_the_report_is_a_table_with_the_details_beneath(monkeypatch, capsys, argv):
    _stub_versions(monkeypatch)
    out, code = _run(monkeypatch, capsys, *argv)
    assert code == 0
    assert "\x1b[" not in out
    assert _row(out, "Component") == ["Component", "Version"]
    assert _row(out, "YellowDog SDK") == ["YellowDog SDK", "15.6.0"]
    assert _row(out, "Jsonnet") == ["Jsonnet", NOT_INSTALLED]
    assert _row(out, "MCP SDK") == ["MCP SDK", "2.3.0"]
    details = out.split("┘", 1)[1]
    assert "Licence:" in details
    assert f"Docs:    {version_info.docs_url()}" in details
    assert "Python Executable" not in out


def test_debug_adds_a_table_of_where_the_cli_runs_from(monkeypatch, capsys):
    _stub_versions(monkeypatch)
    monkeypatch.setattr(yd_version, "find_rclone", lambda: None)
    monkeypatch.setattr(yd_version, "path", ["/first", "/second"])
    out, code = _run(monkeypatch, capsys, "--debug")
    assert code == 0
    assert _row(out, "Detail") == ["Detail", "Value"]
    assert _row(out, "rclone Binary") == ["rclone Binary", "Not found"]
    assert _row(out, "Path-02") == ["Path-02", "/second"]


@pytest.mark.parametrize("argv, coloured", [((), True), (("--nf",), False)])
def test_json_is_coloured_on_a_terminal_unless_no_format(
    monkeypatch, capsys, argv, coloured
):
    from io import StringIO

    from rich.console import Console
    from rich.highlighter import JSONHighlighter

    from yellowdog_cli.utils import printing

    _stub_versions(monkeypatch)
    terminal = StringIO()
    monkeypatch.setattr(
        printing,
        "CONSOLE_JSON",
        Console(
            file=terminal,
            force_terminal=True,
            color_system="256",
            highlighter=JSONHighlighter(),
            emoji=False,
        ),
    )
    out, code = _run(monkeypatch, capsys, "--json", *argv)
    assert code == 0
    if coloured:
        assert out == "" and "\x1b[" in terminal.getvalue()
    else:
        assert terminal.getvalue() == "" and json.loads(out)["mcp"] == "2.3.0"
