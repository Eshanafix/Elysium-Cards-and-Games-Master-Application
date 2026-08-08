"""
Decommissioning a streamer account (LLD section 18; docs/IMPLEMENTATION_
PLAN.md sections 4.3, 4.8). Two-step process: initiate() snapshots the
streamer's current allocation with no writes to inventory; approve() is the
actual cross-database transaction that sweeps positive balances back to
master unassigned stock and disables login. This is the only path allowed
to disable a streamer who holds any nonzero (positive or negative)
inventory -- auth_service.disable_account redirects here rather than ever
disabling such an account directly.
"""

import logging
import uuid
from datetime import datetime, timezone

from elysium.models.decommission import (
    STATUS_APPROVED,
    STATUS_CANCELED,
    STATUS_PENDING,
    DecommissionRequest,
)
from elysium.models.users import ROLE_STREAMER
from elysium.repositories import master_repository as repo
from elysium.services import audit_service, lock_service
from elysium.services.mongo_client import get_client, get_master_db, get_streamer_db

logger = logging.getLogger(__name__)


class DecommissionValidationError(Exception):
    pass


class ActiveStreamLockError(Exception):
    pass


def _assert_not_active_streamer(streamer_id: str) -> None:
    lock = lock_service.get_lock_state()

    if lock.get("stream_active") and lock.get("streamer_id") == streamer_id:
        raise ActiveStreamLockError(
            "This streamer currently owns the active stream. "
            "Complete or cancel it before decommissioning this account."
        )


def initiate(streamer_id: str, initiated_by: str, notes: str | None = None) -> DecommissionRequest:
    user = repo.find_user_by_id(streamer_id)

    if user is None or ROLE_STREAMER not in user.roles:
        raise DecommissionValidationError(f"'{streamer_id}' is not a streamer account.")

    if repo.find_pending_decommission_request_for_streamer(streamer_id):
        raise DecommissionValidationError("A decommission request for this streamer is already pending.")

    _assert_not_active_streamer(streamer_id)

    allocations = repo.list_streamer_allocations_for_streamer(streamer_id)
    snapshot = [
        {"product_id": a["product_id"], "current_packs": a["current_packs"]}
        for a in allocations
        if a.get("current_packs", 0) != 0
    ]

    request = DecommissionRequest(
        id=str(uuid.uuid4()),
        streamer_id=streamer_id,
        initiated_by=initiated_by,
        initiated_at=datetime.now(timezone.utc),
        snapshot_of_allocations_at_initiation=snapshot,
        status=STATUS_PENDING,
        notes=notes,
    )
    repo.insert_decommission_request(request)
    repo.update_user_fields(streamer_id, {"decommission_status": STATUS_PENDING})

    audit_service.record_event(
        action_type="DECOMMISSION_INITIATED",
        performed_by=initiated_by,
        streamer_id=streamer_id,
        after_values={"request_id": request.id, "snapshot": snapshot},
    )

    logger.info("Decommission initiated for streamer '%s' by '%s'", streamer_id, initiated_by)
    return request


def approve(request_id: str, approved_by: str) -> DecommissionRequest:
    request = repo.find_decommission_request(request_id)

    if request is None:
        raise DecommissionValidationError(f"No such decommission request: {request_id}")

    if request.status != STATUS_PENDING:
        raise DecommissionValidationError(f"Decommission request is not pending (status: {request.status}).")

    user = repo.find_user_by_id(request.streamer_id)

    if user is None:
        raise DecommissionValidationError(f"No such user: {request.streamer_id}")

    _assert_not_active_streamer(request.streamer_id)

    client = get_client()
    master_db = get_master_db()
    streamer_db = get_streamer_db(user.streamer_database_name)
    now = datetime.now(timezone.utc)

    def callback(session):
        # Revalidate against live allocations, not the initiation-time
        # snapshot (plan section 6.14) -- inventory may have moved since.
        allocations = master_db.streamer_allocations.find(
            {"streamer_id": request.streamer_id}, session=session
        )

        swept = []
        for allocation in allocations:
            packs = allocation.get("current_packs", 0)

            if packs <= 0:
                # Zero balances need no action; negative (ledger-shortage)
                # balances are left exactly as-is -- decommissioning must
                # not silently erase an open discrepancy (plan section 4.8).
                continue

            product_id = allocation["product_id"]
            swept.append({"product_id": product_id, "current_packs": packs})

            master_db.streamer_allocations.update_one(
                {"streamer_id": request.streamer_id, "product_id": product_id},
                {"$set": {"current_packs": 0, "updated_at": now}, "$inc": {"version": 1}},
                session=session,
            )
            master_db.inventory_current.update_one(
                {"_id": product_id},
                {"$inc": {"unassigned_packs": packs, "version": 1}, "$set": {"updated_at": now}},
                session=session,
            )
            streamer_db.inventory_current.update_one(
                {"_id": product_id},
                {"$set": {"current_packs": 0, "updated_at": now}},
                session=session,
            )

        master_db.decommission_requests.update_one(
            {"request_id": request_id},
            {"$set": {"status": STATUS_APPROVED, "approved_by": approved_by, "approved_at": now}},
            session=session,
        )

        master_db.users.update_one(
            {"_id": request.streamer_id},
            {"$set": {
                "is_active": False,
                "disabled_at": now,
                "updated_at": now,
                "decommission_status": STATUS_APPROVED,
            }},
            session=session,
        )

        audit_service.record_event(
            action_type="DECOMMISSION_APPROVED",
            performed_by=approved_by,
            streamer_id=request.streamer_id,
            after_values={"request_id": request_id, "swept": swept},
            session=session,
        )

    with client.start_session() as session:
        session.with_transaction(callback)

    logger.info("Decommission approved for streamer '%s' by '%s'", request.streamer_id, approved_by)
    return repo.find_decommission_request(request_id)


def cancel(request_id: str, canceled_by: str, notes: str | None = None) -> DecommissionRequest:
    request = repo.find_decommission_request(request_id)

    if request is None:
        raise DecommissionValidationError(f"No such decommission request: {request_id}")

    if request.status != STATUS_PENDING:
        raise DecommissionValidationError(f"Decommission request is not pending (status: {request.status}).")

    now = datetime.now(timezone.utc)
    fields = {"status": STATUS_CANCELED, "canceled_by": canceled_by, "canceled_at": now}

    if notes:
        fields["notes"] = notes

    repo.update_decommission_request_fields(request_id, fields)
    repo.update_user_fields(request.streamer_id, {"decommission_status": None})

    audit_service.record_event(
        action_type="DECOMMISSION_CANCELED",
        performed_by=canceled_by,
        streamer_id=request.streamer_id,
        after_values={"request_id": request_id},
    )

    logger.info("Decommission canceled for streamer '%s' by '%s'", request.streamer_id, canceled_by)
    return repo.find_decommission_request(request_id)


def list_pending() -> list[DecommissionRequest]:
    return repo.list_decommission_requests(status=STATUS_PENDING)


def list_all() -> list[DecommissionRequest]:
    return repo.list_decommission_requests()
