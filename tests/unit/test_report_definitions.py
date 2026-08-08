"""
Regression test: the "breaks"/"break_products" report columns must include
a packs-opened summary and keep the long ID columns (break_id/stream_id)
at the end rather than dominating the row (docs feedback).
"""

from elysium.exports.report_definitions import REPORT_DEFINITIONS


def _definition(key):
    return next(d for d in REPORT_DEFINITIONS if d.key == key)


def test_breaks_report_includes_packs_opened_column():
    columns = _definition("breaks").columns
    assert "packs_opened" in columns


def test_breaks_report_id_columns_are_last():
    columns = _definition("breaks").columns
    assert columns[-2:] == ["break_id", "stream_id"]
    assert columns.index("streamer_username") < columns.index("break_id")


def test_break_products_report_id_columns_are_last():
    columns = _definition("break_products").columns
    assert columns[-3:] == ["product_id", "break_id", "stream_id"]
    assert columns.index("streamer_username") < columns.index("break_id")
