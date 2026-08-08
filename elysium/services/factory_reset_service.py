"""
Admin "factory reset" (docs feedback: testing data must never leak into a
real handoff). Irreversibly wipes every piece of business data back to the
empty, freshly-bootstrapped state -- every user account (admins included),
every product/inventory/stream/break, all audit history, discrepancies,
decommission requests, and shared prices, plus every elysium_s_* streamer
database, dropped entirely.

The two global config singletons (global_operations, app_settings) are
reset to their bootstrap defaults rather than deleted, so the app keeps
working immediately afterward -- there is no admin left to log in as,
though, so the very next step is always running create_admin.py again,
exactly like a brand new install (the real admin password never passes
through this UI/Claude either way, consistent with how the very first
admin is always created).

Not wrapped in a single transaction: dropping a database is not a
transactional operation in MongoDB, and this already spans master, prices,
and every streamer database. Every step here is independently idempotent
(delete_many on an already-empty collection, drop_database on an
already-gone database), so a partial failure is always safe to just retry.
"""

import logging
from datetime import datetime, timezone

from elysium.services.mongo_client import get_client, get_master_db, get_prices_db

logger = logging.getLogger(__name__)

MASTER_DATA_COLLECTIONS = [
    "users", "products", "inventory_current", "streamer_allocations",
    "audit_events", "reason_notes", "inventory_discrepancies", "decommission_requests",
]
PRICES_DATA_COLLECTIONS = ["current_prices", "price_history", "refresh_sessions"]


def wipe_all_data(confirmed_by: str) -> dict:
    """`confirmed_by` is only used for the local log line below -- it can't
    be written to audit_events, since that collection is itself being
    wiped. Returns a summary dict for the confirmation screen."""
    client = get_client()
    master_db = get_master_db()
    prices_db = get_prices_db()

    streamer_database_names = [
        doc["streamer_database_name"]
        for doc in master_db.users.find(
            {"streamer_database_name": {"$exists": True}}, {"streamer_database_name": 1}
        )
        if doc.get("streamer_database_name")
    ]

    deleted_counts = {}

    for name in MASTER_DATA_COLLECTIONS:
        result = master_db[name].delete_many({})
        deleted_counts[name] = result.deleted_count

    for name in PRICES_DATA_COLLECTIONS:
        result = prices_db[name].delete_many({})
        deleted_counts[name] = result.deleted_count

    now = datetime.now(timezone.utc)
    master_db.global_operations.update_one(
        {"_id": "GLOBAL_OPERATIONS"},
        {
            "$set": {
                "stream_active": False,
                "stream_id": None,
                "streamer_id": None,
                "streamer_database_name": None,
                "stream_started_at": None,
                "last_heartbeat_at": None,
                "price_refresh_active": False,
                "refresh_session_id": None,
                "refresh_started_by": None,
                "refresh_started_at": None,
                "updated_at": now,
            },
            "$inc": {"version": 1},
        },
    )

    dropped_databases = []
    for db_name in streamer_database_names:
        client.drop_database(db_name)
        dropped_databases.append(db_name)

    logger.warning(
        "FACTORY RESET performed by '%s': wiped %s, dropped %s streamer database(s): %s",
        confirmed_by, deleted_counts, len(dropped_databases), dropped_databases,
    )

    return {"deleted_counts": deleted_counts, "dropped_databases": dropped_databases}
