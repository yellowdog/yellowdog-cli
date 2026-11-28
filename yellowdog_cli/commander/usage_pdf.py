"""
The Usage Explorer's PDF report, drawn: the pages usage_report_layout plans,
painted with QPainter on a QPdfWriter at 72 dots an inch, so that a unit is
a point. The YellowDog dog from its SVG, as vector art; light colours
always, since a report is printed on white.
"""

from collections.abc import Callable
from functools import cache

from PyQt6.QtCore import QLocale, QMarginsF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPageLayout,
    QPageSize,
    QPaintDevice,
    QPainter,
    QPdfWriter,
    QPen,
)
from PyQt6.QtSvg import QSvgRenderer

from yellowdog_cli.commander.branding import BRANDING_IMAGE
from yellowdog_cli.commander.usage_report_layout import (
    ACCOUNT_SIZE,
    CELL_PADDING,
    FOOTER_HEIGHT,
    FOOTER_SIZE,
    HEADER_HEIGHT,
    NOTE_LINE_HEIGHT,
    NOTE_SIZE,
    SCOPE_LINE_HEIGHT,
    SCOPE_SIZE,
    SECTION_GAP,
    SLIM_HEADER_HEIGHT,
    SUBTITLE_SIZE,
    TILES_HEIGHT,
    TITLE_SIZE,
    Measure,
    Page,
    PageGeometry,
    ReportContent,
    TableFit,
    fit_table,
    fitted_text,
    fitting_size,
    heading_height,
    plan_pages,
    row_height,
)

# A unit is a point
RESOLUTION = 72
MARGIN = 42.0
YELLOW = "#FAB842"
INK = "#222222"
MUTED = "#666666"
FAINT = "#888888"
RULE_GREY = "#cccccc"
TILE_BORDER = "#e2e2e2"
ROW_SHADE = "#f7f7f5"
YELLOW_RULE = 2.5
TABLE_RULE = 1.2
LOGO_WIDTH = 34.0
SLIM_LOGO_WIDTH = 22.0
# Between the header's text and the logo
LOGO_GAP = 12.0
# The logo's height for its width, as the SVG is drawn
LOGO_ASPECT = 44 / 49
TILE_GAP = 8.0
TILE_RADIUS = 4.0
# A tile's figure, in points: smaller, to the floor, where it is too long
TILE_VALUE_SIZE = 14.0
TILE_VALUE_FLOOR = 8.0


def system_locale() -> QLocale:
    """
    The system's locale; a function so that a test can stand another in.
    """
    return QLocale.system()


def page_size() -> QPageSize:
    """
    US Letter where the system measures in US units, A4 elsewhere.
    """
    if (
        system_locale().measurementSystem()
        == QLocale.MeasurementSystem.ImperialUSSystem
    ):
        return QPageSize(QPageSize.PageSizeId.Letter)
    return QPageSize(QPageSize.PageSizeId.A4)


def qt_measure(family: str, device: QPaintDevice) -> Measure:
    """
    Text widths in the device's units (points, on the report's writer) in
    'family' at a size, bold or not.
    """
    metrics = _metrics_for(family, device)
    return lambda text, size, bold: metrics(size, bold).horizontalAdvance(text)


def _metrics_for(
    family: str, device: QPaintDevice
) -> Callable[[float, bool], QFontMetricsF]:
    @cache
    def metrics(size: float, bold: bool) -> QFontMetricsF:
        return QFontMetricsF(_font(family, size, bold), device)

    return metrics


def _font(family: str, size: float, bold: bool = False) -> QFont:
    font = QFont(family)
    font.setPointSizeF(size)
    font.setBold(bold)
    return font


def write_pdf(path: str, content: ReportContent, landscape: bool) -> int:
    """
    The report written to 'path' as a PDF, its page count returned; an
    OSError if the file cannot be written.
    """
    writer = QPdfWriter(path)
    writer.setResolution(RESOLUTION)
    writer.setPageSize(page_size())
    writer.setPageOrientation(
        QPageLayout.Orientation.Landscape
        if landscape
        else QPageLayout.Orientation.Portrait
    )
    writer.setPageMargins(QMarginsF(0, 0, 0, 0))
    writer.setTitle(content.title)
    writer.setCreator("YellowDog CLI")
    painter = QPainter()
    if not painter.begin(writer):
        raise OSError(f"Cannot write '{path}'")
    try:
        rect = writer.pageLayout().fullRectPoints()
        geometry = PageGeometry(float(rect.width()), float(rect.height()), MARGIN)
        family = QFont().defaultFamily()
        measure = qt_measure(family, writer)
        fit = fit_table(content, measure, geometry.content_width)
        pages = plan_pages(content, fit, geometry, measure)
        drawing = _Drawing(painter, family, measure, content, fit, geometry, len(pages))
        for index, page in enumerate(pages):
            if index:
                writer.newPage()
            drawing.page(page)
    finally:
        painter.end()
    return len(pages)


class _Drawing:
    """
    One report's pages painted: each part at the place plan_pages() left it.
    """

    def __init__(
        self,
        painter: QPainter,
        family: str,
        measure: Measure,
        content: ReportContent,
        fit: TableFit,
        geometry: PageGeometry,
        page_count: int,
    ) -> None:
        self.painter = painter
        self.family = family
        self.measure = measure
        self.content = content
        self.fit = fit
        self.geometry = geometry
        self.page_count = page_count
        self.left = geometry.margin
        self.width = geometry.content_width
        # The table spans the width: what the columns leave is shared out
        spare = max(0.0, self.width - sum(fit.widths)) / max(1, len(fit.widths))
        self.widths = [width + spare for width in fit.widths]

    # Text and lines ---------------------------------------------------------

    def _text(
        self,
        rect: QRectF,
        text: str,
        size: float,
        colour: str = INK,
        bold: bool = False,
        align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
        wrap: bool = False,
        whole: bool = False,
    ) -> None:
        """
        A text in 'rect': wrapped, or on one line shortened in the middle to
        fit, or with 'whole' (a figure) drawn as it is and never clipped.
        """
        self.painter.setFont(_font(self.family, size, bold))
        self.painter.setPen(QColor(colour))
        flags = align | Qt.AlignmentFlag.AlignVCenter
        if wrap:
            flags |= Qt.TextFlag.TextWordWrap
        elif whole:
            flags |= Qt.TextFlag.TextDontClip
        else:
            # A single line is never clipped: shortened in the middle instead
            text = fitted_text(text, self.measure, size, bold, rect.width())
        self._draw(rect, flags, text, wrap)

    def _draw(
        self, rect: QRectF, flags: Qt.AlignmentFlag, text: str, wrap: bool
    ) -> None:
        """
        A text as it reaches the page, in the painter's font: the one place
        text is drawn.
        """
        self.painter.drawText(rect, int(flags.value), text)

    def _rule(self, y: float, thickness: float, colour: str) -> None:
        self.painter.fillRect(
            QRectF(self.left, y, self.width, thickness), QColor(colour)
        )

    def _logo(self, width: float, top: float, height: float) -> None:
        logo_height = width * LOGO_ASPECT
        QSvgRenderer(BRANDING_IMAGE).render(
            self.painter,
            QRectF(
                self.left + self.width - width,
                top + (height - logo_height) / 2,
                width,
                logo_height,
            ),
        )

    # A page -----------------------------------------------------------------

    def page(self, page: Page) -> None:
        y = self.geometry.margin
        if page.first:
            y = self._header(y)
            y = self._scope(y)
            y = self._tiles(y)
        else:
            y = self._slim_header(y)
        if page.table:
            y = self._table(page, y)
        if page.empty and self.content.empty_text:
            step = row_height(self.fit.size)
            self._text(
                QRectF(self.left, y, self.width, step),
                self.content.empty_text,
                self.fit.size,
                MUTED,
            )
            y += step
        if page.notes_title or page.notes:
            y = self._notes(page, y)
        self._footer(page)

    def _header(self, top: float) -> float:
        title_height = TITLE_SIZE * 1.4
        # Clear of the logo at the right
        width = self.width - LOGO_WIDTH - LOGO_GAP
        self._text(
            QRectF(self.left, top, width, title_height),
            self.content.title,
            TITLE_SIZE,
            bold=True,
        )
        account_height = ACCOUNT_SIZE * 1.6
        self._text(
            QRectF(self.left, top + title_height, width, account_height),
            self.content.account_line,
            ACCOUNT_SIZE,
            FAINT,
        )
        self._text(
            QRectF(
                self.left,
                top + title_height + account_height,
                width,
                SUBTITLE_SIZE * 1.6,
            ),
            self.content.subtitle,
            SUBTITLE_SIZE,
            MUTED,
        )
        self._logo(LOGO_WIDTH, top, HEADER_HEIGHT - YELLOW_RULE - 6)
        self._rule(top + HEADER_HEIGHT - YELLOW_RULE, YELLOW_RULE, YELLOW)
        return top + HEADER_HEIGHT + SECTION_GAP

    def _slim_header(self, top: float) -> float:
        line = QRectF(
            self.left,
            top,
            self.width - SLIM_LOGO_WIDTH - LOGO_GAP,
            SLIM_HEADER_HEIGHT - YELLOW_RULE - 4,
        )
        self._text(
            line,
            f"{self.content.title} · {self.content.subtitle}",
            SUBTITLE_SIZE,
            MUTED,
        )
        self._logo(SLIM_LOGO_WIDTH, top, line.height())
        self._rule(top + SLIM_HEADER_HEIGHT - YELLOW_RULE, YELLOW_RULE, YELLOW)
        return top + SLIM_HEADER_HEIGHT + SECTION_GAP

    def _scope(self, top: float) -> float:
        y = top
        for line in self.content.scope_lines:
            self._text(
                QRectF(self.left, y, self.width, SCOPE_LINE_HEIGHT),
                line,
                SCOPE_SIZE,
                "#555555",
            )
            y += SCOPE_LINE_HEIGHT
        return y + SECTION_GAP

    def _tiles(self, top: float) -> float:
        tiles = self.content.tiles
        if not tiles:
            return top
        width = (self.width - TILE_GAP * (len(tiles) - 1)) / len(tiles)
        for index, tile in enumerate(tiles):
            x = self.left + index * (width + TILE_GAP)
            box = QRectF(x, top, width, TILES_HEIGHT)
            self.painter.setPen(QPen(QColor(TILE_BORDER), 0.8))
            self.painter.setBrush(Qt.BrushStyle.NoBrush)
            self.painter.drawRoundedRect(box, TILE_RADIUS, TILE_RADIUS)
            inner = x + 8
            inner_width = width - 16
            self._text(
                QRectF(inner, top + 5, inner_width, 10),
                tile.label.upper(),
                6.5,
                "#777777",
            )
            # A figure is never shortened: smaller type where it is long, and
            # whole at the floor where even that is too wide for the tile
            size = fitting_size(
                tile.value,
                self.measure,
                TILE_VALUE_SIZE,
                TILE_VALUE_FLOOR,
                True,
                inner_width,
            )
            self._text(
                QRectF(inner, top + 15, inner_width, 20),
                tile.value,
                size,
                bold=True,
                whole=True,
            )
            self._text(QRectF(inner, top + 35, inner_width, 10), tile.note, 6.5, FAINT)
        return top + TILES_HEIGHT + SECTION_GAP

    def _cells(self, top: float, height: float, texts: list[str], bold: bool) -> None:
        x = self.left
        for column, (text, width) in enumerate(zip(texts, self.widths)):
            key = column < self.content.key_columns
            self._text(
                QRectF(x + CELL_PADDING, top, width - 2 * CELL_PADDING, height),
                text,
                self.fit.size,
                bold=bold,
                align=Qt.AlignmentFlag.AlignLeft
                if key
                else Qt.AlignmentFlag.AlignRight,
            )
            x += width

    def _table(self, page: Page, top: float) -> float:
        size = self.fit.size
        height = heading_height(size)
        line = size * 1.25
        x = self.left
        for column, (lines, width) in enumerate(
            zip(self.fit.heading_lines, self.widths)
        ):
            key = column < self.content.key_columns
            align = Qt.AlignmentFlag.AlignLeft if key else Qt.AlignmentFlag.AlignRight
            # Bottom-aligned: a one-line heading on the second line
            first = top + height - line * len(lines) - size * 0.4
            for number, text in enumerate(lines):
                self._text(
                    QRectF(
                        x + CELL_PADDING,
                        first + number * line,
                        width - 2 * CELL_PADDING,
                        line,
                    ),
                    text,
                    size,
                    bold=True,
                    align=align,
                )
            x += width
        y = top + height
        self._rule(y - TABLE_RULE, TABLE_RULE, INK)
        step = row_height(size)
        for row in page.rows:
            if row % 2:
                self.painter.fillRect(
                    QRectF(self.left, y, self.width, step), QColor(ROW_SHADE)
                )
            self._cells(y, step, self.fit.rows[row], bold=False)
            y += step
        if page.total and self.fit.total is not None:
            self._rule(y, TABLE_RULE, INK)
            self._cells(y + TABLE_RULE, step, self.fit.total, bold=True)
            y += step
        return y

    def _notes(self, page: Page, top: float) -> float:
        y = top
        if page.notes_title:
            y += SECTION_GAP
            self._text(
                QRectF(self.left, y, self.width, NOTE_LINE_HEIGHT),
                "Notes",
                NOTE_SIZE + 0.5,
                bold=True,
            )
            y += NOTE_LINE_HEIGHT
        for line in page.notes:
            self._text(
                QRectF(self.left, y, self.width, NOTE_LINE_HEIGHT),
                line,
                NOTE_SIZE,
                "#444444",
            )
            y += NOTE_LINE_HEIGHT
        return y

    def _footer(self, page: Page) -> None:
        top = self.geometry.height - self.geometry.margin - FOOTER_HEIGHT + 4
        self._rule(top, 0.6, RULE_GREY)
        number = f"Page {page.number} of {self.page_count}"
        number_width = 60.0
        if self.content.caveat:
            self._text(
                QRectF(
                    self.left, top + 3, self.width - number_width - 8, FOOTER_HEIGHT - 6
                ),
                self.content.caveat,
                FOOTER_SIZE,
                "#777777",
                wrap=True,
            )
        self._text(
            QRectF(self.left + self.width - number_width, top + 3, number_width, 12),
            number,
            FOOTER_SIZE,
            "#777777",
            align=Qt.AlignmentFlag.AlignRight,
        )
