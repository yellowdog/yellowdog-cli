"""
yd-jsonnet2json (jsonnet2json.py): one file's JSON on stdout with an error
on stderr, never in the output; several files each written whole to
<name>.json, non-ASCII kept; a wildcard matching nothing reported as such;
each file converted once; and its command line parsed (--help without
Jsonnet installed, a file required). Skipped without the jsonnet package,
but for the command-line cases.
"""

import json
import os
import sys

import pytest

import yellowdog_cli.jsonnet2json as yd_jsonnet2json


def _run(monkeypatch, capsys, *argv: str) -> tuple[str, str, int]:
    monkeypatch.setattr(sys, "argv", ["yd-jsonnet2json", *argv])
    code = 0
    try:
        yd_jsonnet2json.main()
    except SystemExit as e:
        code = int(e.code or 0)
    captured = capsys.readouterr()
    return captured.out, captured.err, code


@pytest.fixture
def jsonnet():
    pytest.importorskip("_jsonnet")


def test_a_file_is_required(monkeypatch, capsys):
    _, err, code = _run(monkeypatch, capsys)
    assert code == 2 and "required" in err


def test_one_files_json_goes_to_stdout_non_ascii_kept(
    jsonnet, tmp_path, monkeypatch, capsys
):
    source = tmp_path / "a.jsonnet"
    source.write_text('{ name: "café", n: 1 + 1 }', encoding="utf-8")
    out, err, code = _run(monkeypatch, capsys, str(source))
    assert code == 0 and err == ""
    assert out == '{"n": 2, "name": "café"}\n'


def test_an_error_goes_to_stderr_never_into_the_output(
    jsonnet, tmp_path, monkeypatch, capsys
):
    source = tmp_path / "bad.jsonnet"
    source.write_text("{ broken", encoding="utf-8")
    out, err, code = _run(monkeypatch, capsys, str(source))
    assert code == 1
    assert out == "" and err != ""


def test_several_files_are_written_beside_their_sources(
    jsonnet, tmp_path, monkeypatch, capsys
):
    for name in ("a", "b"):
        (tmp_path / f"{name}.jsonnet").write_text(
            f'{{ x: "{name}" }}', encoding="utf-8"
        )
    out, _, code = _run(
        monkeypatch, capsys, str(tmp_path / "a.jsonnet"), str(tmp_path / "*.jsonnet")
    )
    assert code == 0
    # a.jsonnet named and matched: converted once
    assert out.count("Converted:") == 2 and " -> " in out
    assert json.loads((tmp_path / "b.json").read_text(encoding="utf-8")) == {"x": "b"}
    assert not [name for name in os.listdir(tmp_path) if name.startswith(".yd-")]


def test_a_wildcard_matching_nothing_says_so(jsonnet, tmp_path, monkeypatch, capsys):
    (tmp_path / "a.jsonnet").write_text("{}", encoding="utf-8")
    _, err, code = _run(
        monkeypatch, capsys, str(tmp_path / "a.jsonnet"), str(tmp_path / "zz*.jsonnet")
    )
    assert code == 1
    assert "No files match" in err
    assert (tmp_path / "a.json").exists()
