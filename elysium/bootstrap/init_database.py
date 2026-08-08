"""
Idempotent database bootstrap (docs/IMPLEMENTATION_PLAN.md section 9.1).

Creates every elysium_master and elysium_prices collection with its
validator and indexes, and the two singleton documents (global_operations,
app_settings) if they don't already exist. Creates no users, no products,
no streamer databases — the roster starts empty per your instruction and
grows dynamically through the app itself.

Safe to run repeatedly: existing collections get their validator refreshed
in place (collMod), indexes are idempotent, and the singleton docs are only
inserted if missing (never resets an existing lock state).

Usage:
    python -m elysium.bootstrap.init_database
"""

import logging
from datetime import datetime, timezone

from elysium.bootstrap.schema_definitions import (
    MASTER_COLLECTIONS,
    PRICES_COLLECTIONS,
    ensure_collection,
    ensure_indexes,
)
from elysium.logging_setup import configure_logging
from elysium.services.mongo_client import check_connection, get_master_db, get_prices_db

logger = logging.getLogger(__name__)


def _ensure_global_operations(db) -> str:
    existing = db.global_operations.find_one({"_id": "GLOBAL_OPERATIONS"})

    if existing:
        return "already present"

    db.global_operations.insert_one({
        "_id": "GLOBAL_OPERATIONS",
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
        "version": 0,
        "updated_at": datetime.now(timezone.utc),
    })
    return "created"


def _ensure_app_settings(db) -> str:
    existing = db.app_settings.find_one({"_id": "GLOBAL"})

    if existing:
        return "already present"

    db.app_settings.insert_one({
        "_id": "GLOBAL",
        "schema_version": 1,
        "stale_card_data_hours": 24,
        "currency": "USD",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    return "created"


def init_database() -> None:
    status = check_connection()

    if not status.is_connected:
        raise RuntimeError(f"Cannot bootstrap: MongoDB is unreachable ({status.detail})")

    master_db = get_master_db()
    prices_db = get_prices_db()

    print(f"Connected. Bootstrapping '{master_db.name}' and '{prices_db.name}'...\n")

    for db, collections, label in (
        (master_db, MASTER_COLLECTIONS, "elysium_master"),
        (prices_db, PRICES_COLLECTIONS, "elysium_prices"),
    ):
        for name, validator, index_specs in collections:
            collection_result = ensure_collection(db, name, validator)
            index_count = ensure_indexes(db, name, index_specs)
            print(f"  [{label}] {name}: {collection_result}, {index_count} index(es) ensured")

    print()
    print(f"  global_operations singleton: {_ensure_global_operations(master_db)}")
    print(f"  app_settings singleton: {_ensure_app_settings(master_db)}")
    print("\nBootstrap complete. No users, products, or streamer databases were created.")


if __name__ == "__main__":
    configure_logging()
    init_database()
