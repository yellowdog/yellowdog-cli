"""
The Usage Explorer's PDF report, laid out: what a report holds
(ReportContent), the table's type fitted to the page's width (fit_table())
and the rows, the Total row and the notes planned onto pages (plan_pages()).
Qt-free: text is measured through a callable (Measure), so the layout is
tested without a screen; usage_pdf.py measures with Qt and draws the plan.
All lengths are points.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timezone

from yellowdog_cli.commander.elision import elide_middle
from yellowdog_cli.commander.usage_views import Level, window_time
from yellowdog_cli.utils.usage_text import report_time

# Width in points of a text at a point size, bold or not
Measure = Callable[[str, float, bool], float]

# The report's title, with cost and without
REPORT_TITLE = "Compute Usage and Cost"
REPORT_TITLE_WITHOUT_COST = "Compute Usage"
# What the cost estimate leaves out: the explorer's cost heading says it, and
# the report's footer with the '+' explained
COST_NOTE = (
    "Linux list prices today; spot Instances at the region's mean spot price;"
    " no discounts, savings plans, licences or disks; running time only"
)
COST_CAVEAT = f"Estimated at {COST_NOTE}; + marks a cost with unpriced time"
# What the explorer and the report say of a view with no groups
NO_INSTANCES = "No Instances in this window"
NO_MATCHING_INSTANCES = "No Instances in this window match the filters"
# Between the values drilled into, as the breadcrumb writes them
DRILL_SEPARATOR = " \u203a "
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

# The table's type: its usual size, the smallest it is reduced to before key
# texts are shortened, and the step it is reduced by
TABLE_SIZE = 9.0
TABLE_FLOOR = 6.0
SIZE_STEP = 0.25
# The smallest size reached when even shortened keys do not fit
TABLE_LAST_RESORT = 2.0
# The fewest characters a shortened key text keeps, besides the ellipsis
MIN_KEY_CHARS = 4
ELLIPSIS = "…"
# Space either side of a cell's text
CELL_PADDING = 5.0
# A row's height, and a line of a two-line heading's, per point of type
ROW_LEADING = 1.75
HEADING_LEADING = 1.25

# The page's parts, top to bottom
TITLE_SIZE = 16.0
SUBTITLE_SIZE = 9.5
ACCOUNT_SIZE = 8.5
HEADER_HEIGHT = 60.0
SLIM_HEADER_HEIGHT = 30.0
SCOPE_SIZE = 7.5
SCOPE_LINE_HEIGHT = 11.0
TILES_HEIGHT = 50.0
SECTION_GAP = 12.0
NOTE_SIZE = 7.5
NOTE_LINE_HEIGHT = 11.0
FOOTER_SIZE = 6.5
FOOTER_HEIGHT = 30.0


@dataclass(frozen=True)
class Tile:
    """
    A headline figure: its label, its value and a line beneath.
    """

    label: str
    value: str
    note: str


@dataclass(frozen=True)
class ReportContent:
    """
    Everything a report shows, as text: the header (the title, the account
    line naming the account and the Platform, the subtitle), the scope lines, the
    tiles, the table (the first key_columns columns keys, the rest figures;
    the Total row apart from the rows, None with no groups), the line shown
    in the table's place when it is empty, the notes after it and the
    footer's caveat (None for none).
    """

    title: str
    account_line: str
    subtitle: str
    scope_lines: list[str]
    tiles: list[Tile]
    headings: list[str]
    key_columns: int
    rows: list[list[str]]
    total: list[str] | None
    empty_text: str | None
    notes: list[str]
    caveat: str | None


@dataclass(frozen=True)
class TableFit:
    """
    The table as it will be drawn: its type size, each column's width
    (padding included), each heading's lines, and its rows and Total row,
    key texts shortened where they had to be.
    """

    size: float
    widths: list[float]
    heading_lines: list[list[str]]
    rows: list[list[str]]
    total: list[str] | None


@dataclass(frozen=True)
class PageGeometry:
    """
    A page's size and its margin on every side.
    """

    width: float
    height: float
    margin: float

    @property
    def content_width(self) -> float:
        return self.width - 2 * self.margin


@dataclass(frozen=True)
class Page:
    """
    One page of the plan: whether it is the first (the full header, the
    scope and the tiles), the data rows drawn on it, whether the table's
    headings are (any table on it) and its Total row are, whether the empty
    table's line is, and the notes' lines, after their title when
    notes_title.
    """

    number: int
    first: bool
    rows: range
    table: bool
    total: bool
    empty: bool
    notes: list[str]
    notes_title: bool


def heading_lines(heading: str) -> list[str]:
    """
    A column heading as drawn: a figure's name over its unit ('Running',
    '(h:mm)'); any other on one line.
    """
    name, space, unit = heading.rpartition(" (")
    if space and name and unit.endswith(")"):
        return [name, f"({unit}"]
    return [heading]


def _two_lines(heading: str) -> list[str]:
    """
    A key heading broken at the space nearest its middle ('Compute',
    'Requirement'); one word as it is.
    """
    spaces = [index for index, character in enumerate(heading) if character == " "]
    if not spaces:
        return [heading]
    middle = min(spaces, key=lambda index: abs(index - len(heading) / 2))
    return [heading[:middle], heading[middle + 1 :]]


def row_height(size: float) -> float:
    return size * ROW_LEADING


def heading_height(size: float) -> float:
    return 2 * size * HEADING_LEADING + size * 0.75


def top_height(first: bool, content: ReportContent) -> float:
    """
    The height above the table: the full header, the scope lines and the
    tiles on the first page; the slim header on the others.
    """
    if not first:
        return SLIM_HEADER_HEIGHT + SECTION_GAP
    return (
        HEADER_HEIGHT
        + SECTION_GAP
        + len(content.scope_lines) * SCOPE_LINE_HEIGHT
        + SECTION_GAP
        + (TILES_HEIGHT + SECTION_GAP if content.tiles else 0.0)
    )


def fit_table(content: ReportContent, measure: Measure, width: float) -> TableFit:
    """
    The table fitted to 'width': at TABLE_SIZE if it fits, else reduced
    until it does, down to TABLE_FLOOR; then the key columns' headings
    broken onto two lines, and their texts (the headings' lines too)
    shortened in the middle, the widest column first, to no fewer than
    MIN_KEY_CHARS characters; then, if it still does not fit, smaller type.
    Each column is as wide as its widest text in any row, so columns keep
    their widths from page to page.
    """
    lines = [heading_lines(heading) for heading in content.headings]
    rows = [list(row) for row in content.rows]
    total = list(content.total) if content.total is not None else None

    size = TABLE_SIZE
    widths = _widths(lines, rows, total, measure, size)
    while sum(widths) > width and size > TABLE_FLOOR:
        size = max(TABLE_FLOOR, size - SIZE_STEP)
        widths = _widths(lines, rows, total, measure, size)
    if sum(widths) > width:
        for column in range(content.key_columns):
            lines[column] = _two_lines(content.headings[column])
        widths = _widths(lines, rows, total, measure, size)
    if sum(widths) > width:
        lines, rows, total, widths = _shorten_keys(
            content, lines, measure, size, width, widths
        )
    while sum(widths) > width and size > TABLE_LAST_RESORT:
        size = max(TABLE_LAST_RESORT, size - SIZE_STEP)
        widths = _widths(lines, rows, total, measure, size)
    return TableFit(size, widths, lines, rows, total)


def _column_texts(
    column: int,
    lines: list[list[str]],
    rows: list[list[str]],
    total: list[str] | None,
) -> list[tuple[str, bool]]:
    """
    A column's texts and whether each is bold: its heading's lines, its
    cells and its Total.
    """
    texts = [(line, True) for line in lines[column]]
    texts += [(row[column], False) for row in rows]
    if total is not None:
        texts.append((total[column], True))
    return texts


def _column_width(
    texts: list[tuple[str, bool]], measure: Measure, size: float
) -> float:
    return max(measure(text, size, bold) for text, bold in texts) + 2 * CELL_PADDING


def _widths(
    lines: list[list[str]],
    rows: list[list[str]],
    total: list[str] | None,
    measure: Measure,
    size: float,
) -> list[float]:
    return [
        _column_width(_column_texts(column, lines, rows, total), measure, size)
        for column in range(len(lines))
    ]


def _shorten_keys(
    content: ReportContent,
    lines: list[list[str]],
    measure: Measure,
    size: float,
    width: float,
    widths: list[float],
) -> tuple[list[list[str]], list[list[str]], list[str] | None, list[float]]:
    """
    The key columns' texts shortened, the widest column by a character at a
    time, until the table fits or none can be shortened further.
    """
    widths = list(widths)
    caps = {
        column: max(
            len(text)
            for text, _ in _column_texts(column, lines, content.rows, content.total)
        )
        for column in range(content.key_columns)
    }
    shortest = MIN_KEY_CHARS + len(ELLIPSIS)

    def capped(texts: list[str], column_caps: dict[int, int]) -> list[str]:
        return [
            elide_middle(text, column_caps[column]) if column in column_caps else text
            for column, text in enumerate(texts)
        ]

    def shortened_column(column: int) -> list[tuple[str, bool]]:
        cap = caps[column]
        return [
            (elide_middle(text, cap), bold)
            for text, bold in _column_texts(column, lines, content.rows, content.total)
        ]

    while sum(widths) > width:
        candidates = [column for column, cap in caps.items() if cap > shortest]
        if not candidates:
            break
        column = max(candidates, key=lambda c: widths[c])
        caps[column] -= 1
        widths[column] = _column_width(shortened_column(column), measure, size)
    shortened = [
        [elide_middle(line, caps[column]) for line in column_lines]
        if column in caps
        else column_lines
        for column, column_lines in enumerate(lines)
    ]
    rows = [capped(row, caps) for row in content.rows]
    total = capped(content.total, caps) if content.total is not None else None
    return shortened, rows, total, widths


def wrap_text(text: str, measure: Measure, size: float, width: float) -> list[str]:
    """
    A text broken into lines at spaces, each within 'width'; a word wider
    than it (a URL in a warning) broken wherever it must be.
    """
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}" if line else word
        if measure(candidate, size, False) <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
        line = word
        while measure(line, size, False) > width and len(line) > 1:
            cut = len(line) - 1
            while cut > 1 and measure(line[:cut], size, False) > width:
                cut -= 1
            lines.append(line[:cut])
            line = line[cut:]
    if line:
        lines.append(line)
    return lines


def fitted_text(
    text: str, measure: Measure, size: float, bold: bool, width: float
) -> str:
    """
    A single line within 'width': as it is if it fits, else shortened in the
    middle with an ellipsis, keeping its start and its end.
    """
    if measure(text, size, bold) <= width:
        return text
    length = len(text)
    while length > len(ELLIPSIS) + 1:
        length -= 1
        shortened = elide_middle(text, length)
        if measure(shortened, size, bold) <= width:
            return shortened
    return ELLIPSIS


def plan_pages(
    content: ReportContent, fit: TableFit, geometry: PageGeometry, measure: Measure
) -> list[Page]:
    """
    The pages: the first holds the header, scope and tiles, then as many
    rows as fit; the rest the slim header, the table's headings again and
    their rows. The Total row is kept with the last data row, never alone at
    the top of a page. The notes follow the table, wrapped to the width,
    continuing onto further pages as needed.
    """
    bottom = geometry.height - geometry.margin - FOOTER_HEIGHT
    step = row_height(fit.size)
    pages: list[dict] = []

    def new_page(first: bool) -> dict:
        page = {
            "first": first,
            "rows": range(0),
            "table": False,
            "total": False,
            "empty": False,
            "notes": [],
            "notes_title": False,
            "y": geometry.margin + top_height(first, content),
        }
        pages.append(page)
        return page

    page = new_page(first=True)
    count = len(fit.rows)
    has_total = fit.total is not None
    if count == 0 and not has_total:
        page["empty"] = content.empty_text is not None
        page["y"] += step if page["empty"] else 0.0
    else:
        start = 0
        while True:
            table_top = page["y"] + heading_height(fit.size)
            capacity = max(1, int((bottom - table_top) // step))
            remaining = count - start
            if remaining + (1 if has_total else 0) <= capacity:
                take, total_here = remaining, has_total
            elif remaining <= capacity:
                # The rest fit, but not the Total too: one row goes with it
                take, total_here = max(0, remaining - 1), False
            else:
                take, total_here = capacity, False
            page["rows"] = range(start, start + take)
            page["table"] = True
            page["total"] = total_here
            page["y"] = table_top + (take + (1 if total_here else 0)) * step
            start += take
            if total_here or (not has_total and start >= count):
                break
            page = new_page(first=False)

    lines = [
        line
        for note in content.notes
        for line in wrap_text(note, measure, NOTE_SIZE, geometry.content_width)
    ]
    if lines:
        title_height = NOTE_LINE_HEIGHT + SECTION_GAP
        if page["y"] + title_height + NOTE_LINE_HEIGHT > bottom:
            page = new_page(first=False)
        page["notes_title"] = True
        page["y"] += title_height
        for line in lines:
            if page["y"] + NOTE_LINE_HEIGHT > bottom:
                page = new_page(first=False)
            page["notes"].append(line)
            page["y"] += NOTE_LINE_HEIGHT

    return [
        Page(
            number=number,
            first=page["first"],
            rows=page["rows"],
            table=page["table"],
            total=page["total"],
            empty=page["empty"],
            notes=page["notes"],
            notes_title=page["notes_title"],
        )
        for number, page in enumerate(pages, start=1)
    ]


def period_text(from_iso: str, until_iso: str) -> str:
    """
    The report's period for its subtitle: 'October 2026' for a window of
    exactly one UTC calendar month, else its two times to the minute
    ('2026-11-19 10:57 → 2026-11-26 10:57 UTC'). Month names are English
    whatever the locale, as the rest of the report is.
    """
    try:
        start = report_time(from_iso).astimezone(timezone.utc)
        end = report_time(until_iso).astimezone(timezone.utc)
    except ValueError:
        start = end = None
    if (
        start is not None
        and end is not None
        and start.day == 1
        and (start.hour, start.minute, start.second, start.microsecond) == (0, 0, 0, 0)
    ):
        # Only now: on a later day, the next month may have no such day
        following = (
            start.replace(year=start.year + 1, month=1)
            if start.month == 12
            else start.replace(month=start.month + 1)
        )
        if end == following:
            return f"{_MONTHS[start.month - 1]} {start.year}"
    shown_from = window_time(from_iso).removesuffix(" UTC")
    return f"{shown_from} → {window_time(until_iso)}"


def report_content(
    document: dict,
    levels: tuple[Level, ...],
    headings: list[str],
    key_columns: int,
    rows: list[list[str]],
    total: list[str] | None,
    total_by_heading: dict[str, str] | None,
    cost: bool,
    notes: list[str],
) -> ReportContent:
    """
    The report of a view: 'document' its `yd usage --json` document,
    'levels' its breadcrumb, 'headings', 'rows' and 'total' its visible
    columns as displayed (the first key_columns keys), 'total_by_heading'
    the Total row of every column (None with no groups), which the tiles
    read whether or not their columns are visible, 'cost' whether the view
    has cost, and 'notes' the lines printed after the table. Every figure is
    the table's own text; nothing about cost when 'cost' is false.
    """
    namespace = document.get("namespace")
    period = period_text(str(document.get("from", "")), str(document.get("until", "")))
    window = (
        f"{window_time(str(document.get('from', ''))).removesuffix(' UTC')} →"
        f" {window_time(str(document.get('until', '')))}"
    )
    scope_lines = [
        f"Window: {window} · "
        + (f"Namespace: {namespace}" if namespace else "All namespaces"),
        "Totalled by " + ", ".join(headings[:key_columns]),
    ]
    if len(levels) > 1:
        scope_lines.append(
            "Within: " + DRILL_SEPARATOR.join(level.label for level in levels[1:])
        )
    scope_lines.append(
        f"Report fetched {window_time(str(document.get('fetched', '')))}"
    )
    return ReportContent(
        title=REPORT_TITLE if cost else REPORT_TITLE_WITHOUT_COST,
        account_line=" · ".join(
            part
            for part in (
                f"Account: {document['accountName']}"
                if document.get("accountName")
                else "",
                str(document.get("url") or ""),
            )
            if part
        ),
        subtitle=f"{period} · {namespace or 'all namespaces'}",
        scope_lines=scope_lines,
        tiles=_tiles(document, total_by_heading, len(rows), cost),
        headings=headings,
        key_columns=key_columns,
        rows=rows,
        total=total,
        empty_text=None
        if rows
        else (NO_MATCHING_INSTANCES if document.get("where") else NO_INSTANCES),
        notes=notes,
        caveat=COST_CAVEAT if cost else None,
    )


def _tiles(
    document: dict, total: dict[str, str] | None, groups: int, cost: bool
) -> list[Tile]:
    """
    The headline tiles from the Total row's cells, found by their headings'
    names ('Running' of 'Running (h:mm)'): the cost (or, without it, the
    total time), the running time and the Instances.
    """
    by_name = {
        heading_lines(heading)[0]: cell for heading, cell in (total or {}).items()
    }
    # Grouped by Instance ID there is no Instances column: each row is one
    instances = Tile(
        "Instances",
        by_name.get("Instances", f"{groups:,}"),
        f"in {groups:,} group{'' if groups == 1 else 's'}",
    )
    running = Tile("Running", by_name.get("Running", "0:00"), "hours:minutes")
    if not cost:
        return [
            Tile("Total time", by_name.get("Total", "0:00"), "hours:minutes"),
            running,
            instances,
        ]
    currency = str(document.get("currency") or "USD")
    figure = by_name.get("Est. cost", "0.00")
    value = f"${figure}" if currency == "USD" else f"{figure} {currency}"
    return [
        Tile("Estimated cost", value, f"{currency}, list prices"),
        running,
        instances,
    ]
