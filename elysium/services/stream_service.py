"""
Stream lifecycle (LLD sections 13, 15, 16; docs/IMPLEMENTATION_PLAN.md
section 4.3). end_stream is the highest-stakes transaction in the app --
it's the only place actual packs ever leave inventory permanently.
"""

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from elysium.models.breaks import Break
from elysium.models.prices import STATUS_AMBIGUOUS, STATUS_UNRESOLVED
from elysium.models.streams import STATUS_ACTIVE, STATUS_CANCELED, STATUS_COMPLETED, Stream
from elysium.repositories import price_repository as price_repo
from elysium.repositories import streamer_repository as streamer_repo
from elysium.services import audit_service, lock_service, product_service
from elysium.services.mongo_client import get_client, get_master_db, get_streamer_db

logger = logging.getLogger(__name__)


class StreamStartBlockedError(Exception):
    pass


class StreamValidationError(Exception):
    pass


class StreamAuthorizationError(Exception):
    pass


def _build_price_snapshot(streamer_database_name: str) -> tuple[list[dict], list[str]]:
    """
    Returns (snapshot_entries, blocked_product_ids). Every positive-
    quantity product must have an accepted price (LLD 13.1/13.5) --
    blocked_product_ids lists any that don't, so the caller can surface
    exactly which ones need a manual/previous-price resolution before the
    stream can start, rather than a generic failure.
    """
    inventory = streamer_repo.list_inventory_current(streamer_database_name)
    positive_product_ids = [pid for pid, doc in inventory.items() if doc["current_packs"] > 0]

    if not positive_product_ids:
        return [], []

    products_by_id = {p.id: p for p in product_service.list_products() if p.id in positive_product_ids}
    prices = price_repo.find_current_prices(positive_product_ids)

    snapshot = []
    blocked = []
    now = datetime.now(timezone.utc)

    for product_id in positive_product_ids:
        product = products_by_id.get(product_id)
        price = prices.get(product_id)

        if price is None or price.price_status in (STATUS_UNRESOLVED, STATUS_AMBIGUOUS):
            blocked.append(product_id)
            continue

        snapshot.append({
            "product_id": product_id,
            "product_name_at_snapshot": product.name if product else product_id,
            "resolved_pack_price": price.resolved_pack_price,
            "price_source": price.resolved_price_source,
            "raw_loose_price": price.raw_loose_pack_market_price,
            "raw_box_price": price.raw_box_market_price,
            "packs_per_box": product.packs_per_box if product else price.packs_per_box,
            "price_doc_version": price.version,
            "snapshot_at": now,
        })

    return snapshot, blocked


def start_stream(streamer_id: str, streamer_database_name: str) -> Stream:
    inventory = streamer_repo.list_inventory_current(streamer_database_name)
    inventory_snapshot = [
        {"product_id": pid, "packs_at_start": doc["current_packs"]}
        for pid, doc in inventory.items() if doc["current_packs"] > 0
    ]

    price_snapshot, blocked = _build_price_snapshot(streamer_database_name)

    if blocked:
        raise StreamStartBlockedError(
            "Cannot start stream: the following products need an accepted price "
            "(use Previous Price or Enter Manual Price on Shared Sealed Prices first): "
            + ", ".join(blocked)
        )

    stream_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    stream = Stream(
        id=stream_id,
        streamer_id=streamer_id,
        status=STATUS_ACTIVE,
        date=now.date().isoformat(),
        start_time=now,
        inventory_snapshot=inventory_snapshot,
        price_snapshot=price_snapshot,
        created_at=now,
        updated_at=now,
        lock_heartbeat_at=now,
    )

    client = get_client()

    def callback(session):
        lock_service.acquire_stream_lock(streamer_id, stream_id, streamer_database_name, session=session)
        streamer_repo.insert_stream(streamer_database_name, stream, session=session)

        audit_service.record_event(
            action_type="STREAM_STARTED",
            performed_by=streamer_id,
            streamer_id=streamer_id,
            stream_id=stream_id,
            session=session,
        )

    with client.start_session() as session:
        session.with_transaction(callback)

    logger.info("Streamer '%s' started stream '%s'", streamer_id, stream_id)
    return stream


def resume_check(streamer_database_name: str) -> Stream | None:
    """For the post-login crash-recovery prompt (LLD 16.1)."""
    return streamer_repo.find_active_stream(streamer_database_name)


def _assert_lock_owned_by(stream_id: str, streamer_id: str, session) -> None:
    lock = get_master_db().global_operations.find_one({"_id": "GLOBAL_OPERATIONS"}, session=session)

    if not lock or not lock.get("stream_active") or lock.get("stream_id") != stream_id or lock.get("streamer_id") != streamer_id:
        raise StreamAuthorizationError(
            "This stream no longer holds the global stream lock (it may have been resumed "
            "elsewhere or force-canceled) -- reload before trying again."
        )


def cancel_stream(stream_id: str, streamer_id: str, streamer_database_name: str, canceled_by: str) -> None:
    """LLD 16.3: no inventory deduction, preserves all data, releases lock."""
    client = get_client()
    now = datetime.now(timezone.utc)

    def callback(session):
        _assert_lock_owned_by(stream_id, streamer_id, session)

        streamer_repo.update_stream_fields(
            streamer_database_name, stream_id,
            {"status": STATUS_CANCELED, "end_time": now, "updated_at": now},
            session=session,
        )

        lock_service.release_stream_lock(session=session)

        audit_service.record_event(
            action_type="STREAM_CANCELED",
            performed_by=canceled_by,
            streamer_id=streamer_id,
            stream_id=stream_id,
            session=session,
        )

    with client.start_session() as session:
        session.with_transaction(callback)

    logger.info("Stream '%s' canceled by '%s'", stream_id, canceled_by)


def force_cancel_stream(admin_id: str, reason: str) -> None:
    """LLD 16.4: admin recovery for a stuck stream -- operates on whatever
    stream currently holds the lock, since the original streamer may be
    unreachable. No inventory deduction."""
    if not reason or not reason.strip():
        raise StreamValidationError("A reason is required to force-cancel a stream.")

    client = get_client()
    now = datetime.now(timezone.utc)

    def callback(session):
        lock = get_master_db().global_operations.find_one({"_id": "GLOBAL_OPERATIONS"}, session=session)

        if not lock or not lock.get("stream_active"):
            raise StreamValidationError("There is no active stream to force-cancel.")

        stream_id = lock["stream_id"]
        streamer_id = lock["streamer_id"]
        streamer_database_name = lock["streamer_database_name"]

        streamer_repo.update_stream_fields(
            streamer_database_name, stream_id,
            {
                "status": STATUS_CANCELED,
                "end_time": now,
                "updated_at": now,
                "force_canceled": True,
                "force_cancel_reason": reason,
                "force_canceled_by": admin_id,
                "force_canceled_at": now,
            },
            session=session,
        )

        lock_service.release_stream_lock(session=session)

        audit_service.record_event(
            action_type="STREAM_FORCE_CANCELED",
            performed_by=admin_id,
            streamer_id=streamer_id,
            stream_id=stream_id,
            reason=reason,
            session=session,
        )

    with client.start_session() as session:
        session.with_transaction(callback)

    logger.info("Admin '%s' force-canceled the active stream (reason: %s)", admin_id, reason)


def aggregate_breaks_for_settlement(breaks: list[Break]) -> dict:
    """Pure aggregation used both by the End Stream review screen (live
    recalculation, LLD 15.1 step 6) and by end_stream's final transaction
    (recomputed from breaks as the source of truth, LLD 15.5 step 2)."""
    sum_of_break_gross = sum((b.break_gross or Decimal("0")) for b in breaks)
    stream_pack_market_value = sum((b.total_pack_market_value or Decimal("0")) for b in breaks)

    used_packs_by_product: dict[str, int] = {}
    for b in breaks:
        for line in b.pack_lines:
            used_packs_by_product[line["product_id"]] = (
                used_packs_by_product.get(line["product_id"], 0) + line["quantity"]
            )

    return {
        "sum_of_break_gross": sum_of_break_gross,
        "stream_pack_market_value": stream_pack_market_value,
        "used_packs_by_product": used_packs_by_product,
    }


def compute_stream_profit(final_stream_gross: Decimal, stream_pack_market_value: Decimal) -> Decimal:
    """LLD 15.4: Stream Profit = Final Stream Gross - Stream Pack Market Value."""
    return final_stream_gross - stream_pack_market_value


def end_stream(stream_id: str, streamer_id: str, streamer_database_name: str, final_stream_gross: Decimal, requested_by: str) -> Stream:
    if final_stream_gross < 0:
        raise StreamValidationError("Final stream gross cannot be negative.")

    client = get_client()
    master_db = get_master_db()
    streamer_db = get_streamer_db(streamer_database_name)
    now = datetime.now(timezone.utc)

    def callback(session):
        _assert_lock_owned_by(stream_id, streamer_id, session)

        breaks = streamer_repo.list_breaks_for_stream(streamer_database_name, stream_id, session=session)
        aggregates = aggregate_breaks_for_settlement(breaks)
        used_packs_by_product = aggregates["used_packs_by_product"]

        # Verify current inventory covers every grouped pack total before
        # touching anything (LLD 15.5 step 2) -- re-checked here even
        # though availability was enforced while breaks were built, since
        # this transaction is the actual point of no return.
        shortfalls = []
        for product_id, used in used_packs_by_product.items():
            current = streamer_db.inventory_current.find_one({"_id": product_id}, session=session)
            held = current["current_packs"] if current else 0
            if held < used:
                shortfalls.append(f"{product_id}: needs {used}, has {held}")

        if shortfalls:
            raise StreamValidationError(
                "Cannot complete stream -- inventory is insufficient for: " + "; ".join(shortfalls)
            )

        for product_id, used in used_packs_by_product.items():
            if used <= 0:
                continue

            streamer_db.inventory_current.update_one(
                {"_id": product_id}, {"$inc": {"current_packs": -used}, "$set": {"updated_at": now}}, session=session
            )
            master_db.streamer_allocations.update_one(
                {"streamer_id": streamer_id, "product_id": product_id},
                {"$inc": {"current_packs": -used, "version": 1}, "$set": {"updated_at": now}},
                upsert=True,
                session=session,
            )
            master_db.inventory_current.update_one(
                {"_id": product_id}, {"$inc": {"total_packs": -used}, "$set": {"updated_at": now}}, session=session
            )

        gross_difference = final_stream_gross - aggregates["sum_of_break_gross"]
        stream_profit = compute_stream_profit(final_stream_gross, aggregates["stream_pack_market_value"])
        stream_profit_margin = (stream_profit / final_stream_gross) if final_stream_gross != 0 else None

        streamer_repo.update_stream_fields(
            streamer_database_name, stream_id,
            {
                "status": STATUS_COMPLETED,
                "end_time": now,
                "updated_at": now,
                "final_stream_gross": final_stream_gross,
                "sum_of_break_gross": aggregates["sum_of_break_gross"],
                "gross_difference": gross_difference,
                "stream_pack_market_value": aggregates["stream_pack_market_value"],
                "stream_profit": stream_profit,
                "stream_profit_margin": stream_profit_margin,
            },
            session=session,
        )

        lock_service.release_stream_lock(session=session)

        audit_service.record_event(
            action_type="STREAM_COMPLETED",
            performed_by=requested_by,
            streamer_id=streamer_id,
            stream_id=stream_id,
            amount_change=stream_profit,
            after_values={"used_packs_by_product": used_packs_by_product},
            session=session,
        )

    with client.start_session() as session:
        session.with_transaction(callback)

    logger.info("Stream '%s' completed by '%s'", stream_id, requested_by)
    return streamer_repo.find_stream_by_id(streamer_database_name, stream_id)
