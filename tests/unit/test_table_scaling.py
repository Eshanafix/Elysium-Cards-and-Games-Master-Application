"""
Regression test: columns must stay individually drag-resizable (Interactive
mode) while the table still fills its available width via a stretched
trailing column -- a full QHeaderView.Stretch (tried first) fixed columns
looking clumped on a smaller monitor but made every column un-draggable,
which broke manual column resizing entirely.
"""

from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem

from elysium.ui.table_scaling import (
    COLUMN_CONTENT_PADDING,
    MIN_COLUMN_WIDTH,
    make_columns_stretch,
    resize_columns_to_contents,
)


def test_make_columns_stretch_keeps_columns_interactive_and_resizable(qtbot):
    table = QTableWidget(0, 3)
    qtbot.addWidget(table)

    make_columns_stretch(table)

    header = table.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.Interactive
    assert header.stretchLastSection() is True
    assert header.minimumSectionSize() == MIN_COLUMN_WIDTH


def test_resize_columns_to_contents_leaves_padding_beyond_the_raw_text_width(qtbot):
    # A bare resizeColumnsToContents() measured (real reproduction, not a
    # guess): a 269px-wide product name landed in a 276px column -- 7px of
    # total slack, which reads as text crammed against the column border.
    table = QTableWidget(1, 1)
    qtbot.addWidget(table)
    table.setHorizontalHeaderLabels(["Product"])
    table.setItem(0, 0, QTableWidgetItem("Marvel Super Heroes Collector Booster"))

    resize_columns_to_contents(table)

    text_width = table.fontMetrics().horizontalAdvance("Marvel Super Heroes Collector Booster")
    assert table.columnWidth(0) >= text_width + COLUMN_CONTENT_PADDING
