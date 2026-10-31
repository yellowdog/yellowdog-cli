"""
The run yd-create and yd-remove share: each item (a resource specification,
or for yd-remove a YellowDog ID) processed in turn, a failure
printed once and recorded, the run carried on past it, and stopped by a
failure every later request would repeat (an authentication or connection
failure), the items not attempted then recorded as skipped. The run exits
with the code its failures share, or FAILURE for different causes.
"""

import logging
from collections.abc import Callable, Sequence
from typing import TypeVar

from yellowdog_cli.utils.exit_codes import SESSION_FAILURES, ReportedFailure, classify
from yellowdog_cli.utils.failure_advice import advise
from yellowdog_cli.utils.interactive import NoAnswerToPrompt
from yellowdog_cli.utils.load_resources import (
    RESOURCE_SOURCE_DIR,
    resource_display_name,
)
from yellowdog_cli.utils.printing import counted, print_error
from yellowdog_cli.utils.property_names import PROP_RESOURCE
from yellowdog_cli.utils.results import record_resource

_LOG = logging.getLogger(__name__)

Item = TypeVar("Item")


def missing_property(e: KeyError) -> ValueError:
    """
    The error for a required property a specification lacks; 'e' is the
    KeyError its lookup raised, whose str() is the quoted property name.
    """
    return ValueError(f"Expected property {e} to be defined")


def process_each(
    items: Sequence[Item],
    act: Callable[[Item], None],
    describe: Callable[[Item], str],
    record: Callable[[Item, str, str], None],
    verb: str,
) -> None:
    """
    Apply 'act' to each item. A failure is printed once, as 'Failed to
    <verb> <describe(item)>: <error>', and recorded by record(item,
    'failed', error); a session failure records every item after it with
    record(item, 'skipped', 'not attempted: ...') and stops the run, as does
    a prompt that finds stdin at its end (NoAnswerToPrompt, re-raised for the
    wrapper to report once), since every later prompt would find the same.
    Raises ReportedFailure at the end if anything failed.
    """
    _LOG.debug(
        "To %s, in this order: %s",
        verb,
        "; ".join(f"{n}. {describe(item)}" for n, item in enumerate(items, 1)),
    )
    failures: list[Exception] = []
    for index, item in enumerate(items):
        try:
            act(item)
        except NoAnswerToPrompt as e:
            record(item, "failed", str(e))
            for rest in items[index + 1 :]:
                record(rest, "skipped", f"not attempted: {e}")
            raise
        except Exception as e:
            _LOG.debug("Failed to %s %s", verb, describe(item), exc_info=True)
            print_error(f"Failed to {verb} {describe(item)}: {e}")
            advise(e)
            record(item, "failed", str(e))
            failures.append(e)
            if classify(e) in SESSION_FAILURES:
                # Every later request would fail the same way
                for rest in items[index + 1 :]:
                    record(rest, "skipped", f"not attempted: {e}")
                raise ReportedFailure(e)

    if failures:
        message = f"{counted(len(failures), 'resource')} failed to {verb}"
        print_error(message)
        codes = {classify(e) for e in failures}
        # The shared cause's exit code, or FAILURE for different causes
        raise ReportedFailure(failures[0] if len(codes) == 1 else RuntimeError(message))


def process_specification(
    specification: dict, process: Callable[[str, dict], None]
) -> None:
    """
    process(resource_type, resource) for one specification, 'resource' being
    it less its 'resource' property; a specification without one fails.
    """
    resource_type = specification.get(PROP_RESOURCE)
    if resource_type is None:
        # Without the source directory load_resources.py stamps on it
        shown = {k: v for k, v in specification.items() if k != RESOURCE_SOURCE_DIR}
        raise ValueError(
            f"Missing required '{PROP_RESOURCE}' property in the following"
            f" resource specification: {shown}"
        )
    process(
        resource_type,
        {k: v for k, v in specification.items() if k != PROP_RESOURCE},
    )


def describe_specification(specification: dict) -> str:
    """
    A specification as a failure names it: its type and name, where it has them.
    """
    resource_type = specification.get(PROP_RESOURCE)
    name = resource_display_name(resource_type, specification)
    if resource_type is None:
        return "resource" if name is None else f"resource '{name}'"
    return resource_type if name is None else f"{resource_type} '{name}'"


def record_specification(specification: dict, action: str, error: str) -> None:
    """
    Record a specification's resource that failed, or was not attempted.
    """
    resource_type = specification.get(PROP_RESOURCE)
    record_resource(
        resource_type,
        resource_display_name(resource_type, specification),
        None,
        action,
        error=error,
    )


def process_resources(
    specifications: Sequence[dict],
    process: Callable[[str, dict], None],
    verb: str,
    record_outcomes: bool = True,
) -> None:
    """
    process(resource_type, resource) for each resource specification, as
    process_each() and process_specification() do. 'record_outcomes' false
    (a dry run, whose '--json' document is the specifications) records
    neither failures nor the items not attempted.
    """

    def _record(specification: dict, action: str, error: str) -> None:
        if record_outcomes:
            record_specification(specification, action, error)

    process_each(
        specifications,
        lambda specification: process_specification(specification, process),
        describe_specification,
        _record,
        verb,
    )
