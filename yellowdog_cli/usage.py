#!/usr/bin/env python3

"""
yd usage: the hours Instances spent in each status over a time window
('--from', '--until'), totalled by namespace or the other keys '--by'
names, from the Platform's compute usage report (utils/usage_report.py).
The report is kept as CSV files in a private temporary directory and used
again for the same window and namespace until '--refresh' fetches it
afresh; the window it covers, when it was fetched and where it is kept are
said above the table. '--json' prints one document holding the same.
"""

import csv
import shlex
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import NotFoundError
from yellowdog_cli.utils.output_style import UNPRICED_TYPES_SHOWN
from yellowdog_cli.utils.printing import (
    counted,
    print_info,
    print_json,
    print_warning,
)
from yellowdog_cli.utils.tables import print_table
from yellowdog_cli.utils.usage_cost import (
    COST_CURRENCY,
    Costing,
    cost_text,
    estimated_cost,
    kept_prices,
    list_prices,
)
from yellowdog_cli.utils.usage_report import (
    STATUS_COLUMNS,
    CreatorNames,
    KeptReport,
    Report,
    UsageGroup,
    counted_places,
    creator_names,
    filter_of,
    grouped_usage,
    namespace_exists,
    reports_kept,
    shown_path,
    size_text,
    usage_report,
)
from yellowdog_cli.utils.usage_text import duration_text, heading
from yellowdog_cli.utils.wrapper import main_wrapper

_SECONDS_PER_HOUR = 3600
_DATEPARSER_SETTINGS = {
    "RETURN_AS_TIMEZONE_AWARE": True,
    "TO_TIMEZONE": "UTC",
    "PREFER_DATES_FROM": "past",
}


@main_wrapper
def main(ctx: RunContext):
    if ctx.args.usage_reports:
        show_reports(ctx)
    else:
        show_usage(ctx)


def reuse_command(kept: KeptReport) -> str:
    """
    The yd usage command that uses a kept report again: its own window, and
    its namespace if it was fetched for one.
    """
    words = ["yd", "usage", "--from", kept.report.from_time]
    words += ["--until", kept.report.until_time]
    if kept.namespace:
        words += ["-n", kept.namespace]
    return " ".join(shlex.quote(word) for word in words)


def show_reports(ctx: RunContext) -> None:
    """
    yd usage --reports: the reports kept for this account and Application,
    the last fetched first, each with the command that uses it again.
    """
    kept = reports_kept(ctx)
    if ctx.args.json_output:
        print_json(
            [
                {
                    "from": item.report.from_time,
                    "until": item.report.until_time,
                    "namespace": item.namespace,
                    "namespaces": item.report.namespaces,
                    "fetched": _iso(item.report.fetched),
                    "lastUsed": _iso(item.last_used),
                    "bytes": item.report.fetched_bytes,
                    "reportFile": str(item.report.path),
                    "command": reuse_command(item),
                }
                for item in kept
            ]
        )
        return
    if not kept:
        print_info("No usage reports are kept for this account and Application")
        return
    print_info(
        f"{counted(len(kept), 'usage report')} kept for this account and"
        " Application, the last fetched first"
    )
    print_table(
        ["#", "From", "Until", "Namespace", "Fetched", "Last Used", "Size"],
        [
            [
                str(number),
                _shown_text(item.report.from_time),
                _shown_text(item.report.until_time),
                item.namespace or "(all)",
                _shown(item.report.fetched),
                _shown(item.last_used),
                (
                    "-"
                    if item.report.fetched_bytes is None
                    else size_text(item.report.fetched_bytes)
                ),
            ]
            for number, item in enumerate(kept, start=1)
        ],
    )
    print_info("Each is used again by its window and namespace:")
    for number, item in enumerate(kept, start=1):
        print_info(f"{number}: {reuse_command(item)}")


def show_usage(ctx: RunContext) -> None:
    """
    Fetch (or reuse) the report for the window and print its totals.
    """
    from_text = ctx.args.usage_from or "7 days ago"
    until_text = ctx.args.usage_until or "now"
    from_time = _parsed("--from", from_text)
    until_time = _parsed("--until", until_text)
    if from_time >= until_time:
        raise ValueError(
            f"The window's start ({_shown(from_time)}) is not before its end"
            f" ({_shown(until_time)})"
        )
    namespace = ctx.args.namespace or None
    by = list(ctx.args.usage_by or ("namespace",))

    report = usage_report(
        ctx,
        from_time,
        until_time,
        namespace,
        refresh=bool(ctx.args.usage_refresh),
    )
    # Where the report came from, said as soon as it is in hand, before
    # any lookups and price searches that follow
    age = "from an earlier run" if report.from_cache else "fetched now"
    when = _shown(report.fetched)
    if report.fetched_bytes is not None:
        when += f", {size_text(report.fetched_bytes)}"
    age += f" ({when})"
    print_info(
        f"{'Reusing report' if report.from_cache else 'Report'} {age},"
        f" in '{shown_path(report.path)}'"
        + ("; '--refresh' fetches it again" if report.from_cache else "")
    )
    if namespace is None and report.namespaces is not None:
        # The Application may read usage only in these (usage_report._fetch())
        print_info(
            f"Reporting on the {counted(len(report.namespaces), 'namespace')}"
            f" this Application can read usage in: {', '.join(report.namespaces)}"
            + (
                f"; not on {', '.join(report.refused)}, where it cannot"
                if report.refused
                else ""
            )
        )
    if (
        namespace
        and not grouped_usage(report, [])
        and not namespace_exists(ctx, namespace)
    ):
        # Nothing ran in it: say whether that is because it does not exist
        raise NotFoundError(f"No namespace '{namespace}' exists")
    where = filter_of(ctx.args.usage_where)
    # The creators' names, read only when asked for, and only once the
    # namespace is known to exist
    creators = None
    if "creator" in by or "creator" in where:
        creators = creator_names(ctx)
        if creators.unreadable:
            print_warning(
                f"Could not read the account's {' or '.join(creators.unreadable)};"
                " their creators are shown by ID"
            )
    costing = _costing(ctx, report, where, creators) if ctx.args.usage_cost else None
    groups = sorted_groups(
        grouped_usage(report, by, where, creators, costing),
        ctx.args.usage_sort or ("total",),
        bool(ctx.args.reverse),
    )
    shown, rest = top_groups(groups, ctx.args.usage_top)

    if ctx.args.json_output:
        print_json(
            {
                "from": report.from_time,
                "until": report.until_time,
                "namespace": namespace,
                "namespaces": report.namespaces,
                "by": by,
                "where": where,
                "fetched": report.fetched.isoformat().replace("+00:00", "Z"),
                "reused": report.from_cache,
                "reportFile": str(report.path),
                "groups": [_group_json(group, costing) for group in shown],
                "total": _total_json(_total_group(groups, {}), len(groups), costing),
                **(
                    {"more": _more_json(rest, len(groups) - len(shown), costing)}
                    if ctx.args.usage_top
                    else {}
                ),
                **(_unpriced_json(costing) if costing is not None else {}),
            }
        )
        return

    if ctx.args.csv_output:
        csv.writer(sys.stdout, lineterminator="\n").writerows(
            csv_rows(by, shown, rest, costing is not None)
        )
        # A partial cost is the number alone in the CSV: what it leaves out
        # is warned of on standard error
        for line in _unpriced_lines(costing):
            print_warning(line)
        if not groups:
            print_warning(_nothing_counted(where))
        return

    # The heading of the table beneath
    scope = f" in namespace '{namespace}'" if namespace else ""
    print_info(
        f"Instance usage{scope} from {_shown_text(report.from_time)} until"
        f" {_shown_text(report.until_time)}, by {', '.join(by)}"
        + (f", where {_filter_text(where)}" if where else "")
    )
    if not groups:
        print_warning(_nothing_counted(where))
        return
    headers = (
        [heading(key) for key in by]
        + [
            "Instances",
            "Running (h:mm)",
            "Stopped (h:mm)",
            "Total (h:mm)",
        ]
        + ([f"Est. cost ({COST_CURRENCY})"] if costing is not None else [])
    )
    rows = [
        [
            *group.keys.values(),
            f"{group.instances:,}",
            duration_text(group.seconds["running"]),
            duration_text(group.seconds["stopped"]),
            duration_text(group.total_seconds),
            *([cost_text(group)] if costing is not None else []),
        ]
        for group in shown + ([rest] if rest is not None else [])
    ]
    print_table(headers, rows)
    for line in _unpriced_lines(costing):
        print_warning(line)
    total = _total_group(groups, {})
    print_info(
        f"Total: {counted(total.instances, 'Instance')},"
        f" {duration_text(total.seconds['running'])} running of"
        f" {duration_text(total.total_seconds)} in all statuses"
        + (_total_cost_text(total) if costing is not None else "")
    )


def _unpriced_lines(costing: Costing | None) -> list[str]:
    """
    A warning for each instance type '--cost' had no price for, with its
    running time, the most first; beyond UNPRICED_TYPES_SHOWN, one line for
    the rest.
    """
    if costing is None:
        return []
    ordered = sorted(costing.unpriced.items(), key=lambda item: (-item[1], item[0]))
    shown, rest = ordered[:UNPRICED_TYPES_SHOWN], ordered[UNPRICED_TYPES_SHOWN:]
    lines = [
        f"No list price for {provider} {region} {instance_type} ({pricing}):"
        f" {duration_text(seconds)} running not costed"
        for (provider, region, instance_type, pricing), seconds in shown
    ]
    if rest:
        lines.append(
            f"No list price for {len(rest):,} more instance types:"
            f" {duration_text(sum(seconds for _, seconds in rest))} running not"
            " costed; '--json' lists them all"
        )
    return lines


def _nothing_counted(where: dict[str, list[str]]) -> str:
    return (
        "No Instances in the window match the filters"
        if where
        else "No Instances ran in the window"
    )


def csv_rows(
    by: list[str],
    groups: list[UsageGroup],
    rest: UsageGroup | None,
    cost: bool,
) -> list[list[str]]:
    """
    '--csv''s rows, the header first: the '--by' keys as '--json' names
    them, the Instances, each status's hours and the total as decimal hours,
    and with '--cost' the estimate, a partial one as the number alone and
    one with nothing priced empty; '--top''s remainder last.
    """
    header = [
        # A creator's ID beside its name, as under '--json', since creators
        # sharing a name are separate rows
        *(
            k
            for key in by
            for k in ((key, "creatorId") if key == "creator" else (key,))
        ),
        "instances",
        *(f"{status}_hours" for status in STATUS_COLUMNS),
        "total_hours",
        *(["estimated_cost"] if cost else []),
    ]
    rows = [header]
    for group in groups + ([rest] if rest is not None else []):
        estimate = estimated_cost(group) if cost else None
        rows.append(
            [
                *(
                    v
                    for key, value in group.keys.items()
                    for v in (
                        (value, group.creator_id or "")
                        if key == "creator"
                        else (value,)
                    )
                ),
                str(group.instances),
                *(
                    str(round(group.seconds[status] / _SECONDS_PER_HOUR, 3))
                    for status in STATUS_COLUMNS
                ),
                str(round(group.total_seconds / _SECONDS_PER_HOUR, 3)),
                *(
                    []
                    if not cost
                    else ["" if estimate is None else str(round(estimate, 2))]
                ),
            ]
        )
    return rows


# The '--sort' keys other than the '--by' keys, each a group's value, the
# most first; None for a group without one (a cost with nothing priced),
# which sorted_groups() puts last
_SORT_VALUES: dict[str, Callable[[UsageGroup], float | None]] = {
    "instances": lambda group: group.instances,
    "running": lambda group: group.seconds["running"],
    "stopped": lambda group: group.seconds["stopped"],
    "total": lambda group: group.total_seconds,
    "cost": estimated_cost,
}


def sorted_groups(
    groups: list[UsageGroup], sort: tuple[str, ...], reverse: bool
) -> list[UsageGroup]:
    """
    The groups ordered by each '--sort' key in turn, the first the most
    significant: a '--by' key's value alphabetically, any other key the
    most first, '--reverse' inverting both. A group without a value for a
    key goes after those with one whichever the direction, and ties keep
    grouped_usage()'s order: one stable sort per key, from the least
    significant to the most.
    """
    ordered = list(groups)
    for name in reversed(sort):
        value = _sort_value(name)
        present = [group for group in ordered if value(group) is not None]
        present.sort(key=value, reverse=(name in _SORT_VALUES) != reverse)
        ordered = present + [group for group in ordered if value(group) is None]
    return ordered


def _sort_value(name: str) -> Callable[[UsageGroup], Any]:
    """
    A '--sort' key's value for a group: a '--by' key's value, or one of
    _SORT_VALUES.
    """
    return _SORT_VALUES.get(name) or (lambda group: group.keys[name])


def top_groups(
    groups: list[UsageGroup], top: int | None
) -> tuple[list[UsageGroup], UsageGroup | None]:
    """
    The first 'top' groups, and the rest summed into one group whose first
    key reads '(<n> more)' and whose others are blank; None for the rest
    when nothing is cut.
    """
    if not top or len(groups) <= top:
        return groups, None
    shown, cut = groups[:top], groups[top:]
    first, *others = cut[0].keys
    rest = _total_group(
        cut, {first: f"({len(cut):,} more)", **dict.fromkeys(others, "")}
    )
    return shown, rest


def _total_group(groups: list[UsageGroup], keys: dict[str, str]) -> UsageGroup:
    """
    The groups summed into one, holding these keys: the figures of the
    '--top' remainder, the total line and the document's 'total'.
    """
    total = UsageGroup(keys=keys)
    for group in groups:
        total.instances += group.instances
        for status, seconds in group.seconds.items():
            total.seconds[status] += seconds
        total.cost += group.cost
        total.priced_seconds += group.priced_seconds
        total.unpriced_seconds += group.unpriced_seconds
    return total


def _total_json(total: UsageGroup, count: int, costing: Costing | None) -> dict:
    """
    The document's 'total': every group, those '--top' cut included.
    """
    return {"groups": count, **_group_json(total, costing)}


def _more_json(
    rest: UsageGroup | None, count: int, costing: Costing | None
) -> dict | None:
    """
    '--top''s remainder in the document: the groups cut and their sums.
    """
    if rest is None:
        return None
    summed = _group_json(rest, costing)
    for key in rest.keys:
        summed.pop(key, None)
    summed.pop("creatorId", None)
    return {"groups": count, **summed}


def _costing(
    ctx: RunContext,
    report: Report,
    where: dict[str, list[str]],
    creators: CreatorNames | None,
) -> Costing:
    """
    The prices '--cost' needs, for the places the Instances counted ran in,
    with a warning for each place whose prices could not be read, whose
    Instances go unpriced, or one warning when the Application may not read
    cloud prices at all.
    """
    places = counted_places(report, where, creators)
    kept: dict = {}
    missing = places
    if not ctx.args.usage_refresh:
        kept, missing = kept_prices(ctx, places)
    if kept_places := places - missing:
        print_info(
            f"Reusing list prices for {_regions_text(kept_places)} from the last"
            " 24 hours; '--refresh' fetches them again"
        )
    if missing:
        # The searches take a second or so each: say what the pause is
        print_info(f"Fetching list prices for {_regions_text(missing)}")
    found = list_prices(ctx, missing)
    found.prices.update(kept)
    if found.refused:
        print_warning(
            "This Application may not read cloud prices; no cost is estimated"
        )
    else:
        for provider, region in found.unreadable:
            print_warning(
                f"Could not read the list prices in {provider} {region}; its"
                " Instances are not costed"
            )
    return Costing(found.prices, found.unreadable, found.refused)


def _regions_text(places: set[tuple[str, str]]) -> str:
    """
    '2 regions (AWS eu-west-2, OCI uk-london-1)'.
    """
    names = ", ".join(f"{provider} {region}" for provider, region in sorted(places))
    return f"{counted(len(places), 'region')} ({names})"


def _total_cost_text(total: UsageGroup) -> str:
    """
    The total line's estimate: ', est. $12.34 at list prices', with a '+'
    when some running time had no price.
    """
    cost = estimated_cost(total)
    if cost is None:
        return ", no running time priced at list prices"
    return f", est. ${cost:,.2f}{'+' if total.unpriced_seconds else ''} at list prices"


def _parsed(flag: str, text: str) -> datetime:
    from dateparser import parse as date_parse

    parsed = date_parse(text, settings=_DATEPARSER_SETTINGS)  # type: ignore[arg-type]
    if parsed is None:
        raise ValueError(f"Unable to read {flag} '{text}' as a date and time")
    return parsed


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _shown(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _shown_text(iso: str) -> str:
    """
    A time from the report ('2026-11-12T07:46:44.428279Z') as the summary
    shows it, or as it is if it cannot be read.
    """
    try:
        return _shown(datetime.fromisoformat(iso.replace("Z", "+00:00")))
    except ValueError:
        return iso


def _filter_text(where: dict[str, list[str]]) -> str:
    """
    The filters as the summary says them: 'provider=aws or azure, pricing=spot'.
    """
    return ", ".join(
        f"{key}={' or '.join(patterns)}" for key, patterns in where.items()
    )


def _unpriced_json(costing: Costing) -> dict:
    """
    The document's cost keys: the currency, and what had no price.
    """
    return {
        "currency": COST_CURRENCY,
        "pricesRefused": costing.refused,
        "unreadablePrices": [
            {"provider": provider, "region": region}
            for provider, region in costing.unreadable
        ],
        "unpriced": [
            {
                "provider": provider,
                "region": region,
                "instanceType": instance_type,
                "pricing": pricing,
                "runningHours": round(seconds / _SECONDS_PER_HOUR, 3),
            }
            for (provider, region, instance_type, pricing), seconds in sorted(
                costing.unpriced.items()
            )
        ],
    }


def _group_json(group: UsageGroup, costing: Costing | None = None) -> dict:
    keys: dict = {}
    for key, value in group.keys.items():
        keys[key] = value
        if key == "creator":
            # The ID too, for a script to join on: the name is for reading
            keys["creatorId"] = group.creator_id
    return {
        **keys,
        "instances": group.instances,
        "hours": {
            **{
                status: round(group.seconds[status] / _SECONDS_PER_HOUR, 3)
                for status in STATUS_COLUMNS
            },
            "total": round(group.total_seconds / _SECONDS_PER_HOUR, 3),
        },
        # Exact: the report's seconds, which 'hours' rounds
        "seconds": {
            **{status: round(group.seconds[status]) for status in STATUS_COLUMNS},
            "total": round(group.total_seconds),
        },
        **(_cost_json(group) if costing is not None else {}),
    }


def _cost_json(group: UsageGroup) -> dict:
    cost = estimated_cost(group)
    return {
        "estimatedCost": None if cost is None else round(cost, 2),
        "unpricedRunningHours": round(group.unpriced_seconds / _SECONDS_PER_HOUR, 3),
    }


if __name__ == "__main__":
    main()
