"""
Regression tests: plain QTableWidgetItem sorting compares displayed text,
so "$100.00" sorts before "$4.60" and "10" sorts before "9". Sortable price/
inventory tables need NumericTableWidgetItem instead.
"""

from decimal import Decimal

from elysium.ui.numeric_table_item import NumericTableWidgetItem


def test_numeric_items_sort_by_value_not_text():
    cheap = NumericTableWidgetItem("$4.60", Decimal("4.60"))
    expensive = NumericTableWidgetItem("$100.00", Decimal("100.00"))

    assert cheap < expensive
    assert not (expensive < cheap)


def test_items_without_a_value_sort_last():
    unresolved = NumericTableWidgetItem("UNRESOLVED", None)
    priced = NumericTableWidgetItem("$4.60", Decimal("4.60"))

    assert priced < unresolved
    assert not (unresolved < priced)


def test_two_unresolved_items_are_not_less_than_each_other():
    a = NumericTableWidgetItem("UNRESOLVED", None)
    b = NumericTableWidgetItem("UNRESOLVED", None)

    assert not (a < b)
    assert not (b < a)
