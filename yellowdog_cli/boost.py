#!/usr/bin/env python3

"""
A script to boost allowances.
"""

from yellowdog_cli.utils.exit_codes import classify
from yellowdog_cli.utils.interactive import confirmed
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.settings import ET_ALLOWANCES, ExitCode
from yellowdog_cli.utils.wrapper import ARGS_PARSER, CLIENT, main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

# Failures of the session rather than of one Allowance: every Allowance after
# the first would fail in the same way, so none is attempted. Each is still a
# per-item failure, exiting 1, as the action commands' failures are
_FAILS_EVERY_ALLOWANCE = frozenset({ExitCode.AUTHENTICATION, ExitCode.CONNECTION})


def _record(allowance: str, outcome: str, error: str | None = None, **extra) -> None:
    record_action(
        allowance,
        ET_ALLOWANCES,
        "boost",
        outcome,
        error,
        hours=ARGS_PARSER.boost_hours,
        **extra,
    )


def _hours(hours: float) -> str:
    """'1 hour', '10 hours', '2.5 hours'."""
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


@main_wrapper
def main() -> None:
    hours = _hours(ARGS_PARSER.boost_hours)
    allowances = _without_duplicates(ARGS_PARSER.allowance_list)
    boosted = skipped = failed = 0

    for index, allowance in enumerate(allowances):
        if get_ydid_type(allowance) != YDIDType.ALLOWANCE:
            print_error(f"Not a valid Allowance ID: '{allowance}'")
            _record(allowance, "failed", "not a valid Allowance ID")
            failed += 1
            continue
        if not confirmed(f"Boost Allowance {allowance} by {hours}?"):
            _record(allowance, "skipped")
            skipped += 1
            continue
        try:
            result = CLIENT.allowances_client.boost_allowance_by_id(
                allowance, ARGS_PARSER.boost_hours
            )
        except Exception as e:
            print_error(f"Unable to boost Allowance {allowance}: {e}")
            _record(allowance, "failed", str(e))
            failed += 1
            if classify(e) in _FAILS_EVERY_ALLOWANCE:
                not_attempted = allowances[index + 1 :]
                if not_attempted:
                    print_warning(
                        f"Not attempting the remaining {len(not_attempted)}"
                        " Allowance(s), which would fail in the same way"
                    )
                for remaining in not_attempted:
                    _record(remaining, "skipped", f"not attempted: {e}")
                skipped += len(not_attempted)
                break
            continue

        remaining_hours = _remaining_hours(result)
        print_info(
            f"Boosted Allowance {allowance} by {hours}"
            + (
                ""
                if remaining_hours is None
                else f" ({_hours(remaining_hours)} remaining)"
            )
        )
        _record(allowance, "boosted", remainingHours=remaining_hours)
        boosted += 1

    if len(allowances) > 1:
        print_info(
            f"Boosted {boosted} of {len(allowances)} Allowances by {hours}"
            f" ({skipped} skipped, {failed} failed)"
        )


# Standalone entry point
if __name__ == "__main__":
    main()
