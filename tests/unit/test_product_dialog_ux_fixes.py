"""
Regression tests for a batch of New Product UX fixes from user feedback:
- booster type / loose / box dropdowns shouldn't change value on an
  accidental mouse-wheel scroll while unopened
- the search bar should have keyboard focus as soon as the dialog opens
- create mode's dialog should be tall enough to avoid needing to scroll
- picking a TCGCSV group with zero sealed products should say so, instead
  of silently leaving both dropdowns empty
"""

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QWheelEvent

from elysium.ui import products
from elysium.ui.no_scroll_combo import NoScrollComboBox


def test_no_scroll_combo_ignores_wheel_event(qtbot):
    combo = NoScrollComboBox()
    combo.addItems(["A", "B", "C"])
    combo.setCurrentIndex(0)
    qtbot.addWidget(combo)

    event = QWheelEvent(
        QPointF(5, 5), QPointF(5, 5), QPoint(0, 120), QPoint(0, 120),
        products.Qt.NoButton, products.Qt.NoModifier, products.Qt.ScrollUpdate, False,
    )
    combo.wheelEvent(event)

    assert event.isAccepted() is False
    assert combo.currentIndex() == 0


def test_product_dialog_combos_are_no_scroll(qtbot):
    dialog = products.ProductDialog(product=None)
    qtbot.addWidget(dialog)

    assert isinstance(dialog.booster_type_combo, NoScrollComboBox)
    assert isinstance(dialog.search_panel.loose_combo, NoScrollComboBox)
    assert isinstance(dialog.search_panel.box_combo, NoScrollComboBox)


def test_create_mode_focuses_search_bar_on_open(qtbot):
    dialog = products.ProductDialog(product=None)
    qtbot.addWidget(dialog)
    dialog.show()

    # hasFocus() depends on real OS window activation, which is unreliable
    # under a headless test runner -- focusWidget() reflects what Qt itself
    # considers the focused descendant regardless of that.
    assert dialog.focusWidget() is dialog.search_panel.search_input


def test_edit_mode_has_no_search_panel_to_focus(qtbot):
    product = products.Product(
        id="p1", name="Test Booster", booster_type="PLAY", packs_per_box=36,
        tcgcsv_category_id="1", tcgcsv_group_id="1", loose_pack_tcgcsv_product_id="1",
        box_tcgcsv_product_id="2", image_url="https://example.com/x.jpg",
    )
    dialog = products.ProductDialog(product=product)
    qtbot.addWidget(dialog)

    assert dialog.search_panel is None


def test_select_group_shows_hint_when_no_sealed_products_found(qtbot, monkeypatch):
    panel = products.SetSearchPanel(on_selection_resolved=lambda r: None)
    qtbot.addWidget(panel)

    monkeypatch.setattr(products.tcgcsv_catalog_service, "fetch_group_products", lambda cat, grp: [])

    item = products.QListWidgetItem("Mystery Booster Cards")
    item.setData(products.Qt.UserRole, {
        "name": "Mystery Booster Cards", "category_id": "1", "group_id": "2572",
    })

    panel.select_group(item)

    assert "no sealed pack/box products found" in panel.selected_set_label.text()
    assert panel.loose_combo.count() == 0
    assert panel.box_combo.count() == 0


def test_select_group_no_hint_when_products_found(qtbot, monkeypatch):
    panel = products.SetSearchPanel(on_selection_resolved=lambda r: None)
    qtbot.addWidget(panel)

    monkeypatch.setattr(
        products.tcgcsv_catalog_service, "fetch_group_products",
        lambda cat, grp: [
            {"productId": 1, "name": "Kaladesh - Booster Pack", "imageUrl": None},
            {"productId": 2, "name": "Kaladesh - Booster Box", "imageUrl": None},
        ],
    )

    item = products.QListWidgetItem("Kaladesh")
    item.setData(products.Qt.UserRole, {"name": "Kaladesh", "category_id": "1", "group_id": "1791"})

    panel.select_group(item)

    assert "no sealed pack/box products found" not in panel.selected_set_label.text()
    assert panel.loose_combo.count() == 1
