"""
Shell completion: what Tab offers for a partly typed 'yd' command line.

complete() works from the registries alone (command_registry.COMMANDS,
noun_registry's nouns and derived commands, and top_level.TOP_LEVEL, the
words after 'yd'), importing no command module and no SDK, since the shell
runs 'yd completion --complete' on every Tab.
It offers a noun's verbs, the options a command or verb offers (never one
it hides), and the values the registry states: choices, '--sort' keys, the
entity and Cloud Info types, and local files or directories for an option
marked Completes.FILE or Completes.DIR. A value it knows nothing of
offers nothing.
An entity argument (utils/completion_targets.LOOKUPS) is completed from
the Platform, but not here: complete() returns a LookupRequest naming the
lookup and the configuration options typed on the line, and the
yd completion command makes it (utils/completion_lookups.py), so this
module stays local and SDK-free.
A command whose arguments the registry does not describe (yd commander and
yd mcp, the launchers) is left to the shell's own completion of files, which
is what it had before the stubs claimed its name, with '--help' for a word
starting with '-'.

The stubs register 'yd' alone: a deprecated 'yd-*' script is not
completed.
"""

from __future__ import annotations

from argparse import SUPPRESS, ArgumentTypeError
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum, auto
from typing import cast

from yellowdog_cli.utils.command_registry import (
    CLOUD_INFO_TYPES,
    COMMANDS,
    CONFIG,
    ENTITY_TYPES,
    ENV_OVERRIDE,
    KEY,
    NAMESPACE,
    NO_CONFIG,
    PAC,
    PROPERTY,
    SECRET,
    SORT_KEY_TYPES,
    TAG,
    URL,
    VARIABLE,
    Command,
    Completes,
    Exclusive,
    Option,
    resolve_cloud_info_type,
    resolve_entity_type,
    resolve_resource_type,
)
from yellowdog_cli.utils.completion_targets import (
    LOOKUPS,
    RESOURCE_LOOKUPS,
    RESOURCE_TARGETS,
    WITHIN_LOOKUPS,
    Lookup,
)
from yellowdog_cli.utils.invocation import invoked_name
from yellowdog_cli.utils.noun_registry import (
    NOUN_COMMANDS,
    NOUNS_BY_NAME,
    RESOURCE_LIST_TYPES,
)
from yellowdog_cli.utils.top_level import TOP_LEVEL, Kind

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
    ("yd resource list", "entity_type"): tuple(sorted(RESOURCE_LIST_TYPES)),
}

_HELP_FLAGS = (("--help", "show the help message and exit"),)

# The options a lookup's configuration is loaded under, by option identity:
# the setting each gives (the CLIParser property load_config reads), and
# whether it is a value, a repeated value or a flag
_STORED, _APPENDED, _FLAG = "stored", "appended", "flag"
_LOOKUP_SETTINGS: dict[str, tuple[str, str]] = {
    CONFIG.name: ("config_file", _STORED),
    KEY.name: ("key", _STORED),
    SECRET.name: ("secret", _STORED),
    URL.name: ("url", _STORED),
    NAMESPACE.name: ("namespace", _STORED),
    TAG.name: ("tag", _STORED),
    VARIABLE.name: ("variables", _APPENDED),
    PROPERTY.name: ("property_overrides", _APPENDED),
    ENV_OVERRIDE.name: ("env_override", _FLAG),
    NO_CONFIG.name: ("no_config", _FLAG),
    PAC.name: ("use_pac", _FLAG),
}

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
class LookupRequest:
    """
    A lookup for the command to make: what to look up, the word it
    completes, the configuration options typed on the line, as the
    CLIParser properties load_config reads (None, or False, when not typed),
    and the names or IDs typed already, which are not offered again.
    """

    lookup: Lookup
    current: str
    settings: dict[str, object]
    given: tuple[str, ...] = ()  # the names or IDs typed already
    # Put ahead of each name or ID found: the '--flag=' of a value typed
    # in the one word with its option
    prefix: str = ""


@dataclass(frozen=True)
class Completions:
    mode: Mode = Mode.VALUES
    # With a lookup, the candidates are what to offer if it finds nothing
    candidates: tuple[Candidate, ...] = ()
    lookup: LookupRequest | None = None


_NOTHING = Completions()


def complete(words: list[str], current: str) -> Completions:
    """
    What completes 'current', the word under the cursor, after 'words', the
    words before it ('yd' first).
    """
    if not words or invoked_name(words[0]) != "yd":
        return _NOTHING
    if len(words) == 1:
        if current.startswith("-"):
            return _matching(_HELP_FLAGS, current)
        return _matching(((e.word, e.summary) for e in TOP_LEVEL.values()), current)
    entry = TOP_LEVEL.get(words[1])
    if entry is None:
        return _NOTHING
    rest = words[2:]
    command: Command | None
    if entry.kind is Kind.NOUN:
        noun = NOUNS_BY_NAME[entry.target]
        if not rest:
            if current.startswith("-"):
                return _matching(_HELP_FLAGS, current)
            return _matching(((v.name, v.summary) for v in noun.verbs), current)
        command = NOUN_COMMANDS.get(f"yd {noun.name} {rest[0]}")
        rest = rest[1:]
    elif entry.kind is Kind.OTHER:
        command = None
    else:
        command = COMMANDS[entry.target]
    if entry.kind is Kind.OTHER or (command is not None and not command.all_options()):
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
    candidate. Bash 3.2, macOS's, does not split the words at them, but
    readline still replaces only what follows the last, so the prefix is
    taken off there too.
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
    last = max(current.rfind(character) for character in _BASH_BREAKS)
    return joined, current, current[: last + 1]


def unquoted(word: str) -> str:
    """
    A word as the shell will pass it to the command: its quotes taken away
    and its backslash escapes undone ('my ns', "a b", a\\ b), a quote
    opened and not yet closed (the word being typed, "'nigh") dropped.
    The words bash and zsh hand completion are as typed, quotes and all.
    """
    characters: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(word):
        character = word[index]
        escaped = word[index + 1] if index + 1 < len(word) else None
        if quote is None and character in "'\"":
            quote = character
        elif quote is None and character == "\\" and escaped is not None:
            characters.append(escaped)
            index += 1
        elif character == quote:
            quote = None
        elif quote == '"' and character == "\\" and escaped in ('"', "\\", "$", "`"):
            characters.append(cast(str, escaped))
            index += 1
        else:
            characters.append(character)
        index += 1
    return "".join(characters)


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
    settings = _unset_settings()
    typed_values: dict[str, str] = {}  # each option's value as typed, by name
    filled = 0
    typed: list[str] = []  # the positional words, for a lookup to leave out
    awaiting: Option | None = None  # an option whose value comes next
    optional_value = False  # the value may be left out (nargs='?')
    options_ended = False
    for word in words:
        if awaiting is not None:
            value_of, awaiting = awaiting, None
            if not (optional_value and word.startswith("-")):
                _set(settings, value_of, word)
                typed_values[value_of.name] = word
                continue
            # Given no value: its 'const', as argparse sets it ('-n' is '')
            _set(settings, value_of, value_of.kwargs.get("const"))
        if not options_ended and word == "--":
            options_ended = True
            continue
        if not options_ended and word.startswith("-") and word != "-":
            found, equals, value = _option_in(word, by_flag)
            if found is not None:
                given.add(found.name)
                if not _takes_value(found):
                    _set(settings, found, True)
                elif equals:
                    _set(settings, found, value)
                    typed_values[found.name] = value
                else:
                    awaiting = found
                    optional_value = found.kwargs.get("nargs") == "?"
            continue
        filled += 1
        typed.append(word)

    if awaiting is not None and not (optional_value and current.startswith("-")):
        lookup = _option_lookup(command, awaiting, typed)
        if lookup is not None:
            return Completions(lookup=LookupRequest(lookup, current, settings))
        return _values(command, awaiting, current)
    if not options_ended and _is_long(current) and "=" in current:
        flag, _, value = current.partition("=")
        found = _option_named(flag, by_flag)
        if found is None or not _takes_value(found):
            return _NOTHING
        # Looked up as the value would be after a space ('--within <Tab>')
        lookup = _option_lookup(command, found, typed)
        if lookup is not None:
            return Completions(
                lookup=LookupRequest(lookup, value, settings, prefix=f"{flag}=")
            )
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
        lookup = LOOKUPS.get((command.name, positional.name)) or _resource_lookup(
            command, positional, typed_values
        )
        if lookup is not None:
            request = LookupRequest(lookup, current, settings, tuple(typed))
            if current or options_ended:
                return Completions(lookup=request)
            fallback = _option_names(command, offered, given, current)
            return Completions(candidates=fallback.candidates, lookup=request)
        values = _values(command, positional, current)
        if values.mode is not Mode.VALUES or values.candidates or current:
            return values
    if current or options_ended:
        return _NOTHING
    return _option_names(command, offered, given, current)


def _resource_lookup(
    command: Command, positional: Option, values: dict[str, str]
) -> Lookup | None:
    """
    For a remove's or a show's targets given '--type', the lookup of that
    resource type's names: the type typed as the command reads it, in any
    case; none for a type it does not take.
    """
    typed = values.get("--type")
    if typed is None or (command.name, positional.name) not in RESOURCE_TARGETS:
        return None
    try:
        return RESOURCE_LOOKUPS.get(resolve_resource_type(typed))
    except ArgumentTypeError:
        return None


def _option_lookup(command: Command, option: Option, typed: list[str]) -> Lookup | None:
    """
    The lookup an option's value is completed by, if any: a verb's own, or
    for 'yd list <type> --within' the one for the entity type typed (a full
    name, a prefix or a synonym, as the command resolves it).
    """
    lookup = LOOKUPS.get((command.name, option.name))
    if lookup is not None or option.name != "--within" or not typed:
        return lookup
    try:
        entity_type = resolve_entity_type(typed[0])
    except ArgumentTypeError:
        return None
    return WITHIN_LOOKUPS.get(entity_type)


def _option_in(word: str, by_flag: dict[str, Option]) -> tuple[Option | None, str, str]:
    """
    The option a word names, as argparse reads it, with its value when the
    word holds one: '--flag=value', an unambiguous abbreviation of a long
    flag ('--names' for '--namespace'), or a short flag with its value
    attached ('-nprod'). Returns the option (or None), and '=' and the value
    when the word holds one, else two empty strings.
    """
    flag, equals, value = word.partition("=")
    found = _option_named(flag, by_flag)
    if found is not None:
        return found, equals, value
    attached = by_flag.get(word[:2])
    if not word.startswith("--") and attached is not None and _takes_value(attached):
        return attached, "=", word[2:]
    return None, "", ""


def _option_named(flag: str, by_flag: dict[str, Option]) -> Option | None:
    """
    The option a flag names: exactly, or as the one long flag it begins.
    """
    found = by_flag.get(flag)
    if found is not None or not _is_long(flag):
        return found
    matches = {
        option.name: option
        for candidate, option in by_flag.items()
        if candidate.startswith("--") and candidate.startswith(flag)
    }
    return next(iter(matches.values())) if len(matches) == 1 else None


def _unset_settings() -> dict[str, object]:
    """
    The lookup settings as they are with nothing typed.
    """
    return {
        setting: False if kind == _FLAG else None
        for setting, kind in _LOOKUP_SETTINGS.values()
    }


def _set(settings: dict[str, object], option: Option, value: object) -> None:
    """
    Record an option's value in the lookup settings, if it is one of theirs.
    """
    entry = _LOOKUP_SETTINGS.get(option.name)
    if entry is None:
        return
    setting, kind = entry
    if kind == _APPENDED:
        settings[setting] = [*cast(list, settings[setting] or []), value]
    else:
        settings[setting] = value


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


# The option types read in any case ('--type keyring' is 'Keyring'), whose
# values are completed in any case too
_ANY_CASE_TYPES = frozenset({resolve_resource_type})


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
    if kind in _ANY_CASE_TYPES:
        return _matching_any_case(values, current)
    return _matching(((value, "") for value in values), current)


def _matching_any_case(values: Iterable[str], current: str) -> Completions:
    """
    The values that start with 'current' in any case, for an option the
    command reads in any case: offered in lower case when 'current' is, as
    typed, so that a shell matching case keeps them, and as written
    otherwise.
    """
    lower = bool(current) and current == current.lower()
    return Completions(
        candidates=tuple(
            Candidate(value.lower() if lower else value)
            for value in values
            if value.lower().startswith(current.lower())
        )
    )


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
