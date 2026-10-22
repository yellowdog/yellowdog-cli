"""
The words after 'yd': each noun and its alias ('yd wr submit'), and each
command no noun verb replaces ('yd list', 'yd doctor', 'yd commander'),
built from the registries alone. The registry commands keep their 'yd-*'
names in code; a word is a name less 'yd-'.
"""

import sys
from dataclasses import dataclass
from enum import Enum, auto

from yellowdog_cli.utils.command_registry import COMMANDS, OTHER_COMMANDS
from yellowdog_cli.utils.invocation import invoked_name
from yellowdog_cli.utils.noun_registry import NOUNS, REPLACED_BY_VERBS


class Kind(Enum):
    NOUN = auto()  # its verb is run (noun_dispatch.run_noun())
    COMMAND = auto()  # a registry command, run with its parser selected
    OTHER = auto()  # an entry point the registry does not describe


@dataclass(frozen=True)
class Entry:
    word: str
    kind: Kind
    target: str  # the noun's name, or the command's 'yd-*' name
    summary: str


def word_of(name: str) -> str:
    """
    The word after 'yd' that stands for a 'yd-*' command.
    """
    return name.removeprefix("yd-")


def yd_form(name: str) -> str:
    """
    A 'yd-*' command as typed under 'yd': 'yd-list' is 'yd list'.
    """
    return f"yd {word_of(name)}"


def _entries() -> dict[str, Entry]:
    entries: dict[str, Entry] = {}
    for noun in NOUNS:
        entries[noun.name] = Entry(noun.name, Kind.NOUN, noun.name, noun.summary)
        if noun.alias is not None:
            entries[noun.alias] = Entry(
                noun.alias, Kind.NOUN, noun.name, f"short for 'yd {noun.name}'"
            )
    for name, command in COMMANDS.items():
        if name not in REPLACED_BY_VERBS:
            word = word_of(name)
            entries[word] = Entry(word, Kind.COMMAND, name, command.summary)
    for name, summary in OTHER_COMMANDS.items():
        word = word_of(name)
        entries[word] = Entry(word, Kind.OTHER, name, summary)
    return entries


TOP_LEVEL: dict[str, Entry] = _entries()

# Every 'yd-*' script released before 'yd', with what replaces it: a noun
# verb's forms, or the command's 'yd' form. Kept for a release, with a
# warning, then removed. A command with no script (Command.script) has none.
SCRIPT_FORMS: dict[str, list[str]] = {
    **{
        name: forms
        for name, forms in REPLACED_BY_VERBS.items()
        if COMMANDS[name].script
    },
    **{
        name: [yd_form(name)]
        for name in [*COMMANDS, *OTHER_COMMANDS]
        if name not in REPLACED_BY_VERBS
        and (name not in COMMANDS or COMMANDS[name].script)
    },
}


def deprecation_message(name: str, forms: list[str] | None = None) -> str:
    """
    The warning for a deprecated script typed by its name: its forms are
    SCRIPT_FORMS' unless given.
    """
    forms = [f"'{form}'" for form in (SCRIPT_FORMS[name] if forms is None else forms)]
    use = forms[0] if len(forms) == 1 else f"{', '.join(forms[:-1])} or {forms[-1]}"
    return f"'{name}' is deprecated and will be removed in a future release: use {use}"


def warn_if_deprecated_script(name: str) -> None:
    """
    Warn, on stderr, when a command not on the wrappers was typed by its
    deprecated script's name ('yd-help'), not as 'yd help' or 'python -m'.
    """
    if invoked_name(sys.argv[0]) != name:
        return
    from yellowdog_cli.utils.printing import print_warning

    print_warning(deprecation_message(name), stderr=True)
