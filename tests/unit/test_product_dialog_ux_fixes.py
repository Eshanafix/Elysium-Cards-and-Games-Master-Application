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


def test_edit_mode_does_not_crash_on_a_box_less_product(qtbot):
    """Regression: QLineEdit(None) raises a TypeError in PySide6 -- editing
    an existing box-less product (box_tcgcsv_product_id=None) used to
    crash the dialog outright rather than just showing an empty field."""
    product = products.Product(
        id="secret-lair-x-mschf-the-zeta-set-booster-pack",
        name="Secret Lair x MSCHF: The Zeta Set Booster Pack",
        booster_type="SECRET_LAIR", packs_per_box=1,
        tcgcsv_category_id="1", tcgcsv_group_id="24836",
        loose_pack_tcgcsv_product_id="714891",
        box_tcgcsv_product_id=None,
        image_url="https://example.com/zeta.jpg",
    )

    dialog = products.ProductDialog(product=product)
    qtbot.addWidget(dialog)

    assert dialog.box_tcgcsv_id_input.text() == ""


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


# --- Box-less sealed products (docs feedback: "Secret Lair x MSCHF: The
# Zeta Set" is a genuinely randomized booster pack sold with no booster
# box/display SKU on TCGCSV at all -- unlike every other product this
# dialog has ever dealt with, which always has both a pack and a box). ---


def test_select_group_shows_no_box_hint_when_a_pack_exists_but_no_box_does(qtbot, monkeypatch):
    panel = products.SetSearchPanel(on_selection_resolved=lambda r: None)
    qtbot.addWidget(panel)

    monkeypatch.setattr(
        products.tcgcsv_catalog_service, "fetch_group_products",
        lambda cat, grp: [
            {"productId": 714891, "name": "Secret Lair x MSCHF: The Zeta Set Booster Pack", "imageUrl": None},
        ],
    )

    item = products.QListWidgetItem("Secret Lair x MSCHF: The Zeta Set")
    item.setData(products.Qt.UserRole, {
        "name": "Secret Lair x MSCHF: The Zeta Set", "category_id": "1", "group_id": "24836",
    })

    panel.select_group(item)

    assert panel.loose_combo.count() == 1
    assert panel.box_combo.count() == 0
    assert "no booster box/display found" in panel.selected_set_label.text()
    assert "no sealed pack/box products found" not in panel.selected_set_label.text()


def test_packs_per_box_defaults_to_one_when_no_box_exists_in_the_whole_group(qtbot, monkeypatch):
    """Regression: with no box candidate at all, this used to fall through
    to default_packs_per_box(booster_type) -- e.g. 30 for a SET-qualifier
    collision -- instead of recognizing there's no real box to multiply by
    in the first place. 1 is the only correct default here."""
    resolved = {}
    panel = products.SetSearchPanel(on_selection_resolved=resolved.update)
    qtbot.addWidget(panel)

    monkeypatch.setattr(
        products.tcgcsv_catalog_service, "fetch_group_products",
        lambda cat, grp: [
            # Qualifier word "Set" (from "...The Zeta Set...") collides
            # with the real SET booster type -- DEFAULT_PACKS_PER_BOX[SET]
            # is 30, which is exactly the wrong value this test guards
            # against.
            {"productId": 714891, "name": "Secret Lair x MSCHF: The Zeta Set Booster Pack", "imageUrl": None},
        ],
    )

    item = products.QListWidgetItem("Secret Lair x MSCHF: The Zeta Set")
    item.setData(products.Qt.UserRole, {
        "name": "Secret Lair x MSCHF: The Zeta Set", "category_id": "1", "group_id": "24836",
    })

    panel.select_group(item)

    assert resolved["packs_per_box"] == 1
    assert resolved["box"] is None


def test_packs_per_box_still_uses_default_table_when_a_box_genuinely_exists(qtbot, monkeypatch):
    """Making sure the box-less fix above doesn't change behavior for the
    overwhelming majority of real sets, which do have a box."""
    resolved = {}
    panel = products.SetSearchPanel(on_selection_resolved=resolved.update)
    qtbot.addWidget(panel)

    monkeypatch.setattr(
        products.tcgcsv_catalog_service, "fetch_group_products",
        lambda cat, grp: [
            {"productId": 1, "name": "Dominaria United - Set Booster Pack", "imageUrl": None},
            {"productId": 2, "name": "Dominaria United - Set Booster Box", "imageUrl": None},
        ],
    )

    item = products.QListWidgetItem("Dominaria United")
    item.setData(products.Qt.UserRole, {"name": "Dominaria United", "category_id": "1", "group_id": "3102"})

    panel.select_group(item)

    # No parseable "contains: N" text in this fake description, so this
    # falls through to the SET default (30) -- unchanged from before.
    assert resolved["packs_per_box"] == 30
