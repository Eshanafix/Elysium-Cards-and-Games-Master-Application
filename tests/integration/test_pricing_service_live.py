"""
Live integration tests for pricing_service: real Atlas + real TCGCSV.
Uses the real "Ixalan" Booster mapping (category 1, group 2043,
loose=141991 [$6.89 as of verification], box=141989 [$227.13]) -- switched
from the original "Foundations" mapping (2026-08-21) once Foundations
became a real catalog product itself: reusing its TCGCSV ids here collided
with the real product's own unique loose/box id constraints. Ixalan (the
2017 set) isn't in the real catalog, so it's safe to reuse indefinitely.
Disposable itest_* products, cleaned up afterward -- never touches your
real catalog.
"""

import uuid
from decimal import Decimal

import pytest

from elysium.models.prices import STATUS_MANUAL, STATUS_OK
from elysium.repositories import price_repository as price_repo
from elysium.services import lock_service, pricing_service, product_service
from elysium.services.mongo_client import check_connection, get_master_db, get_prices_db

pytestmark = pytest.mark.skipif(
    not check_connection().is_connected,
    reason="MongoDB is not reachable -- set MONGODB_URI in .env to run integration tests",
)


@pytest.fixture
def created_products():
    products = []
    yield products

    master_db = get_master_db()
    prices_db = get_prices_db()

    for product in products:
        master_db.products.delete_one({"_id": product.id})
        master_db.inventory_current.delete_one({"_id": product.id})
        master_db.audit_events.delete_many({"product_id": product.id})
        prices_db.current_prices.delete_one({"_id": product.id})
        prices_db.price_history.delete_many({"product_id": product.id})

    # PRICE_REFRESH_STARTED/COMPLETED/FAILED audit events and
    # refresh_sessions docs aren't scoped to any single product (a refresh
    # spans the whole catalog), so they're cleaned up separately here
    # rather than per-product above.
    master_db.audit_events.delete_many({"performed_by": "integration-test"})
    prices_db.refresh_sessions.delete_many({"started_by": "integration-test"})
    prices_db.price_history.delete_many({"initiated_by": "integration-test"})

    # Belt-and-braces: make sure the lock is never left held if a test
    # fails partway through, since every other integration test depends
    # on it being free.
    lock_service.release_price_refresh_lock()


def unique_name(label: str) -> str:
    return f"itest {label} {uuid.uuid4().hex[:8]}"


def make_real_ixalan_product(created_products, booster_type="CLASSIC"):
    product = product_service.create_product(
        name=unique_name("Ixalan Booster"),
        booster_type=booster_type,
        packs_per_box=36,
        tcgcsv_category_id="1",
        tcgcsv_group_id="2043",
        loose_pack_tcgcsv_product_id="141991",
        box_tcgcsv_product_id="141989",
        image_url="https://example.com/ixalan-booster.jpg",
        english_confirmed=True,
        created_by="integration-test",
    )
    created_products.append(product)
    return product


def test_refresh_prefers_box_derived_price_when_both_available(created_products):
    """Box-derived is the default source ahead of loose-pack (business
    decision 2026-08-24) -- the real Ixalan mapping has both a loose and a
    box price, so a refresh must resolve to the box-derived value, not
    loose, even though loose is also present and valid."""
    product = make_real_ixalan_product(created_products)

    session_id = pricing_service.refresh_prices("integration-test")

    price = price_repo.find_current_price(product.id)
    assert price is not None
    assert price.price_status == STATUS_OK
    assert price.resolved_price_source == "DERIVED_FROM_BOX_MARKET"
    assert price.resolved_pack_price > Decimal("0")
    assert price.raw_box_market_price is not None
    assert price.resolved_pack_price == price.raw_box_market_price / product.packs_per_box

    session = price_repo.find_refresh_session(session_id)
    assert session["status"] == "COMPLETED"
    assert session["products_checked"] >= 1
    assert session["box_derived_prices_used"] >= 1
    assert session["unique_groups_requested"] >= 1

    history = list(get_prices_db().price_history.find({"product_id": product.id}))
    assert len(history) >= 1
    assert history[-1]["new_source"] == "DERIVED_FROM_BOX_MARKET"


def test_refresh_falls_back_to_loose_pack_price_when_box_unavailable(created_products):
    """Loose-pack is still used when box price isn't available at all --
    box-derived only wins when both exist."""
    product = product_service.create_product(
        name=unique_name("Ixalan Booster No Box"),
        booster_type="CLASSIC", packs_per_box=36,
        tcgcsv_category_id="1", tcgcsv_group_id="2043",
        loose_pack_tcgcsv_product_id="141991",  # real, verified loose id
        box_tcgcsv_product_id="00000009",  # doesn't exist in this group
        image_url="https://example.com/x.jpg", english_confirmed=True,
        created_by="integration-test",
    )
    created_products.append(product)

    pricing_service.refresh_prices("integration-test")

    price = price_repo.find_current_price(product.id)
    assert price is not None
    assert price.price_status == STATUS_OK
    assert price.resolved_price_source == "LOOSE_PACK_MARKET"
    assert price.resolved_pack_price == price.raw_loose_pack_market_price


def test_refresh_releases_lock_after_completion(created_products):
    make_real_ixalan_product(created_products)

    pricing_service.refresh_prices("integration-test")

    state = lock_service.get_lock_state()
    assert state["price_refresh_active"] is False


def test_concurrent_refresh_is_rejected(created_products):
    make_real_ixalan_product(created_products)

    session_id = lock_service.acquire_price_refresh_lock("someone-else")

    try:
        with pytest.raises(lock_service.LockConflictError):
            pricing_service.refresh_prices("integration-test")
    finally:
        lock_service.release_price_refresh_lock()


def test_manual_price_survives_a_refresh_that_still_resolves_automatically_is_overwritten(created_products):
    """LLD 9.5: a later valid automatic price replaces a manual one."""
    product = make_real_ixalan_product(created_products)

    pricing_service.enter_manual_price(product.id, Decimal("9.99"), "integration-test", note="test")
    manual_price = price_repo.find_current_price(product.id)
    assert manual_price.price_status == STATUS_MANUAL

    pricing_service.refresh_prices("integration-test")

    after_refresh = price_repo.find_current_price(product.id)
    assert after_refresh.price_status == STATUS_OK
    assert after_refresh.resolved_price_source == "DERIVED_FROM_BOX_MARKET"
    assert after_refresh.resolved_pack_price != Decimal("9.99")


def test_manual_price_preserved_when_tcgcsv_mapping_is_broken(created_products):
    """A refresh that can't find an automatic price must NOT clobber an
    existing manual price (LLD 9.5)."""
    product = product_service.create_product(
        name=unique_name("Broken Mapping"), booster_type="PLAY", packs_per_box=36,
        tcgcsv_category_id="1", tcgcsv_group_id="23556",
        loose_pack_tcgcsv_product_id="00000000",  # doesn't exist in this group
        box_tcgcsv_product_id="00000001",
        image_url="https://example.com/x.jpg", english_confirmed=True,
        created_by="integration-test",
    )
    created_products.append(product)

    pricing_service.enter_manual_price(product.id, Decimal("3.50"), "integration-test")

    pricing_service.refresh_prices("integration-test")

    price = price_repo.find_current_price(product.id)
    assert price.price_status == STATUS_MANUAL
    assert price.resolved_pack_price == Decimal("3.50")


def test_unresolved_product_then_manual_entry_then_accept_previous(created_products):
    product = product_service.create_product(
        name=unique_name("Unresolved Then Manual"), booster_type="PLAY", packs_per_box=36,
        tcgcsv_category_id="1", tcgcsv_group_id="23556",
        loose_pack_tcgcsv_product_id="00000002",
        box_tcgcsv_product_id="00000003",
        image_url="https://example.com/x.jpg", english_confirmed=True,
        created_by="integration-test",
    )
    created_products.append(product)

    pricing_service.refresh_prices("integration-test")
    unresolved = price_repo.find_current_price(product.id)
    assert unresolved.price_status == "UNRESOLVED"
    assert unresolved.resolved_pack_price is None

    # No previous price exists yet -- accept_previous_price must refuse.
    with pytest.raises(pricing_service.PriceEntryError):
        pricing_service.accept_previous_price(product.id, "integration-test")

    pricing_service.enter_manual_price(product.id, Decimal("2.00"), "integration-test")
    manual = price_repo.find_current_price(product.id)
    assert manual.resolved_pack_price == Decimal("2.00")

    event = get_master_db().audit_events.find_one({
        "action_type": "MANUAL_PRICE_ENTERED", "product_id": product.id,
    })
    assert event is not None
