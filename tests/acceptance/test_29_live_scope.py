"""
LLD section 29 acceptance criteria that require real Atlas (+ real TCGCSV
for pricing). Skipped automatically if MongoDB is unreachable. Uses
disposable itest_*/integration-test-prefixed data, always cleaned up.

29.7-29.14 (price refresh lock, one active stream, active-inventory
protection, stream price snapshot, grouped pack lines, final stream
calculation, stream cancellation, crash recovery) already have thorough,
dedicated coverage in test_stream_service_live.py and are not duplicated
here -- this file covers everything else in section 29.
"""

import uuid
from decimal import Decimal

import pytest

from elysium.models.streams import STATUS_COMPLETED
from elysium.models.users import ROLE_ADMIN, ROLE_STREAMER
from elysium.repositories import master_repository as repo
from elysium.repositories import streamer_repository as streamer_repo
from elysium.services import (
    auth_service,
    break_service,
    correction_service,
    decommission_service,
    inventory_service,
    pricing_service,
    product_service,
    report_service,
    stream_service,
)
from elysium.services.mongo_client import check_connection, get_master_db

pytestmark = pytest.mark.skipif(
    not check_connection().is_connected,
    reason="MongoDB is not reachable -- set MONGODB_URI in .env to run integration tests",
)


def unique(label: str) -> str:
    return f"itest_{label}_{uuid.uuid4().hex[:8]}"


def make_product(real_pricing: bool = False, **overrides):
    """By default uses fully unique fake TCGCSV ids -- no collision risk
    with any other test or leftover data, and no real network call. Pass
    real_pricing=True for tests that actually need pricing_service.
    refresh_prices() to resolve a real price (the real "Foundations Play
    Booster" mapping verified during Phase 3: category 1, group 23556,
    loose=562116, box=562118)."""
    kwargs = dict(
        name=unique("Product"), booster_type="PLAY", packs_per_box=36,
        tcgcsv_category_id="1", tcgcsv_group_id="23556",
        loose_pack_tcgcsv_product_id=unique("loose"), box_tcgcsv_product_id=unique("box"),
        image_url="https://example.com/x.jpg", english_confirmed=True,
        created_by="integration-test",
    )
    if real_pricing:
        kwargs["loose_pack_tcgcsv_product_id"] = "562116"
        kwargs["box_tcgcsv_product_id"] = "562118"
    kwargs.update(overrides)
    return product_service.create_product(**kwargs)


def cleanup_product(product):
    master_db = get_master_db()
    master_db.products.delete_one({"_id": product.id})
    master_db.inventory_current.delete_one({"_id": product.id})
    master_db.streamer_allocations.delete_many({"product_id": product.id})
    master_db.audit_events.delete_many({"product_id": product.id})
    master_db.inventory_discrepancies.delete_many({"product_id": product.id})
    prices_db = master_db.client["elysium_prices"]
    prices_db.current_prices.delete_one({"_id": product.id})
    prices_db.price_history.delete_many({"product_id": product.id})


def make_streamer():
    return auth_service.create_user(unique("streamer"), "Passw0rd!!", [ROLE_STREAMER], created_by="integration-test")


def cleanup_streamer(streamer):
    master_db = get_master_db()
    master_db.streamer_allocations.delete_many({"streamer_id": streamer.id})
    master_db.audit_events.delete_many({
        "$or": [{"performed_by": streamer.id}, {"streamer_id": streamer.id}, {"after_values.user_id": streamer.id}]
    })
    master_db.inventory_discrepancies.delete_many({"streamer_id": streamer.id})
    master_db.decommission_requests.delete_many({"streamer_id": streamer.id})
    master_db.users.delete_one({"_id": streamer.id})
    master_db.client.drop_database(streamer.streamer_database_name)


def make_admin():
    return auth_service.create_user(unique("admin"), "Passw0rd!!", [ROLE_ADMIN], created_by="integration-test")


def cleanup_admin(admin):
    master_db = get_master_db()
    master_db.audit_events.delete_many({
        "$or": [{"performed_by": admin.id}, {"after_values.user_id": admin.id}]
    })
    master_db.users.delete_one({"_id": admin.id})


def test_29_2_master_addition():
    product = None
    try:
        product = make_product()

        before = repo.get_inventory_current(product.id)
        assert before["total_packs"] == 0 and before["unassigned_packs"] == 0

        inventory_service.admin_add_inventory(product.id, 76, "integration-test")

        after = repo.get_inventory_current(product.id)
        assert after["total_packs"] == 76
        assert after["unassigned_packs"] == 76

        audit = get_master_db().audit_events.find_one({"action_type": "MASTER_INVENTORY_ADDED", "product_id": product.id})
        assert audit is not None
    finally:
        if product is not None:
            cleanup_product(product)


def test_29_3_valid_streamer_claim():
    product = None
    streamer = None
    try:
        product = make_product()
        streamer = make_streamer()

        inventory_service.admin_add_inventory(product.id, 60, "integration-test")
        inventory_service.streamer_claim(streamer.id, streamer.streamer_database_name, product.id, 30, requested_by=streamer.id)

        master_inv = repo.get_inventory_current(product.id)
        assert master_inv["unassigned_packs"] == 30
        assert master_inv["total_packs"] == 60

        allocation = repo.get_streamer_allocation(streamer.id, product.id)
        assert allocation["current_packs"] == 30

        streamer_inv = streamer_repo.get_inventory_current(streamer.streamer_database_name, product.id)
        assert streamer_inv["current_packs"] == 30
    finally:
        if streamer is not None:
            cleanup_streamer(streamer)
        if product is not None:
            cleanup_product(product)


def test_29_4_over_claim_rejection():
    product = None
    streamer = None
    try:
        product = make_product()
        streamer = make_streamer()

        inventory_service.admin_add_inventory(product.id, 30, "integration-test")
        before = repo.get_inventory_current(product.id)

        with pytest.raises(inventory_service.InsufficientInventoryError):
            inventory_service.streamer_claim(streamer.id, streamer.streamer_database_name, product.id, 40, requested_by=streamer.id)

        after = repo.get_inventory_current(product.id)
        assert after == before  # nothing changed
        assert repo.get_streamer_allocation(streamer.id, product.id) is None
    finally:
        if streamer is not None:
            cleanup_streamer(streamer)
        if product is not None:
            cleanup_product(product)


def test_29_5_streamer_return():
    product = None
    streamer = None
    try:
        product = make_product()
        streamer = make_streamer()

        inventory_service.admin_add_inventory(product.id, 30, "integration-test")
        inventory_service.streamer_claim(streamer.id, streamer.streamer_database_name, product.id, 30, requested_by=streamer.id)

        inventory_service.streamer_return(
            streamer.id, streamer.streamer_database_name, product.id, 10, reason="test return", requested_by=streamer.id
        )

        allocation = repo.get_streamer_allocation(streamer.id, product.id)
        assert allocation["current_packs"] == 20

        master_inv = repo.get_inventory_current(product.id)
        assert master_inv["unassigned_packs"] == 10
        assert master_inv["total_packs"] == 30  # unchanged
    finally:
        if streamer is not None:
            cleanup_streamer(streamer)
        if product is not None:
            cleanup_product(product)


def test_29_6_price_priority_box_derived_fallback():
    """Missing loose price plus a valid box price uses the box price
    divided by packs per box (the loose/manual/previous cases are already
    covered live in test_pricing_service_live.py)."""
    product = None
    try:
        # Real box mapping, but a fake loose id -> loose resolves absent.
        product = make_product(real_pricing=True, loose_pack_tcgcsv_product_id=unique("no-such-loose"))

        pricing_service.refresh_prices("integration-test")

        from elysium.repositories import price_repository as price_repo
        current = price_repo.find_current_price(product.id)

        assert current.raw_loose_pack_market_price is None
        assert current.raw_box_market_price is not None
        assert current.resolved_price_source == "DERIVED_FROM_BOX_MARKET"
        assert current.resolved_pack_price == (current.raw_box_market_price / product.packs_per_box)
    finally:
        if product is not None:
            cleanup_product(product)


def test_29_15_completed_stream_correction():
    """Streamer cannot edit a completed stream's break; admin can, with a
    required reason, using the original locked price, recalculating
    inventory and profit -- original figures remain in audit history."""
    product = None
    streamer = None
    admin = None
    try:
        product = make_product(real_pricing=True)
        streamer = make_streamer()
        admin = make_admin()

        inventory_service.admin_add_inventory(product.id, 20, "integration-test")
        inventory_service.streamer_claim(streamer.id, streamer.streamer_database_name, product.id, 20, requested_by=streamer.id)
        pricing_service.refresh_prices("integration-test")

        stream = stream_service.start_stream(streamer.id, streamer.streamer_database_name)
        b1 = break_service.start_new_break(stream, streamer.streamer_database_name)
        b1 = break_service.set_break_pack_line_quantity(stream, streamer.streamer_database_name, b1, product.id, 3)
        b1 = break_service.end_break(streamer.streamer_database_name, b1, Decimal("30.00"), ended_by=streamer.id)
        completed = stream_service.end_stream(
            stream.id, streamer.id, streamer.streamer_database_name, Decimal("30.00"), requested_by=streamer.id
        )
        assert completed.status == STATUS_COMPLETED

        # Streamer cannot edit a completed stream's break.
        with pytest.raises(break_service.BreakValidationError):
            break_service.edit_break_gross(streamer.streamer_database_name, b1, Decimal("40.00"), edited_by=streamer.id)

        original_locked_price = b1.pack_lines[0]["locked_unit_price"]

        # Admin corrects it with a required reason.
        with pytest.raises(correction_service.CorrectionValidationError):
            correction_service.correct_break(
                stream.id, streamer.id, streamer.streamer_database_name, b1.id,
                admin_id=admin.id, reason="", new_break_gross=Decimal("40.00"),
            )

        corrected_stream = correction_service.correct_break(
            stream.id, streamer.id, streamer.streamer_database_name, b1.id,
            admin_id=admin.id, reason="reviewed footage, gross was misread", new_break_gross=Decimal("40.00"),
        )

        corrected_break = streamer_repo.find_break_by_id(streamer.streamer_database_name, b1.id)
        assert corrected_break.break_gross == Decimal("40.00")
        assert corrected_break.pack_lines[0]["locked_unit_price"] == original_locked_price  # unchanged, still locked
        assert corrected_break.break_profit == Decimal("40.00") - corrected_break.total_pack_market_value
        assert len(corrected_stream.corrections) == 1

        # Original values remain in the audit trail for the *original* action.
        original_audit = get_master_db().audit_events.find_one({"action_type": "BREAK_ENDED", "break_id": b1.id})
        assert original_audit is not None
        assert original_audit["amount_change"].to_decimal() == Decimal("30.00")
    finally:
        if admin is not None:
            cleanup_admin(admin)
        if streamer is not None:
            cleanup_streamer(streamer)
        if product is not None:
            cleanup_product(product)


def test_29_16_zero_stock():
    """A product reduced to zero stock stays in the catalog/prices/
    inventory/reports and sorts below any positive-stock product."""
    zero_product = None
    positive_product = None
    try:
        zero_product = make_product(name=unique("Zero Stock Product"))
        positive_product = make_product(name=unique("Positive Stock Product"))

        inventory_service.admin_add_inventory(zero_product.id, 10, "integration-test")
        inventory_service.admin_reduce_inventory(zero_product.id, 10, reason="test zeroing", admin_id="integration-test")
        inventory_service.admin_add_inventory(positive_product.id, 5, "integration-test")

        zero_inv = repo.get_inventory_current(zero_product.id)
        assert zero_inv["total_packs"] == 0
        assert repo.find_product_by_id(zero_product.id) is not None  # still in the catalog

        products = repo.list_products()
        ids_in_order = [p.id for p in products]
        assert ids_in_order.index(positive_product.id) < ids_in_order.index(zero_product.id)
    finally:
        if zero_product is not None:
            cleanup_product(zero_product)
        if positive_product is not None:
            cleanup_product(positive_product)


def test_29_17_decommission():
    """Initiation creates a pending request and does not disable login;
    approval returns inventory to unassigned and disables login; the
    streamer's historical database still exists afterward."""
    product = None
    streamer = None
    try:
        product = make_product()
        streamer = make_streamer()

        inventory_service.admin_add_inventory(product.id, 20, "integration-test")
        inventory_service.streamer_claim(streamer.id, streamer.streamer_database_name, product.id, 12, requested_by=streamer.id)

        request = decommission_service.initiate(streamer.id, initiated_by="integration-test")
        assert request.status == "PENDING"

        still_active = repo.find_user_by_id(streamer.id)
        assert still_active.is_active is True  # not disabled yet

        decommission_service.approve(request.id, approved_by="integration-test")

        master_inv = repo.get_inventory_current(product.id)
        assert master_inv["unassigned_packs"] == 20  # the 12 came back

        allocation = repo.get_streamer_allocation(streamer.id, product.id)
        assert allocation["current_packs"] == 0

        disabled = repo.find_user_by_id(streamer.id)
        assert disabled.is_active is False

        # Historical database remains -- not dropped by decommissioning.
        db_names = get_master_db().client.list_database_names()
        assert streamer.streamer_database_name in db_names
    finally:
        if streamer is not None:
            cleanup_streamer(streamer)
        if product is not None:
            cleanup_product(product)


def test_29_20_csv_permissions():
    """Admin can export company-wide data; a streamer can only ever
    retrieve their own data; audit exports are admin-only."""
    from elysium.exports.report_definitions import available_reports

    streamer = None
    admin = None
    try:
        streamer = make_streamer()
        admin = make_admin()

        # Audit export is admin-only: not even listed for a streamer, and
        # the underlying query refuses a streamer caller outright.
        streamer_reports = {r.key for r in available_reports(streamer)}
        assert "inventory_audit" not in streamer_reports
        assert "users" not in streamer_reports

        with pytest.raises(report_service.ReportPermissionError):
            report_service.inventory_audit_report(streamer)

        # Admin sees everything, including the admin-only datasets.
        admin_reports = {r.key for r in available_reports(admin)}
        assert "inventory_audit" in admin_reports
        assert "users" in admin_reports
    finally:
        if admin is not None:
            cleanup_admin(admin)
        if streamer is not None:
            cleanup_streamer(streamer)
