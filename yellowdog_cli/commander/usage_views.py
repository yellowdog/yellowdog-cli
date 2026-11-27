"""
The Usage Explorer's logic that needs no Qt: the window a view covers, the
`yd usage` arguments of a view, drilling down the breadcrumb, and a row's cell
text. Commander groups and adds up nothing itself: every figure shown is the
CLI's, read from its `--json` document.
"""

import shlex
from dataclasses import dataclass
from datetime import datetime, timezone

from yellowdog_cli.utils.command_registry import (
    USAGE_GROUP_KEYS,
    USAGE_SORT_VALUE_KEYS,
)
from yellowdog_cli.utils.usage_text import (
    cost_text_of,
    duration_text,
    heading,
    report_time,
)

__all__ = [
    "DEFAULT_PRESET",
    "DRILL_PATH",
    "INSTANCE_KEYS",
    "INSTANCE_LEVEL",
    "KEY_VALUE_SEPARATOR",
    "PRESETS",
    "USAGE_GROUP_KEYS",
    "USAGE_SORT_VALUE_KEYS",
    "VIEW_TOP_ROWS",
    "Level",
    "Scope",
    "command_line",
    "drill",
    "eligible_keys",
    "heading",
    "narrowed",
    "preset_window",
    "row_cells",
    "share_basis",
    "share_text",
    "sort_order",
    "toggled_by",
    "view_args",
]

# The default path down the breadcrumb, each level the next key to total by
DRILL_PATH: tuple[str, ...] = ("namespace", "cr", "instance-type", "instance-id")

# Between a multi-key row's values in its crumb (a spaced middle dot)
KEY_VALUE_SEPARATOR = " \u00b7 "

# The key that makes a level the Instance level, the last
INSTANCE_LEVEL = "instance-id"

# The Instance level's keys when drilled into, so that each row says what the
# Instance was; ticks like any others, which Total by may take away
INSTANCE_KEYS: tuple[str, ...] = (
    "instance-id",
    "instance-type",
    "provider",
    "region",
    "pricing",
    "cr",
)

PRESETS: tuple[str, ...] = (
    "Last 24 hours",
    "Last 7 days",
    "Last 30 days",
    "This month",
    "Last month",
)
DEFAULT_PRESET = "Last 7 days"

_RELATIVE_PRESETS = {
    "Last 24 hours": "24 hours ago",
    "Last 7 days": "7 days ago",
    "Last 30 days": "30 days ago",
}

# The seconds columns after Total, hidden until asked for, in the order shown
_OTHER_STATE_KEYS = ("pending", "stopping", "terminating", "unknown")


# How a fixed time is written in --from and --until: UTC, to the minute, as
# the report line and Kept Reports show it, which yd usage reads back
WINDOW_TIME_FORMAT = "%Y-%m-%d %H:%M UTC"


def _month_start(year: int, month: int) -> str:
    """
    The first instant of a calendar month, as a window time.
    """
    return datetime(year, month, 1, tzinfo=timezone.utc).strftime(WINDOW_TIME_FORMAT)


def window_time(iso: str) -> str:
    """
    A report's time ('2026-11-19T10:57:30.559218Z') as --from and --until
    are written ('2026-11-19 10:57 UTC'), or as it is if it cannot be read.
    The seconds dropped are well within the window a kept report is reused
    for.
    """
    try:
        moment = report_time(str(iso))
    except ValueError:
        return str(iso)
    if moment.tzinfo is None:
        return str(iso)
    return moment.astimezone(timezone.utc).strftime(WINDOW_TIME_FORMAT)


def preset_window(preset: str, now: datetime) -> tuple[str, str]:
    """
    The `--from` and `--until` texts of a preset: relative for the last hours
    or days, UTC calendar months for this and last month.
    """
    if preset in _RELATIVE_PRESETS:
        return _RELATIVE_PRESETS[preset], "now"
    now = now.astimezone(timezone.utc)
    if preset == "This month":
        return _month_start(now.year, now.month), "now"
    if preset == "Last month":
        year, month = (
            (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
        )
        return _month_start(year, month), _month_start(now.year, now.month)
    raise ValueError(f"Unknown preset: {preset}")


@dataclass(frozen=True)
class Scope:
    """
    What one fetched report covers. The window is as typed until a report has
    been fetched, then pinned to the report's own 'from' and 'until' (to the
    minute, window_time()), so that every later view regroups that same
    report.
    """

    from_text: str
    until_text: str
    namespace: str | None
    cost: bool
    pinned: bool = False

    def pinned_to(self, from_iso: str, until_iso: str) -> "Scope":
        """
        A copy pinned to the report's window.
        """
        return Scope(
            window_time(from_iso),
            window_time(until_iso),
            self.namespace,
            self.cost,
            pinned=True,
        )


# The rows a view asks for (--top), the rest summed in one row, so that a
# level of a great many groups (an account's every Instance) arrives as a
# table that can be shown; Show All asks for every row
VIEW_TOP_ROWS = 500


@dataclass(frozen=True)
class Level:
    """
    One breadcrumb level: the keys it totals by (columns, in this order), the
    exact filters the row drilled into gave it, how it sorts: the '--sort'
    keys, the first the most significant ('total' when none), and whether
    '--reverse' turns them all round; whether every row is shown, or the
    first VIEW_TOP_ROWS with the rest summed; and the text Find looks for
    in its first key's values ('' for none).
    """

    by: tuple[str, ...]
    filters: tuple[tuple[str, str], ...] = ()
    label: str = "All"
    sort: tuple[str, ...] = ()
    reverse: bool = False
    all_rows: bool = False
    match: str = ""

    @property
    def leaf(self) -> bool:
        """
        Whether this is the Instance level, the last.
        """
        return INSTANCE_LEVEL in self.by


def glob_literal(text: str) -> str:
    """
    Text in a '--where' pattern, a '[' matching itself rather than opening a
    class; a '*' or '?' typed is a wildcard still.
    """
    return text.replace("[", "[[]")


def sort_order(level: Level | None) -> list[tuple[str, bool]]:
    """
    Each key a level sorts by ('total' unless set), the most significant
    first, with whether the most, or for a key's value Z, comes first: the
    CLI's order is a figure the most first and a value A to Z, '--reverse'
    turning every key the other way.
    """
    keys = (level.sort if level else ()) or ("total",)
    reverse = bool(level and level.reverse)
    return [(key, (key in USAGE_SORT_VALUE_KEYS) != reverse) for key in keys]


def view_args(scope: Scope, levels: list[Level], refresh: bool = False) -> list[str]:
    """
    The `yd usage` arguments of the view the last level describes (the
    runner adds '--json' and the configuration arguments).
    """
    current = levels[-1]
    args = ["--from", scope.from_text, "--until", scope.until_text]
    if scope.namespace:
        args += ["-n", scope.namespace]
    args += ["--by", ",".join(current.by)]
    for level in levels:
        for key, value in level.filters:
            args += ["--where", f"{key}=={value}"]
    if current.match:
        args += ["--where", f"{current.by[0]}=*{glob_literal(current.match)}*"]
    if current.sort:
        args += ["--sort", ",".join(current.sort)]
        if current.reverse:
            args.append("--reverse")
    if not current.all_rows:
        args += ["--top", str(VIEW_TOP_ROWS)]
    if scope.cost:
        args.append("--cost")
    if refresh:
        args.append("--refresh")
    return args


def _fixed_keys(levels: list[Level] | tuple[Level, ...]) -> set[str]:
    """
    The keys the breadcrumb's filters fix to one value (a creator by its ID
    fixing its name too).
    """
    fixed = {key for level in levels for key, _ in level.filters}
    if "creator-id" in fixed:
        fixed.add("creator")
    return fixed


def eligible_keys(levels: list[Level] | tuple[Level, ...]) -> tuple[str, ...]:
    """
    The keys the last level may total by: those no filter above fixes.
    """
    fixed = _fixed_keys(levels)
    return tuple(key for key in USAGE_GROUP_KEYS if key not in fixed)


def toggled_by(by: tuple[str, ...], key: str) -> tuple[str, ...] | None:
    """
    The keys to total by after ticking or unticking one: a key ticked is
    added after the others, Instance ID too; None for the last key
    unticked, which stays.
    """
    if key in by:
        return None if len(by) == 1 else tuple(k for k in by if k != key)
    return (*by, key)


def _exact_filter(key: str, row: dict) -> tuple[str, str]:
    """
    The '--where key==value' filter matching a row's value of a key: a
    creator by its ID, no creator (null) as '-', as the CLI shows and
    matches it.
    """
    if key == "creator":
        return "creator-id", str(row.get("creatorId") or "-")
    return key, str(row.get(key, ""))


def narrowed(levels: list[Level], key: str, row: dict) -> list[Level]:
    """
    The levels after filtering to a row's value of one key of several: a
    level totalled by the others, filtered to that value, sorted as before
    less that key.
    """
    current = levels[-1]
    filter_ = _exact_filter(key, row)
    sort = tuple(k for k in current.sort if k != key)
    return [
        *levels,
        Level(
            tuple(k for k in current.by if k != key),
            (filter_,),
            str(row.get(key, filter_[1])),
            sort=sort,
            reverse=current.reverse if sort else False,
        ),
    ]


def drill(levels: list[Level], row: dict) -> list[Level] | None:
    """
    The levels after drilling into a row: each of the row's keys as an
    exact filter, and the next key down the default path, after the row's
    keys and not fixed above, to total by. None at the Instance level, which
    is a leaf. A creator is filtered by its ID.
    """
    current = levels[-1]
    if current.leaf:
        return None
    filters: list[tuple[str, str]] = []
    shown: list[str] = []
    for key in current.by:
        filter_ = _exact_filter(key, row)
        filters.append(filter_)
        shown.append(str(row.get(key, filter_[1])))
    fixed = _fixed_keys([*levels, Level(current.by, tuple(filters))])
    fixed.update(current.by)
    places = [DRILL_PATH.index(key) for key in current.by if key in DRILL_PATH]
    after = max(places) + 1 if places else 0
    next_by = next((key for key in DRILL_PATH[after:] if key not in fixed), None)
    # The path's end, the Instance level: ticked with the keys that say what
    # each Instance was, less those the filters fix
    by = (
        (next_by,)
        if next_by not in (None, INSTANCE_LEVEL)
        else tuple(
            key for key in INSTANCE_KEYS if key == INSTANCE_LEVEL or key not in fixed
        )
    )
    label = KEY_VALUE_SEPARATOR.join(shown)
    return [*levels, Level(by, tuple(filters), label)]


# The options every run is given for the explorer to read its output, which
# the command line shown leaves out: typed in a terminal, the command prints
# its table
EXPLORER_OUTPUT_OPTIONS = frozenset({"--nf", "-q", "--json"})


def command_line(arguments: list[str]) -> str:
    """
    The command as typed in a shell, for display and copying, less
    EXPLORER_OUTPUT_OPTIONS.
    """
    shown = [a for a in arguments if a not in EXPLORER_OUTPUT_OPTIONS]
    return " ".join(["yd usage", *(shlex.quote(a) for a in shown)])


def row_cells(row: dict, by: list[str], cost: bool) -> list[str]:
    """
    A row's cell texts, as `yd usage` writes them: the `--by` keys' values,
    Instances, the running, stopped and total times, the cost when asked for,
    its share of the total (share_text()), then the pending, stopping,
    terminating and unknown times.
    """
    seconds = row.get("seconds", {})
    cells = [str(row.get(key, "-")) for key in by]
    cells.append(f"{row.get('instances', 0):,}")
    cells += [
        duration_text(seconds.get(key, 0)) for key in ("running", "stopped", "total")
    ]
    if cost:
        cells.append(
            cost_text_of(
                row.get("estimatedCost"), row.get("unpricedRunningHours", 0) > 0
            )
        )
    cells.append(share_text(row, cost))
    cells += [duration_text(seconds.get(key, 0)) for key in _OTHER_STATE_KEYS]
    return cells


def share_basis(cost: bool) -> str:
    """
    What a share is of: the estimated cost where the view has it, else the
    time (the key under a group's 'share').
    """
    return "cost" if cost else "hours"


def share_text(row: dict, cost: bool) -> str:
    """
    A row's share of the total as a percentage to one place, '-' where it
    has none (nothing to share, or nothing priced).
    """
    share = (row.get("share") or {}).get(share_basis(cost))
    return f"{share * 100:.1f}%" if isinstance(share, int | float) else "-"
