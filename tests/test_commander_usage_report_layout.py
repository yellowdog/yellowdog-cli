"""
The Usage Explorer's PDF report, laid out without Qt
(commander/usage_report_layout.py): the table's type fitted to the page's
width, key texts shortened at the floor, and the rows, the Total row and the
notes planned onto pages. Text is measured by a fake: half the point size per
character, a tenth wider bold.
"""

import pytest

from yellowdog_cli.commander.usage_report_layout import (
    COST_CAVEAT,
    MIN_KEY_CHARS,
    NO_INSTANCES,
    NO_MATCHING_INSTANCES,
    TABLE_FLOOR,
    TABLE_SIZE,
    PageGeometry,
    ReportContent,
    Tile,
    fit_table,
    fitted_text,
    heading_lines,
    period_text,
    plan_pages,
    report_content,
    sort_text,
    wrap_text,
)
from yellowdog_cli.commander.usage_views import Level

A4 = PageGeometry(width=595.0, height=842.0, margin=42.0)
A4_LANDSCAPE = PageGeometry(width=842.0, height=595.0, margin=42.0)
WIDTH = A4.width - 2 * A4.margin


def measure(text: str, size: float, bold: bool) -> float:
    return len(text) * size * 0.5 * (1.1 if bold else 1.0)


FIGURES = ["Instances", "Running (h:mm)", "Stopped (h:mm)", "Total (h:mm)"]


def content(
    keys: list[str] | None = None,
    figures: list[str] | None = None,
    rows: list[list[str]] | None = None,
    total: list[str] | None = None,
    notes: list[str] | None = None,
    empty_text: str | None = None,
) -> ReportContent:
    keys = ["Namespace"] if keys is None else keys
    figures = FIGURES if figures is None else figures
    if rows is None:
        rows = [
            [f"team-{n}" for _ in keys]
            + ["3", "12:00", "0:30", "12:30"][: len(figures)]
            for n in range(4)
        ]
    if total is None and rows:
        total = ["Total"] + [""] * (len(keys) - 1) + ["12", "48:00", "2:00", "50:00"]
        total = total[: len(keys) + len(figures)]
    return ReportContent(
        title="Compute Usage and Cost",
        account_line="YellowDog Production · https://api.yellowdog.ai",
        subtitle="October 2026 · all namespaces",
        scope_lines=["Window: ...", "Totalled by Namespace", "Report fetched ..."],
        tiles=[Tile("Running", "48:00", "hours:minutes")],
        headings=keys + figures,
        key_columns=len(keys),
        rows=rows,
        total=total,
        empty_text=empty_text,
        notes=notes or [],
        caveat=None,
    )


def wide_content(key_length: int = 20, figure_count: int = 9) -> ReportContent:
    keys = ["Namespace", "Compute Requirement", "Instance type"]
    figures = [f"Figure {n} (h:mm)" for n in range(figure_count)]
    rows = [
        [
            "n" * key_length,
            "c" * key_length,
            "t" * key_length,
            *("12,345:59" for _ in figures),
        ]
        for _ in range(5)
    ]
    total = ["Total", "", "", *("99,999:59" for _ in figures)]
    return content(keys=keys, figures=figures, rows=rows, total=total)


def test_heading_lines_splits_the_unit():
    assert heading_lines("Est. cost (USD)") == ["Est. cost", "(USD)"]
    assert heading_lines("Running (h:mm)") == ["Running", "(h:mm)"]
    assert heading_lines("Namespace") == ["Namespace"]
    assert heading_lines("Compute Requirement ID") == ["Compute Requirement ID"]


def test_a_narrow_table_keeps_the_normal_size():
    fit = fit_table(content(), measure, WIDTH)
    assert fit.size == TABLE_SIZE
    assert sum(fit.widths) <= WIDTH


def test_a_wide_table_is_reduced_to_fit():
    report = wide_content(key_length=12)
    fit = fit_table(report, measure, WIDTH)
    assert TABLE_FLOOR <= fit.size < TABLE_SIZE
    assert sum(fit.widths) <= WIDTH
    assert fit.rows == report.rows and fit.total == report.total


def test_at_the_floor_key_texts_are_shortened():
    report = wide_content(key_length=40)
    fit = fit_table(report, measure, WIDTH)
    assert fit.size == TABLE_FLOOR
    assert sum(fit.widths) <= WIDTH
    shortened = fit.rows[0][:3]
    assert any("…" in text and len(text) < 40 for text in shortened)
    # Figures are never shortened
    assert [row[3:] for row in fit.rows] == [row[3:] for row in report.rows]


def test_at_the_floor_key_headings_break_before_they_shorten():
    narrow = fit_table(content(keys=["Compute Requirement"]), measure, WIDTH)
    assert narrow.heading_lines[0] == ["Compute Requirement"]
    report = wide_content(key_length=40)
    fit = fit_table(report, measure, WIDTH)
    assert fit.heading_lines[1] == ["Compute", "Requirement"]
    assert fit.heading_lines[2] == ["Instance", "type"]
    assert fit.heading_lines[3] == ["Figure 0", "(h:mm)"]


def test_never_shortened_below_four_characters_then_smaller_type():
    report = wide_content(key_length=40, figure_count=14)
    fit = fit_table(report, measure, WIDTH)
    assert fit.size < TABLE_FLOOR
    assert sum(fit.widths) <= WIDTH
    for row in fit.rows:
        for text in row[:3]:
            assert len(text.replace("…", "")) >= MIN_KEY_CHARS


def test_widths_are_the_widest_cell_across_every_row():
    rows = [["a", "1"], ["a-much-longer-name", "2"]]
    report = content(
        keys=["Namespace"], figures=["Instances"], rows=rows, total=["Total", "3"]
    )
    fit = fit_table(report, measure, WIDTH)
    assert fit.widths[0] > measure("a-much-longer-name", fit.size, False)
    # The bold Total is measured bold
    total_only = content(
        keys=["Namespace"],
        figures=["Instances"],
        rows=[["a", "1"]],
        total=["Total", "123456789012345"],
    )
    fit = fit_table(total_only, measure, WIDTH)
    assert fit.widths[1] > measure("123456789012345", fit.size, True)


def test_rows_flow_onto_pages_with_the_first_page_first():
    report = content(
        rows=[[f"ns-{n}", "1", "1:00", "0:00", "1:00"] for n in range(200)]
    )
    fit = fit_table(report, measure, WIDTH)
    pages = plan_pages(report, fit, A4, measure)
    assert len(pages) > 1
    assert pages[0].first and not any(page.first for page in pages[1:])
    assert [page.number for page in pages] == list(range(1, len(pages) + 1))
    covered = [n for page in pages for n in page.rows]
    assert covered == list(range(200))
    assert [page.total for page in pages].count(True) == 1 and pages[-1].total


def test_the_total_row_is_never_alone():
    # Find a row count whose Total falls alone at the top of a page, if
    # planned row by row: the planner keeps a data row with it
    for count in range(30, 160):
        report = content(
            rows=[[f"ns-{n}", "1", "1:00", "0:00", "1:00"] for n in range(count)]
        )
        fit = fit_table(report, measure, WIDTH)
        pages = plan_pages(report, fit, A4, measure)
        last = next(page for page in pages if page.total)
        assert len(last.rows) >= 1, count


def test_notes_follow_the_table_and_may_continue():
    notes = [f"Note {n}: " + "word " * 40 for n in range(60)]
    report = content(notes=notes)
    fit = fit_table(report, measure, WIDTH)
    pages = plan_pages(report, fit, A4, measure)
    assert len(pages) > 1
    assert pages[0].total
    lines = [line for page in pages for line in page.notes]
    # Every note wrapped to the width, in order
    assert all(measure(line, 7.5, False) <= WIDTH for line in lines)
    assert " ".join(lines).split() == " ".join(notes).split()
    assert pages[1].rows == range(0) and not pages[1].total


def test_an_empty_report_is_one_page():
    report = content(rows=[], total=None, empty_text="No Instances in this window")
    fit = fit_table(report, measure, WIDTH)
    pages = plan_pages(report, fit, A4, measure)
    assert len(pages) == 1
    assert pages[0].rows == range(0) and not pages[0].total


def test_landscape_needs_less_reduction():
    report = wide_content(key_length=14)
    portrait = fit_table(report, measure, WIDTH)
    landscape = fit_table(report, measure, A4_LANDSCAPE.width - 2 * A4_LANDSCAPE.margin)
    assert landscape.size > portrait.size


@pytest.mark.parametrize("geometry", [A4, A4_LANDSCAPE])
def test_every_page_holds_what_is_planned_on_it(geometry):
    report = content(
        rows=[[f"ns-{n}", "1", "1:00", "0:00", "1:00"] for n in range(500)]
    )
    width = geometry.width - 2 * geometry.margin
    fit = fit_table(report, measure, width)
    pages = plan_pages(report, fit, geometry, measure)
    rows_per_page = [len(page.rows) for page in pages[1:-1]]
    # Pages after the first are filled alike
    assert len(set(rows_per_page)) <= 1


# --- The report's content from the shown view -----------------------------

TOP = Level(("namespace",))
DRILLED = (
    Level(("namespace",)),
    Level(("cr",), (("namespace", "team-render"),), "team-render"),
)
OCTOBER = {
    "from": "2026-10-01T00:00:00Z",
    "until": "2026-11-01T00:00:00Z",
    "fetched": "2026-11-01T09:30:12.5Z",
    "namespace": None,
    "currency": "USD",
    "groups": [{}],
}
CR_HEADINGS = [
    "Compute Requirement",
    "Instances",
    "Running (h:mm)",
    "Stopped (h:mm)",
    "Total (h:mm)",
    "Est. cost (USD)",
]
CR_ROWS = [
    ["render-nightly", "24", "186:24", "12:30", "198:54", "952.36+"],
    ["render-adhoc", "9", "41:12", "3:00", "44:12", "214.80"],
    ["render-preview", "6", "18:54", "0:00", "18:54", "61.43"],
    ["thumbnails", "4", "7:36", "1:12", "8:48", "9.88"],
]
CR_TOTAL = ["Total", "43", "254:06", "16:42", "270:48", "1,238.47+"]


def made(
    document=None,
    levels=DRILLED,
    headings=CR_HEADINGS,
    rows=CR_ROWS,
    total=CR_TOTAL,
    cost=True,
    notes=(),
    sort=None,
) -> ReportContent:
    document = dict(OCTOBER, namespace="team-render") if document is None else document
    by_heading = dict(zip(headings, total)) if total is not None else None
    return report_content(
        document,
        levels,
        headings,
        1,
        rows,
        total,
        by_heading,
        cost,
        list(notes),
        sort,
    )


def test_period_of_a_calendar_month():
    assert period_text("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z") == "October 2026"
    assert (
        period_text("2026-12-01T00:00:00.000Z", "2027-01-01T00:00:00Z")
        == "December 2026"
    )


@pytest.mark.parametrize(
    "start, until",
    [
        ("2026-10-31T10:57:00Z", "2026-11-07T10:57:00Z"),
        ("2026-01-30T00:00:00Z", "2026-02-06T00:00:00Z"),
        ("2026-08-31T00:00:00Z", "2026-09-30T00:00:00Z"),
    ],
)
def test_a_window_starting_late_in_a_month_is_not_one(start, until):
    assert period_text(start, until).endswith(" UTC")


def test_period_of_any_other_window():
    assert (
        period_text("2026-11-19T10:57:30.5Z", "2026-11-26T10:57:30Z")
        == "2026-11-19 10:57 → 2026-11-26 10:57 UTC"
    )
    # This month, its end clamped to now
    assert (
        period_text("2026-11-01T00:00:00Z", "2026-11-27T10:00:00Z")
        == "2026-11-01 00:00 → 2026-11-27 10:00 UTC"
    )
    assert period_text("not a time", "2026-11-27T10:00:00Z") == (
        "not a time → 2026-11-27 10:00 UTC"
    )


def test_subtitle_names_the_namespace_or_all():
    assert made().subtitle == "October 2026 · team-render"
    assert made(document=OCTOBER, levels=(TOP,)).subtitle == (
        "October 2026 · all namespaces"
    )


def test_scope_lines():
    assert made().scope_lines == [
        "Window: 2026-10-01 00:00 → 2026-11-01 00:00 UTC · Namespace: team-render",
        "Totalled by Compute Requirement",
        "Within: team-render",
        "Report fetched 2026-11-01 09:30 UTC",
    ]
    top = made(document=OCTOBER, levels=(TOP,))
    assert top.scope_lines[0].endswith("· All namespaces")
    assert not any(line.startswith("Within") for line in top.scope_lines)


def test_the_sort_is_stated_with_what_it_totals_by():
    content = made(sort="Total (h:mm), most first")
    assert content.scope_lines[1] == (
        "Totalled by Compute Requirement · sorted by Total (h:mm), most first"
    )


@pytest.mark.parametrize(
    "figure, most_first, expected",
    [
        (True, True, "Total (h:mm), most first"),
        (True, False, "Total (h:mm), least first"),
        (False, False, "Total (h:mm), A to Z"),
        (False, True, "Total (h:mm), Z to A"),
    ],
)
def test_sort_text(figure, most_first, expected):
    assert sort_text([("Total (h:mm)", figure, most_first)]) == expected


def test_sort_text_of_several_keys_says_then():
    assert sort_text([("Namespace", False, False), ("Total (h:mm)", True, True)]) == (
        "Namespace, A to Z, then Total (h:mm), most first"
    )


def test_the_instances_tile_counts_every_group_those_cut_included():
    # 500 rows shown of 1,200, the rest summed in a '(700 more)' row
    document = dict(OCTOBER, namespace="team-render", total={"groups": 1200})
    assert made(document=document).tiles[2].note == "in 1,200 groups"


def test_tiles_with_cost_copy_the_total_row():
    assert made().tiles == [
        Tile("Estimated cost", "$1,238.47+", "USD, list prices"),
        Tile("Running", "254:06", "hours:minutes"),
        Tile("Instances", "43", "in 4 groups"),
    ]
    assert made().caveat == COST_CAVEAT
    assert made().title == "Compute Usage and Cost"


def test_tiles_follow_the_scope_not_the_visible_columns():
    # Running hidden: its tile still reads the Total row of every column
    visible = [0, 1, 3, 4, 5]
    report = report_content(
        dict(OCTOBER, namespace="team-render"),
        DRILLED,
        [CR_HEADINGS[c] for c in visible],
        1,
        [[row[c] for c in visible] for row in CR_ROWS],
        [CR_TOTAL[c] for c in visible],
        dict(zip(CR_HEADINGS, CR_TOTAL)),
        True,
        [],
    )
    assert report.tiles[1] == Tile("Running", "254:06", "hours:minutes")


def test_without_cost_nothing_of_cost_appears():
    headings = CR_HEADINGS[:-1]
    report = made(
        headings=headings,
        rows=[row[:-1] for row in CR_ROWS],
        total=CR_TOTAL[:-1],
        cost=False,
    )
    assert report.tiles[0] == Tile("Total time", "270:48", "hours:minutes")
    assert report.title == "Compute Usage"
    assert report.caveat is None
    texts = [
        report.title,
        report.subtitle,
        *report.scope_lines,
        *(
            text
            for tile in report.tiles
            for text in (tile.label, tile.value, tile.note)
        ),
        *report.headings,
        *(cell for row in report.rows for cell in row),
        *(report.total or []),
        *report.notes,
    ]
    assert not any("cost" in text.lower() or "$" in text for text in texts)


def test_an_empty_view():
    report = made(
        document=dict(OCTOBER, groups=[]),
        levels=(TOP,),
        headings=["Namespace", *CR_HEADINGS[1:]],
        rows=[],
        total=None,
    )
    assert [tile.value for tile in report.tiles] == ["$0.00", "0:00", "0"]
    assert report.tiles[2].note == "in 0 groups"
    assert report.empty_text == NO_INSTANCES
    assert report.total is None
    filtered = made(
        document=dict(OCTOBER, groups=[], where={"provider": ["azure"]}),
        rows=[],
        total=None,
    )
    assert filtered.empty_text == NO_MATCHING_INSTANCES


def test_one_group_is_one_group():
    assert made(rows=CR_ROWS[:1]).tiles[2].note == "in 1 group"


def test_notes_are_carried():
    assert made(notes=["first", "second"]).notes == ["first", "second"]


def test_a_line_wider_than_its_space_is_shortened_in_the_middle():
    text = "Within: " + "a-very-long-namespace-name \u203a " * 8 + "the-end"
    fitted = fitted_text(text, measure, 8.0, False, 300.0)
    assert measure(fitted, 8.0, False) <= 300.0
    assert "…" in fitted and fitted.startswith("Within: ") and fitted.endswith("end")
    assert fitted_text("short", measure, 8.0, False, 300.0) == "short"


def test_a_word_wider_than_the_page_is_broken():
    url = "https://example.com/" + "x" * 300
    lines = wrap_text(f"See {url} for more", measure, 7.5, 200.0)
    assert all(measure(line, 7.5, False) <= 200.0 for line in lines)
    assert "".join(lines).replace(" ", "") == f"See{url}formore"


def test_at_the_instance_level_the_instances_tile_counts_the_rows():
    headings = ["Instance ID", *CR_HEADINGS[2:]]
    rows = [[f"i-{n}", *row[2:]] for n, row in enumerate(CR_ROWS * 300)]
    total = ["Total", *CR_TOTAL[2:]]
    report = made(headings=headings, rows=rows, total=total)
    assert report.tiles[2] == Tile("Instances", "1,200", "in 1,200 groups")


def test_the_account_line_names_the_account_and_the_platform():
    document = dict(
        OCTOBER,
        namespace="team-render",
        accountName="YellowDog Production",
        url="https://api.yellowdog.ai",
    )
    assert made(document=document).account_line == (
        "Account: YellowDog Production · https://api.yellowdog.ai"
    )
    # A report kept without the account's name: the URL alone
    unnamed = dict(document, accountName=None)
    assert made(document=unnamed).account_line == "https://api.yellowdog.ai"
    assert made(document=dict(unnamed, url=None)).account_line == ""
