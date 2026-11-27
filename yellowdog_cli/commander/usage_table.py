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

from yellowdog_cli.commander.usage_views import heading, row_cells

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
# What the estimate leaves out, said on its heading
COST_TOOLTIP = (
    "Linux list prices today; spot Instances at the region's mean spot price;"
    " no discounts, savings plans, licences or disks; running time only"
)
# The status columns after the cost, in row_cells()'s order, hidden at first
STATUS_COLUMNS: tuple[str, ...] = ("pending", "stopping", "terminating", "unknown")
# The figure columns a right-click may hide, in the order shown: all but the
# cost, which the Estimated cost checkbox adds and removes
HIDEABLE_COLUMNS: tuple[str, ...] = (
    *(key for _, key in VALUE_COLUMNS),
    *STATUS_COLUMNS,
)
TOTAL_LABEL = "Total"
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
    return dict((k, name) for name, k in VALUE_COLUMNS).get(key) or heading(key)


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
        # The document's dict behind each row, the total's last
        self._sources: list[dict] = []
        self._headings: list[str] = []
        self._has_total = False

    def set_document(self, document: dict, cost: bool) -> None:
        """
        Show a document's groups and total; 'cost' says whether it was asked
        for with '--cost'. Raises KeyError, TypeError or ValueError for a
        document not shaped as `yd usage --json` writes it, leaving the table
        as it was.
        """
        by = [str(key) for key in document["by"]]
        groups = [dict(group) for group in document["groups"]]
        rows = [row_cells(group, by, cost) for group in groups]
        sources = list(groups)
        total = document.get("total")
        if groups and isinstance(total, dict):
            cells = row_cells(total, by, cost)
            cells[: len(by)] = [TOTAL_LABEL] + [""] * (len(by) - 1)
            rows.append(cells)
            sources.append(dict(total))
        self.beginResetModel()
        self._by, self._cost, self._groups, self._rows = by, cost, groups, rows
        self._sources = sources
        self._has_total = len(rows) > len(groups)
        self._headings = (
            [heading(key) for key in by]
            + [
                name if key == "instances" else DURATION_HEADING.format(heading=name)
                for name, key in VALUE_COLUMNS
            ]
            + ([COST_HEADING.format(currency=document["currency"])] if cost else [])
            + [DURATION_HEADING.format(heading=heading(key)) for key in STATUS_COLUMNS]
        )
        self.endResetModel()

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
            if figure in (None, "instances", COST_SORT_KEY):
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
            row: list[str] = []
            for column in columns:
                figure = self._figure(column)
                if figure is None:
                    key = self._by[column]
                    row.append(
                        (TOTAL_LABEL if column == 0 else "")
                        if total
                        else str(source.get(key, ""))
                    )
                elif figure == "instances":
                    row.append(str(source.get("instances", 0)))
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
        figures = [key for _, key in VALUE_COLUMNS]
        figures += [COST_SORT_KEY] if self._cost else []
        figures += list(STATUS_COLUMNS)
        return figures[column - len(self._by)]

    def clear(self) -> None:
        self.beginResetModel()
        self._by, self._groups, self._rows, self._headings = [], [], [], []
        self._sources = []
        self._has_total = False
        self.endResetModel()

    @property
    def by(self) -> list[str]:
        return list(self._by)

    def group(self, row: int) -> dict | None:
        """
        The document's group a row shows; None for the Total row.
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

    def sort_key(self, column: int) -> str | None:
        """
        The '--sort' key of a column: a key column's own key, a figure's
        name; None for a status column, which the CLI does not sort by.
        """
        if column < len(self._by):
            return self._by[column]
        column -= len(self._by)
        keys = [key for _, key in VALUE_COLUMNS] + (
            [COST_SORT_KEY] if self._cost else []
        )
        return keys[column] if column < len(keys) else None

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
        if role == Qt.ItemDataRole.DisplayRole:
            return self._headings[section]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return self._alignment(section)
        if role == Qt.ItemDataRole.ToolTipRole and self.sort_key(section) == (
            COST_SORT_KEY
        ):
            return COST_TOOLTIP
        return None

    def _alignment(self, column: int) -> Qt.AlignmentFlag:
        horizontal = (
            Qt.AlignmentFlag.AlignLeft
            if column < len(self._by)
            else Qt.AlignmentFlag.AlignRight
        )
        return horizontal | Qt.AlignmentFlag.AlignVCenter
