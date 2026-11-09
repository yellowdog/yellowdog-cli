"""
yd resource plan: what 'yd resource create' would do, without doing it.
Read by yellowdog_cli/resource_plan.py, the command.

The engine: each specification planned in turn by its type's planner
(PLANNERS, registered by resource_planners.py), an SDK model reduced to the
properties a specification can set (comparable()), the two sides compared
property by property (differences()), and each outcome printed, recorded
under '--json' and counted. A failed specification is reported and the rest
planned, as 'yd resource create' carries on (resource_processing.py).
"""

import json
import re
import sys
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Literal

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    RN_ALLOWANCE,
    RN_APPLICATION,
    RN_CONFIGURED_POOL,
    RN_CREDENTIAL,
    RN_EXTERNAL_USER,
    RN_GROUP,
    RN_IMAGE_FAMILY,
    RN_INTERNAL_USER,
    RN_KEYRING,
    RN_NAMESPACE,
    RN_NAMESPACE_POLICY,
    RN_NUMERIC_ATTRIBUTE_DEFINITION,
    RN_REQUIREMENT_TEMPLATE,
    RN_SOURCE_TEMPLATE,
    RN_STRING_ATTRIBUTE_DEFINITION,
)
from yellowdog_cli.utils.exit_codes import ExitCode, ReportedFailure
from yellowdog_cli.utils.load_resources import RESOURCE_SOURCE_DIR
from yellowdog_cli.utils.printing import counted, info_silenced, print_info
from yellowdog_cli.utils.resource_creation import CreateOptions, options_in_effect
from yellowdog_cli.utils.resource_processing import (
    describe_specification,
    process_each,
    process_specification,
    record_specification,
)
from yellowdog_cli.utils.results import record_resource
from yellowdog_cli.utils.specs.sdk_models import (
    SERVER_ASSIGNED_COVERAGE,
    settable_properties,
)

ChangeKind = Literal["changed", "cleared", "added", "removed"]
Action = Literal["create", "update", "unchanged", "unknown", "failed"]


@dataclass(frozen=True)
class PlanOptions:
    """
    The command line's choices for a plan.
    """

    json_output: bool = False
    fail_on_changes: bool = False
    match_allowances_by_description: bool = False
    regenerate_app_keys: bool = False


@dataclass(frozen=True)
class Change:
    """
    One difference between the resource as it is and as the specification
    would make it: a property 'changed' or 'cleared', or a list item
    'added' or 'removed'. 'path' is the property's JSON path.
    """

    path: str
    before: Any
    after: Any
    kind: ChangeKind


@dataclass(frozen=True)
class ToBeCreated:
    """
    A reference, in a change, to a resource an earlier specification in the
    plan would create, so has no ID yet: shown as its name, '(to be
    created)'.
    """

    name: str

    def __str__(self) -> str:
        return f"'{self.name}' (to be created)"


@dataclass(frozen=True)
class PlanEntry:
    """
    One specification's outcome: what 'yd resource create' would do to its
    resource, with the changes an update would make, the reason an outcome
    is unknown or a resource left as it is, and a Credential's Keyring.
    """

    resource_type: str
    name: str | None
    id: str | None
    action: Action
    changes: tuple[Change, ...] = ()
    reason: str | None = None
    keyring: str | None = None


# A planner: (ctx, resource, source_dir, planned) -> PlanEntry, 'resource'
# being the specification less 'resource' and its source directory, and
# 'planned' the (resource type, name) of every resource an earlier
# specification would create. Registered by the per-type planner modules.
Planner = Callable[[RunContext, dict, str | None, set[tuple[str, str]]], PlanEntry]
PLANNERS: dict[str, Planner] = {}

# Resource type -> {property path, list indices written '[]': reason}. A
# property the Platform fills in with a default when a specification omits
# it, so the specification omitting it is no change. Each is found by the live
# check (tests/live/test_live_setup.py: a plan of what setup just created
# must be all unchanged), never guessed
PLATFORM_DEFAULTS: dict[str, dict[str, str]] = {
    RN_REQUIREMENT_TEMPLATE: {
        # Live run ydst-2611091205-j0sf: {} on every provider's template
        "instanceTags": "the Platform sets an empty map when unset",
    },
}

# Resource type -> {list property path, indices written '[]': reason}. A
# list the Platform does not keep in the order sent, compared as a multiset.
# The live check finds none: the Platform keeps every list in the order sent
UNORDERED_LISTS: dict[str, dict[str, str]] = {}

# The resource types as 'yd resource create' names them
RESOURCE_TYPE_NAMES: dict[str, str] = {
    RN_SOURCE_TEMPLATE: "Compute Source Template",
    RN_REQUIREMENT_TEMPLATE: "Compute Requirement Template",
    RN_IMAGE_FAMILY: "Machine Image Family",
    RN_KEYRING: "Keyring",
    RN_CREDENTIAL: "Credential",
    RN_CONFIGURED_POOL: "Configured Worker Pool",
    RN_ALLOWANCE: "Allowance",
    RN_STRING_ATTRIBUTE_DEFINITION: "String Attribute Definition",
    RN_NUMERIC_ATTRIBUTE_DEFINITION: "Numeric Attribute Definition",
    RN_NAMESPACE_POLICY: "Namespace Policy",
    RN_GROUP: "Group",
    RN_APPLICATION: "Application",
    RN_INTERNAL_USER: "Internal User",
    RN_EXTERNAL_USER: "External User",
    RN_NAMESPACE: "Namespace",
}

# How each outcome is shown in the text plan (the records keep the action)
_LABELS: dict[str, str] = {
    "create": "New",
    "update": "Changed",
    "unchanged": "Unchanged",
    "unknown": "Unknown",
}
_LABEL_WIDTH = max(len(label) for label in _LABELS.values())
# A change's line, under the resource type in its entry's line
_CHANGE_INDENT = " " * (_LABEL_WIDTH + 2)
_LONGEST_SHOWN = 60
_USER_DATA = "userData"
# An Application's key: a change to it is shown as regenerated, never a value
API_KEY = "apiKey"
API_KEY_REGENERATED = "regenerated"
# A list index or a by-name match in a path: 'sources[1]', 'images[name=a]'
_INDEX = re.compile(r"\[[^\]]*\]")
# The SDK's polymorphic discriminator, which settable_properties() leaves out
# (the specification's creator pops it), but which tells two models apart
_DISCRIMINATOR = "type"


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _compared_fields(model: object, model_name: str) -> set[str]:
    """
    The fields of a dataclass model a specification can set: its settable
    properties, or, for a class the SDK does not know by that name, every
    field; less the server-assigned ones and 'id', with the discriminator.
    """
    names = {f.name for f in fields(model)}  # type: ignore[arg-type]
    try:
        settable = settable_properties(model_name)
    except AttributeError:
        # Not an SDK model: nothing records what can be set, so all of it
        settable = set(names)
    settable -= {
        name
        for name, evidenced_for in SERVER_ASSIGNED_COVERAGE.items()
        if model_name in evidenced_for
    }
    settable.discard("id")
    if _DISCRIMINATOR in names:
        settable.add(_DISCRIMINATOR)
    return settable & names


def comparable(model: object, model_name: str | None = None) -> Any:
    """
    An SDK model (or plain data holding them) as plain data, restricted to
    what a specification can set, at every level: an enum as its value, a
    datetime or date in ISO 8601, a duration as the SDK writes it, a None
    property left out. A dict is kept whole, its values converted.
    """
    if model is None or isinstance(model, (str, int, float, bool)):
        return model
    if isinstance(model, Enum):
        return model.value
    if isinstance(model, (datetime, date)):
        return model.isoformat()
    if isinstance(model, timedelta):
        from yellowdog_client.common.iso_datetime import iso_timedelta_format

        return iso_timedelta_format(model)
    if isinstance(model, dict):
        return {key: comparable(value) for key, value in model.items()}
    if isinstance(model, (list, tuple)):
        return [comparable(item) for item in model]
    if isinstance(model, (set, frozenset)):
        items = [comparable(item) for item in model]
        try:
            return sorted(items)
        except TypeError:
            return items
    if is_dataclass(model) and not isinstance(model, type):
        name = model_name or type(model).__name__
        kept = _compared_fields(model, name)
        result: dict[str, Any] = {}
        for field in fields(model):
            if field.name not in kept:
                continue
            value = getattr(model, field.name)
            if value is not None:
                result[field.name] = comparable(value)
        return result
    return model


def path_pattern(path: str) -> str:
    """
    A path with its list indices and by-name matches written '[]', as the
    PLATFORM_DEFAULTS, UNORDERED_LISTS and 'by_name' paths are.
    """
    return _INDEX.sub("[]", path)


def _child(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _named(items: list) -> bool:
    return all(isinstance(item, dict) and "name" in item for item in items)


def differences(
    before: Any,
    after: Any,
    path: str = "",
    by_name: frozenset[str] = frozenset(),
    defaults: frozenset[str] = frozenset(),
    unordered: frozenset[str] = frozenset(),
) -> list[Change]:
    """
    The changes that would make 'before' (the resource as it is) 'after'
    (as the specification describes it), each comparable() data. Dicts are
    compared key by key, a key 'before' has and 'after' lacks (or holds
    None) 'cleared' unless its path is in 'defaults'. Lists are compared by
    position, except a list whose path is in 'by_name', matched on each
    item's 'name' (each match compared under '<list>[name=<name>]'), and one
    whose path is in 'unordered', compared as a multiset. The paths in the
    three sets write list indices as '[]': 'sources[].instanceType'.
    """
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[Change] = []
        for key in [*before, *(k for k in after if k not in before)]:
            child = _child(path, key)
            was, now = before.get(key), after.get(key)
            if was is None and now is None:
                continue
            if now is None:
                if path_pattern(child) not in defaults:
                    changes.append(Change(child, was, None, "cleared"))
            elif was is None:
                changes.append(Change(child, None, now, "added"))
            else:
                changes += differences(was, now, child, by_name, defaults, unordered)
        return changes

    if isinstance(before, list) and isinstance(after, list):
        pattern = path_pattern(path)
        if pattern in by_name and _named(before) and _named(after):
            return _by_name(before, after, path, by_name, defaults, unordered)
        if pattern in unordered:
            return _as_multiset(before, after, path)
        return _by_position(before, after, path, by_name, defaults, unordered)

    if before != after or isinstance(before, bool) != isinstance(after, bool):
        return [Change(path, before, after, "changed")]
    return []


def _by_name(
    before: list[dict],
    after: list[dict],
    path: str,
    by_name: frozenset[str],
    defaults: frozenset[str],
    unordered: frozenset[str],
) -> list[Change]:
    was = {item["name"]: item for item in before}
    now = {item["name"]: item for item in after}
    changes = [
        Change(path, item, None, "removed")
        for item in before
        if item["name"] not in now
    ]
    for item in after:
        name = item["name"]
        if name not in was:
            changes.append(Change(path, None, item, "added"))
        else:
            changes += differences(
                was[name], item, f"{path}[name={name}]", by_name, defaults, unordered
            )
    return changes


def _as_multiset(before: list, after: list, path: str) -> list[Change]:
    remaining = list(after)
    changes: list[Change] = []
    for item in before:
        if item in remaining:
            remaining.remove(item)
        else:
            changes.append(Change(path, item, None, "removed"))
    changes += [Change(path, None, item, "added") for item in remaining]
    return changes


def _by_position(
    before: list,
    after: list,
    path: str,
    by_name: frozenset[str],
    defaults: frozenset[str],
    unordered: frozenset[str],
) -> list[Change]:
    changes: list[Change] = []
    for index in range(max(len(before), len(after))):
        child = f"{path}[{index}]"
        if index >= len(after):
            changes.append(Change(child, before[index], None, "removed"))
        elif index >= len(before):
            changes.append(Change(child, None, after[index], "added"))
        else:
            changes += differences(
                before[index], after[index], child, by_name, defaults, unordered
            )
    return changes


def resource_differences(
    resource_type: str,
    before: Any,
    after: Any,
    by_name: frozenset[str] = frozenset(),
) -> list[Change]:
    """
    differences() for a resource of this type, with its PLATFORM_DEFAULTS
    and UNORDERED_LISTS.
    """
    return differences(
        before,
        after,
        by_name=by_name,
        defaults=frozenset(PLATFORM_DEFAULTS.get(resource_type, {})),
        unordered=frozenset(UNORDERED_LISTS.get(resource_type, {})),
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _is_user_data(path: str) -> bool:
    return path.endswith(_USER_DATA)


def _plain(value: Any) -> Any:
    """
    A value with each ToBeCreated in it, at any depth, as its text, so a
    list item or a nested property naming one prints and records as JSON.
    """
    if isinstance(value, ToBeCreated):
        return str(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def shown_value(path: str, value: Any) -> str:
    """
    A value as a plan line shows it: User Data as its length, a string in
    single quotes, as the CLI's messages quote one, cut short past 60
    characters, a resource to be created as its name and '(to be created)',
    and anything else as compact JSON.
    """
    if isinstance(value, ToBeCreated):
        return str(value)
    if not isinstance(value, str):
        return json.dumps(
            _plain(value), separators=(",", ":"), ensure_ascii=False, default=str
        )
    if _is_user_data(path):
        return counted(len(value), "character")
    if len(value) > _LONGEST_SHOWN:
        value = value[: _LONGEST_SHOWN - 3] + "..."
    return f"'{value}'"


def _change_line(change: Change) -> str:
    path, before, after = change.path, change.before, change.after
    if path == API_KEY:
        return f"{path}: would be regenerated"
    match change.kind:
        case "cleared":
            return f"{path}: (cleared; was {shown_value(path, before)})"
        case "added":
            return f"{path}: + {shown_value(path, after)}"
        case "removed":
            return f"{path}: - {shown_value(path, before)}"
    if _is_user_data(path) and isinstance(before, str) and isinstance(after, str):
        return f"{path}: changed ({len(before):,} → {counted(len(after), 'character')})"
    return f"{path}: {shown_value(path, before)} → {shown_value(path, after)}"


def _entry_text(entry: PlanEntry) -> str:
    shown_type = RESOURCE_TYPE_NAMES.get(entry.resource_type, entry.resource_type)
    line = f"{_LABELS[entry.action]:<{_LABEL_WIDTH}}  {shown_type}"
    if entry.name is not None:
        line += f" '{entry.name}'"
    if entry.keyring is not None:
        line += f" in Keyring '{entry.keyring}'"
    if entry.id is not None:
        line += f" ({entry.id})"
    if entry.reason is not None:
        line += f": {entry.reason}"
    return "\n".join(
        [line, *(_CHANGE_INDENT + _change_line(change) for change in entry.changes)]
    )


def _recorded_value(path: str, value: Any) -> Any:
    """
    A change's value as '--json' records it: User Data summarised, a
    resource to be created, at any depth, as shown_value() shows it, and
    anything else as it is.
    """
    if _is_user_data(path) and isinstance(value, str):
        return shown_value(path, value)
    return _plain(value)


def _report(entry: PlanEntry) -> None:
    """
    Print one specification's outcome, and record it for '--json'.
    """
    print_info(_entry_text(entry))
    extra: dict[str, Any] = {}
    # An update's changes, or the Allowances a create would replace
    if entry.changes:
        extra["changes"] = [
            {
                "path": change.path,
                "from": _recorded_value(change.path, change.before),
                "to": _recorded_value(change.path, change.after),
            }
            for change in entry.changes
        ]
    if entry.reason is not None:
        extra["reason"] = entry.reason
    if entry.keyring is not None:
        extra["keyring"] = entry.keyring
    record_resource(entry.resource_type, entry.name, entry.id, entry.action, **extra)


def _summary(counts: dict[str, int]) -> str:
    parts = [
        f"{counts[action]:,} {wording}"
        for action, wording in (
            ("create", "new"),
            ("update", "changed"),
            ("unchanged", "unchanged"),
            ("unknown", "unknown"),
            ("failed", "failed"),
        )
        if counts.get(action)
    ]
    return ", ".join(parts) if parts else "Nothing to change"


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def plan_one(
    ctx: RunContext,
    resource_type: str,
    resource: dict,
    source_dir: str | None,
    planned: set[tuple[str, str]],
) -> PlanEntry:
    """
    The outcome of one specification, from its type's planner, which runs
    with print_info() silenced: the creators' preparation it shares says what
    it resolves ("Compute Source Template name 'x' -> ID ..."), which is a
    real run's progress, not the plan's. Warnings still print.
    """
    # The per-type planners, registered as their module is imported; here,
    # since that module imports this one
    from yellowdog_cli.utils import resource_planners  # noqa: F401

    planner = PLANNERS.get(resource_type)
    if planner is None:
        raise ValueError(f"Unknown resource type '{resource_type}'")
    with info_silenced():
        return planner(ctx, resource, source_dir, planned)


def plan_resources(
    ctx: RunContext, specifications: list[dict], options: PlanOptions
) -> None:
    """
    Say what creating the resources 'specifications' describes would change:
    a line per specification, in order, and a summary. A failed
    specification is reported and the rest planned; the failures then raise
    ReportedFailure, as resource_processing.process_each() does. With
    '--fail-on-changes', and no failure, anything to create or update, or
    unknown, exits FAILURE once the plan is printed.
    """
    # The planners' preparation takes the specifications apart, as the
    # creators' does, so they are given a copy, as create_resources() does
    specifications = deepcopy(specifications)
    print_info(f"Plan for {counted(len(specifications), 'resource specification')}")
    planned: set[tuple[str, str]] = set()
    counts: dict[str, int] = {}

    def _plan(resource_type: str, resource: dict) -> None:
        source_dir: str | None = resource.pop(RESOURCE_SOURCE_DIR, None)
        entry = plan_one(ctx, resource_type, resource, source_dir, planned)
        _report(entry)
        counts[entry.action] = counts.get(entry.action, 0) + 1
        if entry.action == "create" and entry.name is not None:
            planned.add((entry.resource_type, entry.name))

    def _record(specification: dict, action: str, error: str) -> None:
        if action == "failed":
            counts["failed"] = counts.get("failed", 0) + 1
        record_specification(specification, action, error)

    # The prepare steps and planners read the plan-shaping options as the
    # creators read them
    create_options = CreateOptions(
        json_output=options.json_output,
        match_allowances_by_description=options.match_allowances_by_description,
        regenerate_app_keys=options.regenerate_app_keys,
    )
    try:
        with options_in_effect(create_options):
            process_each(
                specifications,
                lambda specification: process_specification(specification, _plan),
                describe_specification,
                _record,
                "plan",
            )
    except ReportedFailure:
        print_info(_summary(counts))
        raise

    print_info(_summary(counts))
    if options.fail_on_changes and any(
        counts.get(action) for action in ("create", "update", "unknown")
    ):
        sys.exit(int(ExitCode.FAILURE))
