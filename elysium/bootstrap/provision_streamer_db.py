"""
Creates a new streamer's MongoDB database (docs/IMPLEMENTATION_PLAN.md
section 9.2). Called by auth_service.create_user at the moment an admin
creates a streamer account — not lazily on first claim — so the roster
stays empty until an admin actually adds someone, per your instruction.
"""

from elysium.bootstrap.schema_definitions import STREAMER_COLLECTIONS, ensure_collection, ensure_indexes
from elysium.services.mongo_client import get_streamer_db

STREAMER_DB_PREFIX = "elysium_s_"


def streamer_database_name(streamer_database_key: str) -> str:
    return f"{STREAMER_DB_PREFIX}{streamer_database_key}"


def provision_streamer_database(streamer_database_key: str) -> str:
    """Idempotent — safe to call again on an already-provisioned database."""
    db_name = streamer_database_name(streamer_database_key)
    db = get_streamer_db(db_name)

    for name, validator, index_specs in STREAMER_COLLECTIONS:
        ensure_collection(db, name, validator)
        ensure_indexes(db, name, index_specs)

    return db_name
