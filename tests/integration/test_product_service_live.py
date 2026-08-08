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
