#!/usr/bin/env python3

"""
A script to boost allowances.

Each Allowance ID (checked to be one as the command line is parsed) is first
fetched, in the order given, so that a missing one fails before anything is
boosted and the confirmation can show each Allowance's description, an
Allowance having no name. The rest are confirmed once and boosted. A failure
every later call would repeat (exit_codes.SESSION_FAILURES: authentication,
connection) stops the run, and the Allowances not yet attempted are recorded
as skipped.
"""

from typing import Any

from yellowdog_client.model import Allowance

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import ET_ALLOWANCES
from yellowdog_cli.utils.exit_codes import SESSION_FAILURES, ReportedFailure, classify
from yellowdog_cli.utils.interactive import confirmed
from yellowdog_cli.utils.misc_utils import is_http_not_found
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.wrapper import main_wrapper


def _record(
    ctx: RunContext,
    allowance_id: str,
    outcome: str,
    error: str | None = None,
    allowance: Allowance | None = None,
    **extra: Any,
) -> None:
    """
    Record an outcome for '--json', with the Allowance's description once
    it has been fetched.
    """
    if allowance is not None:
        extra = {"description": allowance.description, **extra}
    record_action(
        allowance_id,
        ET_ALLOWANCES,
        "boost",
        outcome,
        error,
        hours=ctx.args.boost_hours,
        **extra,
    )


def _hours(hours: float) -> str:
    """
    '1 hour', '10 hours', '2.50 hours': the hours to boost by are whole, but
    an Allowance's remaining hours need not be.
    """
    number = f"{hours:,.0f}" if float(hours).is_integer() else f"{hours:,.2f}"
    return f"{number} hour{'' if hours == 1 else 's'}"


def _without_duplicates(allowances: list[str]) -> list[str]:
    """
    The Allowance IDs in the order given, each once: a repeated ID would
    otherwise be boosted again.
    """
    unique = list(dict.fromkeys(allowances))
    if len(unique) < len(allowances):
        print_warning(
            f"Ignoring {len(allowances) - len(unique)} duplicate Allowance ID(s)"
        )
    return unique


def _remaining_hours(allowance: object) -> float | None:
    """The boosted Allowance's remaining hours, if the Platform gave them."""
    remaining = getattr(allowance, "remainingHours", None)
    if isinstance(remaining, (int, float)) and not isinstance(remaining, bool):
        return remaining
    return None


def _label(allowance_id: str, allowance: Allowance) -> str:
    description = allowance.description
    return f"{allowance_id} ('{description}')" if description else allowance_id


def _confirmation(hours: str, found: list[tuple[str, Allowance]]) -> str:
    return (
        f"Boost {len(found)} Allowance(s) by {hours} ("
        + ", ".join(_label(a, allowance) for a, allowance in found)
        + ")?"
    )


def _stop(
    ctx: RunContext, e: Exception, not_attempted: list[tuple[str, Allowance | None]]
) -> None:
    """
    Having recorded a failure: if it is the session's, record the Allowances
    not yet attempted as skipped and raise ReportedFailure, which exits with
    the failure's own code.
    """
    if classify(e) not in SESSION_FAILURES:
        return
    if not_attempted:
        print_warning(
            f"Not attempting the remaining {len(not_attempted)}"
            " Allowance(s), which would fail in the same way"
        )
    for allowance_id, allowance in not_attempted:
        _record(ctx, allowance_id, "skipped", f"not attempted: {e}", allowance)
    raise ReportedFailure(e)


@main_wrapper
def main(ctx: RunContext) -> None:
    hours = _hours(ctx.args.boost_hours)
    allowance_ids = _without_duplicates(ctx.args.allowance_list)

    # Fetch each, in the order given
    found: list[tuple[str, Allowance]] = []
    for index, allowance_id in enumerate(allowance_ids):
        try:
            found.append(
                (
                    allowance_id,
                    ctx.client.allowances_client.get_allowance_by_id(allowance_id),
                )
            )
        except Exception as e:
            error = "not found" if is_http_not_found(e) else str(e)
            print_error(f"Unable to boost Allowance {allowance_id}: {error}")
            _record(ctx, allowance_id, "failed", error)
            _stop(
                ctx,
                e,
                [*found, *((a, None) for a in allowance_ids[index + 1 :])],
            )

    if not found:
        print_info("No Allowances boosted")
        return

    if not confirmed(_confirmation(hours, found)):
        for allowance_id, allowance in found:
            _record(ctx, allowance_id, "skipped", allowance=allowance)
        print_info("No Allowances boosted")
        return

    boosted = failed = 0
    for index, (allowance_id, allowance) in enumerate(found):
        try:
            result = ctx.client.allowances_client.boost_allowance_by_id(
                allowance_id, ctx.args.boost_hours
            )
        except Exception as e:
            print_error(
                f"Unable to boost Allowance {_label(allowance_id, allowance)}: {e}"
            )
            _record(ctx, allowance_id, "failed", str(e), allowance)
            failed += 1
            _stop(ctx, e, list(found[index + 1 :]))
            continue

        remaining_hours = _remaining_hours(result)
        print_info(
            f"Boosted Allowance {_label(allowance_id, allowance)} by {hours}"
            + (
                ""
                if remaining_hours is None
                else f" ({_hours(remaining_hours)} remaining)"
            )
        )
        _record(
            ctx,
            allowance_id,
            "boosted",
            allowance=allowance,
            remainingHours=remaining_hours,
        )
        boosted += 1

    if len(allowance_ids) > 1:
        print_info(
            f"Boosted {boosted} of {len(allowance_ids)} Allowances by {hours}"
            f" ({len(allowance_ids) - len(found)} not found or unavailable,"
            f" {failed} failed)"
        )


# Entry point
if __name__ == "__main__":
    main()
