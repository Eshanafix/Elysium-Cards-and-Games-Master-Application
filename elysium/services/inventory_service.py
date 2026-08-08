"""
Master and streamer inventory (LLD sections 10, 11; docs/IMPLEMENTATION_
PLAN.md section 4.3). Packs are the only stored inventory unit -- box
counts are a UI-only convenience converted to packs before anything is
written (LLD 4.1). Claim/return span two databases in one MongoDB
transaction; add/reduce touch only elysium_master but still use a
transaction so the inventory update and its audit record can never
diverge.
"""

import logging
import uuid
from datetime import datetime, timezone

from elysium.models.reason_notes import ReasonNote
from elysium.repositories import master_repository as repo
from elysium.repositories import streamer_repository as streamer_repo
from elysium.services import audit_service
from elysium.services.mongo_client import get_client, get_master_db, get_streamer_db

logger = logging.getLogger(__name__)


class InventoryValidationError(Exception):
    pass


class InsufficientInventoryError(Exception):
    pass


class StreamerLockedError(Exception):
    pass


def box_to_packs(boxes: int, loose_packs: int, packs_per_box: int) -> int:
    """LLD 4.1: UI accepts boxes + loose packs; only the final pack count
    is ever stored. No box quantity is stored in inventory or audit."""
    if boxes < 0 or loose_packs < 0:
        raise InventoryValidationError("Box and pack counts cannot be negative.")

    if packs_per_box < 1:
        raise InventoryValidationError("Packs per box must be a positive integer.")

    return boxes * packs_per_box + loose_packs


def _require_positive_quantity(packs: int) -> None:
    if packs <= 0:
        raise InventoryValidationError("Quantity must be a positive number of packs.")


def _active_stream_lock(session) -> dict | None:
    return get_master_db().global_operations.find_one({"_id": "GLOBAL_OPERATIONS"}, session=session)


def _create_reason_note(
    action_type: str, product_id: str, streamer_id: str | None, text: str, created_by: str, now, session
) -> str:
    """Master reduction and streamer return are the only two action types
    with no other live document to hold an editable reason (plan section
    4.5) -- this is their one-time-created, later-editable home. streamer_id
    is set only for STREAMER_INVENTORY_RETURNED, so that streamer (and only
    that streamer, or an admin) can later edit their own reason text."""
    note = ReasonNote(
        id=str(uuid.uuid4()),
        action_type=action_type,
        current_text=text,
        streamer_id=streamer_id,
        product_id=product_id,
        history=[{"text": text, "edited_by": created_by, "edited_at": now}],
        created_at=now,
        created_by=created_by,
        updated_at=now,
    )
    repo.insert_reason_note(note, session=session)
    return note.id


def _assert_streamer_not_locked(streamer_id: str, session) -> None:
    """Forward-compatible with Phase 5: global_operations.stream_active is
    always False until stream_service exists, so this is currently always
    a no-op -- it will correctly start blocking claims/returns for the
    active streamer the moment streams are implemented, with no changes
    needed here later."""
    lock = _active_stream_lock(session)

    if lock and lock.get("stream_active") and lock.get("streamer_id") == streamer_id:
        raise StreamerLockedError(
            "This streamer's inventory is locked because they have an active stream. "
            "Complete or cancel the stream before modifying this inventory."
        )


# --- Admin: master inventory (LLD 10.3, 10.4) ---


def admin_add_inventory(product_id: str, packs: int, admin_id: str) -> None:
    _require_positive_quantity(packs)

    client = get_client()
    db = get_master_db()
    now = datetime.now(timezone.utc)

    def callback(session):
        before = db.inventory_current.find_one({"_id": product_id}, session=session)

        if before is None:
            raise InventoryValidationError(f"No master inventory record for product '{product_id}'.")

        db.inventory_current.update_one(
            {"_id": product_id},
            {"$inc": {"total_packs": packs, "unassigned_packs": packs, "version": 1}, "$set": {"updated_at": now}},
            session=session,
        )

        audit_service.record_event(
            action_type="MASTER_INVENTORY_ADDED",
            performed_by=admin_id,
            product_id=product_id,
            quantity_change=packs,
            before_values={"total_packs": before["total_packs"], "unassigned_packs": before["unassigned_packs"]},
            after_values={"total_packs": before["total_packs"] + packs, "unassigned_packs": before["unassigned_packs"] + packs},
            session=session,
        )

    with client.start_session() as session:
        session.with_transaction(callback)

    logger.info("Admin '%s' added %s packs to product '%s'", admin_id, packs, product_id)


def admin_reduce_inventory(product_id: str, packs: int, reason: str, admin_id: str) -> None:
    _require_positive_quantity(packs)

    if not reason or not reason.strip():
        raise InventoryValidationError("A reason is required to reduce master inventory.")

    client = get_client()
    db = get_master_db()
    now = datetime.now(timezone.utc)

    def callback(session):
        before = db.inventory_current.find_one({"_id": product_id}, session=session)

        if before is None:
            raise InventoryValidationError(f"No master inventory record for product '{product_id}'.")

        if before["unassigned_packs"] < packs:
            raise InsufficientInventoryError(
                f"Cannot remove {packs} packs: only {before['unassigned_packs']} are unassigned "
                f"(total: {before['total_packs']})."
            )

        db.inventory_current.update_one(
            {"_id": product_id},
            {"$inc": {"total_packs": -packs, "unassigned_packs": -packs, "version": 1}, "$set": {"updated_at": now}},
            session=session,
        )

        reason_note_id = _create_reason_note(
            "MASTER_INVENTORY_REMOVED", product_id, None, reason, admin_id, now, session
        )

        audit_service.record_event(
            action_type="MASTER_INVENTORY_REMOVED",
            performed_by=admin_id,
            product_id=product_id,
            quantity_change=-packs,
            reason=reason,
            reason_note_id=reason_note_id,
            before_values={"total_packs": before["total_packs"], "unassigned_packs": before["unassigned_packs"]},
            after_values={"total_packs": before["total_packs"] - packs, "unassigned_packs": before["unassigned_packs"] - packs},
            session=session,
        )

    with client.start_session() as session:
        session.with_transaction(callback)

    logger.info("Admin '%s' removed %s packs from product '%s' (reason: %s)", admin_id, packs, product_id, reason)


# --- Streamer: claim/return own inventory (LLD 11.2, 11.3) ---


def streamer_claim(streamer_id: str, streamer_database_name: str, product_id: str, packs: int, requested_by: str) -> None:
    _require_positive_quantity(packs)

    client = get_client()
    master_db = get_master_db()
    streamer_db = get_streamer_db(streamer_database_name)
    now = datetime.now(timezone.utc)

    def callback(session):
        _assert_streamer_not_locked(streamer_id, session)

        updated = master_db.inventory_current.find_one_and_update(
            {"_id": product_id, "unassigned_packs": {"$gte": packs}},
            {"$inc": {"unassigned_packs": -packs, "version": 1}, "$set": {"updated_at": now}},
            session=session,
        )

        if updated is None:
            current = master_db.inventory_current.find_one({"_id": product_id}, session=session)
            unassigned = current["unassigned_packs"] if current else 0
            already_assigned = (current["total_packs"] - unassigned) if current else 0
            raise InsufficientInventoryError(
                f"Unable to claim {packs} packs.\n"
                f"Master total: {current['total_packs'] if current else 0}\n"
                f"Already assigned: {already_assigned}\n"
                f"Currently unassigned: {unassigned}"
            )

        master_db.streamer_allocations.update_one(
            {"streamer_id": streamer_id, "product_id": product_id},
            {"$inc": {"current_packs": packs, "version": 1}, "$set": {"updated_at": now}},
            upsert=True,
            session=session,
        )

        streamer_db.inventory_current.update_one(
            {"_id": product_id},
            {"$inc": {"current_packs": packs}, "$set": {"updated_at": now, "product_id": product_id}},
            upsert=True,
            session=session,
        )

        audit_service.record_event(
            action_type="STREAMER_INVENTORY_CLAIMED",
            performed_by=requested_by,
            streamer_id=streamer_id,
            product_id=product_id,
            quantity_change=packs,
            session=session,
        )

    with client.start_session() as session:
        session.with_transaction(callback)

    logger.info("Streamer '%s' claimed %s packs of product '%s'", streamer_id, packs, product_id)


def streamer_return(streamer_id: str, streamer_database_name: str, product_id: str, packs: int, reason: str, requested_by: str) -> None:
    _require_positive_quantity(packs)

    if not reason or not reason.strip():
        raise InventoryValidationError("A reason is required to return inventory.")

    client = get_client()
    master_db = get_master_db()
    streamer_db = get_streamer_db(streamer_database_name)
    now = datetime.now(timezone.utc)

    def callback(session):
        _assert_streamer_not_locked(streamer_id, session)

        updated = streamer_db.inventory_current.find_one_and_update(
            {"_id": product_id, "current_packs": {"$gte": packs}},
            {"$inc": {"current_packs": -packs}, "$set": {"updated_at": now}},
            session=session,
        )

        if updated is None:
            current = streamer_db.inventory_current.find_one({"_id": product_id}, session=session)
            held = current["current_packs"] if current else 0
            raise InsufficientInventoryError(
                f"Unable to return {packs} packs: this streamer currently holds only {held}."
            )

        master_db.streamer_allocations.update_one(
            {"streamer_id": streamer_id, "product_id": product_id},
            {"$inc": {"current_packs": -packs, "version": 1}, "$set": {"updated_at": now}},
            upsert=True,
            session=session,
        )

        master_db.inventory_current.update_one(
            {"_id": product_id},
            {"$inc": {"unassigned_packs": packs}, "$set": {"updated_at": now}},
            session=session,
        )

        reason_note_id = _create_reason_note(
            "STREAMER_INVENTORY_RETURNED", product_id, streamer_id, reason, requested_by, now, session
        )

        audit_service.record_event(
            action_type="STREAMER_INVENTORY_RETURNED",
            performed_by=requested_by,
            streamer_id=streamer_id,
            product_id=product_id,
            quantity_change=-packs,
            reason=reason,
            reason_note_id=reason_note_id,
            session=session,
        )

    with client.start_session() as session:
        session.with_transaction(callback)

    logger.info("Streamer '%s' returned %s packs of product '%s' (reason: %s)", streamer_id, packs, product_id, reason)


# --- Views ---


def get_master_inventory_view() -> list[dict]:
    """One row per product for the Master Inventory screen (LLD 10.5):
    product info + total/unassigned/assigned + per-streamer breakdown."""
    from elysium.repositories import price_repository as price_repo

    products = repo.list_products()
    inventory_by_product = repo.list_inventory_current()
    allocations = repo.list_all_streamer_allocations()
    prices = price_repo.list_all_current_prices()
    username_by_id = {user.id: user.username for user in repo.list_users()}

    allocations_by_product: dict[str, list[dict]] = {}
    for allocation in allocations:
        # Attach the readable username once here rather than showing a
        # truncated streamer_id (e.g. "ff63f196:18") in the UI.
        allocation = dict(allocation)
        allocation["streamer_username"] = username_by_id.get(allocation["streamer_id"], allocation["streamer_id"])
        allocations_by_product.setdefault(allocation["product_id"], []).append(allocation)

    rows = []
    for product in products:
        inventory = inventory_by_product.get(product.id, {"total_packs": 0, "unassigned_packs": 0})
        product_allocations = allocations_by_product.get(product.id, [])
        price = prices.get(product.id)

        rows.append({
            "product": product,
            "total_packs": inventory["total_packs"],
            "unassigned_packs": inventory["unassigned_packs"],
            "assigned_packs": inventory["total_packs"] - inventory["unassigned_packs"],
            "allocations": product_allocations,
            "resolved_pack_price": price.resolved_pack_price if price else None,
            "price_status": price.price_status if price else "UNRESOLVED",
        })

    return rows


def get_streamer_inventory_view(streamer_database_name: str) -> list[dict]:
    """One row per product with a nonzero (or ever-claimed) balance for the
    My Inventory screen -- joined with product catalog info for display."""
    from elysium.repositories import price_repository as price_repo

    products_by_id = {p.id: p for p in repo.list_products()}
    inventory = streamer_repo.list_inventory_current(streamer_database_name)
    prices = price_repo.list_all_current_prices()

    rows = []
    for product_id, doc in inventory.items():
        product = products_by_id.get(product_id)

        if product is None:
            continue

        price = prices.get(product_id)

        rows.append({
            "product": product,
            "current_packs": doc["current_packs"],
            "resolved_pack_price": price.resolved_pack_price if price else None,
            "price_status": price.price_status if price else "UNRESOLVED",
        })

    return rows
