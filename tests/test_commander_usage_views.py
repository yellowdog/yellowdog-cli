"""
The Usage Explorer's Qt-free logic (commander/usage_views.py): the window of a
preset, the arguments of a view, drilling and a row's cells. Needs no Qt.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from yellowdog_cli.commander.usage_views import (
    DRILL_PATH,
    INSTANCE_KEYS,
    INSTANCE_LEVEL,
    KEY_VALUE_SEPARATOR,
    PRESETS,
    Level,
    Scope,
    command_line,
    drill,
    eligible_keys,
    heading,
    preset_window,
    row_cells,
    toggled_by,
    view_args,
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
        "--cost",
    ]


def test_a_pinned_view_passes_the_reports_window():
    scope = Scope("7 days ago", "now", None, False).pinned_to(
        "2026-11-18T15:02:30Z", "2026-11-25T15:02:30Z"
    )
    assert scope.pinned
    assert view_args(scope, [Level(("namespace",))])[:4] == [
        "--from",
        "2026-11-18T15:02:30Z",
        "--until",
        "2026-11-25T15:02:30Z",
    ]


def test_a_cost_change_keeps_the_pin():
    scope = Scope("a", "b", None, False).pinned_to("x", "y")
    assert replace(scope, cost=True).pinned


def test_namespace_filters_sort_and_refresh():
    levels = [
        Level(("namespace",)),
        Level(
            ("cr",), (("namespace", "team-a"),), "team-a", sort="total", reverse=True
        ),
    ]
    assert view_args(Scope("a", "b", "team-*", True), levels, refresh=True) == [
        "--from", "a", "--until", "b", "-n", "team-*", "--by", "cr",
        "--where", "namespace==team-a", "--sort", "total", "--reverse",
        "--cost", "--refresh",
    ]  # fmt: skip


def test_sort_without_reverse():
    args = view_args(Scope("a", "b", None, False), [Level(("cr",), sort="cost")])
    assert args[-2:] == ["--sort", "cost"]


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
    assert skipped[-1].by == ("instance-id",)


def test_a_key_off_the_path_starts_from_its_beginning():
    # A key off the path starts from the path's beginning
    off = drill([Level(("region",), (("namespace", "n"),), "n")], {"region": "eu"})
    assert off is not None
    assert off[-1].by == ("cr",)


def test_the_instance_level_is_a_leaf_and_shows_its_details():
    assert drill([Level(("instance-id",))], {"instance-id": "i-1"}) is None
    args = view_args(Scope("a", "b", None, False), [Level(("instance-id",))])
    assert args[args.index("--by") + 1] == ",".join(INSTANCE_KEYS)
    assert INSTANCE_KEYS[0] == "instance-id"


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
    assert view_args(Scope("a", "b", None, False), levels)[-4:] == [
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
    assert levels[-1].by == ("instance-id",)


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
    # The Instance level replaces the others, and any other replaces it
    assert toggled_by(("namespace", "region"), INSTANCE_LEVEL) == (INSTANCE_LEVEL,)
    assert toggled_by((INSTANCE_LEVEL,), "region") == ("region",)


def test_the_path_and_keys_are_valid():
    assert set(DRILL_PATH) <= set(USAGE_GROUP_KEYS)
    assert set(INSTANCE_KEYS) <= set(USAGE_GROUP_KEYS)


def test_presets():
    assert [preset_window(p, NOW) for p in PRESETS] == [
        ("24 hours ago", "now"),
        ("7 days ago", "now"),
        ("30 days ago", "now"),
        ("2026-11-01T00:00:00Z", "now"),
        ("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"),
    ]


def test_last_month_in_january_is_december():
    january = datetime(2027, 1, 5, tzinfo=timezone.utc)
    assert preset_window("Last month", january) == (
        "2026-12-01T00:00:00Z",
        "2027-01-01T00:00:00Z",
    )


def test_months_are_utc_whatever_the_clock():
    # 23:30 on 30 November in UTC-5 is already 1 December in UTC
    late = datetime(2026, 11, 30, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
    assert preset_window("This month", late)[0] == "2026-12-01T00:00:00Z"


def test_command_line_quotes():
    assert command_line(["--where", "cr==a b"]) == "yd usage --where 'cr==a b'"


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
    }
    assert row_cells(row, ["namespace"], True) == [
        "team-a", "1,234", "41:10", "<0:01", "1,500:00", "216.40+",
        "0:00", "<0:01", "0:00", "0:01",
    ]  # fmt: skip
    row["unpricedRunningHours"] = 0
    row["estimatedCost"] = None
    assert row_cells(row, ["namespace"], True)[5] == "-"
    assert len(row_cells(row, ["namespace"], False)) == 9


def test_heading_reads_as_the_command():
    assert heading("cr") == "Compute Requirement"
    assert heading("instance-type") == "Instance type"
