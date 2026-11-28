"""
The Usage Explorer's PDF report drawn (commander/usage_pdf.py): a PDF file
written with Qt, one page per page planned, A4 or US Letter by the system's
measurement system, landscape when asked, and an unwritable path an OSError.
The layout itself is test_commander_usage_report_layout.py's.
"""

import re

import qt_guard

qt_guard.require_qt()

import pytest
from PyQt6.QtCore import QLocale
from PyQt6.QtGui import QPageSize

from yellowdog_cli.commander import usage_pdf
from yellowdog_cli.commander.usage_pdf import page_size, write_pdf
from yellowdog_cli.commander.usage_report_layout import (
    COST_CAVEAT,
    ReportContent,
    Tile,
)


def report(rows: int = 4, cost: bool = True) -> ReportContent:
    headings = [
        "Compute Requirement",
        "Instances",
        "Running (h:mm)",
        "Stopped (h:mm)",
        "Total (h:mm)",
        *(["Est. cost (USD)"] if cost else []),
    ]
    data = [
        [f"render-{n}", "3", "12:00", "0:30", "12:30", *(["61.43"] if cost else [])]
        for n in range(rows)
    ]
    return ReportContent(
        title="Compute Usage and Cost",
        account_line="YellowDog Production · https://api.yellowdog.ai",
        subtitle="October 2026 · team-render",
        scope_lines=[
            "Window: 2026-10-01 00:00 → 2026-11-01 00:00 UTC · Namespace: team-render",
            "Totalled by Compute Requirement",
            "Report fetched 2026-11-01 09:30 UTC",
        ],
        tiles=[
            Tile("Estimated cost", "$245.72", "USD, list prices"),
            Tile("Running time", "48:00", "hours:minutes"),
            Tile("Instances", "12", f"in {rows} groups"),
        ],
        headings=headings,
        key_columns=1,
        rows=data,
        total=["Total", "12", "48:00", "2:00", "50:00", *(["245.72"] if cost else [])],
        empty_text=None,
        notes=["⚠ 1 instance type had no list price (0:42 running)"],
        caveat=COST_CAVEAT if cost else None,
    )


def pages_of(path) -> int:
    return len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", path.read_bytes()))


def media_box(path) -> tuple[float, float]:
    match = re.search(
        rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)", path.read_bytes()
    )
    assert match is not None
    return float(match.group(1)), float(match.group(2))


def test_a_pdf_is_written(qapp, tmp_path):
    target = tmp_path / "usage.pdf"
    assert write_pdf(str(target), report(), landscape=False) == 1
    assert target.read_bytes().startswith(b"%PDF")
    assert pages_of(target) == 1


def test_many_rows_make_many_pages(qapp, tmp_path):
    target = tmp_path / "usage.pdf"
    count = write_pdf(str(target), report(rows=300), landscape=False)
    assert count > 1
    assert pages_of(target) == count


def test_landscape_pages_are_wider_than_tall(qapp, tmp_path):
    portrait = tmp_path / "portrait.pdf"
    landscape = tmp_path / "landscape.pdf"
    write_pdf(str(portrait), report(), landscape=False)
    write_pdf(str(landscape), report(), landscape=True)
    width, height = media_box(portrait)
    assert width < height
    width, height = media_box(landscape)
    assert width > height


def test_a_report_without_cost_is_written(qapp, tmp_path):
    target = tmp_path / "usage.pdf"
    assert write_pdf(str(target), report(cost=False), landscape=False) == 1


@pytest.mark.parametrize(
    "territory, size",
    [
        (QLocale.Country.UnitedStates, QPageSize.PageSizeId.Letter),
        (QLocale.Country.UnitedKingdom, QPageSize.PageSizeId.A4),
    ],
)
def test_page_size_follows_the_measurement_system(monkeypatch, territory, size):
    locale = QLocale(QLocale.Language.English, territory)
    monkeypatch.setattr(usage_pdf, "system_locale", lambda: locale)
    assert page_size().id() == size


def test_an_unwritable_path_raises_oserror(qapp, tmp_path):
    with pytest.raises(OSError, match="missing"):
        write_pdf(str(tmp_path / "missing" / "usage.pdf"), report(), landscape=False)


def test_no_line_is_wider_than_its_space(qapp, tmp_path, monkeypatch):
    from dataclasses import replace

    from PyQt6.QtGui import QFontMetricsF

    long_name = "team-" + "render-farm-" * 6
    content = replace(
        report(rows=3),
        subtitle=f"2026-11-19 10:57 → 2026-11-26 10:57 UTC · {long_name}",
        scope_lines=[
            f"Window: 2026-11-19 10:57 → 2026-11-26 10:57 UTC · Namespace: {long_name}",
            "Totalled by Compute Requirement",
            f"Within: {long_name} \u203a {long_name}",
            "Report fetched 2026-11-26 10:58 UTC",
        ],
        notes=["See https://example.com/" + "x" * 400 + " for the details"],
    )
    overflows: list[str] = []
    real = usage_pdf._Drawing._draw

    def recorded(self, rect, flags, text, wrap):
        metrics = QFontMetricsF(self.painter.font(), self.painter.device())
        width = metrics.horizontalAdvance(text)
        if not wrap and width > rect.width() + 0.5:
            overflows.append(f"{text!r}: {width:.0f} > {rect.width():.0f}")
        real(self, rect, flags, text, wrap)

    monkeypatch.setattr(usage_pdf._Drawing, "_draw", recorded)
    write_pdf(str(tmp_path / "usage.pdf"), content, landscape=False)
    write_pdf(str(tmp_path / "usage-wide.pdf"), report(rows=300), landscape=False)
    assert overflows == []


def _tile_figures_drawn(
    tmp_path, monkeypatch, figure: str
) -> list[tuple[str, float, float, float]]:
    """
    Each text drawn that is 'figure' (an Estimated cost tile's), on one line
    or several, with its widest line's width, its room and its size, from a
    report whose other tiles are long too.
    """
    from dataclasses import replace

    from PyQt6.QtGui import QFontMetricsF

    content = replace(
        report(),
        tiles=[
            Tile("Estimated cost", figure, "USD, list prices"),
            Tile("Running time", "1,234,567:00", "hours:minutes"),
            Tile("Total time", "1,234,567:00", "hours:minutes, all statuses"),
            Tile("Instances", "1,508,498", "in 872 rows"),
        ],
    )
    drawn: list[tuple[str, float, float, float]] = []
    real = usage_pdf._Drawing._draw

    def recorded(self, rect, flags, text, wrap):
        font = self.painter.font()
        metrics = QFontMetricsF(font, self.painter.device())
        widest = max(metrics.horizontalAdvance(line) for line in text.split("\n"))
        drawn.append((text, widest, rect.width(), font.pointSizeF()))
        real(self, rect, flags, text, wrap)

    monkeypatch.setattr(usage_pdf._Drawing, "_draw", recorded)
    write_pdf(str(tmp_path / "usage.pdf"), content, landscape=False)
    return [d for d in drawn if d[0].replace("\n", "") == figure]


def test_a_tiles_long_figure_is_drawn_whole_in_smaller_type(
    qapp, tmp_path, monkeypatch
):
    # Fonts differ by platform: where even the floor is too wide, as on
    # Windows, the figure is wrapped there
    [(_, width, room, size)] = _tile_figures_drawn(
        tmp_path, monkeypatch, "$12,345,678.90+"
    )
    assert size < usage_pdf.TILE_VALUE_SIZE
    assert width <= room + 0.5


def test_a_tiles_figure_too_long_for_the_floor_is_wrapped_whole(
    qapp, tmp_path, monkeypatch
):
    [(text, width, room, size)] = _tile_figures_drawn(
        tmp_path, monkeypatch, "$123,456,789,012,345,678.90+"
    )
    assert size == usage_pdf.TILE_VALUE_FLOOR
    # Two lines here, three in the Windows runner's wider font
    lines = text.split("\n")
    assert len(lines) >= 2
    assert all(line.endswith(",") for line in lines[:-1])
    assert width <= room + 0.5
