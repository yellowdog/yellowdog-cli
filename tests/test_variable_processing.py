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
            ("{{{a}}}", ["{{{a}}}"]),  # its braces balance, so are content
            ("{{a}}}}", ["{{a}}"]),
            ("{{{{a}}", []),  # never closed
            ("}} {{a}}", ["{{a}}"]),
        ],
    )
    def test_finds_top_level_expressions(self, s, expected):
        assert find_delimited_expressions(s, "{{", "}}") == expected

    @pytest.mark.parametrize(
        "s,expected",
        [
            # A '}' closing a '{' opened inside the expression is its content
            ('{{table:t:={"a":1}}}', ['{{table:t:={"a":1}}}']),
            ('{{table:t:={"a":{"b":1}}}}', ['{{table:t:={"a":{"b":1}}}}']),
            ("{{table:t:={}}}", ["{{table:t:={}}}"]),
            ("{{cmd:=echo ${HOME}}}", ["{{cmd:=echo ${HOME}}}"]),
            ('{{t:={"a":{{x}}}}}', ['{{t:={"a":{{x}}}}}']),
            # Outside an expression a brace is text: JSON around one is not it
            ('{"n":{{x}}}', ["{{x}}"]),
        ],
    )
    def test_braces_inside_an_expression(self, s, expected):
        assert find_delimited_expressions(s, "{{", "}}") == expected
        # The strict scanner splitting values agrees with the one scanning text
        assert [
            e for e in split_delimited_string(s, "{{", "}}") if e.startswith("{{")
        ] == expected

    def test_braces_in_json_text_around_an_expression(self):
        # Its '}}' would be a stray closing delimiter to the strict scanner
        s = '{"a":{"n":{{x}}}}'
        assert find_delimited_expressions(s, "{{", "}}") == ["{{x}}"]

    def test_prefixed_delimiters(self):
        assert find_delimited_expressions(
            '{"a":"__{{a}}__","b":"{{b}}"}}', "__{{", "}}__"
        ) == ["__{{a}}__"]
