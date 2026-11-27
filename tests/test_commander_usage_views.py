"""
The Usage Explorer's Qt-free logic (commander/usage_views.py): the window of a
preset, the arguments of a view, drilling and a row's cells. Needs no Qt.
"""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from yellowdog_cli.commander.usage_views import (
    DRILL_PATH,
    INSTANCE_KEYS,
    INSTANCE_LEVEL,
    KEY_VALUE_SEPARATOR,
    PRESETS,
    VIEW_TOP_ROWS,
    Level,
    Scope,
    command_line,
    day_end_text,
    day_of,
    day_start_text,
    drill,
    eligible_keys,
    heading,
    narrowed,
    preset_window,
    row_cells,
    row_count_text,
    sort_order,
    toggled_by,
    view_args,
    window_time,
)
from yellowdog_cli.utils.command_registry import USAGE_GROUP_KEYS

NOW = datetime(2026, 11, 25, 15, 2, 30, tzinfo=timezone.utc)


def test_first_view_passes_the_window_as_typed():
    assert view_args(
        Scope("7 days ago", "now", None, True), [Level(("namespace",))]
    ) == [
        "--from",
        "7 days ago",
        "--until",
        "now",
        "--by",
        "namespace",
        "--top",
        "500",
        "--cost",
    ]


def test_a_pinned_view_passes_the_reports_window():
    scope = Scope("7 days ago", "now", None, False).pinned_to(
        "2026-11-18T15:02:30Z", "2026-11-25T15:02:30Z"
    )
    assert scope.pinned
    assert view_args(scope, [Level(("namespace",))])[:4] == [
        "--from",
        "2026-11-18 15:02 UTC",
        "--until",
        "2026-11-25 15:02 UTC",
    ]


def test_a_pinned_window_is_written_to_the_minute():
    scope = Scope("24 hours ago", "now", None, False).pinned_to(
        "2026-11-18T10:57:30.559218Z", "2026-11-19T10:57:30.601337+00:00"
    )
    assert (scope.from_text, scope.until_text) == (
        "2026-11-18 10:57 UTC",
        "2026-11-19 10:57 UTC",
    )


def test_window_time_converts_to_utc_and_keeps_what_it_cannot_read():
    assert window_time("2026-11-19T11:57:30.5+01:00") == "2026-11-19 10:57 UTC"
    assert window_time("2026-11-19T10:57:30") == "2026-11-19T10:57:30"
    assert window_time("7 days ago") == "7 days ago"
    assert window_time("") == ""


def test_a_cost_change_keeps_the_pin():
    scope = Scope("a", "b", None, False).pinned_to("x", "y")
    assert replace(scope, cost=True).pinned


def test_namespace_filters_sort_and_refresh():
    levels = [
        Level(("namespace",)),
        Level(
            ("cr",), (("namespace", "team-a"),), "team-a", sort=("total",), reverse=True
        ),
    ]
    assert view_args(Scope("a", "b", "team-*", True), levels, refresh=True) == [
        "--from", "a", "--until", "b", "-n", "team-*", "--by", "cr",
        "--where", "namespace==team-a", "--sort", "total", "--reverse",
        "--top", "500", "--cost", "--refresh",
    ]  # fmt: skip


def test_sort_without_reverse():
    args = view_args(Scope("a", "b", None, False), [Level(("cr",), sort=("cost",))])
    assert args[-4:-2] == ["--sort", "cost"]


def test_a_view_shows_the_first_rows_unless_all_are_asked_for():
    scope = Scope("a", "b", None, False)
    assert view_args(scope, [Level(("cr",))])[-2:] == ["--top", str(VIEW_TOP_ROWS)]
    assert "--top" not in view_args(scope, [Level(("cr",), all_rows=True)])


def test_several_sort_keys_are_one_sort():
    level = Level(("cr", "region"), sort=("region", "total"), reverse=True)
    args = view_args(Scope("a", "b", None, False), [level])
    assert args[-5:-2] == ["--sort", "region,total", "--reverse"]


@pytest.mark.parametrize(
    "level, expected",
    [
        (None, [("total", True)]),
        (Level(("cr",)), [("total", True)]),
        (Level(("cr",), sort=("cr", "running")), [("cr", False), ("running", True)]),
        # --reverse turns every key round
        (
            Level(("cr",), sort=("cr", "running"), reverse=True),
            [("cr", True), ("running", False)],
        ),
    ],
)
def test_sort_order_is_each_key_and_whether_the_most_or_z_is_first(level, expected):
    assert sort_order(level) == expected


def test_drill_filters_exactly_and_moves_down_the_path():
    levels = drill([Level(("namespace",))], {"namespace": "team-render"})
    assert levels is not None
    assert levels[-1] == Level(("cr",), (("namespace", "team-render"),), "team-render")


def test_drill_filter_is_exact_for_awkward_values():
    for value in ["Render", "team[1]", "=odd", "*", "-"]:
        levels = drill([Level(("tag",))], {"tag": value})
        assert levels is not None
        assert f"tag=={value}" in view_args(Scope("a", "b", None, False), levels)


def test_a_creator_row_with_no_creator_drills_by_a_dash():
    levels = drill([Level(("creator",))], {"creator": "-", "creatorId": None})
    assert levels is not None
    assert levels[-1].filters == (("creator-id", "-"),)


def test_a_creator_row_drills_by_its_id():
    levels = drill(
        [Level(("creator",))],
        {"creator": "render-farm (Application)", "creatorId": "ydid:app:1"},
    )
    assert levels is not None
    assert levels[-1].filters == (("creator-id", "ydid:app:1"),)
    assert levels[-1].label == "render-farm (Application)"


def test_drill_skips_a_key_already_filtered_on():
    drilled = drill([Level(("cr",), (("namespace", "n"),), "n")], {"cr": "farm"})
    assert drilled is not None
    assert drilled[-1].by == ("instance-type",)
    levels = [Level(("namespace",)), Level(("cr",), (("instance-type", "t"),), "t")]
    skipped = drill(levels, {"cr": "x"})
    assert skipped is not None
    # The Instance level, ticked with its describing keys less those fixed
    assert skipped[-1].by == tuple(
        key for key in INSTANCE_KEYS if key not in ("instance-type", "cr")
    )


def test_a_key_off_the_path_starts_from_its_beginning():
    # A key off the path starts from the path's beginning
    off = drill([Level(("region",), (("namespace", "n"),), "n")], {"region": "eu"})
    assert off is not None
    assert off[-1].by == ("cr",)


def test_the_instance_level_is_a_leaf_asking_for_its_ticks_alone():
    assert drill([Level(("instance-id",))], {"instance-id": "i-1"}) is None
    args = view_args(Scope("a", "b", None, False), [Level(("instance-id",))])
    assert args[args.index("--by") + 1] == "instance-id"
    assert INSTANCE_KEYS[0] == "instance-id"


def test_a_level_holding_instance_id_is_a_leaf():
    assert drill([Level(("namespace", "instance-id"))], {"namespace": "a"}) is None
    args = view_args(Scope("a", "b", None, False), [Level(("tag", "instance-id"))])
    assert args[args.index("--by") + 1] == "tag,instance-id"


def test_several_keys_group_and_drill_on_all_of_them():
    top = Level(("namespace", "region"))
    args = view_args(Scope("a", "b", None, False), [top])
    assert args[args.index("--by") + 1] == "namespace,region"
    levels = drill([top], {"namespace": "team-render", "region": "eu-west-2"})
    assert levels is not None
    assert levels[-1] == Level(
        ("cr",),
        (("namespace", "team-render"), ("region", "eu-west-2")),
        f"team-render{KEY_VALUE_SEPARATOR}eu-west-2",
    )
    assert view_args(Scope("a", "b", None, False), levels)[-6:-2] == [
        "--where",
        "namespace==team-render",
        "--where",
        "region==eu-west-2",
    ]


def test_drilling_several_keys_moves_on_after_the_furthest_down_the_path():
    levels = drill(
        [Level(("instance-type", "namespace"))],
        {"instance-type": "t3.large", "namespace": "n"},
    )
    assert levels is not None
    assert levels[-1].by == tuple(k for k in INSTANCE_KEYS if k != "instance-type")


def test_the_eligible_keys_are_those_no_filter_fixes():
    levels = [
        Level(("namespace",)),
        Level(("creator",), (("namespace", "n"),), "n"),
        Level(("cr",), (("creator-id", "ydid:app:1"),), "app"),
    ]
    eligible = eligible_keys(levels)
    assert "namespace" not in eligible
    assert "creator" not in eligible and "creator-id" not in eligible
    assert eligible == tuple(
        k for k in USAGE_GROUP_KEYS if k not in ("namespace", "creator", "creator-id")
    )


def test_toggling_keys():
    assert toggled_by(("namespace",), "region") == ("namespace", "region")
    assert toggled_by(("namespace", "region"), "namespace") == ("region",)
    # The last key stays
    assert toggled_by(("namespace",), "namespace") is None
    # Instance ID combines with the others, as any key does
    assert toggled_by(("namespace", "region"), INSTANCE_LEVEL) == (
        "namespace",
        "region",
        INSTANCE_LEVEL,
    )
    assert toggled_by((INSTANCE_LEVEL,), "tag") == (INSTANCE_LEVEL, "tag")
    assert toggled_by(("namespace", INSTANCE_LEVEL), INSTANCE_LEVEL) == ("namespace",)


def test_the_path_and_keys_are_valid():
    assert set(DRILL_PATH) <= set(USAGE_GROUP_KEYS)
    assert set(INSTANCE_KEYS) <= set(USAGE_GROUP_KEYS)


def test_presets():
    assert [preset_window(p, NOW) for p in PRESETS] == [
        ("24 hours ago", "now"),
        ("7 days ago", "now"),
        ("30 days ago", "now"),
        ("2026-11-01 00:00 UTC", "now"),
        ("2026-10-01 00:00 UTC", "2026-11-01 00:00 UTC"),
    ]


def test_last_month_in_january_is_december():
    january = datetime(2027, 1, 5, tzinfo=timezone.utc)
    assert preset_window("Last month", january) == (
        "2026-12-01 00:00 UTC",
        "2027-01-01 00:00 UTC",
    )


def test_months_are_utc_whatever_the_clock():
    # 23:30 on 30 November in UTC-5 is already 1 December in UTC
    late = datetime(2026, 11, 30, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
    assert preset_window("This month", late)[0] == "2026-12-01 00:00 UTC"


def test_command_line_quotes():
    assert command_line(["--where", "cr==a b"]) == "yd usage --where 'cr==a b'"


def test_command_line_leaves_out_the_explorers_output_options():
    assert (
        command_line(["-c", "config.toml", "--nf", "-q", "--json", "--by", "cr"])
        == "yd usage -c config.toml --by cr"
    )


def test_row_cells_format_as_the_cli():
    row = {
        "namespace": "team-a",
        "instances": 1234,
        "seconds": {
            "pending": 0,
            "running": 41 * 3600 + 600,
            "stopping": 1,
            "stopped": 30,
            "terminating": 0,
            "unknown": 60,
            "total": 5_400_000,
        },
        "estimatedCost": 216.4,
        "unpricedRunningHours": 0.5,
        "share": {"hours": 0.4123, "cost": 0.25},
    }
    assert row_cells(row, ["namespace"], True) == [
        "team-a", "1,234", "41:10", "<0:01", "1,500:00", "216.40+", "25.0%",
        "0:00", "<0:01", "0:00", "0:01",
    ]  # fmt: skip
    row["unpricedRunningHours"] = 0
    row["estimatedCost"] = None
    assert row_cells(row, ["namespace"], True)[5] == "-"
    # Without the cost, the share of the time
    assert len(row_cells(row, ["namespace"], False)) == 10
    assert row_cells(row, ["namespace"], False)[5] == "41.2%"
    # No share to give: none of anything
    row["share"] = {"hours": None, "cost": None}
    assert row_cells(row, ["namespace"], True)[6] == "-"
    del row["share"]
    assert row_cells(row, ["namespace"], False)[5] == "-"


def test_heading_reads_as_the_command():
    assert heading("cr") == "Compute Requirement"
    assert heading("instance-type") == "Instance type"


def test_narrowing_to_a_value_drops_its_key_and_filters_by_it():
    level = Level(("namespace", "region"), sort=("region", "total"), reverse=True)
    row = {"namespace": "team-a", "region": "eu-west-2"}
    levels = narrowed([level], "region", row)
    assert levels == [
        level,
        Level(
            ("namespace",),
            (("region", "eu-west-2"),),
            "eu-west-2",
            sort=("total",),
            reverse=True,
        ),
    ]


def test_narrowing_to_a_creator_filters_by_its_id():
    level = Level(("creator", "region"))
    row = {"creator": "alice (User)", "creatorId": "ydid:user:1", "region": "r"}
    [_, narrow] = narrowed([level], "creator", row)
    assert narrow.filters == (("creator-id", "ydid:user:1"),)
    assert narrow.label == "alice (User)"


def test_find_matches_the_first_key_anywhere_in_its_value():
    args = view_args(
        Scope("a", "b", None, False), [Level(("cr", "region"), match="rend")]
    )
    where = [args[i + 1] for i, arg in enumerate(args) if arg == "--where"]
    assert where == ["cr=*rend*"]


def test_a_bracket_found_matches_itself():
    args = view_args(Scope("a", "b", None, False), [Level(("cr",), match="a[1]")])
    assert args[args.index("--where") + 1] == "cr=*a[[]1]*"


def test_a_day_starts_and_ends_at_midnight_utc():
    assert day_start_text(date(2026, 10, 1)) == "2026-10-01 00:00 UTC"
    # The end of a day is the next one's start; of a year's last, the next year
    assert day_end_text(date(2026, 10, 31)) == "2026-11-01 00:00 UTC"
    assert day_end_text(date(2026, 12, 31)) == "2027-01-01 00:00 UTC"


@pytest.mark.parametrize(
    "text, until, day",
    [
        ("2026-10-05 00:00 UTC", False, date(2026, 10, 5)),
        ("2026-10-05 13:30 UTC", False, date(2026, 10, 5)),
        # Until a midnight is until the end of the day before
        ("2026-11-01 00:00 UTC", True, date(2026, 10, 31)),
        ("2026-11-01 09:30 UTC", True, date(2026, 11, 1)),
        ("2026-10-05", False, date(2026, 10, 5)),
        ("7 days ago", False, None),
        ("now", True, None),
        # Not a day or a time there is
        ("2026-02-30", False, None),
        ("2026-11-01 25:00 UTC", False, None),
    ],
)
def test_the_day_a_field_names(text, until, day):
    assert day_of(text, until) == day


@pytest.mark.parametrize(
    "shown, total, text",
    [
        (1, 1, "1 row"),
        (4, 4, "4 rows"),
        (1234, 1234, "1,234 rows"),
        # Rows left out by --top, summed in the '(n more)' row
        (500, 1234, "500 of 1,234 rows"),
    ],
)
def test_row_count_text(shown, total, text):
    assert row_count_text(shown, total) == text
