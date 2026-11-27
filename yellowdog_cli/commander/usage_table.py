"""
The Usage Explorer's table model: one row per group of a `yd usage --json`
document, its cells as the CLI writes them (usage_views.row_cells()), and the
document's own total as the last row. Commander sorts and adds up nothing:
the rows arrive in the CLI's order and the Total row is the CLI's 'total'.
"""

from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget

from yellowdog_cli.commander.usage_report_layout import COST_NOTE, direction_text
from yellowdog_cli.commander.usage_views import (
    INSTANCE_LEVEL,
    heading,
    row_cells,
    share_basis,
)

# The value columns after the key columns, and the '--sort' key of each
VALUE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("Instances", "instances"),
    ("Running", "running"),
    ("Stopped", "stopped"),
    ("Total", "total"),
)
# The cost column's heading, with the document's currency, as yd usage writes it
COST_HEADING = "Est. cost ({currency})"
COST_SORT_KEY = "cost"
# Each row's share of the total: of the cost where the view has it, else of
# the time, sorting as the figure it is a share of
SHARE_KEY = "share"
SHARE_HEADING = "Share"
SHARE_OF_COST_HEADING = "Share of cost"
SHARE_OF_TIME_HEADING = "Share of time"
RAW_SHARE_HEADING = "{heading} (fraction)"
# What the estimate leaves out, said on its heading
COST_TOOLTIP = COST_NOTE
# The status columns after the cost, in row_cells()'s order, hidden at first
STATUS_COLUMNS: tuple[str, ...] = ("pending", "stopping", "terminating", "unknown")
# The figure columns a right-click may hide, in the order shown: all but the
# cost, which the Estimated cost checkbox adds and removes
HIDEABLE_COLUMNS: tuple[str, ...] = (
    *(key for _, key in VALUE_COLUMNS),
    SHARE_KEY,
    *STATUS_COLUMNS,
)
TOTAL_LABEL = "Total"
# The row summing the groups '--top' left out, as yd usage's own table labels it
MORE_LABEL = "({count:,} more)"
MORE_TOOLTIP = (
    "The rows past the first, summed: Show All shows them, and sorting by"
    " another column brings others to the top"
)
# A time column's heading in the table and the shown export, saying how its
# cells read, as yd usage's own table heads them
DURATION_HEADING = "{heading} (h:mm)"
# The raw export's headings beyond the key columns: the figures as yd usage
# --json gives them, hours as decimals and the cost as a number, and the
# running time no price covered, which the shown cost's '+' marks
RAW_HOURS_HEADING = "{heading} (hours)"
UNPRICED_HEADING = "Unpriced running (hours)"

_Index = QModelIndex | QPersistentModelIndex


def figure_heading(key: str) -> str:
    """
    A figure column's heading: a value column's own, else the key's.
    """
    if key == SHARE_KEY:
        return SHARE_HEADING
    return dict((k, name) for name, k in VALUE_COLUMNS).get(key) or heading(key)


_SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh")


def superscript(number: int) -> str:
    return str(number).translate(_SUPERSCRIPT)


def ordinal(number: int) -> str:
    """
    'second' for 2, up to 'seventh'; '8th' and on past it.
    """
    return _ORDINALS[number - 1] if number <= len(_ORDINALS) else f"{number}th"


class UsageTableModel(QAbstractTableModel):
    """
    A document's groups as rows, then its total. Key columns are aligned left
    and figures right; only the Total row's label is bold.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._by: list[str] = []
        self._cost = False
        self._groups: list[dict] = []
        self._rows: list[list[str]] = []
        # The figure columns shown, in order (no 'instances' at the Instance
        # level, where every row is one Instance)
        self._figures: list[str] = []
        # The document's dict behind each row, the total's last
        self._sources: list[dict] = []
        self._headings: list[str] = []
        self._has_total = False
        # The label of the row summing what '--top' left out (None for none)
        self._more_label: str | None = None
        # What a group's row says it leads to (None: nowhere)
        self._row_tooltip: str | None = None
        # The sort keys after the first (whose column the header's own
        # indicator marks): each key's place and whether the most or Z first
        self._sort_marks: dict[str, tuple[int, bool]] = {}

    def set_document(self, document: dict, cost: bool) -> None:
        """
        Show a document's groups and total; 'cost' says whether it was asked
        for with '--cost'. Raises KeyError, TypeError or ValueError for a
        document not shaped as `yd usage --json` writes it, leaving the table
        as it was.
        """
        by = [str(key) for key in document["by"]]
        groups = [dict(group) for group in document["groups"]]
        # Grouped by Instance ID, each row is one Instance: no Instances column
        counts = INSTANCE_LEVEL not in by
        rows = [self._cells(group, by, cost, counts) for group in groups]
        sources = list(groups)
        more = document.get("more")
        more_label = None
        if isinstance(more, dict):
            more_label = MORE_LABEL.format(count=int(more["groups"]))
            cells = self._cells(more, by, cost, counts)
            cells[: len(by)] = [more_label] + [""] * (len(by) - 1)
            rows.append(cells)
            sources.append(dict(more))
        total = document.get("total")
        if groups and isinstance(total, dict):
            cells = self._cells(total, by, cost, counts)
            cells[: len(by)] = [TOTAL_LABEL] + [""] * (len(by) - 1)
            rows.append(cells)
            sources.append(dict(total))
        figures = [key for _, key in VALUE_COLUMNS if counts or key != "instances"]
        figures += [COST_SORT_KEY] if cost else []
        figures += [SHARE_KEY, *STATUS_COLUMNS]
        self.beginResetModel()
        self._by, self._cost, self._groups, self._rows = by, cost, groups, rows
        self._figures = figures
        self._sources = sources
        self._more_label = more_label
        self._has_total = len(rows) > len(groups) + (more_label is not None)
        self._headings = [heading(key) for key in by] + [
            self._figure_heading(key, document, cost) for key in figures
        ]
        self.endResetModel()

    @staticmethod
    def _cells(row: dict, by: list[str], cost: bool, counts: bool) -> list[str]:
        """
        A row's cells, as row_cells() gives them, less the Instances cell
        where there is no Instances column.
        """
        cells = row_cells(row, by, cost)
        if not counts:
            del cells[len(by)]
        return cells

    @staticmethod
    def _figure_heading(key: str, document: dict, cost: bool) -> str:
        if key == SHARE_KEY:
            return SHARE_OF_COST_HEADING if cost else SHARE_OF_TIME_HEADING
        if key == "instances":
            return figure_heading(key)
        if key == COST_SORT_KEY:
            return COST_HEADING.format(currency=document["currency"])
        return DURATION_HEADING.format(heading=figure_heading(key))

    def text_rows(self, columns: list[int]) -> list[list[str]]:
        """
        The given columns' headings, then every row's cells (the Total row's
        too), as the table shows them.
        """
        return [
            [self._headings[column] for column in columns],
            *([row[column] for column in columns] for row in self._rows),
        ]

    def raw_rows(self, columns: list[int]) -> list[list[str]]:
        """
        As text_rows(), but each figure as the document gives it: Instances
        a count, times in decimal hours (headed so), the cost a number (empty
        with nothing priced), followed by the running hours no price covered.
        """
        headings: list[str] = []
        for column in columns:
            figure = self._figure(column)
            if figure == SHARE_KEY:
                headings.append(
                    RAW_SHARE_HEADING.format(heading=self._headings[column])
                )
            elif figure in (None, "instances", COST_SORT_KEY):
                headings.append(self._headings[column])
            else:
                headings.append(
                    RAW_HOURS_HEADING.format(heading=figure_heading(figure))
                )
            if figure == COST_SORT_KEY:
                headings.append(UNPRICED_HEADING)
        rows = [headings]
        for index, source in enumerate(self._sources):
            total = self._has_total and index == len(self._sources) - 1
            label = TOTAL_LABEL if total else None
            if self.is_more(index):
                label = self._more_label
            row: list[str] = []
            for column in columns:
                figure = self._figure(column)
                if figure is None:
                    key = self._by[column]
                    row.append(
                        (label if column == 0 else "")
                        if label is not None
                        else str(source.get(key, ""))
                    )
                elif figure == "instances":
                    row.append(str(source.get("instances", 0)))
                elif figure == SHARE_KEY:
                    share = (source.get("share") or {}).get(share_basis(self._cost))
                    row.append("" if share is None else str(share))
                elif figure == COST_SORT_KEY:
                    cost = source.get("estimatedCost")
                    row.append("" if cost is None else str(cost))
                    row.append(str(source.get("unpricedRunningHours", 0)))
                else:
                    row.append(str(source.get("hours", {}).get(figure, 0)))
            rows.append(row)
        return rows

    def _figure(self, column: int) -> str | None:
        """
        The figure a column shows ('instances', a state or 'total' for its
        hours, or 'cost'); None for a key column.
        """
        if column < len(self._by):
            return None
        return self._figures[column - len(self._by)]

    def clear(self) -> None:
        self.beginResetModel()
        self._by, self._groups, self._rows, self._headings = [], [], [], []
        self._figures = []
        self._sources = []
        self._more_label = None
        self._has_total = False
        self.endResetModel()

    @property
    def by(self) -> list[str]:
        return list(self._by)

    def group(self, row: int) -> dict | None:
        """
        The document's group a row shows; None for the Total row and the
        row summing what '--top' left out.
        """
        return self._groups[row] if 0 <= row < len(self._groups) else None

    @property
    def has_total(self) -> bool:
        """
        Whether the last row is the Total row (none with no groups).
        """
        return self._has_total

    def is_total(self, row: int) -> bool:
        return self._has_total and row == len(self._rows) - 1

    def set_row_tooltip(self, text: str | None) -> None:
        """
        The tooltip of every group's row: what double-clicking it shows.
        """
        self._row_tooltip = text

    def is_more(self, row: int) -> bool:
        """
        Whether a row is the one summing the groups '--top' left out.
        """
        return self._more_label is not None and row == len(self._groups)

    @property
    def more_label(self) -> str | None:
        return self._more_label

    def sort_key(self, column: int) -> str | None:
        """
        The '--sort' key of a column: a key column's own key, a figure's
        name (the share's, the figure it is a share of); None for a status
        column, which the CLI does not sort by. Read from the column's own
        figure, since the Instances column comes and goes.
        """
        if column < len(self._by):
            return self._by[column]
        figure = self._figure(column)
        if figure == SHARE_KEY:
            return COST_SORT_KEY if self._cost else "total"
        sortable = {key for _, key in VALUE_COLUMNS} | {COST_SORT_KEY}
        return figure if figure in sortable else None

    def set_sort_order(self, order: list[tuple[str, bool]]) -> None:
        """
        The view's sort keys (usage_views.sort_order()): the second and later
        each marked in its heading by its place (' ²') and a tooltip, the
        header's own indicator showing only one column.
        """
        marks = {
            key: (place, most_first)
            for place, (key, most_first) in enumerate(order, start=1)
            if place > 1
        }
        if marks != self._sort_marks:
            self._sort_marks = marks
            if self._headings:
                self.headerDataChanged.emit(
                    Qt.Orientation.Horizontal, 0, len(self._headings) - 1
                )

    def heading(self, column: int) -> str:
        """
        A column's heading as written, without its sort mark: what an export
        heads it with.
        """
        return self._headings[column]

    def _sort_mark(self, column: int) -> tuple[int, bool] | None:
        key = self.sort_key(column)
        return None if key is None else self._sort_marks.get(key)

    def column_of_sort_key(self, key: str) -> int | None:
        for column in range(len(self._headings)):
            if self.sort_key(column) == key:
                return column
        return None

    def figure_column(self, key: str) -> int | None:
        """
        The column of a figure ('instances', 'running', 'pending', ...), None
        while nothing is shown.
        """
        for column in range(len(self._by), len(self._headings)):
            if self._figure(column) == key:
                return column
        return None

    def rowCount(self, parent: _Index = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: _Index = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._headings)

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row, column = index.row(), index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return self._rows[row][column]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return self._alignment(column)
        if role == Qt.ItemDataRole.FontRole and column == 0 and self.is_total(row):
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.ItemDataRole.FontRole and self.is_more(row):
            font = QFont()
            font.setItalic(True)
            return font
        if role == Qt.ItemDataRole.ToolTipRole:
            if self.is_more(row):
                return MORE_TOOLTIP
            return self._row_tooltip if row < len(self._groups) else None
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation != Qt.Orientation.Horizontal or not (
            0 <= section < len(self._headings)
        ):
            return None
        mark = self._sort_mark(section)
        if role == Qt.ItemDataRole.DisplayRole:
            heading = self._headings[section]
            return heading if mark is None else f"{heading} {superscript(mark[0])}"
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return self._alignment(section)
        if role == Qt.ItemDataRole.ToolTipRole:
            lines = []
            if mark is not None:
                place, most_first = mark
                figure = section >= len(self._by)
                lines.append(
                    f"Sorted {ordinal(place)}, {direction_text(figure, most_first)}"
                )
            if self.sort_key(section) == COST_SORT_KEY:
                lines.append(COST_TOOLTIP)
            return "\n".join(lines) or None
        return None

    def _alignment(self, column: int) -> Qt.AlignmentFlag:
        horizontal = (
            Qt.AlignmentFlag.AlignLeft
            if column < len(self._by)
            else Qt.AlignmentFlag.AlignRight
        )
        return horizontal | Qt.AlignmentFlag.AlignVCenter
