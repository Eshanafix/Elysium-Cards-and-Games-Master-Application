"""
Live integration tests for the full stream/break lifecycle against real
Atlas + real TCGCSV, replicating LLD acceptance tests 29.7-29.14. Uses
disposable itest_* products/streamers, cleaned up afterward. The global
stream/price-refresh lock is force-released before and after every test in
this file, regardless of outcome, since a stuck lock would break every
other test file (and the user's real app) until manually cleared.
"""

import uuid
from decimal import Decimal

import pytest

from elysium.models.streams import STATUS_ACTIVE, STATUS_CANCELED, STATUS_COMPLETED
from elysium.models.users import ROLE_STREAMER
from elysium.repositories import streamer_repository as streamer_repo
from elysium.services import (
    auth_service,
    break_service,
    inventory_service,
    lock_service,
    pricing_service,
    product_service,
    stream_service,
)
from elysium.services.mongo_client import check_connection, get_master_db

pytestmark = pytest.mark.skipif(
    not check_connection().is_connected,
    reason="MongoDB is not reachable -- set MONGODB_URI in .env to run integration tests",
)


def unique(label: str) -> str:
    return f"itest_{label}_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def clean_global_lock():
    lock_service.release_stream_lock()
    lock_service.release_price_refresh_lock()
    yield
    lock_service.release_stream_lock()
    lock_service.release_price_refresh_lock()


@pytest.fixture
def scenario():
    """One disposable product with a real TCGCSV mapping (so a real price
    refresh resolves it) plus one disposable streamer who claims 20 packs
    of it. Everything torn down afterward."""
    product = product_service.create_product(
        name=unique("Foundations Play Booster"), booster_type="PLAY", packs_per_box=36,
        tcgcsv_category_id="1", tcgcsv_group_id="23556",
        loose_pack_tcgcsv_product_id="562116", box_tcgcsv_product_id="562118",
        image_url="https://example.com/x.jpg", english_confirmed=True,
        created_by="integration-test",
    )
    pricing_service.refresh_prices("integration-test")

    streamer = auth_service.create_user(
        unique("streamStreamer"), "Passw0rd!!", [ROLE_STREAMER], created_by="integration-test"
    )

    inventory_service.admin_add_inventory(product.id, 20, "integration-test")
    inventory_service.streamer_claim(
        streamer.id, streamer.streamer_database_name, product.id, 20, requested_by=streamer.id
    )

    yield product, streamer

    master_db = get_master_db()

    active = stream_service.resume_check(streamer.streamer_database_name)
    if active is not None:
        lock_service.release_stream_lock()

    master_db.streamer_allocations.delete_many({"streamer_id": streamer.id})
    master_db.audit_events.delete_many({
        "$or": [{"performed_by": streamer.id}, {"streamer_id": streamer.id}, {"after_values.user_id": streamer.id}]
    })
    master_db.audit_events.delete_many({"performed_by": "integration-test"})
    master_db.users.delete_one({"_id": streamer.id})
    master_db.client.drop_database(streamer.streamer_database_name)

    master_db.products.delete_one({"_id": product.id})
    master_db.inventory_current.delete_one({"_id": product.id})
    master_db.audit_events.delete_many({"product_id": product.id})

    prices_db = master_db.client["elysium_prices"]
    prices_db.current_prices.delete_one({"_id": product.id})
    prices_db.price_history.delete_many({"product_id": product.id})
    prices_db.refresh_sessions.delete_many({"started_by": "integration-test"})


def test_2910_start_stream_snapshots_price_and_inventory(scenario):
    product, streamer = scenario

    stream = stream_service.start_stream(streamer.id, streamer.streamer_database_name)

    assert stream.status == STATUS_ACTIVE
    assert stream.inventory_snapshot == [{"product_id": product.id, "packs_at_start": 20}]

    price_entry = stream.price_for_product(product.id)
    assert price_entry is not None
    assert price_entry["resolved_pack_price"] > Decimal("0")
    locked_price = price_entry["resolved_pack_price"]

    lock = lock_service.get_lock_state()
    assert lock["stream_active"] is True
    assert lock["streamer_id"] == streamer.id
    assert lock["stream_id"] == stream.id

    # LLD 29.10: price cannot change mid-stream even if TCGCSV data moves --
    # a later refresh must be blocked outright while this stream holds the lock.
    with pytest.raises(lock_service.LockConflictError):
        pricing_service.refresh_prices("someone-else")

    stream_service.cancel_stream(stream.id, streamer.id, streamer.streamer_database_name, canceled_by=streamer.id)

    reloaded = streamer_repo.find_stream_by_id(streamer.streamer_database_name, stream.id)
    assert reloaded.price_for_product(product.id)["resolved_pack_price"] == locked_price


def test_298_299_one_stream_company_wide_and_inventory_protection(scenario):
    product, streamer_a = scenario

    streamer_b = auth_service.create_user(
        unique("secondStreamer"), "Passw0rd!!", [ROLE_STREAMER], created_by="integration-test"
    )

    try:
        stream_a = stream_service.start_stream(streamer_a.id, streamer_a.streamer_database_name)

        with pytest.raises(lock_service.LockConflictError):
            stream_service.start_stream(streamer_b.id, streamer_b.streamer_database_name)

        # Streamer A is locked -- claim/return must be blocked for A...
        with pytest.raises(inventory_service.StreamerLockedError):
            inventory_service.streamer_return(
                streamer_a.id, streamer_a.streamer_database_name, product.id, 1,
                reason="test", requested_by=streamer_a.id,
            )

        # ...but B can still manage their own inventory freely.
        inventory_service.admin_add_inventory(product.id, 5, "integration-test")
        inventory_service.streamer_claim(
            streamer_b.id, streamer_b.streamer_database_name, product.id, 5, requested_by=streamer_b.id
        )

        stream_service.cancel_stream(
            stream_a.id, streamer_a.id, streamer_a.streamer_database_name, canceled_by=streamer_a.id
        )
    finally:
        master_db = get_master_db()
        master_db.streamer_allocations.delete_many({"streamer_id": streamer_b.id})
        master_db.audit_events.delete_many({
            "$or": [{"performed_by": streamer_b.id}, {"streamer_id": streamer_b.id}, {"after_values.user_id": streamer_b.id}]
        })
        master_db.users.delete_one({"_id": streamer_b.id})
        master_db.client.drop_database(streamer_b.streamer_database_name)


def test_2911_2912_grouped_pack_lines_and_final_settlement(scenario):
    """LLD 29.11 (grouped, not per-pack, records) + 29.12 (final settlement
    math) + the actual inventory deduction this whole app exists to get
    right, all against real Atlas."""
    product, streamer = scenario

    stream = stream_service.start_stream(streamer.id, streamer.streamer_database_name)
    locked_price = stream.price_for_product(product.id)["resolved_pack_price"]

    b1 = break_service.start_new_break(stream, streamer.streamer_database_name)
    b1 = break_service.set_break_pack_line_quantity(stream, streamer.streamer_database_name, b1, product.id, 3)

    assert len(b1.pack_lines) == 1  # grouped: one line for quantity 3, not three records
    assert b1.pack_lines[0]["quantity"] == 3
    assert b1.total_pack_market_value == locked_price * 3

    availability = break_service.get_availability(stream, None, streamer.streamer_database_name)
    assert availability[product.id] == 17  # 20 - 3

    b1 = break_service.end_break(streamer.streamer_database_name, b1, Decimal("30.00"), ended_by=streamer.id)
    assert b1.break_profit == Decimal("30.00") - b1.total_pack_market_value

    b2 = break_service.start_new_break(stream, streamer.streamer_database_name)
    b2 = break_service.set_break_pack_line_quantity(stream, streamer.streamer_database_name, b2, product.id, 2)
    b2 = break_service.end_break(streamer.streamer_database_name, b2, Decimal("25.00"), ended_by=streamer.id)

    # A third break gets started then deleted -- its packs must NOT count
    # against the final settlement (LLD 15.2).
    b3 = break_service.start_new_break(stream, streamer.streamer_database_name)
    b3 = break_service.set_break_pack_line_quantity(stream, streamer.streamer_database_name, b3, product.id, 4)
    break_service.delete_break(streamer.streamer_database_name, b3, deleted_by=streamer.id)

    availability_after_delete = break_service.get_availability(stream, None, streamer.streamer_database_name)
    assert availability_after_delete[product.id] == 15  # 20 - 3 - 2, the deleted 4 freed back up

    final_gross = Decimal("52.00")  # sum of breaks = 55.00, so a -3.00 gross difference
    completed = stream_service.end_stream(
        stream.id, streamer.id, streamer.streamer_database_name, final_gross, requested_by=streamer.id
    )

    assert completed.status == STATUS_COMPLETED
    assert completed.sum_of_break_gross == Decimal("55.00")
    assert completed.gross_difference == Decimal("-3.00")
    expected_market_value = locked_price * 5  # 3 + 2 packs used across the two real breaks
    assert completed.stream_pack_market_value == expected_market_value
    assert completed.stream_profit == final_gross - expected_market_value

    # The actual point of the whole app: inventory really left the building.
    streamer_inv = get_master_db().client[streamer.streamer_database_name].inventory_current.find_one({"_id": product.id})
    assert streamer_inv["current_packs"] == 15  # 20 - 5 used (not 20-9; the deleted break's 4 never counted)

    master_inv = get_master_db().inventory_current.find_one({"_id": product.id})
    assert master_inv["total_packs"] == 15  # started at 20, 5 packs permanently consumed
    allocation = get_master_db().streamer_allocations.find_one({"streamer_id": streamer.id, "product_id": product.id})
    assert allocation["current_packs"] == 15

    lock = lock_service.get_lock_state()
    assert lock["stream_active"] is False

    completed_audit = get_master_db().audit_events.find_one({
        "action_type": "STREAM_COMPLETED", "stream_id": stream.id,
    })
    assert completed_audit is not None


def test_2913_stream_cancellation_makes_no_inventory_deduction(scenario):
    product, streamer = scenario

    stream = stream_service.start_stream(streamer.id, streamer.streamer_database_name)
    b1 = break_service.start_new_break(stream, streamer.streamer_database_name)
    break_service.set_break_pack_line_quantity(stream, streamer.streamer_database_name, b1, product.id, 10)

    stream_service.cancel_stream(stream.id, streamer.id, streamer.streamer_database_name, canceled_by=streamer.id)

    streamer_inv = get_master_db().client[streamer.streamer_database_name].inventory_current.find_one({"_id": product.id})
    assert streamer_inv["current_packs"] == 20  # unchanged

    master_inv = get_master_db().inventory_current.find_one({"_id": product.id})
    assert master_inv["total_packs"] == 20  # unchanged

    reloaded = streamer_repo.find_stream_by_id(streamer.streamer_database_name, stream.id)
    assert reloaded.status == STATUS_CANCELED

    lock = lock_service.get_lock_state()
    assert lock["stream_active"] is False


def test_2914_crash_recovery_resume(scenario):
    product, streamer = scenario

    stream = stream_service.start_stream(streamer.id, streamer.streamer_database_name)
    b1 = break_service.start_new_break(stream, streamer.streamer_database_name)
    break_service.set_break_pack_line_quantity(stream, streamer.streamer_database_name, b1, product.id, 6)
    break_service.end_break(streamer.streamer_database_name, b1, Decimal("20.00"), ended_by=streamer.id)

    # Simulate the app closing and reopening -- resume_check must find the
    # exact same in-progress state, fully persisted (LLD 16.1/16.2).
    resumed = stream_service.resume_check(streamer.streamer_database_name)

    assert resumed is not None
    assert resumed.id == stream.id
    assert resumed.status == STATUS_ACTIVE

    breaks = streamer_repo.list_breaks_for_stream(streamer.streamer_database_name, resumed.id)
    assert len(breaks) == 1
    assert breaks[0].break_gross == Decimal("20.00")
    assert breaks[0].pack_lines[0]["quantity"] == 6

    stream_service.cancel_stream(stream.id, streamer.id, streamer.streamer_database_name, canceled_by=streamer.id)


def test_force_cancel_stuck_stream(scenario):
    product, streamer = scenario

    stream = stream_service.start_stream(streamer.id, streamer.streamer_database_name)
    b1 = break_service.start_new_break(stream, streamer.streamer_database_name)
    break_service.set_break_pack_line_quantity(stream, streamer.streamer_database_name, b1, product.id, 5)

    stream_service.force_cancel_stream("admin-integration-test", "streamer unreachable")

    reloaded = streamer_repo.find_stream_by_id(streamer.streamer_database_name, stream.id)
    assert reloaded.status == STATUS_CANCELED
    assert reloaded.force_canceled is True
    assert reloaded.force_cancel_reason == "streamer unreachable"

    lock = lock_service.get_lock_state()
    assert lock["stream_active"] is False

    # No inventory deduction from a force-cancel (LLD 16.4).
    streamer_inv = get_master_db().client[streamer.streamer_database_name].inventory_current.find_one({"_id": product.id})
    assert streamer_inv["current_packs"] == 20


def test_only_one_active_break_at_a_time(scenario):
    product, streamer = scenario

    stream = stream_service.start_stream(streamer.id, streamer.streamer_database_name)
    break_service.start_new_break(stream, streamer.streamer_database_name)

    with pytest.raises(break_service.BreakValidationError):
        break_service.start_new_break(stream, streamer.streamer_database_name)

    stream_service.cancel_stream(stream.id, streamer.id, streamer.streamer_database_name, canceled_by=streamer.id)


def test_cannot_select_more_packs_than_available(scenario):
    product, streamer = scenario

    stream = stream_service.start_stream(streamer.id, streamer.streamer_database_name)
    b1 = break_service.start_new_break(stream, streamer.streamer_database_name)

    with pytest.raises(break_service.InsufficientAvailabilityError):
        break_service.set_break_pack_line_quantity(stream, streamer.streamer_database_name, b1, product.id, 21)

    stream_service.cancel_stream(stream.id, streamer.id, streamer.streamer_database_name, canceled_by=streamer.id)
