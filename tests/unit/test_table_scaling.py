"""
Regression test: columns must stay individually drag-resizable (Interactive
mode) while the table still fills its available width via a stretched
trailing column -- a full QHeaderView.Stretch (tried first) fixed columns
looking clumped on a smaller monitor but made every column un-draggable,
which broke manual column resizing entirely.
"""

from PySide6.QtWidgets import QHeaderView, QTableWidget

from elysium.ui.table_scaling import MIN_COLUMN_WIDTH, make_columns_stretch


def test_make_columns_stretch_keeps_columns_interactive_and_resizable(qtbot):
    table = QTableWidget(0, 3)
    qtbot.addWidget(table)

    make_columns_stretch(table)

    header = table.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.Interactive
    assert header.stretchLastSection() is True
    assert header.minimumSectionSize() == MIN_COLUMN_WIDTH
