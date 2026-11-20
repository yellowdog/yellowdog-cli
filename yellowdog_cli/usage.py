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

from datetime import datetime, timezone

from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.exit_codes import NotFoundError
from yellowdog_cli.utils.printing import (
    counted,
    print_info,
    print_json,
    print_warning,
)
from yellowdog_cli.utils.tables import print_table
from yellowdog_cli.utils.usage_report import (
    STATUS_COLUMNS,
    UsageGroup,
    creator_names,
    filter_of,
    grouped_usage,
    namespace_exists,
    shown_path,
    size_text,
    usage_report,
)
from yellowdog_cli.utils.wrapper import main_wrapper

_SECONDS_PER_HOUR = 3600
_SECONDS_PER_MINUTE = 60
_DATEPARSER_SETTINGS = {
    "RETURN_AS_TIMEZONE_AWARE": True,
    "TO_TIMEZONE": "UTC",
    "PREFER_DATES_FROM": "past",
}


@main_wrapper
def main(ctx: RunContext):
    show_usage(ctx)


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
        from_text,
        until_text,
        namespace,
        refresh=bool(ctx.args.usage_refresh),
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
    groups = grouped_usage(report, by, where, creators)

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
                "reportFile": str(report.path),
                "groups": [_group_json(group) for group in groups],
            }
        )
        return

    # Where the report came from, then the heading of the table beneath it
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
    scope = f" in namespace '{namespace}'" if namespace else ""
    print_info(
        f"Instance usage{scope} from {_shown_text(report.from_time)} until"
        f" {_shown_text(report.until_time)}, by {', '.join(by)}"
        + (f", where {_filter_text(where)}" if where else "")
    )
    if not groups:
        print_warning(
            "No Instances in the window match the filters"
            if where
            else "No Instances ran in the window"
        )
        return
    headers = [key.replace("-", " ").capitalize() for key in by] + [
        "Instances",
        "Running (h:mm)",
        "Stopped (h:mm)",
        "Total (h:mm)",
    ]
    rows = [
        [
            *group.keys.values(),
            f"{group.instances:,}",
            duration_text(group.seconds["running"]),
            duration_text(group.seconds["stopped"]),
            duration_text(group.total_seconds),
        ]
        for group in groups
    ]
    print_table(headers, rows)
    instances = sum(group.instances for group in groups)
    running = sum(group.seconds["running"] for group in groups)
    total = sum(group.total_seconds for group in groups)
    print_info(
        f"Total: {counted(instances, 'Instance')}, {duration_text(running)}"
        f" running of {duration_text(total)} in all statuses"
    )


def _parsed(flag: str, text: str) -> datetime:
    from dateparser import parse as date_parse

    parsed = date_parse(text, settings=_DATEPARSER_SETTINGS)  # type: ignore[arg-type]
    if parsed is None:
        raise ValueError(f"Unable to read {flag} '{text}' as a date and time")
    return parsed


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
    The filters as the summary says them: 'provider=aws or azure, spot=spot'.
    """
    return ", ".join(
        f"{key}={' or '.join(patterns)}" for key, patterns in where.items()
    )


def duration_text(seconds: float) -> str:
    """
    A duration as the table gives it, hours and minutes ('351:24', thousands
    of hours separated), to the nearest minute; under a minute but more than
    none is '<0:01', so that time spent never reads as none.
    """
    if 0 < seconds < _SECONDS_PER_MINUTE:
        return "<0:01"
    minutes = int(seconds / _SECONDS_PER_MINUTE + 0.5)
    return f"{minutes // 60:,}:{minutes % 60:02}"


def _group_json(group: UsageGroup) -> dict:
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
    }


if __name__ == "__main__":
    main()
