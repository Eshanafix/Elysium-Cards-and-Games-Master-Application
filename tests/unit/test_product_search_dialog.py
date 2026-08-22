"""
ProductSearchDialog: the type-to-filter product picker that replaced the
giant "every product in one dropdown" combo boxes on Claim Received
Inventory and Master Inventory's Add Inventory.
"""

from PySide6.QtCore import Qt

from elysium.ui.product_search import ProductSearchDialog


class FakeProduct:
    def __init__(self, id, name):
        self.id = id
        self.name = name


PRODUCTS = [
    FakeProduct("zeta", "Zeta Booster"),
    FakeProduct("alpha", "Alpha Booster"),
    FakeProduct("mid-alpha", "Middle Alpha Set Booster"),
]


def test_lists_all_products_sorted_alphabetically_by_default(qtbot):
    dialog = ProductSearchDialog(PRODUCTS)
    qtbot.addWidget(dialog)

    names = [dialog.results_list.item(i).text() for i in range(dialog.results_list.count())]
    assert names == ["Alpha Booster", "Middle Alpha Set Booster", "Zeta Booster"]


def test_typing_filters_the_list_case_insensitively(qtbot):
    dialog = ProductSearchDialog(PRODUCTS)
    qtbot.addWidget(dialog)

    dialog.search_input.setText("alpha")

    names = [dialog.results_list.item(i).text() for i in range(dialog.results_list.count())]
    assert names == ["Alpha Booster", "Middle Alpha Set Booster"]


def test_double_clicking_a_result_accepts_the_dialog_with_that_product(qtbot):
    dialog = ProductSearchDialog(PRODUCTS)
    qtbot.addWidget(dialog)

    item = dialog.results_list.item(0)  # "Alpha Booster" after alphabetical sort
    dialog._accept_item(item)

    assert dialog.result() == 1  # QDialog.Accepted
    assert dialog.selected_product().id == "alpha"


def test_ok_with_no_selection_does_not_accept(qtbot):
    dialog = ProductSearchDialog(PRODUCTS)
    qtbot.addWidget(dialog)

    dialog.search_input.setText("does-not-exist-anywhere")
    assert dialog.results_list.count() == 0

    dialog._accept_current()

    assert dialog.selected_product() is None
