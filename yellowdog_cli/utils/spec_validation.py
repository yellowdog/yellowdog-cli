"""
Run-time validation of a loaded specification against its family's schema:
every violation, with its JSON path, as a warning on an ordinary run, or as
the command's whole output under --validate.

A document is validated once it is loaded -- after the variable
substitution the loader applies, and after a Jsonnet file's evaluation, a
TOML file's conversion or a CSV file's task expansion -- so an unresolved
{{variable}} still passes wherever the schema admits one, and a property the
{{::}} unset syntax removed is already gone.

fastjsonschema stops at the first failure, so every violation is found by
repair: each one reported is patched out of a copy of the document -- the
properties an object must not contain are deleted, the ones it must contain
are added, any other failing value is replaced by a {{variable}} token, which
the schema admits wherever a value may stand -- and the copy is validated
again, until it passes or what fails is the document itself.

Each violation is named in plain words -- "unknown property 'a'", "missing
required properties 'a', 'b'", "must contain one of ...", "must not have
both ..." -- where fastjsonschema's own message would show a Python repr.

_locate() follows fastjsonschema's rendered path, which writes an index as
'[n]' and joins keys with '.', so a key containing '[' or ']' cannot be
followed: a failing value under one cannot be replaced, and the repair loop
stops there, having reported that violation but not any after it.

A {{variable}} in a dispatch key (a resource's 'resource', a node action's
'type') matches no case, so the rest of that object is left unchecked: which
case applies is not known until the variable is substituted.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable
from sys import exit
from typing import Any, NamedTuple, NoReturn

import fastjsonschema

from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.property_names import ALL_KEYS, DATA_CLIENT_SECTION, SCHEMA_KEY
from yellowdog_cli.utils.results import json_requested, record
from yellowdog_cli.utils.settings import ExitCode
from yellowdog_cli.utils.spec_properties import (
    ALL_CONFIG_SECTIONS,
    CONFIG_SECTIONS,
    FLOAT_CAST,
    INT_CAST,
)
from yellowdog_cli.utils.spec_schema import (
    Family,
    SchemaGenerationError,
    compile_config_schema,
    compile_schema,
)

# What stands in for a failing value while the rest is checked: a
# {{variable}}, which the schema admits for every value
_STAND_IN = "{{_}}"

# A bound on the repairs, far beyond any real document's violations
MAX_VIOLATIONS = 500

DOCUMENT_PATH = "(document)"


class Violation(NamedTuple):
    path: str
    message: str


def strip_schema_key(document: Any) -> Any:
    """
    Remove the '$schema' key an editor is pointed at a schema by, from the
    document and, for a resource list, from each resource: the CLI ignores
    it, and a Worker Pool file is otherwise posted to the Platform as
    written. Returns the document, changed in place.
    """
    for item in document if isinstance(document, list) else [document]:
        if isinstance(item, dict):
            item.pop(SCHEMA_KEY, None)
    return document


def _path(exc: fastjsonschema.JsonSchemaValueException) -> str:
    """'data.taskGroups[0].maxWorkers' -> 'taskGroups[0].maxWorkers'."""
    name = exc.name or "data"
    path = name[len("data") :] if name.startswith("data") else name
    return path.removeprefix(".") or DOCUMENT_PATH


def _required_branches(branches: Any) -> list[list[str]] | None:
    """
    The key lists of an 'anyOf' whose every branch is a bare 'required' --
    how the schema says 'one of these' (ONE_OF_REQUIRED) or, under 'not',
    'not these together' (a writeFile's content sources) -- else None.
    """
    if not isinstance(branches, list) or not branches:
        return None
    keys: list[list[str]] = []
    for branch in branches:
        if not isinstance(branch, dict) or set(branch) != {"required"}:
            return None
        keys.append(list(branch["required"]))
    return keys


def _one_of(exc: fastjsonschema.JsonSchemaValueException) -> list[list[str]] | None:
    """An 'anyOf' failure's alternatives, if it is a one-of-these-keys rule."""
    if exc.rule != "anyOf" or not isinstance(exc.value, dict):
        return None
    return _required_branches(exc.rule_definition)


def _not_together(exc: fastjsonschema.JsonSchemaValueException) -> list[str] | None:
    """The keys present together that a 'not' rule forbids, if it is such a rule."""
    if exc.rule != "not" or not isinstance(exc.value, dict):
        return None
    rule = exc.rule_definition
    if not isinstance(rule, dict):
        return None
    branches = (
        _required_branches(rule.get("anyOf"))
        if "anyOf" in rule
        else _required_branches([{"required": rule["required"]}])
        if set(rule) - {"description"} == {"required"}
        else None
    )
    for keys in branches or ():
        if all(key in exc.value for key in keys):
            return keys
    return None


def _definition(exc: fastjsonschema.JsonSchemaValueException) -> dict[str, Any]:
    return exc.definition if isinstance(exc.definition, dict) else {}


def _unknown(exc: fastjsonschema.JsonSchemaValueException) -> list[str]:
    """The properties an 'additionalProperties' failure's object must not contain."""
    if exc.rule != "additionalProperties" or not isinstance(exc.value, dict):
        return []
    allowed = _definition(exc).get("properties", {})
    return [key for key in exc.value if key not in allowed]


def _missing(exc: fastjsonschema.JsonSchemaValueException) -> list[str]:
    """The properties a 'required' failure's object must contain and does not."""
    if exc.rule != "required" or not isinstance(exc.value, dict):
        return []
    return [k for k in _definition(exc).get("required", ()) if k not in exc.value]


def _named(singular: str, keys: list[str]) -> str:
    """The keys, sorted and quoted, after 'singular' and 'property(ies)'."""
    quoted = ", ".join(f"'{key}'" for key in sorted(keys))
    return f"{singular} {'property' if len(keys) == 1 else 'properties'} {quoted}"


def _and_list(keys: list[str], conjunction: str) -> str:
    return (
        keys[0]
        if len(keys) == 1
        else f"{', '.join(keys[:-1])} {conjunction} {keys[-1]}"
    )


def _message(exc: fastjsonschema.JsonSchemaValueException) -> str:
    """'data.taskGroups[0].maxWorkers must be integer' -> 'must be integer'."""
    alternatives = _one_of(exc)
    if alternatives is not None:
        return "must contain one of " + ", ".join(
            _and_list(keys, "and") for keys in alternatives
        )
    together = _not_together(exc)
    if together is not None:
        both = "both" if len(together) == 2 else "all of"
        return f"must not have {both} {_and_list(together, 'and')}"
    # fastjsonschema names these keys by a Python repr ("must not contain
    # {'a', 'b'} properties", a set's order unstable)
    unknown = _unknown(exc)
    if unknown:
        return _named("unknown", unknown)
    missing = _missing(exc)
    if missing:
        return _named("missing required", missing)
    text = exc.message
    prefix = f"{exc.name} "
    return text[len(prefix) :] if exc.name and text.startswith(prefix) else text


def _locate(document: Any, parts: list[str]) -> tuple[Any, Any] | None:
    """
    The container holding the value at fastjsonschema's path 'parts'
    ('data' first) and the value's key or index there, or None for the
    document itself or a path that cannot be followed. The path is the
    rendered name split on '.', '[' and ']', so a key containing a '.'
    spans parts, and is joined back together here; a key containing '[' or
    ']' has lost which of them it held, and cannot be (see the module
    docstring).
    """
    parts = list(parts[1:])
    if not parts:
        return None
    container = None
    key: Any = None
    current = document
    while parts:
        if isinstance(current, list):
            try:
                index = int(parts[0])
            except ValueError:
                return None
            if not 0 <= index < len(current):
                return None
            container, key = current, index
            parts = parts[1:]
        elif isinstance(current, dict):
            for count in range(1, len(parts) + 1):
                candidate = ".".join(parts[:count])
                if candidate in current:
                    container, key = current, candidate
                    parts = parts[count:]
                    break
            else:
                return None
        else:
            return None
        current = container[key]
    return container, key


def _repair(document: Any, exc: fastjsonschema.JsonSchemaValueException) -> bool:
    """
    Patch the failure 'exc' reports out of 'document', in place, so that
    validating it again moves on to the next one. False if it cannot be:
    the failure is the document's own.
    """
    value: Any = exc.value
    # A one-of-these-keys rule is satisfied by the first alternative, and a
    # not-these-together rule by dropping the last of the keys, so the
    # object's other violations are still found
    alternatives = _one_of(exc)
    if alternatives is not None:
        for key in alternatives[0]:
            value.setdefault(key, _STAND_IN)
        return True
    together = _not_together(exc)
    if together is not None:
        del value[together[-1]]
        return True
    extra = _unknown(exc)
    for key in extra:
        del value[key]
    if extra:
        return True
    missing = _missing(exc)
    for key in missing:
        value[key] = _STAND_IN
    if missing:
        return True
    location = _locate(document, list(exc.path))
    if location is None:
        return False
    container, key = location
    container[key] = _STAND_IN
    return True


def validate_specification(
    family: Family, document: Any, source: str
) -> list[Violation]:
    """
    Every violation of the family's schema in 'document', each with the JSON
    path it is at. 'source' names the document, for the callers' messages.
    """
    return _violations(compile_schema(family), document)


def _violations(validate: Callable[[Any], Any], document: Any) -> list[Violation]:
    """Every violation 'validate' finds in 'document', found by repair."""
    working = copy.deepcopy(document)
    violations: list[Violation] = []
    seen: set[Violation] = set()
    while True:
        try:
            validate(working)
            break
        except fastjsonschema.JsonSchemaValueException as exc:
            if len(violations) == MAX_VIOLATIONS:
                violations.append(
                    Violation(
                        DOCUMENT_PATH,
                        f"...and more: stopped after {MAX_VIOLATIONS} violations",
                    )
                )
                break
            violation = Violation(_path(exc), _message(exc))
            if violation in seen:  # A repair that did not take: stop
                break
            seen.add(violation)
            violations.append(violation)
            if not _repair(working, exc):
                break
    return violations


MISPLACED_MESSAGE = "'{key}' is not read in this section"


# A property the loader casts with int() or float() (spec_properties'
# INT_CAST, FLOAT_CAST) fails as a type list or as a pattern; either way what
# it must be is a number of that kind
def _worded(violation: Violation) -> Violation:
    """A cast property's failure in words, else the violation as it is."""
    section, _, key = violation.path.partition(".")
    for prop in CONFIG_SECTIONS.get(section, ()):
        if prop.name == key and prop.schema is INT_CAST:
            return Violation(violation.path, "must be an integer")
        if prop.name == key and prop.schema is FLOAT_CAST:
            return Violation(violation.path, "must be a number")
    return violation


def _without_nulls(value: Any) -> Any:
    """
    'value' with every None removed from its tables: TOML has no null, so
    one came from '--property section.key=null', which unsets the property.
    """
    if isinstance(value, dict):
        return {k: _without_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_without_nulls(item) for item in value]
    return value


def _misplaced_or_unknown(key: str) -> str:
    return (
        MISPLACED_MESSAGE.format(key=key)
        if key in ALL_KEYS
        else f"unknown property '{key}'"
    )


def _check_keys(
    table: dict, allowed: set[str], path: str, violations: list[Violation]
) -> None:
    """Report, and delete from 'table', every key 'allowed' does not hold."""
    for key in [k for k in table if k not in allowed]:
        violations.append(Violation(path, _misplaced_or_unknown(key)))
        del table[key]


def validate_config(document: dict, sections: frozenset[str]) -> list[Violation]:
    """
    Every violation in the configuration file's 'sections'. Each section's
    own keys are checked here, so that a key another section reads is
    reported as misplaced rather than unknown -- validate_properties() has
    already refused, at import, a key that no section reads, so an unknown
    one here came from '--property' -- and deleted from a copy, which the
    schema then checks for everything else. A [dataClient] section's table
    values are profiles, checked with the section's keys.
    """
    working = _without_nulls(copy.deepcopy(document))
    violations: list[Violation] = []
    if sections == ALL_CONFIG_SECTIONS:
        known = ALL_CONFIG_SECTIONS | {SCHEMA_KEY}
        for name in [k for k in working if k not in known]:
            kind = "unknown section" if isinstance(working[name], dict) else None
            violations.append(
                Violation(
                    DOCUMENT_PATH,
                    f"{kind} '{name}'" if kind else f"'{name}' is not in a section",
                )
            )
            del working[name]
    for name in sorted(sections):
        section = working.get(name)
        if not isinstance(section, dict):
            continue  # absent, or not a table: the schema says which
        allowed = {p.name for p in CONFIG_SECTIONS[name]}
        if name == DATA_CLIENT_SECTION:
            for profile, table in section.items():
                if isinstance(table, dict):
                    _check_keys(table, allowed, f"{name}.{profile}", violations)
            allowed |= {k for k, v in section.items() if isinstance(v, dict)}
        _check_keys(section, allowed, name, violations)
    # The schema over the sections the file has, not all it could have: an
    # absent section has nothing to check, and [workRequirement]'s, built
    # from the SDK, is most of the full schema's size. Anything left at the
    # top level is a known section or '$schema', so the subset schema's
    # leaving other sections open changes nothing
    present = sections & frozenset(working)
    return violations + [
        _worded(v) for v in _violations(compile_config_schema(present), working)
    ]


def _describe(source: str, violation: Violation) -> str:
    return f"'{source}': {violation.path}: {violation.message}"


def warn_of_violations(family: Family, document: Any, source: str) -> list[Violation]:
    """
    An ordinary run: each violation as a warning, naming the file and the
    path; the command goes on, and the Platform or the loader has the last
    word on what is accepted.

    A schema that cannot be built -- an SDK annotation the mapping does not
    describe, or a definition fastjsonschema will not compile -- is one
    warning saying the document went unchecked, never a refusal: the run
    goes on as it would without a schema. '--validate' and yd-schema stay
    fail-loud, and name the cause.
    """
    try:
        violations = validate_specification(family, document, source)
    except (SchemaGenerationError, fastjsonschema.JsonSchemaDefinitionException) as e:
        print_warning(
            f"cannot check '{source}' against the {family.value} schema: {e};"
            f" run 'yd-schema {family.value}' to see why"
        )
        return []
    for violation in violations:
        print_warning(f"{_describe(source, violation)} (see yd-schema {family.value})")
    return violations


def validate_all_and_exit(
    family: Family, documents: Iterable[tuple[Any, str]]
) -> NoReturn:
    """
    '--validate': report every violation in every (document, source) as an
    error, and record each as {path, message} (with 'source') for '--json',
    then exit 1 if there were any, else 0 having said each document is OK.
    """
    failed = False
    for document, source in documents:
        violations = validate_specification(family, document, source)
        for violation in violations:
            record(
                {"source": source, "path": violation.path, "message": violation.message}
            )
            print_error(_describe(source, violation))
        if violations:
            failed = True
        elif not json_requested():
            print_info(f"'{source}': valid against the {family.value} schema")
    exit(ExitCode.FAILURE if failed else ExitCode.SUCCESS)


def validate_and_exit(family: Family, document: Any, source: str) -> NoReturn:
    """'--validate' for a command that loads a single specification."""
    validate_all_and_exit(family, [(document, source)])


def check_specification(
    family: Family, document: Any, source: str, validate: bool
) -> Any:
    """
    The hook every loader calls on a specification it has loaded: strip the
    '$schema' key, then stop under '--validate' ('validate') or warn of the
    violations and return the stripped document.
    """
    document = strip_schema_key(document)
    if validate:
        validate_and_exit(family, document, source)
    warn_of_violations(family, document, source)
    return document
