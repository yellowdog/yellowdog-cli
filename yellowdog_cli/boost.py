#!/usr/bin/env python3

"""
A script to boost allowances, through action_runner.py's rules, as the other
action commands are.

Each Allowance ID (checked to be one as the command line is parsed) is first
fetched, in the order given and each once, so that a missing one fails
before anything is boosted and the confirmation can show each Allowance's
description, an Allowance having no name. The rest are confirmed once and
boosted. A failure every later call would repeat (exit_codes.SESSION_FAILURES:
authentication, connection) stops the run, and the Allowances not yet
attempted are recorded as skipped.
"""

from typing import Any, cast

from yellowdog_client.model import Allowance

from yellowdog_cli.utils.action_runner import (
    Item,
    Record,
    Unit,
    Unresolved,
    carry_out,
    confirm_items,
    resolve_targets,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import ET_ALLOWANCES
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.printing import print_info
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.wrapper import main_wrapper


def _record(
    ctx: RunContext,
    entity: object,
    outcome: str,
    error: str | None = None,
    **extra: Any,
) -> None:
    """
    Record an outcome for '--json': 'entity' is the Allowance's ID until it
    has been fetched, then the Allowance, whose description is added.
    """
    if not isinstance(entity, str):
        extra = {"description": getattr(entity, "description", None), **extra}
    record_action(
        entity,
        ET_ALLOWANCES,
        "boost",
        outcome,
        error,
        hours=ctx.args.boost_hours,
        **extra,
    )


def _recorder(ctx: RunContext) -> Record:
    """
    The record, as action_runner calls it.
    """
    return lambda entity, _type, outcome, error: _record(ctx, entity, outcome, error)


def _hours(hours: float) -> str:
    """
    '1 hour', '10 hours', '2.50 hours': the hours to boost by are whole, but
    an Allowance's remaining hours need not be.
    """
    number = f"{hours:,.0f}" if float(hours).is_integer() else f"{hours:,.2f}"
    return f"{number} hour{'' if hours == 1 else 's'}"


def _remaining_hours(allowance: object) -> float | None:
    """
    The boosted Allowance's remaining hours, if the Platform gave them.
    """
    remaining = getattr(allowance, "remainingHours", None)
    if isinstance(remaining, (int, float)) and not isinstance(remaining, bool):
        return remaining
    return None


def _label(allowance: Allowance) -> str:
    description = allowance.description
    return f"{allowance.id} ('{description}')" if description else str(allowance.id)


def _resolve(ctx: RunContext, allowance_id: str) -> Item:
    """
    The Allowance an ID names, raising Unresolved if there is none.
    """
    try:
        allowance = ctx.client.allowances_client.get_allowance_by_id(allowance_id)
    except Exception as e:
        if is_http_not_found(e):
            raise Unresolved(f"Cannot find Allowance {allowance_id}") from e
        raise
    return Item(allowance, ET_ALLOWANCES, allowance_id, allowance)


def _boost(ctx: RunContext, allowance: Allowance, hours: str) -> None:
    """
    Boost one Allowance, reporting and recording it. Raises on failure, for
    carry_out() to record.
    """
    result = ctx.client.allowances_client.boost_allowance_by_id(
        cast(str, allowance.id), ctx.args.boost_hours
    )
    remaining_hours = _remaining_hours(result)
    print_info(
        f"Boosted Allowance {_label(allowance)} by {hours}"
        + ("" if remaining_hours is None else f" ({_hours(remaining_hours)} remaining)")
    )
    _record(ctx, allowance, "boosted", remainingHours=remaining_hours)


@main_wrapper
def main(ctx: RunContext) -> None:
    hours = _hours(ctx.args.boost_hours)
    allowance_ids = list(dict.fromkeys(ctx.args.allowance_list))
    record = _recorder(ctx)
    items = resolve_targets(
        allowance_ids,
        resolve=lambda allowance_id: _resolve(ctx, allowance_id),
        describe=lambda allowance_id: (allowance_id, ET_ALLOWANCES),
        record=record,
        verb="boost",
        order=lambda items: items,
    )
    if not items or not confirm_items(
        f"Boost {len(items)} Allowance(s) by {hours} ("
        + ", ".join(_label(item.value) for item in items)
        + ")?",
        items,
        record,
    ):
        print_info("No Allowances boosted")
        return

    done = carry_out(
        [
            Unit(
                [item],
                act=lambda allowance=item.value: _boost(ctx, allowance, hours),
                failure=lambda e, allowance=item.value: (
                    f"Unable to boost Allowance {_label(allowance)}: {e}"
                ),
            )
            for item in items
        ],
        record,
    )

    if len(allowance_ids) > 1:
        print_info(
            f"Boosted {len(done)} of {len(allowance_ids)} Allowances by {hours}"
            f" ({len(allowance_ids) - len(items)} not found or unavailable,"
            f" {len(items) - len(done)} failed)"
        )


# Entry point
if __name__ == "__main__":
    main()
