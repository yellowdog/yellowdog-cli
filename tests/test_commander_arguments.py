"""
How Commander splits its text fields into command-line arguments, and quotes
arguments back into a field (yellowdog_cli/commander/arguments.py). Qt-free.
"""

import pytest

from yellowdog_cli.commander.arguments import (
    QuotingError,
    property_is_complete,
    quote_argument,
    split_arguments,
)


@pytest.mark.parametrize(
    ("text", "arguments"),
    [
        ("", []),
        ("   ", []),
        ("--foo bar", ["--foo", "bar"]),
        ("  --foo   bar  ", ["--foo", "bar"]),
        # The case this exists for: a JSON value containing spaces
        (
            """--property 'workRequirement.workerTags=["a", "b"]'""",
            ["--property", 'workRequirement.workerTags=["a", "b"]'],
        ),
        # Quotes around the value alone, as in a shell
        (
            """workRequirement.workerTags='["a", "b"]'""",
            ['workRequirement.workerTags=["a", "b"]'],
        ),
        ('common.tag="my tag"', ["common.tag=my tag"]),
        ("a '' b", ["a", "", "b"]),
        ('''"it's"''', ["it's"]),
        ("""'say "hi"'""", ['say "hi"']),
    ],
)
def test_splitting(text, arguments):
    assert split_arguments(text) == arguments


def test_a_backslash_is_an_ordinary_character():
    # Windows paths are typed into these fields; a shell's escapes would eat them
    assert split_arguments(r"--into C:\results\new") == ["--into", r"C:\results\new"]


@pytest.mark.parametrize("text", ["'open", 'a "b c', """'["a", "b"]"""])
def test_an_unclosed_quote_is_an_error(text):
    with pytest.raises(QuotingError, match="never closed"):
        split_arguments(text)


@pytest.mark.parametrize(
    "argument",
    [
        "plain",
        "common.tag=x",
        'workRequirement.workerTags=["a", "b"]',
        "common.tag=my tag",
        "it's here",
        "",
        r"C:\a b\c",
    ],
)
def test_quoting_round_trips(argument):
    assert split_arguments(quote_argument(argument)) == [argument]


def test_an_argument_needing_no_quotes_is_left_alone():
    assert quote_argument('workRequirement.workerTags=["a"]') == (
        """'workRequirement.workerTags=["a"]'"""
    )
    assert quote_argument("common.tag=x") == "common.tag=x"


def test_an_argument_with_both_quotes_and_a_space_cannot_be_quoted():
    with pytest.raises(QuotingError, match="both kinds"):
        quote_argument("""it's "here\"""")


@pytest.mark.parametrize(
    ("argument", "complete"),
    [
        ("workRequirement.name=x", True),
        ("workRequirement.name=", True),  # an empty string is a value
        ("common.variables.x=1", True),
        ("workRequirement", False),
        ("workRequirement.", False),
        ("workRequirement.name", False),
        ("workRequirement.=x", False),
        (".name=x", False),
        ("name=x", False),
        ("=x", False),
    ],
)
def test_property_completeness(argument, complete):
    assert property_is_complete(argument) is complete
