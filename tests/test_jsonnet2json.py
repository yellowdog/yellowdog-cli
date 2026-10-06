"""
yd-jsonnet2json (jsonnet2json.py): one file's JSON on stdout, coloured on a
terminal unless --no-format, with an error on stderr, never in the output;
several files each written whole to <name>.json, non-ASCII kept, an
existing one the conversion would change replaced only once confirmed or
with --yes, and nothing written when the prompt can get no answer; a
wildcard matching nothing reported as such; each file converted once; and
its command line parsed (--help without Jsonnet installed, a file
required). Skipped without the jsonnet package,
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


@pytest.mark.parametrize("argv, coloured", [((), True), (("--nf",), False)])
def test_one_files_json_is_coloured_on_a_terminal_unless_no_format(
    jsonnet, tmp_path, monkeypatch, capsys, argv, coloured
):
    from io import StringIO

    from rich.console import Console
    from rich.highlighter import JSONHighlighter

    from yellowdog_cli.utils import printing

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
    source = tmp_path / "a.jsonnet"
    source.write_text('{ name: "café" }', encoding="utf-8")
    out, _, code = _run(monkeypatch, capsys, *argv, str(source))
    assert code == 0
    if coloured:
        assert out == "" and "\x1b[" in terminal.getvalue()
        assert "café" in terminal.getvalue()
    else:
        assert terminal.getvalue() == "" and out == '{"name": "café"}\n'


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


def _sources(tmp_path) -> tuple[str, str]:
    """
    a.jsonnet with nothing beside it, and b.jsonnet beside a hand-written
    b.json; returns the glob over both and b.json's text.
    """
    (tmp_path / "a.jsonnet").write_text("{ a: 1 }", encoding="utf-8")
    (tmp_path / "b.jsonnet").write_text("{ b: 2 }", encoding="utf-8")
    hand_written = '{"hand": "written"}\n'
    (tmp_path / "b.json").write_text(hand_written, encoding="utf-8")
    return str(tmp_path / "*.jsonnet"), hand_written


def _answer(monkeypatch, text: str) -> None:
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def test_declining_keeps_an_existing_file_and_writes_the_new_ones(
    jsonnet, tmp_path, monkeypatch, capsys
):
    pattern, hand_written = _sources(tmp_path)
    _answer(monkeypatch, "n\n")
    out, _, code = _run(monkeypatch, capsys, pattern)
    assert code == 0
    assert "Would overwrite:" in out and "Not overwritten:" in out
    assert (tmp_path / "b.json").read_text(encoding="utf-8") == hand_written
    assert json.loads((tmp_path / "a.json").read_text(encoding="utf-8")) == {"a": 1}


def test_confirming_overwrites(jsonnet, tmp_path, monkeypatch, capsys):
    pattern, _ = _sources(tmp_path)
    _answer(monkeypatch, "y\n")
    _, _, code = _run(monkeypatch, capsys, pattern)
    assert code == 0
    assert json.loads((tmp_path / "b.json").read_text(encoding="utf-8")) == {"b": 2}


def test_yes_overwrites_without_asking(jsonnet, tmp_path, monkeypatch, capsys):
    pattern, _ = _sources(tmp_path)
    _answer(monkeypatch, "")
    _, _, code = _run(monkeypatch, capsys, "--yes", pattern)
    assert code == 0
    assert json.loads((tmp_path / "b.json").read_text(encoding="utf-8")) == {"b": 2}


def test_no_answer_writes_nothing_at_all(jsonnet, tmp_path, monkeypatch, capsys):
    pattern, hand_written = _sources(tmp_path)
    _answer(monkeypatch, "")
    _, err, code = _run(monkeypatch, capsys, pattern)
    assert code == 1 and "--yes" in err
    assert (tmp_path / "b.json").read_text(encoding="utf-8") == hand_written
    assert not (tmp_path / "a.json").exists()


def test_a_file_the_conversion_would_not_change_is_left_unasked(
    jsonnet, tmp_path, monkeypatch, capsys
):
    pattern, _ = _sources(tmp_path)
    (tmp_path / "b.json").write_text('{"b": 2}\n', encoding="utf-8")
    before = os.stat(tmp_path / "b.json").st_mtime_ns
    _answer(monkeypatch, "")
    out, _, code = _run(monkeypatch, capsys, pattern)
    assert code == 0
    assert "Unchanged: " in out and "Would overwrite" not in out
    assert os.stat(tmp_path / "b.json").st_mtime_ns == before
