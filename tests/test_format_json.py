"""
yd-format-json (format_json.py): only the layout changes -- numbers are
written back as written, non-ASCII text kept, a repeated key refused with
the file untouched -- the file is replaced whole or not at all, an
unchanged file is left alone, --check writes nothing and exits 1 if
anything would change, and a failure exits 1 with its message on stderr.
"""

import os
import stat
import sys

import pytest

import yellowdog_cli.format_json as yd_format_json


def _run(monkeypatch, capsys, *argv: str) -> tuple[str, str, int]:
    monkeypatch.setattr(sys, "argv", ["yd-format-json", *argv])
    code = 0
    try:
        yd_format_json.main()
    except SystemExit as e:
        code = int(e.code or 0)
    captured = capsys.readouterr()
    return captured.out, captured.err, code


def test_only_the_layout_changes(tmp_path, monkeypatch, capsys):
    path = tmp_path / "a.json"
    path.write_text(
        '{"v":1.10,"e":1e3,"big":0.1000000000000000055,"z":-0,"n":"é"}',
        encoding="utf-8",
    )
    out, _, code = _run(monkeypatch, capsys, str(path))
    assert code == 0 and "Reformatted" in out
    assert path.read_text(encoding="utf-8") == (
        '{"v": 1.10, "e": 1e3, "big": 0.1000000000000000055, "z": -0, "n": "é"}\n'
    )


def test_a_repeated_key_is_refused_and_the_file_left(tmp_path, monkeypatch, capsys):
    path = tmp_path / "dup.json"
    path.write_text('{"a":1,"a":2}', encoding="utf-8")
    out, err, code = _run(monkeypatch, capsys, str(path))
    assert code == 1
    assert "duplicate key 'a'" in err and out == ""
    assert path.read_text(encoding="utf-8") == '{"a":1,"a":2}'


def test_an_unchanged_file_is_not_rewritten(tmp_path, monkeypatch, capsys):
    path = tmp_path / "a.json"
    path.write_text('{"a": 1}\n', encoding="utf-8")
    before = path.stat().st_mtime_ns
    out, _, code = _run(monkeypatch, capsys, str(path))
    assert code == 0 and "Unchanged" in out
    assert path.stat().st_mtime_ns == before


def test_check_writes_nothing_and_exits_1(tmp_path, monkeypatch, capsys):
    path = tmp_path / "a.json"
    path.write_text('{"a":1}', encoding="utf-8")
    out, _, code = _run(monkeypatch, capsys, "--check", str(path))
    assert code == 1 and "Would reformat" in out
    assert path.read_text(encoding="utf-8") == '{"a":1}'


def test_an_interrupted_write_leaves_the_original(tmp_path, monkeypatch, capsys):
    path = tmp_path / "a.json"
    path.write_text('{"a":1}', encoding="utf-8")

    def interrupted(source, destination):
        raise OSError("disk full")

    monkeypatch.setattr(yd_format_json.os, "replace", interrupted)
    _, err, code = _run(monkeypatch, capsys, str(path))
    assert code == 1 and "disk full" in err
    assert path.read_text(encoding="utf-8") == '{"a":1}'
    assert os.listdir(tmp_path) == ["a.json"]  # no temporary file left


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_the_files_permissions_are_kept(tmp_path, monkeypatch, capsys):
    path = tmp_path / "a.json"
    path.write_text('{"a":1}', encoding="utf-8")
    path.chmod(0o640)
    _run(monkeypatch, capsys, str(path))
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_invalid_json_fails_and_the_rest_are_formatted(tmp_path, monkeypatch, capsys):
    bad, good = tmp_path / "bad.json", tmp_path / "good.json"
    bad.write_text("{nope", encoding="utf-8")
    good.write_text('{"a":1}', encoding="utf-8")
    _, err, code = _run(monkeypatch, capsys, str(bad), str(good))
    assert code == 1 and "Unable to process" in err
    assert good.read_text(encoding="utf-8") == '{"a": 1}\n'


def test_a_file_is_required(monkeypatch, capsys):
    _, err, code = _run(monkeypatch, capsys)
    assert code == 2 and "required" in err
