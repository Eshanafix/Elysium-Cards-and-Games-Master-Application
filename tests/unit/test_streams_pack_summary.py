"""
Regression test: the streamer-facing break tables' pack summary used to
comma-join products onto one line ("A x1, B x2"), which ran too wide for
a break with several products. Now stacked one product per line, paired
with resizeRowsToContents() in the UI so every line renders.
"""

from elysium.ui.streams import _pack_summary


def make_break(pack_lines):
    return type("FakeBreak", (), {"pack_lines": pack_lines})()


def test_pack_summary_stacks_products_one_per_line():
    break_obj = make_break([
        {"product_id": "p1", "quantity": 1},
        {"product_id": "p2", "quantity": 2},
    ])
    product_names = {"p1": "Ravnica Allegiance Draft Booster", "p2": "Dominaria United Draft Booster"}

    result = _pack_summary(break_obj, product_names)

    assert result == "Ravnica Allegiance Draft Booster x1\nDominaria United Draft Booster x2"


def test_pack_summary_no_packs_selected():
    assert _pack_summary(make_break([]), {}) == "(no packs selected)"


def test_pack_summary_falls_back_to_product_id_when_name_unknown():
    break_obj = make_break([{"product_id": "unknown-id", "quantity": 3}])
    assert _pack_summary(break_obj, {}) == "unknown-id x3"
