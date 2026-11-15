"""
Live integration tests for product_service against real Atlas + the real
TCGCSV product mapping for Magic's "Foundations" Play Booster (verified in
Phase 3 implementation: category 1, group 23556, loose=562116, box=562118).
Disposable itest_* products, cleaned up afterward.
"""

import uuid

import pytest

from elysium.repositories import master_repository as repo
from elysium.services import product_service
from elysium.services.mongo_client import check_connection, get_master_db

pytestmark = pytest.mark.skipif(
    not check_connection().is_connected,
    reason="MongoDB is not reachable -- set MONGODB_URI in .env to run integration tests",
)


@pytest.fixture
def created_products():
    products = []
    yield products

    master_db = get_master_db()

    for product in products:
        master_db.products.delete_one({"_id": product.id})
        master_db.inventory_current.delete_one({"_id": product.id})
        master_db.audit_events.delete_many({"product_id": product.id})


def unique_name(label: str) -> str:
    return f"itest {label} {uuid.uuid4().hex[:8]}"


def test_create_product_seeds_zero_inventory(created_products):
    name = unique_name("Foundations Play Booster")

    product = product_service.create_product(
        name=name,
        booster_type="PLAY",
        packs_per_box=36,
        tcgcsv_category_id="1",
        tcgcsv_group_id="23556",
        loose_pack_tcgcsv_product_id="562116",
        box_tcgcsv_product_id="562118",
        image_url="https://example.com/foundations-play-booster.jpg",
        english_confirmed=True,
        created_by="integration-test",
    )
    created_products.append(product)

    inventory_doc = get_master_db().inventory_current.find_one({"_id": product.id})
    assert inventory_doc is not None
    assert inventory_doc["total_packs"] == 0
    assert inventory_doc["unassigned_packs"] == 0


def test_create_product_writes_audit_event(created_products):
    name = unique_name("Audit Test Booster")

    product = product_service.create_product(
        name=name, booster_type="PLAY", packs_per_box=36,
        tcgcsv_category_id="1", tcgcsv_group_id="23556",
        loose_pack_tcgcsv_product_id=f"loose-{uuid.uuid4().hex[:8]}",
        box_tcgcsv_product_id=f"box-{uuid.uuid4().hex[:8]}",
        image_url="https://example.com/x.jpg", english_confirmed=True,
        created_by="integration-test",
    )
    created_products.append(product)

    event = get_master_db().audit_events.find_one({"action_type": "PRODUCT_CREATED", "product_id": product.id})
    assert event is not None


def test_duplicate_loose_tcgcsv_id_rejected(created_products):
    shared_loose_id = f"loose-{uuid.uuid4().hex[:8]}"

    first = product_service.create_product(
        name=unique_name("First"), booster_type="PLAY", packs_per_box=36,
        tcgcsv_category_id="1", tcgcsv_group_id="23556",
        loose_pack_tcgcsv_product_id=shared_loose_id,
        box_tcgcsv_product_id=f"box-{uuid.uuid4().hex[:8]}",
        image_url="https://example.com/x.jpg", english_confirmed=True,
        created_by="integration-test",
    )
    created_products.append(first)

    with pytest.raises(product_service.DuplicateProductError):
        product_service.create_product(
            name=unique_name("Second"), booster_type="PLAY", packs_per_box=36,
            tcgcsv_category_id="1", tcgcsv_group_id="23556",
            loose_pack_tcgcsv_product_id=shared_loose_id,
            box_tcgcsv_product_id=f"box-{uuid.uuid4().hex[:8]}",
            image_url="https://example.com/x.jpg", english_confirmed=True,
            created_by="integration-test",
        )


def test_duplicate_normalized_name_and_type_rejected(created_products):
    base_name = unique_name("Duplicate Name Test")

    first = product_service.create_product(
        name=base_name, booster_type="COLLECTOR", packs_per_box=12,
        tcgcsv_category_id="1", tcgcsv_group_id="23556",
        loose_pack_tcgcsv_product_id=f"loose-{uuid.uuid4().hex[:8]}",
        box_tcgcsv_product_id=f"box-{uuid.uuid4().hex[:8]}",
        image_url="https://example.com/x.jpg", english_confirmed=True,
        created_by="integration-test",
    )
    created_products.append(first)

    # Same name (different whitespace/case) + same booster type must collide.
    with pytest.raises(product_service.DuplicateProductError):
        product_service.create_product(
            name=f"  {base_name.upper()}  ", booster_type="COLLECTOR", packs_per_box=12,
            tcgcsv_category_id="1", tcgcsv_group_id="23556",
            loose_pack_tcgcsv_product_id=f"loose-{uuid.uuid4().hex[:8]}",
            box_tcgcsv_product_id=f"box-{uuid.uuid4().hex[:8]}",
            image_url="https://example.com/x.jpg", english_confirmed=True,
            created_by="integration-test",
        )


def test_create_product_allows_a_box_less_secret_lair_product(created_products):
    """Real-world case: "Secret Lair x MSCHF: The Zeta Set" is a genuinely
    randomized booster pack with no booster box/display SKU on TCGCSV at
    all -- box_tcgcsv_product_id is the one field allowed to be None, and
    only for booster_type SECRET_LAIR."""
    product = product_service.create_product(
        name=unique_name("Secret Lair x MSCHF: The Zeta Set Booster Pack"),
        booster_type="SECRET_LAIR", packs_per_box=1,
        tcgcsv_category_id="1", tcgcsv_group_id="24836",
        loose_pack_tcgcsv_product_id=f"loose-{uuid.uuid4().hex[:8]}",
        box_tcgcsv_product_id=None,
        image_url="https://example.com/zeta.jpg", english_confirmed=True,
        created_by="integration-test",
    )
    created_products.append(product)

    assert product.box_tcgcsv_product_id is None

    doc = get_master_db().products.find_one({"_id": product.id})
    assert "box_tcgcsv_product_id" not in doc

    reloaded = product_service.get_product(product.id)
    assert reloaded.box_tcgcsv_product_id is None


def test_create_product_rejects_a_box_less_normal_booster_type(created_products):
    """The same box-less call must be rejected for any type other than
    SECRET_LAIR -- a normal booster product should always have a real
    box/display SKU on TCGCSV."""
    with pytest.raises(product_service.ProductValidationError):
        product_service.create_product(
            name=unique_name("Should Not Be Created"),
            booster_type="PLAY", packs_per_box=36,
            tcgcsv_category_id="1", tcgcsv_group_id="23556",
            loose_pack_tcgcsv_product_id=f"loose-{uuid.uuid4().hex[:8]}",
            box_tcgcsv_product_id=None,
            image_url="https://example.com/x.jpg", english_confirmed=True,
            created_by="integration-test",
        )


def test_two_box_less_secret_lair_products_can_coexist(created_products):
    """The sparse unique index on box_tcgcsv_product_id is what makes this
    possible -- a non-sparse unique index would only ever tolerate ONE
    document with a missing box id before rejecting the second as a
    duplicate null."""
    first = product_service.create_product(
        name=unique_name("Secret Lair Box-less A"), booster_type="SECRET_LAIR", packs_per_box=1,
        tcgcsv_category_id="1", tcgcsv_group_id="24836",
        loose_pack_tcgcsv_product_id=f"loose-{uuid.uuid4().hex[:8]}",
        box_tcgcsv_product_id=None,
        image_url="https://example.com/x.jpg", english_confirmed=True,
        created_by="integration-test",
    )
    created_products.append(first)

    second = product_service.create_product(
        name=unique_name("Secret Lair Box-less B"), booster_type="SECRET_LAIR", packs_per_box=1,
        tcgcsv_category_id="1", tcgcsv_group_id="24837",
        loose_pack_tcgcsv_product_id=f"loose-{uuid.uuid4().hex[:8]}",
        box_tcgcsv_product_id=None,
        image_url="https://example.com/x.jpg", english_confirmed=True,
        created_by="integration-test",
    )
    created_products.append(second)  # no DuplicateProductError -- the real point of this test


def test_update_product_can_clear_an_existing_box_mapping(created_products):
    """Editing an existing product to clear its box id must $unset the
    field rather than $set it to "" -- otherwise a second box-less product
    edited the same way would collide with the first on a shared stored
    "" value despite the index being sparse (sparse only exempts documents
    missing the field entirely, not ones storing a falsy value)."""
    product = product_service.create_product(
        name=unique_name("Clearable Box"), booster_type="SECRET_LAIR", packs_per_box=1,
        tcgcsv_category_id="1", tcgcsv_group_id="24838",
        loose_pack_tcgcsv_product_id=f"loose-{uuid.uuid4().hex[:8]}",
        box_tcgcsv_product_id=f"box-{uuid.uuid4().hex[:8]}",
        image_url="https://example.com/x.jpg", english_confirmed=True,
        created_by="integration-test",
    )
    created_products.append(product)

    product_service.update_product(product.id, {"box_tcgcsv_product_id": ""}, updated_by="integration-test")

    doc = get_master_db().products.find_one({"_id": product.id})
    assert "box_tcgcsv_product_id" not in doc


def test_zero_stock_products_still_listed(created_products):
    product = product_service.create_product(
        name=unique_name("Zero Stock"), booster_type="PLAY", packs_per_box=36,
        tcgcsv_category_id="1", tcgcsv_group_id="23556",
        loose_pack_tcgcsv_product_id=f"loose-{uuid.uuid4().hex[:8]}",
        box_tcgcsv_product_id=f"box-{uuid.uuid4().hex[:8]}",
        image_url="https://example.com/x.jpg", english_confirmed=True,
        created_by="integration-test",
    )
    created_products.append(product)

    listed_ids = {p.id for p in product_service.list_products()}
    assert product.id in listed_ids
