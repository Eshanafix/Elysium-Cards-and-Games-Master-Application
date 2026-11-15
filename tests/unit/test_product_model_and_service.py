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


# --- box_tcgcsv_product_id is required for every booster type EXCEPT
# SECRET_LAIR (docs feedback: "Secret Lair x MSCHF: The Zeta Set" is a
# genuinely randomized booster pack sold with no booster box/display SKU
# on TCGCSV at all) -- deliberately narrower than "box is optional for any
# product", so a normal booster product (which should always have a real
# box/display SKU) can't slip through without one by mistake. ---


def test_validate_mandatory_fields_rejects_missing_box_for_a_normal_booster_type():
    with pytest.raises(product_service.ProductValidationError):
        product_service._validate_mandatory_fields(
            name="Foo", booster_type="PLAY", packs_per_box=36,
            tcgcsv_category_id="1", tcgcsv_group_id="1",
            loose_pack_tcgcsv_product_id="1", box_tcgcsv_product_id=None,
            image_url="https://example.com/x.jpg", english_confirmed=True,
        )


def test_validate_mandatory_fields_rejects_missing_box_for_every_type_but_secret_lair():
    from elysium.models.products import BOOSTER_TYPES

    for booster_type in BOOSTER_TYPES:
        if booster_type == "SECRET_LAIR":
            continue

        with pytest.raises(product_service.ProductValidationError):
            product_service._validate_mandatory_fields(
                name="Foo", booster_type=booster_type, packs_per_box=36,
                tcgcsv_category_id="1", tcgcsv_group_id="1",
                loose_pack_tcgcsv_product_id="1", box_tcgcsv_product_id=None,
                image_url="https://example.com/x.jpg", english_confirmed=True,
            )


def test_validate_mandatory_fields_does_not_require_a_box_for_secret_lair():
    # Should not raise -- the one deliberate exception.
    product_service._validate_mandatory_fields(
        name="Foo", booster_type="SECRET_LAIR", packs_per_box=1,
        tcgcsv_category_id="1", tcgcsv_group_id="1",
        loose_pack_tcgcsv_product_id="1", box_tcgcsv_product_id=None,
        image_url="https://example.com/x.jpg", english_confirmed=True,
    )


def test_check_duplicates_skips_box_lookup_when_box_id_is_none(monkeypatch):
    """A box-less product has nothing to check for duplication against --
    repo.box_tcgcsv_id_exists must not even be called, since calling it
    with None would be a meaningless/misleading query."""
    monkeypatch.setattr(repo, "normalized_name_and_type_exists", lambda name, booster_type: False)
    monkeypatch.setattr(repo, "loose_tcgcsv_id_exists", lambda loose_id: False)

    def boom(_box_id):
        raise AssertionError("box_tcgcsv_id_exists should not be called for a box-less product")

    monkeypatch.setattr(repo, "box_tcgcsv_id_exists", boom)

    product_service._check_duplicates("Foo", "SECRET_LAIR", "1", None)  # must not raise


def test_product_to_document_omits_box_tcgcsv_product_id_when_none():
    product = Product(
        id="secret-lair-x-mschf-the-zeta-set-booster-pack",
        name="Secret Lair x MSCHF: The Zeta Set Booster Pack",
        booster_type="SECRET_LAIR",
        packs_per_box=1,
        tcgcsv_category_id="1",
        tcgcsv_group_id="24836",
        loose_pack_tcgcsv_product_id="714891",
        box_tcgcsv_product_id=None,
        image_url="https://example.com/zeta.jpg",
        english_confirmed=True,
    )

    doc = product.to_document()

    assert "box_tcgcsv_product_id" not in doc


def test_product_from_document_defaults_box_tcgcsv_product_id_to_none_when_absent():
    doc = Product(
        id="p1", name="P1", booster_type="SECRET_LAIR", packs_per_box=1,
        tcgcsv_category_id="1", tcgcsv_group_id="1", loose_pack_tcgcsv_product_id="1",
        box_tcgcsv_product_id=None, image_url="https://example.com/x.jpg",
    ).to_document()

    assert "box_tcgcsv_product_id" not in doc  # sanity check on the fixture itself

    restored = Product.from_document(doc)

    assert restored.box_tcgcsv_product_id is None
