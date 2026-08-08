"""
Repository functions for a streamer's own database (elysium_s_<key>),
parametrized by streamer_database_name (docs/IMPLEMENTATION_PLAN.md
section 2.3).
"""

from elysium.models.breaks import STATUS_ACTIVE as BREAK_STATUS_ACTIVE
from elysium.models.breaks import STATUS_DELETED as BREAK_STATUS_DELETED
from elysium.models.breaks import Break
from elysium.models.prices import convert_decimals_to_decimal128
from elysium.models.streams import STATUS_ACTIVE as STREAM_STATUS_ACTIVE
from elysium.models.streams import Stream
from elysium.services.mongo_client import get_streamer_db


def get_inventory_current(streamer_database_name: str, product_id: str) -> dict | None:
    return get_streamer_db(streamer_database_name).inventory_current.find_one({"_id": product_id})


def list_inventory_current(streamer_database_name: str) -> dict[str, dict]:
    docs = get_streamer_db(streamer_database_name).inventory_current.find()
    return {doc["_id"]: doc for doc in docs}


# --- Streams (Phase 5) ---


def find_stream_by_id(streamer_database_name: str, stream_id: str, session=None) -> Stream | None:
    doc = get_streamer_db(streamer_database_name).streams.find_one({"_id": stream_id}, session=session)
    return Stream.from_document(doc) if doc else None


def find_active_stream(streamer_database_name: str, session=None) -> Stream | None:
    doc = get_streamer_db(streamer_database_name).streams.find_one(
        {"status": STREAM_STATUS_ACTIVE}, session=session
    )
    return Stream.from_document(doc) if doc else None


def insert_stream(streamer_database_name: str, stream: Stream, session=None) -> None:
    get_streamer_db(streamer_database_name).streams.insert_one(stream.to_document(), session=session)


def update_stream_fields(streamer_database_name: str, stream_id: str, fields: dict, session=None) -> None:
    get_streamer_db(streamer_database_name).streams.update_one(
        {"_id": stream_id}, {"$set": convert_decimals_to_decimal128(fields)}, session=session
    )


def list_streams(streamer_database_name: str, status: str | None = None, session=None) -> list[Stream]:
    """Company-wide stream browsing for the admin Correct Stream flow
    (plan section 6.13) -- one streamer database at a time, newest first."""
    query = {"status": status} if status else {}
    docs = (
        get_streamer_db(streamer_database_name).streams.find(query, session=session)
        .sort("start_time", -1)
    )
    return [Stream.from_document(doc) for doc in docs]


# --- Breaks (Phase 5) ---


def find_break_by_id(streamer_database_name: str, break_id: str, session=None) -> Break | None:
    doc = get_streamer_db(streamer_database_name).breaks.find_one({"_id": break_id}, session=session)
    return Break.from_document(doc) if doc else None


def find_active_break(streamer_database_name: str, stream_id: str, session=None) -> Break | None:
    doc = get_streamer_db(streamer_database_name).breaks.find_one(
        {"stream_id": stream_id, "status": BREAK_STATUS_ACTIVE}, session=session
    )
    return Break.from_document(doc) if doc else None


def list_breaks_for_stream(
    streamer_database_name: str, stream_id: str, include_deleted: bool = False, session=None
) -> list[Break]:
    query = {"stream_id": stream_id}

    if not include_deleted:
        query["status"] = {"$ne": BREAK_STATUS_DELETED}

    docs = get_streamer_db(streamer_database_name).breaks.find(query, session=session).sort("sequence_number", 1)
    return [Break.from_document(doc) for doc in docs]


def next_break_sequence_number(streamer_database_name: str, stream_id: str, session=None) -> int:
    last = list(
        get_streamer_db(streamer_database_name).breaks
        .find({"stream_id": stream_id}, session=session)
        .sort("sequence_number", -1)
        .limit(1)
    )
    return (last[0]["sequence_number"] + 1) if last else 1


def insert_break(streamer_database_name: str, break_obj: Break, session=None) -> None:
    get_streamer_db(streamer_database_name).breaks.insert_one(break_obj.to_document(), session=session)


def update_break_fields(streamer_database_name: str, break_id: str, fields: dict, session=None) -> None:
    get_streamer_db(streamer_database_name).breaks.update_one(
        {"_id": break_id}, {"$set": convert_decimals_to_decimal128(fields)}, session=session
    )
