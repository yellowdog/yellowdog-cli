"""
yd jsonnet factor: utils/jsonnet_factor.py's factoring of a list of
specifications into a base per kind and each member's differences, held
to evaluating to the same JSON, and jsonnet_factor.py's command: one file
to stdout, or with --write each .json file to <name>.jsonnet beside it, a
.jsonnet file skipped rather than overwritten.
"""

import io
import json
import sys

import pytest

import yellowdog_cli.jsonnet_factor as factor_command
import yellowdog_cli.utils.jsonnet_factor as factor_module
from yellowdog_cli.utils.jsonnet_factor import (
    FactoringError,
    factored,
    factored_and_checked,
)
from yellowdog_cli.utils.output_style import ERROR_MARKER

AWS = "co.yellowdog.platform.model.AwsInstancesComputeSource"
GCE = "co.yellowdog.platform.model.GceInstancesComputeSource"


def _evaluated(text: str):
    _jsonnet = pytest.importorskip("_jsonnet")
    return json.loads(_jsonnet.evaluate_snippet("factored.jsonnet", text))


def _cst(name: str, source_type: str = AWS, **source) -> dict:
    return {
        "resource": "ComputeSourceTemplate",
        "namespace": "render-dev",
        "source": {"type": source_type, "name": name, "region": "eu-west-2", **source},
    }


class TestBases:
    def test_what_a_kind_shares_is_written_once(self):
        text = factored([_cst("a", spot=False), _cst("b", spot=False)])
        assert text.count("render-dev") == 1
        assert text.count("eu-west-2") == 1
        assert "awsInstances {source+: {name: 'a'}}" in text
        assert "awsInstances {source+: {name: 'b'}}" in text

    def test_the_value_most_members_give_is_the_bases(self):
        members = [_cst(n, spot=False) for n in "abc"] + [_cst("d", spot=True)]
        text = factored(members)
        assert "spot: false" in text.split("[")[0]
        assert "awsInstances {source+: {name: 'd', spot: true}}" in text

    def test_each_kind_has_a_base_of_its_own(self):
        members = [_cst("a"), _cst("b"), _cst("c", GCE), _cst("d", GCE)]
        text = factored(members)
        assert "local awsInstances = " in text
        assert "local gceInstances = " in text

    def test_a_kind_with_one_member_is_written_as_it_is(self):
        text = factored([_cst("a"), _cst("b", GCE)])
        assert "local" not in text
        assert _evaluated(text) == [_cst("a"), _cst("b", GCE)]

    def test_a_property_few_set_stays_with_them(self):
        members = [_cst(n) for n in "abcd"] + [_cst("e", keyName="k")]
        base = factored(members).split("[")[0]
        assert "keyName" not in base

    def test_a_member_lacking_a_base_property_hides_it(self):
        # Four in five set it: the base holds it
        members = [_cst(n, spot=False) for n in "abcde"]
        del members[0]["source"]["spot"]
        text = factored(members)
        assert "spot:: null" in text
        assert _evaluated(text) == members

    def test_a_deeper_object_lacking_one_is_written_whole(self):
        members = [_cst(n, tags={"a": "1", "b": "2"}) for n in "abcd"]
        members[0]["source"]["tags"] = {"a": "1"}
        text = factored(members)
        assert "::" not in text
        assert "tags: {a: '1'}" in text
        assert _evaluated(text) == members

    def test_a_member_with_no_differences_is_its_base(self):
        text = factored([{"resource": "Keyring", "name": "k"}] * 2)
        assert text.endswith("[\n  keyring,\n  keyring,\n]\n")


class TestNames:
    def test_bases_are_named_for_their_kind(self):
        text = factored([{"resource": "Keyring", "name": n} for n in "ab"])
        assert text.startswith("local keyring = ")

    def test_two_kinds_of_one_name_are_told_apart(self):
        a = {"resource": "Group", "type": "x.Same", "name": "a"}
        b = {"resource": "Role", "type": "y.Same", "name": "b"}
        text = factored([a, dict(a, name="c"), b, dict(b, name="d")])
        assert "local same = " in text
        assert "local same2 = " in text

    def test_a_key_that_is_no_identifier_is_quoted(self):
        members = [{"resource": "X", "k-1": 1, "if": n} for n in (1, 2)]
        text = factored(members)
        assert "'if': 1" in text
        assert _evaluated(text) == members


class TestLayout:
    def test_short_differences_are_on_one_line(self):
        assert "awsInstances {source+: {name: 'a'}}," in factored(
            [_cst("a"), _cst("b")]
        )

    def test_long_differences_are_one_to_a_line(self):
        long = "x" * 80
        text = factored([_cst("a", description=long), _cst("b")])
        assert f"\n      description: '{long}',\n" in text


@pytest.mark.parametrize(
    "specifications",
    [
        [],
        [{"resource": "Keyring", "name": "k"}],
        ["text", 3, None, {"resource": "Keyring", "name": "k"}],
        [_cst(n, userData='#!/bin/bash\necho "it\'s $HOME"\t\\\n') for n in "ab"],
        [_cst(n, tags={"ü": "é ✓"}) for n in "ab"],
    ],
)
def test_the_text_evaluates_to_the_same_json(specifications):
    assert _evaluated(factored(specifications)) == specifications


def test_every_corpus_file_evaluates_to_itself():
    import resource_corpus

    resource_corpus.require_jsonnet()
    previous = resource_corpus.install_variables()
    try:
        for path in resource_corpus.corpus_files():
            specifications = resource_corpus.load_corpus_file(path)
            text = factored(specifications)
            assert _evaluated(text) == specifications, path.name
    finally:
        resource_corpus.remove_variables(previous)


def test_a_factoring_that_changes_the_json_is_refused(monkeypatch):
    pytest.importorskip("_jsonnet")
    monkeypatch.setattr(factor_module, "factored", lambda _: "[]\n")
    with pytest.raises(FactoringError):
        factored_and_checked([{"resource": "Keyring", "name": "k"}])


def _run_factor(monkeypatch, capsys, *args: str, stdin: str = ""):
    monkeypatch.setattr(sys, "argv", ["yd jsonnet factor", *args])
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    code = 0
    try:
        factor_command.main()
    except SystemExit as e:
        code = e.code
    out, err = capsys.readouterr()
    return code, out, err


class TestCommand:
    @pytest.fixture(autouse=True)
    def _needs_jsonnet(self):
        pytest.importorskip("_jsonnet")

    def _run(self, monkeypatch, capsys, *args: str, stdin: str = ""):
        return _run_factor(monkeypatch, capsys, *args, stdin=stdin)

    def test_a_json_file_is_printed_factored(self, monkeypatch, capsys, tmp_path):
        members = [_cst("a"), _cst("b")]
        path = tmp_path / "csts.json"
        path.write_text(json.dumps(members), encoding="utf-8")
        code, out, err = self._run(monkeypatch, capsys, str(path))
        assert code == 0, err
        assert _evaluated(out) == members

    def test_standard_input_is_read_as_json(self, monkeypatch, capsys):
        members = [_cst("a"), _cst("b")]
        code, out, _ = self._run(monkeypatch, capsys, "-", stdin=json.dumps(members))
        assert code == 0
        assert _evaluated(out) == members

    def test_a_jsonnet_file_is_evaluated_first(self, monkeypatch, capsys, tmp_path):
        path = tmp_path / "keyrings.jsonnet"
        path.write_text(
            "[{resource: 'Keyring', name: n} for n in ['a', 'b']]", encoding="utf-8"
        )
        code, out, _ = self._run(monkeypatch, capsys, str(path))
        assert code == 0
        assert _evaluated(out) == [
            {"resource": "Keyring", "name": "a"},
            {"resource": "Keyring", "name": "b"},
        ]

    @pytest.mark.parametrize(
        "content, reason",
        [
            ('{"resource": "Keyring"}', "a single object"),
            ("[1,", "it is not JSON ("),
            ("", "it is empty"),
        ],
    )
    def test_an_unusable_file_is_an_error_on_stderr(
        self, monkeypatch, capsys, tmp_path, content, reason
    ):
        path = tmp_path / "x.json"
        path.write_text(content, encoding="utf-8")
        code, out, err = self._run(monkeypatch, capsys, str(path))
        assert code == 1
        assert out == ""
        assert err.startswith(f"{ERROR_MARKER}Cannot factor '{path}'")
        assert reason in err

    def test_a_missing_file_is_an_error(self, monkeypatch, capsys, tmp_path):
        code, out, err = self._run(monkeypatch, capsys, str(tmp_path / "none.json"))
        assert code == 1
        assert out == ""
        assert "No such file" in err


class TestWrite:
    @pytest.fixture(autouse=True)
    def _needs_jsonnet(self):
        pytest.importorskip("_jsonnet")

    def _run(self, monkeypatch, capsys, *args: str, stdin: str = ""):
        return _run_factor(monkeypatch, capsys, *args, stdin=stdin)

    def test_each_json_file_is_written_beside_it(self, monkeypatch, capsys, tmp_path):
        members = [_cst("a"), _cst("b")]
        (tmp_path / "a.json").write_text(json.dumps(members), encoding="utf-8")
        (tmp_path / "b.json").write_text(json.dumps(members[:1]), encoding="utf-8")
        code, out, err = self._run(
            monkeypatch, capsys, "--write", str(tmp_path / "*.json")
        )
        assert code == 0, err
        assert out.count("Converted:") == 2
        for name, expected in (("a", members), ("b", members[:1])):
            text = (tmp_path / f"{name}.jsonnet").read_text(encoding="utf-8")
            assert _evaluated(text) == expected

    def test_a_jsonnet_file_is_skipped_never_overwritten(
        self, monkeypatch, capsys, tmp_path
    ):
        source = tmp_path / "keyrings.jsonnet"
        original = "[{resource: 'Keyring', name: n} for n in ['a', 'b']]"
        source.write_text(original, encoding="utf-8")
        code, out, _ = self._run(monkeypatch, capsys, "--write", str(source))
        assert code == 0
        assert "Skipping non-JSON file" in out
        assert source.read_text(encoding="utf-8") == original

    def test_a_file_that_is_no_list_fails_and_the_rest_are_written(
        self, monkeypatch, capsys, tmp_path
    ):
        (tmp_path / "a.json").write_text(json.dumps([_cst("a")]), encoding="utf-8")
        (tmp_path / "b.json").write_text('{"resource": "Keyring"}', encoding="utf-8")
        code, _, err = self._run(
            monkeypatch,
            capsys,
            "--write",
            str(tmp_path / "a.json"),
            str(tmp_path / "b.json"),
        )
        assert code == 1
        assert "a single object" in err
        assert (tmp_path / "a.jsonnet").exists()
        assert not (tmp_path / "b.jsonnet").exists()

    @pytest.mark.parametrize(
        "argv", [["a.json", "b.json"], ["*.json"], ["--write", "-"]]
    )
    def test_what_has_no_one_place_to_go_is_refused(self, monkeypatch, capsys, argv):
        code, _, err = self._run(monkeypatch, capsys, *argv)
        assert code == 2
        assert "error:" in err


class TestNumbersAsWritten:
    @pytest.fixture(autouse=True)
    def _needs_jsonnet(self):
        pytest.importorskip("_jsonnet")

    def test_a_number_keeps_how_it_was_written(self, monkeypatch, capsys):
        members = '[{"resource": "X", "v": 1.10, "n": "a"}, {"resource": "X", "v": 1.10, "n": "b"}]'
        code, out, _ = _run_factor(monkeypatch, capsys, "-", stdin=members)
        assert code == 0
        assert "v: 1.10" in out

    def test_numbers_written_differently_are_not_the_same(self, monkeypatch, capsys):
        members = (
            '[{"resource": "X", "v": 1.10, "n": "a"},'
            ' {"resource": "X", "v": 1.10, "n": "b"},'
            ' {"resource": "X", "v": 1.1, "n": "c"}]'
        )
        code, out, _ = _run_factor(monkeypatch, capsys, "-", stdin=members)
        assert code == 0
        assert "x {v: 1.1, n: 'c'}" in out

    def test_a_repeated_key_is_refused(self, monkeypatch, capsys):
        code, out, err = _run_factor(
            monkeypatch, capsys, "-", stdin='[{"a": 1, "a": 2}]'
        )
        assert (code, out) == (1, "")
        assert "it repeats the key 'a'" in err
