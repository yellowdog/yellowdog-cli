"""
utils/jsonnet_style.py: JSON text rewritten in the Jsonnet style for an
'--output-file' named '.jsonnet', which must evaluate to the same JSON.
"""

import json

import pytest

from yellowdog_cli.utils.compact_json import CompactJSONEncoder
from yellowdog_cli.utils.jsonnet_style import (
    JSONNET_KEYWORDS,
    is_jsonnet_path,
    jsonnet_style,
)
from yellowdog_cli.utils.printing import JSON_INDENT, json_dumps


def _styled(data) -> str:
    return jsonnet_style(json_dumps(data, indent=JSON_INDENT, cls=CompactJSONEncoder))


def _evaluated(text: str):
    _jsonnet = pytest.importorskip("_jsonnet")
    return json.loads(_jsonnet.evaluate_snippet("styled.jsonnet", text))


class TestKeys:
    def test_an_identifier_is_unquoted(self):
        assert _styled({"name": 1}) == "{name: 1}"

    def test_a_key_that_is_no_identifier_is_quoted(self):
        assert "'k-1': 1" in _styled({"k-1": 1})
        assert "'1st': 1" in _styled({"1st": 1})

    @pytest.mark.parametrize("keyword", sorted(JSONNET_KEYWORDS))
    def test_a_keyword_is_quoted(self, keyword):
        assert f"'{keyword}': 1" in _styled({keyword: 1})


class TestStrings:
    def test_a_string_is_in_single_quotes(self):
        assert "name: 'a'" in _styled({"name": "a"})

    def test_a_double_quote_is_unescaped_in_single_quotes(self):
        assert """name: 'say "hi"'""" in _styled({"name": 'say "hi"'})

    def test_a_string_holding_a_single_quote_keeps_double_quotes(self):
        assert 'name: "it\'s"' in _styled({"name": "it's"})

    def test_an_escaped_backslash_before_a_quote_stays_escaped(self):
        assert "name: 'a\\\\'" in _styled({"name": "a\\"})

    def test_a_string_value_like_a_key_is_still_a_string(self):
        assert "names: ['name', 'if']" in _styled({"names": ["name", "if"]})


class TestTrailingCommas:
    def test_the_last_element_of_a_multi_line_object_or_array_has_one(self):
        assert _styled({"a": [{"b": 1, "c": [1, 2]}]}) == (
            "{\n  a: [\n    {\n      b: 1,\n      c: [1, 2],\n    },\n  ],\n}"
        )

    def test_an_inline_container_has_none(self):
        assert "list: [1, 2, 3]," in _styled({"list": [1, 2, 3]})
        assert "empty: {}," in _styled({"empty": {}})


@pytest.mark.parametrize(
    "path, expected",
    [
        ("specs.jsonnet", True),
        ("SPECS.JSONNET", True),
        ("dir.jsonnet/specs.json", False),
        ("specs.json", False),
        ("specs.libsonnet", False),
    ],
)
def test_the_extension_chooses_the_style(path, expected):
    assert is_jsonnet_path(path) is expected


@pytest.mark.parametrize(
    "data",
    [
        {
            "name": 'a\'b "q" \\x',
            "userData": '#!/bin/bash\necho "$HOME"\t\\done\n',
            "list": [1, 2.5, -3, True, False, None],
            "nested": {"k-1": True, "if": None, "deep": [{"a": 1}, {"b": []}]},
            "empty": {},
            "ü": "é ✓",
            '\\"': "'\"",
        },
        [],
        [{"resource": "Keyring", "name": "team-keys"}, "a string", 3],
    ],
)
def test_the_styled_text_evaluates_to_the_same_json(data):
    assert _evaluated(_styled(data)) == data


def test_every_corpus_specification_evaluates_to_itself():
    import resource_corpus

    resource_corpus.require_jsonnet()
    previous = resource_corpus.install_variables()
    try:
        for path in resource_corpus.corpus_files():
            specifications = resource_corpus.load_corpus_file(path)
            assert _evaluated(_styled(specifications)) == specifications, path.name
    finally:
        resource_corpus.remove_variables(previous)
