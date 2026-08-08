"""
Regression tests for the simplified New Product create flow (docs feedback:
"a lot of the menu is unnecessary... we do not need to preview image, and
for now we don't need to confirm English product"). Edit mode is
unaffected and keeps every field visible.
"""

from elysium.models.products import Product
from elysium.ui.products import ProductDialog


def make_product():
    return Product(
        id="foundations-play-booster",
        name="Foundations Play Booster",
        booster_type="PLAY",
        packs_per_box=36,
        tcgcsv_category_id="1",
        tcgcsv_group_id="23556",
        loose_pack_tcgcsv_product_id="562116",
        box_tcgcsv_product_id="562118",
        image_url="https://example.com/image.jpg",
        english_confirmed=True,
    )


def test_create_mode_hides_non_essential_fields(qtbot):
    dialog = ProductDialog(product=None)
    qtbot.addWidget(dialog)

    # Not added to the visible layout -- a widget only gets a parent once
    # it's placed in a layout.
    assert dialog.set_name_input.parent() is None
    assert dialog.set_code_input.parent() is None
    assert dialog.tcgcsv_category_id_input.parent() is None
    assert dialog.tcgcsv_group_id_input.parent() is None
    assert dialog.loose_tcgcsv_id_input.parent() is None
    assert dialog.box_tcgcsv_id_input.parent() is None
    assert dialog.image_url_input.parent() is None
    assert dialog.preview_button.parent() is None
    assert dialog.image_preview_label.parent() is None
    assert dialog.english_confirmed_checkbox.parent() is None


def test_create_mode_still_shows_essential_fields(qtbot):
    dialog = ProductDialog(product=None)
    qtbot.addWidget(dialog)

    assert dialog.name_input.parent() is not None
    assert dialog.booster_type_combo.parent() is not None
    assert dialog.packs_per_box_input.parent() is not None
    assert dialog.search_panel is not None
    assert dialog.search_panel.parent() is not None


def test_create_mode_defaults_english_confirmed_to_true_without_asking(qtbot):
    dialog = ProductDialog(product=None)
    qtbot.addWidget(dialog)

    assert dialog.field_values()["english_confirmed"] is True


def test_create_mode_still_submits_auto_filled_hidden_fields(qtbot):
    """Hidden doesn't mean discarded -- the search picker still populates
    these, and field_values() must still send them."""
    dialog = ProductDialog(product=None)
    qtbot.addWidget(dialog)

    dialog._apply_resolved_selection({
        "group": {"name": "Kaladesh", "abbreviation": "KLD", "category_id": "1", "group_id": "1791"},
        "loose": type("C", (), {"product_id": "121529", "image_url": "https://example.com/kld.jpg", "booster_type": "CLASSIC"})(),
        "box": type("C", (), {"product_id": "121530", "booster_type": "CLASSIC"})(),
        "booster_type": "CLASSIC",
        "packs_per_box": 36,
        "packs_per_box_was_parsed": False,
    })

    values = dialog.field_values()
    assert values["set_name"] == "Kaladesh"
    assert values["set_code"] == "KLD"
    assert values["loose_pack_tcgcsv_product_id"] == "121529"
    assert values["box_tcgcsv_product_id"] == "121530"
    assert values["image_url"] == "https://example.com/kld.jpg"
    assert values["booster_type"] == "CLASSIC"


def test_edit_mode_shows_every_field(qtbot):
    dialog = ProductDialog(product=make_product())
    qtbot.addWidget(dialog)

    assert dialog.set_name_input.parent() is not None
    assert dialog.tcgcsv_category_id_input.parent() is not None
    assert dialog.image_url_input.parent() is not None
    assert dialog.preview_button.parent() is not None
    assert dialog.english_confirmed_checkbox.parent() is not None
    assert dialog.search_panel is None


def test_edit_mode_preserves_existing_english_confirmed_value(qtbot):
    product = make_product()
    product.english_confirmed = False

    dialog = ProductDialog(product=product)
    qtbot.addWidget(dialog)

    assert dialog.english_confirmed_checkbox.isChecked() is False


def test_results_list_has_generous_minimum_height(qtbot):
    dialog = ProductDialog(product=None)
    qtbot.addWidget(dialog)

    assert dialog.search_panel.results_list.minimumHeight() >= 200
