"""
QGridLayout distributes leftover container space proportionally across all
rows by default -- with too few tiles to fill the visible area (e.g. a
card search matching only 2 printings, or a streamer holding only a
couple of products), that stretches the actual content cells (and the
frames/borders inside them) vertically to fill the gap, instead of leaving
it as plain empty space below. This directs all leftover vertical space
into one dedicated trailing row instead, so content cells stay exactly
their natural height.

Deliberately row-only: an earlier version also added a trailing *column*
stretch by the same logic, which fixed nothing further but caused a
regression of its own -- with only the trailing column stretchy and every
real column at its natural width, Qt dumped all leftover horizontal space
into that one invisible column instead of spreading it across the row like
before, making every row look left-justified with a wide empty gutter on
the right.
"""


def apply_trailing_stretch(grid_layout, state: dict, row_count: int, column_count: int | None = None) -> None:
    """`state` is a small dict the caller keeps between rebuilds (e.g. an
    instance attribute) so the previous trailing stretch row gets reset to
    0 before a new one is set -- otherwise a stale stretch from an earlier,
    larger render lingers on the layout (QGridLayout stretch factors are
    layout-level state, not cleared by removing widgets). `column_count` is
    accepted but unused -- kept so existing call sites don't need updating."""
    previous_row = state.get("stretch_row")

    if previous_row is not None:
        grid_layout.setRowStretch(previous_row, 0)

    grid_layout.setRowStretch(row_count, 1)

    state["stretch_row"] = row_count
