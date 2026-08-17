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


def make_columns_stretch(table) -> None:
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setStretchLastSection(True)
    header.setMinimumSectionSize(MIN_COLUMN_WIDTH)
