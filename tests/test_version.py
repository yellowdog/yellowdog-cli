"""
yd-version (version.py): a single-version flag prints the version alone, or
nothing and exit 1 when it is not installed or could not be read, every
flag alike; under --json such a version is null; --debug is refused with a
single-version flag; and the docs link is the release tag's, or main's for a
version that is no release.
"""

import json
import sys

import pytest

import yellowdog_cli.version as yd_version
from yellowdog_cli.utils import version_info
from yellowdog_cli.utils.rclone_version import NOT_INSTALLED, UNKNOWN


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
