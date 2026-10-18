"""
utils/top_level.py: the words after 'yd'. Every noun, alias and command a
user types is one, no word stands for two things, and nothing a noun verb
replaces is one.
"""

from yellowdog_cli.utils.command_registry import COMMANDS, OTHER_COMMANDS
from yellowdog_cli.utils.noun_registry import NOUNS, REPLACED_BY_VERBS
from yellowdog_cli.utils.top_level import TOP_LEVEL, Kind, word_of, yd_form


def test_every_noun_and_alias_is_a_word():
    for noun in NOUNS:
        for word in noun.invoked_names():
            assert TOP_LEVEL[word].kind is Kind.NOUN
            assert TOP_LEVEL[word].target == noun.name


def test_every_command_no_verb_replaces_is_a_word():
    for name in COMMANDS:
        if name in REPLACED_BY_VERBS:
            assert word_of(name) not in TOP_LEVEL, name
        else:
            entry = TOP_LEVEL[word_of(name)]
            assert (entry.kind, entry.target) == (Kind.COMMAND, name)


def test_the_other_commands_are_words():
    for name in OTHER_COMMANDS:
        entry = TOP_LEVEL[word_of(name)]
        assert (entry.kind, entry.target) == (Kind.OTHER, name)


def test_no_word_stands_for_two_things():
    words = [w for noun in NOUNS for w in noun.invoked_names()]
    words += [word_of(n) for n in COMMANDS if n not in REPLACED_BY_VERBS]
    words += [word_of(n) for n in OTHER_COMMANDS]
    assert len(words) == len(set(words)) == len(TOP_LEVEL)


def test_the_words():
    assert {"wr", "list", "doctor", "format-json", "commander", "mcp"} <= set(TOP_LEVEL)
    assert "submit" not in TOP_LEVEL


def test_an_alias_says_what_it_is_short_for():
    assert TOP_LEVEL["wr"].summary == "short for 'yd workrequirement'"


def test_yd_form():
    assert yd_form("yd-list") == "yd list"
    assert yd_form("yd-format-json") == "yd format-json"
