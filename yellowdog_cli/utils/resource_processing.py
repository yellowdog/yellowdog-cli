"""
The run yd-create and yd-remove share: each item (a resource specification,
or with 'yd-remove --ids' a YellowDog ID) processed in turn, a failure
printed once and recorded, the run carried on past it, and stopped by a
failure every later request would repeat (an authentication or connection
failure), the items not attempted then recorded as skipped. The run exits
with the code its failures share, or FAILURE for different causes.
"""

from collections.abc import Callable, Sequence
from typing import TypeVar

from yellowdog_cli.utils.exit_codes import SESSION_FAILURES, ReportedFailure, classify
from yellowdog_cli.utils.load_resources import resource_display_name
from yellowdog_cli.utils.printing import print_error
from yellowdog_cli.utils.results import record_resource
from yellowdog_cli.utils.settings import PROP_RESOURCE

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
    record(item, 'skipped', 'not attempted: ...') and stops the run. Raises
    ReportedFailure at the end if anything failed.
    """
    failures: list[Exception] = []
    for index, item in enumerate(items):
        try:
            act(item)
        except Exception as e:
            print_error(f"Failed to {verb} {describe(item)}: {e}")
            record(item, "failed", str(e))
            failures.append(e)
            if classify(e) in SESSION_FAILURES:
                # Every later request would fail the same way
                for rest in items[index + 1 :]:
                    record(rest, "skipped", f"not attempted: {e}")
                raise ReportedFailure(e)

    if failures:
        message = f"{len(failures)} resource(s) failed to {verb}"
        print_error(message)
        codes = {classify(e) for e in failures}
        # The shared cause's exit code, or FAILURE for different causes
        raise ReportedFailure(failures[0] if len(codes) == 1 else RuntimeError(message))


def process_resources(
    specifications: Sequence[dict],
    process: Callable[[str, dict], None],
    verb: str,
    record_outcomes: bool = True,
) -> None:
    """
    process(resource_type, resource) for each resource specification, as
    process_each(): 'resource' is the specification less its 'resource'
    property, and a specification without one fails. 'record_outcomes'
    false (a dry run, whose '--json' document is the specifications) records
    neither failures nor the items not attempted.
    """

    def _act(specification: dict) -> None:
        resource_type = specification.get(PROP_RESOURCE)
        if resource_type is None:
            raise ValueError(
                f"Missing required '{PROP_RESOURCE}' property in the following"
                f" resource specification: {specification}"
            )
        process(
            resource_type,
            {k: v for k, v in specification.items() if k != PROP_RESOURCE},
        )

    def _describe(specification: dict) -> str:
        resource_type = specification.get(PROP_RESOURCE)
        name = resource_display_name(resource_type, specification)
        if resource_type is None:
            return "resource" if name is None else f"resource '{name}'"
        return resource_type if name is None else f"{resource_type} '{name}'"

    def _record(specification: dict, action: str, error: str) -> None:
        if not record_outcomes:
            return
        resource_type = specification.get(PROP_RESOURCE)
        record_resource(
            resource_type,
            resource_display_name(resource_type, specification),
            None,
            action,
            error=error,
        )

    process_each(specifications, _act, _describe, _record, verb)
