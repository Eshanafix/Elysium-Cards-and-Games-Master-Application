"""
QTableWidgetItem that sorts by a stored numeric value instead of comparing
the displayed text -- plain QTableWidgetItem sorting compares strings, so
"$100.00" sorts before "$4.60" (and "10" sorts before "9") since '1' < '4'
and '1' < '9' as characters. Used with QTableWidget.setSortingEnabled(True)
wherever a column shows money or a plain count (docs feedback: click a
column header, e.g. Price, to sort highest-to-lowest or lowest-to-highest).
"""

from PySide6.QtWidgets import QTableWidgetItem


class NumericTableWidgetItem(QTableWidgetItem):
    def __init__(self, text: str, sort_value):
        super().__init__(text)
        self.sort_value = sort_value

    def __lt__(self, other):
        other_value = getattr(other, "sort_value", None)

        if self.sort_value is None:
            return False  # unresolved/blank values sort last

        if other_value is None:
            return True

        return self.sort_value < other_value
