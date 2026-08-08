from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from elysium.ui.grid_stretch import apply_trailing_stretch


def test_first_call_sets_trailing_row_stretch_only(qtbot):
    """Regression: this must NOT also set a trailing column stretch --
    doing that once caused every row to render left-justified with a wide
    empty gutter on the right (all leftover width dumped into one
    invisible stretchy column instead of spread across the real ones)."""
    container = QWidget()
    qtbot.addWidget(container)
    grid = QGridLayout(container)
    grid.addWidget(QLabel("a"), 0, 0)
    state = {}

    apply_trailing_stretch(grid, state, row_count=1, column_count=2)

    assert grid.rowStretch(1) == 1
    assert state == {"stretch_row": 1}  # no "stretch_col" key -- column stretch is never touched


def test_second_call_clears_previous_row_stretch_before_setting_new_one():
    """Regression: without resetting the old stretch row, a rebuild that
    shrinks (e.g. a narrower search result set) would leave a stale
    stretch factor on a row that's now a real content row again."""
    grid = QGridLayout()
    state = {}

    apply_trailing_stretch(grid, state, row_count=5)
    assert grid.rowStretch(5) == 1

    apply_trailing_stretch(grid, state, row_count=1)

    assert grid.rowStretch(5) == 0
    assert grid.rowStretch(1) == 1


def test_no_content_rows_stretches_row_zero():
    """An empty grid (row_count=0, e.g. zero search results) should not
    error and should stretch the one and only (empty) row."""
    grid = QGridLayout()
    state = {}

    apply_trailing_stretch(grid, state, row_count=0)

    assert grid.rowStretch(0) == 1
