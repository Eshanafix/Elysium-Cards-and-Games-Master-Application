"""
Global operations lock (docs/IMPLEMENTATION_PLAN.md section 4.2). Both
halves live on the single global_operations document, so acquiring either
lock atomically checks BOTH stream_active and price_refresh_active --
a price refresh can never start while a stream is active, and vice versa,
with no window for the two-lock race the plan corrected.
"""

import uuid
from datetime import datetime, timezone

from elysium.services import audit_service
from elysium.services.mongo_client import get_master_db

GLOBAL_OPERATIONS_ID = "GLOBAL_OPERATIONS"


class LockConflictError(Exception):
    pass


def get_lock_state() -> dict:
    doc = get_master_db().global_operations.find_one({"_id": GLOBAL_OPERATIONS_ID})

    if doc is None:
        raise RuntimeError("global_operations document is missing -- run bootstrap/init_database.py")

    return doc


def acquire_price_refresh_lock(started_by: str) -> str:
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    result = get_master_db().global_operations.find_one_and_update(
        {"_id": GLOBAL_OPERATIONS_ID, "stream_active": False, "price_refresh_active": False},
        {
            "$set": {
                "price_refresh_active": True,
                "refresh_session_id": session_id,
                "refresh_started_by": started_by,
                "refresh_started_at": now,
                "updated_at": now,
            },
            "$inc": {"version": 1},
        },
    )

    if result is None:
        state = get_lock_state()

        if state.get("stream_active"):
            raise LockConflictError(
                "Shared sealed prices cannot be refreshed while a stream is active "
                f"(streamer: {state.get('streamer_id')})."
            )

        raise LockConflictError("A price refresh is already in progress.")

    return session_id


def release_price_refresh_lock() -> None:
    get_master_db().global_operations.update_one(
        {"_id": GLOBAL_OPERATIONS_ID},
        {
            "$set": {
                "price_refresh_active": False,
                "refresh_session_id": None,
                "refresh_started_by": None,
                "refresh_started_at": None,
                "updated_at": datetime.now(timezone.utc),
            },
            "$inc": {"version": 1},
        },
    )


def recover_stuck_price_refresh_lock(admin_id: str, reason: str) -> None:
    """Admin-only recovery for a stranded price-refresh lock (plan section
    4.4) -- clears only the refresh sub-state, never touches stream_active."""
    release_price_refresh_lock()

    audit_service.record_event(
        action_type="PRICE_REFRESH_LOCK_RECOVERED",
        performed_by=admin_id,
        reason=reason,
    )


def acquire_stream_lock(streamer_id: str, stream_id: str, streamer_database_name: str, session=None) -> None:
    """
    Called from inside stream_service.start_stream's transaction (session
    required there) so a stream document can never exist without the lock
    that protects it, or vice versa -- if the transaction aborts for any
    reason after this call, the lock acquisition rolls back with it
    instead of leaving an orphaned lock needing manual admin recovery.
    """
    now = datetime.now(timezone.utc)

    result = get_master_db().global_operations.find_one_and_update(
        {"_id": GLOBAL_OPERATIONS_ID, "stream_active": False, "price_refresh_active": False},
        {
            "$set": {
                "stream_active": True,
                "stream_id": stream_id,
                "streamer_id": streamer_id,
                "streamer_database_name": streamer_database_name,
                "stream_started_at": now,
                "last_heartbeat_at": now,
                "updated_at": now,
            },
            "$inc": {"version": 1},
        },
        session=session,
    )

    if result is None:
        state = get_lock_state()

        if state.get("price_refresh_active"):
            raise LockConflictError("Cannot start a stream while a shared price refresh is in progress.")

        raise LockConflictError(
            "A stream is already active.\n"
            f"Streamer: {state.get('streamer_id')}\n"
            f"Started: {state.get('stream_started_at')}"
        )


def release_stream_lock(session=None) -> None:
    get_master_db().global_operations.update_one(
        {"_id": GLOBAL_OPERATIONS_ID},
        {
            "$set": {
                "stream_active": False,
                "stream_id": None,
                "streamer_id": None,
                "streamer_database_name": None,
                "stream_started_at": None,
                "last_heartbeat_at": None,
                "updated_at": datetime.now(timezone.utc),
            },
            "$inc": {"version": 1},
        },
        session=session,
    )
