"""
Shell completion: what Tab offers for a partly typed yd-* command line.

complete() works from the registries alone (command_registry.COMMANDS and
noun_registry's nouns and derived commands), importing no command module
and no SDK, since the shell runs 'yd-completion --complete' on every Tab.
It offers a noun's verbs, the options a command or verb offers (never one
it hides), and the values the registry states: choices, '--sort' keys, the
entity and Cloud Info types, and local files or directories for an option
marked Completes.FILE or Completes.DIR. A value it knows nothing of (a
name, a YDID) offers nothing; Platform names would be another Completes.
A command whose arguments the registry does not describe (yd-commander,
yd-mcp, and the standalone commands that parse their own) is left to the
shell's own completion of files, which is what it had before the stubs
claimed its name, with '--help' for a word starting with '-'.

The deprecated commands are not completed, and so not registered: the
stubs register completion_names().
"""

from __future__ import annotations

from argparse import SUPPRESS
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum, auto

from yellowdog_cli.utils.command_registry import (
    CLOUD_INFO_TYPES,
    COMMANDS,
    ENTITY_TYPES,
    OTHER_COMMANDS,
    SORT_KEY_TYPES,
    Command,
    Completes,
    Exclusive,
    Option,
    command_from_argv0,
    resolve_cloud_info_type,
    resolve_entity_type,
)
from yellowdog_cli.utils.noun_registry import (
    DEPRECATED,
    NOUN_COMMANDS,
    NOUNS,
    NOUNS_BY_NAME,
    RESOURCE_LIST_TYPES,
)

# The actions whose option takes no value
_NO_VALUE_ACTIONS = frozenset(
    {"store_true", "store_false", "store_const", "count", "append_const", "help"}
)
# The actions an option may be given more than once with
_REPEATABLE_ACTIONS = frozenset({"append", "count", "append_const"})

# The values of an option whose 'type' resolves them, as the MCP catalogue
# enumerates them (mcp/tools.py)
_TYPE_VALUES: dict[object, tuple[str, ...]] = {
    resolve_entity_type: tuple(ENTITY_TYPES),
    resolve_cloud_info_type: tuple(CLOUD_INFO_TYPES),
}

# Values a verb narrows by a check of its own rather than in its options:
# (derived command, option name) -> the values it accepts
_VERB_VALUES: dict[tuple[str, str], tuple[str, ...]] = {
    ("yd-resource list", "entity_type"): tuple(sorted(RESOURCE_LIST_TYPES)),
}

_HELP_FLAGS = (("--help", "show the help message and exit"),)

# The characters bash splits a word at that a yd-* argument may hold
_BASH_BREAKS = ("=", ":")


class Mode(Enum):
    VALUES = auto()  # the candidates, which may be none
    FILES = auto()  # the shell's own completion of local files
    DIRS = auto()  # the shell's own completion of local directories


@dataclass(frozen=True)
class Candidate:
    value: str
    description: str = ""


@dataclass(frozen=True)
class Completions:
    mode: Mode = Mode.VALUES
    candidates: tuple[Candidate, ...] = ()


_NOTHING = Completions()


def completion_names() -> list[str]:
    """
    The command names completion is registered for: the nouns and their
    short forms, the registry commands no noun replaces (the generic
    commands and the utilities), and the other entry points.
    """
    names = [name for noun in NOUNS for name in noun.invoked_names()]
    names += sorted(name for name in COMMANDS if name not in DEPRECATED)
    names += sorted(OTHER_COMMANDS)
    return names


def complete(words: list[str], current: str) -> Completions:
    """
    What completes 'current', the word under the cursor, after 'words', the
    words before it (the command's name first).
    """
    if not words:
        return _NOTHING
    name = command_from_argv0(words[0])
    rest = words[1:]
    noun = NOUNS_BY_NAME.get(name)
    if noun is not None:
        if not rest:
            if current.startswith("-"):
                return _matching(_HELP_FLAGS, current)
            return _matching(((v.name, v.summary) for v in noun.verbs), current)
        command = NOUN_COMMANDS.get(f"{noun.name} {rest[0]}")
        rest = rest[1:]
    elif name in DEPRECATED:
        command = None
    else:
        command = COMMANDS.get(name)
    if name in OTHER_COMMANDS or (command is not None and not command.all_options()):
        if current.startswith("-"):
            return _matching(_HELP_FLAGS, current)
        return Completions(Mode.FILES)
    if command is None:
        return _NOTHING
    return _arguments(command, rest, current)


def join_bash_words(words: list[str], current: str) -> tuple[list[str], str, str]:
    """
    Bash's words with those it split at '=' or ':' (COMP_WORDBREAKS) put
    back together: '--sort=name' and a YDID each one word again. Returns the
    words, the current word, and the prefix of the current word bash will
    not replace (what precedes its last '=' or ':'), to be taken off each
    candidate.
    """
    joined: list[str] = []
    for word in words:
        if joined and (word in _BASH_BREAKS or joined[-1].endswith(_BASH_BREAKS)):
            joined[-1] += word
        else:
            joined.append(word)
    if current in _BASH_BREAKS and joined:
        prefix = joined.pop() + current
        return joined, prefix, prefix
    if joined and joined[-1].endswith(_BASH_BREAKS):
        prefix = joined.pop()
        return joined, prefix + current, prefix
    return joined, current, ""


def _is_long(word: str) -> bool:
    return word.startswith("--") and len(word) > 2


def _arguments(command: Command, words: list[str], current: str) -> Completions:
    """
    What completes 'current' among a command's arguments, given the words
    already typed after the command (and verb).
    """
    offered = [o for o in command.flat_options() if o.kwargs.get("help") != SUPPRESS]
    by_flag = {flag: o for o in offered if not o.positional for flag in o.flags}
    positionals = [o for o in offered if o.positional]

    given: set[str] = set()
    filled = 0
    awaiting: Option | None = None  # an option whose value comes next
    optional_value = False  # the value may be left out (nargs='?')
    options_ended = False
    for word in words:
        if awaiting is not None:
            awaiting = None
            if not (optional_value and word.startswith("-")):
                continue
        if not options_ended and word == "--":
            options_ended = True
            continue
        if not options_ended and word.startswith("-") and word != "-":
            flag, equals, _ = word.partition("=")
            found = by_flag.get(flag)
            if found is not None:
                given.add(found.name)
                if _takes_value(found) and not equals:
                    awaiting = found
                    optional_value = found.kwargs.get("nargs") == "?"
            continue
        filled += 1

    if awaiting is not None and not (optional_value and current.startswith("-")):
        return _values(command, awaiting, current)
    if not options_ended and _is_long(current) and "=" in current:
        flag, _, value = current.partition("=")
        found = by_flag.get(flag)
        if found is None or not _takes_value(found):
            return _NOTHING
        values = _values(command, found, value)
        return Completions(
            values.mode,
            tuple(
                Candidate(f"{flag}={c.value}", c.description) for c in values.candidates
            ),
        )
    if not options_ended and current.startswith("-"):
        return _option_names(command, offered, given, current)
    positional = _positional_at(positionals, filled)
    if positional is not None:
        values = _values(command, positional, current)
        if values.mode is not Mode.VALUES or values.candidates or current:
            return values
    if current or options_ended:
        return _NOTHING
    return _option_names(command, offered, given, current)


def _takes_value(option: Option) -> bool:
    return option.kwargs.get("action") not in _NO_VALUE_ACTIONS


def _positional_at(positionals: list[Option], filled: int) -> Option | None:
    """
    The positional the next word fills, 'filled' words having been given,
    as argparse assigns them: one word each, the rest to a '*' or '+'.
    """
    for positional in positionals:
        if positional.kwargs.get("nargs") in ("*", "+"):
            return positional
        if filled == 0:
            return positional
        filled -= 1
    return None


def _values(command: Command, option: Option, current: str) -> Completions:
    """
    The values of an option (or positional) that complete 'current'.
    """
    if option.completes is Completes.FILE:
        return Completions(Mode.FILES)
    if option.completes is Completes.DIR:
        return Completions(Mode.DIRS)
    kind = option.kwargs.get("type")
    sort_keys = next(
        (keys for parse, keys in SORT_KEY_TYPES.items() if parse is kind), None
    )
    if sort_keys is not None:
        return _sort_keys(sort_keys, current)
    values = _VERB_VALUES.get((command.name, option.name))
    if values is None and "choices" in option.kwargs:
        values = tuple(str(choice) for choice in option.kwargs["choices"])
    if values is None:
        values = _TYPE_VALUES.get(kind)
    if values is None:
        return _NOTHING
    return _matching(((value, "") for value in values), current)


def _sort_keys(keys: tuple[str, ...], current: str) -> Completions:
    """
    The '--sort' keys completing the last of a comma-separated list, each
    key offered once.
    """
    head, comma, last = current.rpartition(",")
    used = set(head.split(",")) if comma else set()
    return Completions(
        candidates=tuple(
            Candidate(f"{head}{comma}{key}")
            for key in keys
            if key.startswith(last) and key not in used
        )
    )


def _option_names(
    command: Command, offered: list[Option], given: set[str], current: str
) -> Completions:
    """
    The option names completing 'current': long names, or a short flag
    typed in full. An option given already is left out unless it repeats,
    and so is the rest of an exclusive group with a member given.
    """
    excluded = set(given)
    for item in command.all_options():
        if isinstance(item, Exclusive) and given & {o.name for o in item.options}:
            excluded.update(o.name for o in item.options)
    pairs: list[tuple[str, str]] = []
    for option in offered:
        if option.positional:
            continue
        repeatable = option.kwargs.get("action") in _REPEATABLE_ACTIONS
        if option.name in excluded and not repeatable:
            continue
        help_text = _help_text(option)
        if current.startswith("--") or current in ("", "-"):
            pairs.append((option.name, help_text))
        elif current in option.flags:
            pairs.append((current, help_text))
    if current.startswith("--") or current in ("", "-"):
        pairs.extend(_HELP_FLAGS)
    return _matching(pairs, current)


def _help_text(option: Option) -> str:
    """
    An option's help as argparse shows it: '%(default)s' and the like
    filled in from its keyword arguments.
    """
    text = str(option.kwargs.get("help") or "")
    try:
        return text % {**option.kwargs, "prog": ""}
    except (KeyError, TypeError, ValueError):
        return text


def _matching(pairs: Iterable[tuple[str, str]], current: str) -> Completions:
    """
    The (value, description) pairs whose value starts with 'current'.
    """
    return Completions(
        candidates=tuple(
            Candidate(value, _one_line(description))
            for value, description in pairs
            if value.startswith(current)
        )
    )


def _one_line(text: str) -> str:
    return " ".join(text.split())
