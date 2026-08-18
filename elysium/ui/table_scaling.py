"""
Makes a QTableWidget fill its available width without losing the ability
to drag-resize individual columns.

A full QHeaderView.Stretch (every column auto-sized, none of them
draggable) was tried first, to fix columns/headers reading as clumped on a
smaller monitor -- but Stretch sections categorically cannot be manually
resized at all, which broke drag-to-resize entirely (user feedback: "I
should still be able to drag the column to expand it... I can't resize").

This is the same trailing-stretch philosophy elysium.ui.grid_stretch
already uses for the pack tile grids: real columns keep their normal,
user-resizable (Interactive) behavior -- callers still call
table.resizeColumnsToContents() after repopulating for a sensible starting
width -- and only the trailing column absorbs whatever width is left over
(or gives width back when a user drags an earlier column wider), so the
table still visually fills the window instead of leaving a dead gutter.
"""

from PySide6.QtWidgets import QHeaderView

MIN_COLUMN_WIDTH = 60

# resizeColumnsToContents() sizes to the bare minimum needed to avoid
# truncating text -- confirmed by measurement (a 269px-wide product name
# landed in a 276px column, 7px of slack total) it leaves text reading as
# crammed right up against the column border ("squished"), not just
# theoretically tight. Bumping the base app font for readability (elysium/
# main.py's BASE_FONT_POINT_SIZE) made this worse: the delegate's own
# padding is a small fixed amount, so it shrinks relative to bigger text.
COLUMN_CONTENT_PADDING = 24


def make_columns_stretch(table) -> None:
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setStretchLastSection(True)
    header.setMinimumSectionSize(MIN_COLUMN_WIDTH)


def resize_columns_to_contents(table) -> None:
    """Use in place of a bare table.resizeColumnsToContents() call -- same
    auto-fit, plus COLUMN_CONTENT_PADDING of breathing room per column so
    text isn't flush against the column border."""
    table.resizeColumnsToContents()
    for column in range(table.columnCount()):
        table.setColumnWidth(column, table.columnWidth(column) + COLUMN_CONTENT_PADDING)
