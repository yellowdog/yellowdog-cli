"""
The rules the action commands share for acting on targets, in one place:
yd-start, yd-hold and yd-finish (start_hold_common.py), yd-compute-stop,
-start, -restart and -deprovision and yd-terminate (compute_action_common.py),
yd-cancel,
yd-shutdown and yd-token.

An action takes its explicit targets in two passes. resolve_targets() turns
each argument, in the order given and each once, into an Item: what it
names, as its '--json' record names it. A target that cannot be acted on is
reported and recorded -- 'failed' (not found, ambiguous) or 'skipped' (in
another state) -- by raising Unresolved. What remains is confirmed once
(confirm_items(), which records it all as skipped if declined), then acted
on by carry_out(), a Unit at a time: one Item, or several acted on in one
call (a Compute Requirement's Instances). A listing (the tag, or glob
patterns) skips the first pass and goes straight to carry_out().

In either pass, a failure every later call would repeat
(exit_codes.SESSION_FAILURES: authentication, connection) stops the run:
what has not yet been attempted is recorded as skipped, 'not attempted',
and ReportedFailure is raised with the cause, for the wrapper to exit by.
A Unit that reports and records its own failures, as yd-shutdown's do,
raises SessionStop to stop the run the same way.

Recording is the command's own: every function takes a Record, called as
record(entity, entity_type, outcome, error), which names the action.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from typing import Any, NoReturn

from yellowdog_cli.utils.exit_codes import SESSION_FAILURES, ReportedFailure, classify
from yellowdog_cli.utils.interactive import confirmed
from yellowdog_cli.utils.printing import print_error, print_warning

# record(entity, entity_type, outcome, error): the command's '--json' record
Record = Callable[[object, str, str, "str | None"], None]

SKIPPED = "skipped"
FAILED = "failed"


@dataclass(frozen=True)
class Item:
    """
    Something to act on: 'entity', as its record names it, of 'entity_type';
    'key' identifies it, so that a target named twice (by its name and its
    ID) is acted on once; 'value' is what the command needs to act on it.
    """

    entity: object
    entity_type: str
    key: Hashable
    value: Any = None


@dataclass
class Unit:
    """
    One call's worth of work: 'act' does it, recording its own success, and
    raises on failure, when 'failure' words the error and each of 'items' is
    recorded as failed.
    """

    items: list[Item]
    act: Callable[[], None]
    failure: Callable[[Exception], str]


class Unresolved(Exception):
    """
    A target that cannot be acted on, for a reason the user should see: the
    message is printed and recorded. 'outcome' is 'failed' unless the target
    exists but is in another state ('skipped'), in which case 'entity' is
    what was found, to be recorded by its ID and name.
    """

    def __init__(self, message: str, outcome: str = FAILED, entity: object = None):
        super().__init__(message)
        self.outcome = outcome
        self.entity = entity


class SessionStop(Exception):
    """
    Raised by a Unit that has reported and recorded a session failure itself,
    so that nothing further is attempted.
    """

    def __init__(self, cause: Exception):
        super().__init__(str(cause))
        self.cause = cause


@dataclass
class _Resolution:
    items: list[Item] = field(default_factory=list)
    keys: set[Hashable] = field(default_factory=set)

    def add(self, item: Item) -> None:
        if item.key not in self.keys:
            self.keys.add(item.key)
            self.items.append(item)


# How a command orders the Items it has resolved: in the order it will act on
# them, which is also the order they are recorded in if the run stops
Order = Callable[[list[Item]], list[Item]]


def by_type(*type_order: str) -> Order:
    """
    An Order grouping the items by entity type in 'type_order' (Work
    Requirements, then Tasks), each group in the order its items were given.
    """
    return lambda items: sorted(
        items, key=lambda item: type_order.index(item.entity_type)
    )


def warn_not_attempted(count: int) -> None:
    if count:
        print_warning(
            f"Not attempting the remaining {count} item(s),"
            " which would fail in the same way"
        )


def _not_attempted(cause: Exception) -> str:
    return f"not attempted: {cause}"


def resolve_targets(
    targets: list[str],
    resolve: Callable[[str], Item],
    describe: Callable[[str], tuple[object, str]],
    record: Record,
    verb: str,
    order: Order,
) -> list[Item]:
    """
    Resolve each target, in the order given and each once, to the Item it
    names: 'resolve' returns it, or raises Unresolved if it cannot be acted
    on; 'describe' gives a target's entity and type as recorded before it is
    resolved. Returns the Items, each once, in 'order'.
    """
    unique = list(dict.fromkeys(targets))
    resolution = _Resolution()
    for index, target in enumerate(unique):
        entity, entity_type = describe(target)
        try:
            item = resolve(target)
        except Unresolved as e:
            (print_warning if e.outcome == SKIPPED else print_error)(str(e))
            record(e.entity or entity, entity_type, e.outcome, str(e))
            continue
        except Exception as e:
            print_error(f"Unable to {verb} '{target}': {e}")
            record(entity, entity_type, FAILED, str(e))
            if classify(e) in SESSION_FAILURES:
                remaining = unique[index + 1 :]
                warn_not_attempted(len(remaining) + len(resolution.items))
                for resolved in order(resolution.items):
                    record(
                        resolved.entity,
                        resolved.entity_type,
                        SKIPPED,
                        _not_attempted(e),
                    )
                for target_left in remaining:
                    entity_left, type_left = describe(target_left)
                    record(entity_left, type_left, SKIPPED, _not_attempted(e))
                raise ReportedFailure(e)
            continue
        resolution.add(item)
    return order(resolution.items)


def confirm_items(question: str, items: list[Item], record: Record) -> bool:
    """
    Ask once whether to act on the items, recording each as skipped if not.
    """
    if confirmed(question):
        return True
    for item in items:
        record(item.entity, item.entity_type, SKIPPED, None)
    return False


def carry_out(units: list[Unit], record: Record) -> list[Unit]:
    """
    Do each unit of work in turn, returning those done. A unit that fails is
    reported and its items recorded as failed, and the next is done, unless
    the failure is the session's.
    """
    done: list[Unit] = []
    for index, unit in enumerate(units):
        try:
            unit.act()
        except SessionStop as stop:
            _stop(units[index + 1 :], stop.cause, record)
        except Exception as e:
            print_error(unit.failure(e))
            for item in unit.items:
                record(item.entity, item.entity_type, FAILED, str(e))
            if classify(e) in SESSION_FAILURES:
                _stop(units[index + 1 :], e, record)
        else:
            done.append(unit)
    return done


def _stop(not_attempted: list[Unit], cause: Exception, record: Record) -> NoReturn:
    warn_not_attempted(sum(len(unit.items) for unit in not_attempted))
    for unit in not_attempted:
        for item in unit.items:
            record(item.entity, item.entity_type, SKIPPED, _not_attempted(cause))
    raise ReportedFailure(cause)
