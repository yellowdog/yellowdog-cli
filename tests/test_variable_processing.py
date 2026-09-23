"""
Unit tests for variable processing
"""

import pytest

from yellowdog_cli.utils.misc_utils import (
    find_delimited_expressions,
    remove_outer_delimiters,
    split_delimited_string,
)


class TestVariableProcessing:
    @pytest.mark.parametrize(
        "input_string, opening_delimiter, closing_delimiter, expected",
        [
            ("{{one}}", "{{", "}}", "one"),
            ("{{{one}}}", "{{", "}}", "{one}"),
            ("__{{{on}e}}}__", "__{{", "}}__", "{on}e}"),
            (
                "{{ one two}}",
                "{{",
                "}}",
                " one two",
            ),  # Spaces can be handled, although not documented
        ],
    )
    def test_remove_outer_delimiters(
        self, input_string, opening_delimiter, closing_delimiter, expected
    ):
        assert (
            remove_outer_delimiters(
                input_string=input_string,
                opening_delimiter=opening_delimiter,
                closing_delimiter=closing_delimiter,
            )
            == expected
        )

    @pytest.mark.parametrize(
        "input_string, opening_delimiter, closing_delimiter, expected",
        [
            ("{{one}}", "{{", "}}", ["{{one}}"]),
            (
                "A {{one}}123{{xy}z}}hello",
                "{{",
                "}}",
                ["A ", "{{one}}", "123", "{{xy}z}}", "hello"],
            ),
        ],
    )
    def test_split_delimited_string(
        self, input_string, opening_delimiter, closing_delimiter, expected
    ):
        assert (
            split_delimited_string(
                s=input_string,
                opening_delimiter=opening_delimiter,
                closing_delimiter=closing_delimiter,
            )
            == expected
        )

    def test_split_delimited_string_mismatched_delimiters_raises(self):
        with pytest.raises(Exception, match="Mismatched variable delimiters"):
            split_delimited_string(
                s="{{one}}}}",
                opening_delimiter="{{",
                closing_delimiter="}}",
            )


class TestFindDelimitedExpressions:
    @pytest.mark.parametrize(
        "s, expected",
        [
            ("no expressions", []),
            ('"{{a}}"', ["{{a}}"]),
            ('{"a":"{{a}}","b":"{{b}}"}', ["{{a}}", "{{b}}"]),
            ('{"env":{"a":"{{a}}"}}', ["{{a}}"]),  # the object's '}}' is not one
            ('"{{a_{{b}}}}-{{c}}"', ["{{a_{{b}}}}", "{{c}}"]),
            ("{{a}}\n{{b}}", ["{{a}}", "{{b}}"]),
            ("{{a\n}}", []),  # an expression does not span lines
            ("{{a\n{{b}}", ["{{b}}"]),  # one left open does not swallow the next
            ("{{{a}}}", ["{{{a}}"]),
            ("{{a}}}}", ["{{a}}"]),
            ("{{{{a}}", []),  # never closed
            ("}} {{a}}", ["{{a}}"]),
        ],
    )
    def test_finds_top_level_expressions(self, s, expected):
        assert find_delimited_expressions(s, "{{", "}}") == expected

    def test_prefixed_delimiters(self):
        assert find_delimited_expressions(
            '{"a":"__{{a}}__","b":"{{b}}"}}', "__{{", "}}__"
        ) == ["__{{a}}__"]
