"""
yd jsonnet fromjson (jsonnet_fromjson.py): one JSON file, or standard
input, written to stdout as Jsonnet in the hand-written style and checked
to evaluate to the same JSON, a conversion that would not refused; an
unusable file an error on stderr with nothing on stdout; several files, a
glob pattern, or '-' with --write refused; and with --write each file
written to <name>.jsonnet beside it, a non-.json file skipped and an
existing .jsonnet file the conversion would change replaced only once
confirmed (the confirmation itself is held by test_jsonnet2json.py, the
two sharing utils/file_conversion.py). Skipped without the jsonnet
package, but for the command-line cases.
"""

import io
import json
import sys

import pytest

import yellowdog_cli.jsonnet_fromjson as fromjson
from yellowdog_cli.utils.output_style import ERROR_MARKER


def _run(monkeypatch, capsys, *argv: str, stdin: str = "") -> tuple[str, str, int]:
    monkeypatch.setattr(sys, "argv", ["yd jsonnet fromjson", *argv])
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    code = 0
    try:
        fromjson.main()
    except SystemExit as e:
        code = int(e.code or 0)
    captured = capsys.readouterr()
    return captured.out, captured.err, code


def _evaluated(text: str):
    from _jsonnet import evaluate_snippet

    return json.loads(evaluate_snippet("out.jsonnet", text))


@pytest.fixture
def jsonnet():
    pytest.importorskip("_jsonnet")


SPEC = {
    "workRequirement": {
        "name": "render-{{datetime}}",
        "taskGroups": [{"taskType": "bash", "max-retries": 2, "if": "it's ✓"}],
    }
}


def test_a_files_jsonnet_goes_to_stdout_in_the_style(
    jsonnet, tmp_path, monkeypatch, capsys
):
    source = tmp_path / "spec.json"
    source.write_text(json.dumps(SPEC), encoding="utf-8")
    out, err, code = _run(monkeypatch, capsys, str(source))
    assert code == 0, err
    assert "  workRequirement: {\n" in out
    assert "name: 'render-{{datetime}}'," in out
    assert "'max-retries': 2" in out
    assert "'if': \"it's ✓\"" in out
    assert _evaluated(out) == SPEC


def test_standard_input_is_read(jsonnet, monkeypatch, capsys):
    out, _, code = _run(monkeypatch, capsys, "-", stdin="[1, null, true]")
    assert code == 0
    assert _evaluated(out) == [1, None, True]


def test_a_conversion_that_changes_the_json_is_refused(
    jsonnet, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(fromjson, "jsonnet_style", lambda _: "{}")
    source = tmp_path / "spec.json"
    source.write_text(json.dumps(SPEC), encoding="utf-8")
    out, err, code = _run(monkeypatch, capsys, str(source))
    assert (out, code) == ("", 1)
    assert "would not evaluate to the same JSON" in err


@pytest.mark.parametrize(
    "name, content, reason",
    [
        # The parser's own wording and column vary with the Python version
        ("bad.json", '{"a": 1,}', "it is not JSON ("),
        ("bad.json", "{", " at line 1, column "),
        ("bad.json", " \n", "it is empty"),
        ("spec.jsonnet", "local a = 1; {a: a}", "'yd jsonnet tojson' converts"),
    ],
)
def test_an_unusable_file_is_an_error_saying_why_on_stderr(
    jsonnet, tmp_path, monkeypatch, capsys, name, content, reason
):
    source = tmp_path / name
    source.write_text(content, encoding="utf-8")
    out, err, code = _run(monkeypatch, capsys, str(source))
    assert (out, code) == ("", 1)
    assert err.startswith(f"{ERROR_MARKER}Cannot convert '{source}': ")
    assert reason in err


def test_a_jsonnet_file_holding_json_is_converted(
    jsonnet, tmp_path, monkeypatch, capsys
):
    source = tmp_path / "spec.jsonnet"
    source.write_text('{"a": 1}', encoding="utf-8")
    out, _, code = _run(monkeypatch, capsys, str(source))
    assert (out, code) == ("{a: 1}\n", 0)


def test_a_missing_file_is_an_error(jsonnet, tmp_path, monkeypatch, capsys):
    out, err, code = _run(monkeypatch, capsys, str(tmp_path / "none.json"))
    assert (out, code) == ("", 1)
    assert "No such file" in err


@pytest.mark.parametrize("argv", [["a.json", "b.json"], ["*.json"], ["--write", "-"]])
def test_what_has_no_one_place_to_go_is_refused(monkeypatch, capsys, argv):
    _, err, code = _run(monkeypatch, capsys, *argv)
    assert code == 2
    assert "error:" in err


def test_write_writes_beside_each_source(jsonnet, tmp_path, monkeypatch, capsys):
    (tmp_path / "a.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "b.json").write_text('{"b": [1, 2]}', encoding="utf-8")
    (tmp_path / "c.txt").write_text("{}", encoding="utf-8")
    out, _, code = _run(
        monkeypatch,
        capsys,
        "--write",
        str(tmp_path / "*.json"),
        str(tmp_path / "c.txt"),
    )
    assert code == 0
    assert (tmp_path / "a.jsonnet").read_text(encoding="utf-8") == "{a: 1}\n"
    assert _evaluated((tmp_path / "b.jsonnet").read_text(encoding="utf-8")) == {
        "b": [1, 2]
    }
    assert "Skipping non-JSON file" in out
    assert not (tmp_path / "c.jsonnet").exists()


def test_write_asks_before_replacing_a_different_file(
    jsonnet, tmp_path, monkeypatch, capsys
):
    (tmp_path / "a.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "a.jsonnet").write_text("{ hand: 'written' }\n", encoding="utf-8")
    out, _, code = _run(
        monkeypatch, capsys, "--write", str(tmp_path / "a.json"), stdin="n\n"
    )
    assert code == 0
    assert "Not overwritten" in out
    assert (tmp_path / "a.jsonnet").read_text(encoding="utf-8") == (
        "{ hand: 'written' }\n"
    )
