"""
Repository functions for elysium_prices collections (docs/IMPLEMENTATION_
PLAN.md section 2.2).
"""

import re
from datetime import datetime, timezone

from pymongo import ReplaceOne

from elysium.models.prices import CurrentPrice, to_decimal128
from elysium.services.mongo_client import get_prices_db


def find_current_price(product_id: str) -> CurrentPrice | None:
    doc = get_prices_db().current_prices.find_one({"_id": product_id})
    return CurrentPrice.from_document(doc) if doc else None


def find_current_prices(product_ids: list[str]) -> dict[str, CurrentPrice]:
    docs = get_prices_db().current_prices.find({"_id": {"$in": product_ids}})
    return {doc["_id"]: CurrentPrice.from_document(doc) for doc in docs}


def list_all_current_prices() -> dict[str, CurrentPrice]:
    docs = get_prices_db().current_prices.find()
    return {doc["_id"]: CurrentPrice.from_document(doc) for doc in docs}


def upsert_current_price(price: CurrentPrice) -> None:
    get_prices_db().current_prices.replace_one({"_id": price.product_id}, price.to_document(), upsert=True)


def insert_price_history(
    product_id: str,
    previous_price,
    new_price,
    previous_source: str | None,
    new_source: str | None,
    initiated_by: str,
    refresh_session_id: str,
    tcgcsv_status: str,
    manual_entry_by: str | None = None,
) -> None:
    get_prices_db().price_history.insert_one({
        "product_id": product_id,
        "previous_price": to_decimal128(previous_price),
        "new_price": to_decimal128(new_price),
        "previous_source": previous_source,
        "new_source": new_source,
        "initiated_by": initiated_by,
        "manual_entry_by": manual_entry_by,
        "timestamp": datetime.now(timezone.utc),
        "refresh_session_id": refresh_session_id,
        "tcgcsv_status": tcgcsv_status,
    })


def create_refresh_session(session_id: str, started_by: str) -> None:
    get_prices_db().refresh_sessions.insert_one({
        "_id": session_id,
        "started_by": started_by,
        "started_at": datetime.now(timezone.utc),
        "completed_at": None,
        "status": "RUNNING",
        "unique_groups_requested": 0,
        "products_checked": 0,
        "prices_updated": 0,
        "prices_unchanged": 0,
        "loose_pack_prices_used": 0,
        "box_derived_prices_used": 0,
        "previous_retained": 0,
        "manual_entered": 0,
        "ambiguous_products": 0,
        "failed_products": [],
        "failed_groups": [],
        "error_summary": None,
    })


def update_refresh_session(session_id: str, fields: dict) -> None:
    get_prices_db().refresh_sessions.update_one({"_id": session_id}, {"$set": fields})


def increment_refresh_session_counters(session_id: str, **counters: int) -> None:
    get_prices_db().refresh_sessions.update_one({"_id": session_id}, {"$inc": counters})


def push_refresh_session_failure(session_id: str, field: str, entry: dict) -> None:
    get_prices_db().refresh_sessions.update_one({"_id": session_id}, {"$push": {field: entry}})


def find_refresh_session(session_id: str) -> dict | None:
    return get_prices_db().refresh_sessions.find_one({"_id": session_id})


def list_price_history(product_id: str | None = None, limit: int = 5000) -> list[dict]:
    """Backs the price_history report dataset (LLD 20.5)."""
    query = {"product_id": product_id} if product_id else {}
    docs = get_prices_db().price_history.find(query).sort("timestamp", -1).limit(limit)
    return list(docs)


# --- TCGCSV group (set) cache, for product-creation search (Phase 3 UX revision) ---


def upsert_tcgcsv_groups(groups: list[dict]) -> None:
    if not groups:
        return

    # One batched bulk_write instead of one round trip per group -- with
    # ~450 Magic groups, a per-document replace_one loop measured over 40s
    # against Atlas; bulk_write sends it as a single request.
    operations = [ReplaceOne({"_id": group["_id"]}, group, upsert=True) for group in groups]
    get_prices_db().tcgcsv_groups.bulk_write(operations, ordered=False)


def search_tcgcsv_groups(query: str, category_id: str, limit: int = 20) -> list[dict]:
    regex = {"$regex": re.escape(query), "$options": "i"}
    return list(
        get_prices_db().tcgcsv_groups
        .find({"category_id": category_id, "name": regex})
        .sort("name", 1)
        .limit(limit)
    )


def tcgcsv_groups_count(category_id: str) -> int:
    return get_prices_db().tcgcsv_groups.count_documents({"category_id": category_id})
