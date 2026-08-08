import pytest

from elysium.models.products import Product, normalize_product_name
from elysium.repositories import master_repository as repo
from elysium.services import product_service


def test_normalize_product_name_collapses_whitespace_and_case():
    assert normalize_product_name("Foundations   Play Booster") == "foundations play booster"
    assert normalize_product_name("  foundations play booster  ") == "foundations play booster"
    assert normalize_product_name("FOUNDATIONS PLAY BOOSTER") == "foundations play booster"


def test_product_to_document_and_back_round_trips():
    product = Product(
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

    doc = product.to_document()
    assert doc["name_normalized"] == "foundations play booster"

    restored = Product.from_document(doc)
    assert restored.id == product.id
    assert restored.name == product.name
    assert restored.booster_type == product.booster_type


def test_slugify_produces_url_safe_id():
    assert product_service._slugify("Foundations Play Booster") == "foundations-play-booster"
    assert product_service._slugify("  Multiple   Spaces & Symbols!! ") == "multiple-spaces-symbols"


def test_generate_unique_product_id_disambiguates_on_collision(monkeypatch):
    existing = {"foundations-play-booster"}
    monkeypatch.setattr(repo, "product_id_exists", lambda pid: pid in existing)

    result = product_service._generate_unique_product_id("Foundations Play Booster")
    assert result == "foundations-play-booster-2"


def test_validate_mandatory_fields_rejects_missing_name():
    with pytest.raises(product_service.ProductValidationError):
        product_service._validate_mandatory_fields(
            name="", booster_type="PLAY", packs_per_box=36,
            tcgcsv_category_id="1", tcgcsv_group_id="1",
            loose_pack_tcgcsv_product_id="1", box_tcgcsv_product_id="2",
            image_url="https://example.com/x.jpg", english_confirmed=True,
        )


def test_validate_mandatory_fields_rejects_invalid_booster_type():
    with pytest.raises(product_service.ProductValidationError):
        product_service._validate_mandatory_fields(
            name="Foo", booster_type="INVALID", packs_per_box=36,
            tcgcsv_category_id="1", tcgcsv_group_id="1",
            loose_pack_tcgcsv_product_id="1", box_tcgcsv_product_id="2",
            image_url="https://example.com/x.jpg", english_confirmed=True,
        )


def test_validate_mandatory_fields_requires_english_confirmation():
    with pytest.raises(product_service.ProductValidationError):
        product_service._validate_mandatory_fields(
            name="Foo", booster_type="PLAY", packs_per_box=36,
            tcgcsv_category_id="1", tcgcsv_group_id="1",
            loose_pack_tcgcsv_product_id="1", box_tcgcsv_product_id="2",
            image_url="https://example.com/x.jpg", english_confirmed=False,
        )


def test_validate_mandatory_fields_rejects_zero_packs_per_box():
    with pytest.raises(product_service.ProductValidationError):
        product_service._validate_mandatory_fields(
            name="Foo", booster_type="PLAY", packs_per_box=0,
            tcgcsv_category_id="1", tcgcsv_group_id="1",
            loose_pack_tcgcsv_product_id="1", box_tcgcsv_product_id="2",
            image_url="https://example.com/x.jpg", english_confirmed=True,
        )


def test_validate_mandatory_fields_accepts_valid_input():
    # Should not raise.
    product_service._validate_mandatory_fields(
        name="Foo", booster_type="PLAY", packs_per_box=36,
        tcgcsv_category_id="1", tcgcsv_group_id="1",
        loose_pack_tcgcsv_product_id="1", box_tcgcsv_product_id="2",
        image_url="https://example.com/x.jpg", english_confirmed=True,
    )
