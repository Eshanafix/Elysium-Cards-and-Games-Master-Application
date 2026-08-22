"""
Collection validators + indexes for elysium_master and elysium_prices, per
docs/IMPLEMENTATION_PLAN.md sections 2 and 3. Shared between
bootstrap/init_database.py and (later) provision_streamer_db.py, which
needs the equivalent per-streamer-database definitions.

Each entry: (collection_name, validator_or_None, list_of_index_specs).
An index spec is a dict: {"keys": [...], **create_index kwargs}.
"""

MASTER_COLLECTIONS = [
    (
        "users",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "username", "password_hash", "roles", "is_active"],
                "properties": {
                    "roles": {"bsonType": "array", "items": {"enum": ["admin", "streamer"]}},
                    "is_active": {"bsonType": "bool"},
                },
            }
        },
        [
            {"keys": [("username", 1)], "unique": True, "name": "uniq_username"},
            {"keys": [("streamer_database_key", 1)], "unique": True, "sparse": True, "name": "uniq_streamer_db_key"},
            {"keys": [("streamer_database_name", 1)], "unique": True, "sparse": True, "name": "uniq_streamer_db_name"},
        ],
    ),
    (
        "products",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": [
                    "_id", "name", "name_normalized", "booster_type", "language", "english_confirmed",
                    "packs_per_box", "tcgcsv_category_id", "tcgcsv_group_id",
                    "loose_pack_tcgcsv_product_id", "box_tcgcsv_product_id",
                    "image_url", "is_active",
                ],
                "properties": {
                    "booster_type": {"enum": ["DRAFT", "SET", "COLLECTOR", "PLAY", "CLASSIC", "JUMPSTART"]},
                    "packs_per_box": {"bsonType": "int", "minimum": 1},
                    "english_confirmed": {"bsonType": "bool"},
                    "is_active": {"bsonType": "bool"},
                },
            }
        },
        [
            {"keys": [("loose_pack_tcgcsv_product_id", 1)], "unique": True, "name": "uniq_loose_tcgcsv_id"},
            {"keys": [("box_tcgcsv_product_id", 1)], "unique": True, "name": "uniq_box_tcgcsv_id"},
            {"keys": [("name_normalized", 1), ("booster_type", 1)], "unique": True, "name": "uniq_name_normalized_booster_type"},
            {"keys": [("is_active", 1)], "name": "idx_is_active"},
            {"keys": [("tcgcsv_category_id", 1), ("tcgcsv_group_id", 1)], "name": "idx_tcgcsv_group"},
        ],
    ),
    (
        "inventory_current",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "product_id", "total_packs", "unassigned_packs", "version", "updated_at"],
                "properties": {
                    "total_packs": {"bsonType": "int", "minimum": 0},
                    "unassigned_packs": {"bsonType": "int", "minimum": 0},
                    "version": {"bsonType": "int", "minimum": 0},
                },
            }
        },
        [],
    ),
    (
        "streamer_allocations",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["streamer_id", "product_id", "current_packs", "version", "updated_at"],
                "properties": {
                    "current_packs": {"bsonType": "int"},
                    "version": {"bsonType": "int", "minimum": 0},
                },
            }
        },
        [
            {"keys": [("streamer_id", 1), ("product_id", 1)], "unique": True, "name": "uniq_streamer_product"},
        ],
    ),
    (
        "global_operations",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "stream_active", "price_refresh_active", "version", "updated_at"],
                "properties": {
                    "_id": {"enum": ["GLOBAL_OPERATIONS"]},
                    "stream_active": {"bsonType": "bool"},
                    "price_refresh_active": {"bsonType": "bool"},
                },
            }
        },
        [],
    ),
    (
        "audit_events",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["event_id", "action_type", "performed_by", "timestamp", "status"],
                "properties": {
                    "status": {"enum": ["SUCCESS", "FAILURE", "REVERSED", "CORRECTED"]},
                },
            }
        },
        [
            {"keys": [("timestamp", -1)], "name": "idx_timestamp"},
            {"keys": [("action_type", 1), ("timestamp", 1)], "name": "idx_action_type_timestamp"},
            {"keys": [("streamer_id", 1), ("timestamp", 1)], "name": "idx_streamer_timestamp"},
            {"keys": [("product_id", 1), ("timestamp", 1)], "name": "idx_product_timestamp"},
            {"keys": [("stream_id", 1)], "name": "idx_stream_id"},
        ],
    ),
    (
        "reason_notes",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "action_type", "current_text", "history", "created_at", "created_by"],
                "properties": {
                    "current_text": {"bsonType": "string", "minLength": 1},
                    "history": {"bsonType": "array", "minItems": 1},
                },
            }
        },
        [
            {"keys": [("streamer_id", 1)], "name": "idx_streamer_id"},
            {"keys": [("action_type", 1)], "name": "idx_action_type"},
        ],
    ),
    (
        "inventory_discrepancies",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["discrepancy_id", "streamer_id", "product_id", "type", "quantity", "status"],
                "properties": {
                    "type": {"enum": ["NEGATIVE_INVENTORY", "UNDEDUCTED_SHORTAGE"]},
                    "status": {"enum": ["OPEN", "RESOLVED"]},
                },
            }
        },
        [
            {"keys": [("status", 1)], "name": "idx_status"},
        ],
    ),
    (
        "decommission_requests",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["request_id", "streamer_id", "status", "initiated_by", "initiated_at"],
                "properties": {
                    "status": {"enum": ["PENDING", "APPROVED", "CANCELED"]},
                },
            }
        },
        [
            {"keys": [("status", 1)], "name": "idx_status"},
        ],
    ),
    (
        "app_settings",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "schema_version"],
                "properties": {
                    "_id": {"enum": ["GLOBAL"]},
                },
            }
        },
        [],
    ),
]

PRICES_COLLECTIONS = [
    (
        "current_prices",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "product_id", "price_status", "version"],
                "properties": {
                    "resolved_pack_price": {"bsonType": ["decimal", "null"]},
                    "resolved_price_source": {
                        "enum": ["LOOSE_PACK_MARKET", "DERIVED_FROM_BOX_MARKET", "MANUAL", "PREVIOUS_VALUE", None]
                    },
                    "price_status": {"enum": ["OK", "STALE", "MANUAL", "UNRESOLVED", "AMBIGUOUS"]},
                },
            }
        },
        [],
    ),
    (
        "price_history",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["product_id", "new_price", "timestamp", "refresh_session_id"],
            }
        },
        [
            {"keys": [("product_id", 1), ("timestamp", -1)], "name": "idx_product_timestamp"},
        ],
    ),
    (
        "refresh_sessions",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "started_by", "started_at", "status"],
                "properties": {
                    "status": {"enum": ["RUNNING", "COMPLETED", "FAILED", "ABORTED"]},
                },
            }
        },
        [
            {"keys": [("started_at", -1)], "name": "idx_started_at"},
        ],
    ),
    (
        # Cache of every TCGCSV group (set) for a category, refreshed on
        # demand, so the product-creation UI can offer a set-name
        # autocomplete instead of requiring an admin to know raw TCGCSV
        # category/group ids (docs/IMPLEMENTATION_PLAN.md Phase 3 UX
        # revision). Not a per-product cache -- individual products within
        # a chosen group are still fetched live, since caching every
        # product (singles included) across ~450+ groups is unnecessary.
        "tcgcsv_groups",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "group_id", "category_id", "name"],
            }
        },
        [
            {"keys": [("name", 1)], "name": "idx_name"},
            {"keys": [("category_id", 1)], "name": "idx_category_id"},
        ],
    ),
]

# elysium_s_<key> — identical schema per streamer, used by provision_streamer_db.py.
STREAMER_COLLECTIONS = [
    (
        "inventory_current",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "product_id", "current_packs", "updated_at"],
                "properties": {"current_packs": {"bsonType": "int"}},
            }
        },
        [],
    ),
    (
        "streams",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "streamer_id", "status", "start_time"],
                "properties": {"status": {"enum": ["ACTIVE", "COMPLETED", "CANCELED"]}},
            }
        },
        [
            {"keys": [("status", 1), ("start_time", -1)], "name": "idx_status_start_time"},
        ],
    ),
    (
        "breaks",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "stream_id", "sequence_number", "status", "pack_lines"],
                "properties": {
                    "status": {"enum": ["ACTIVE", "ENDED_EDITABLE", "DELETED"]},
                    "sequence_number": {"bsonType": "int", "minimum": 1},
                },
            }
        },
        [
            {"keys": [("stream_id", 1), ("sequence_number", 1)], "unique": True, "name": "uniq_stream_sequence"},
            {"keys": [("stream_id", 1), ("status", 1)], "name": "idx_stream_status"},
        ],
    ),
    (
        "streamer_history",
        {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["event_type", "timestamp"],
            }
        },
        [
            {"keys": [("timestamp", -1)], "name": "idx_timestamp"},
        ],
    ),
]


def ensure_collection(db, name: str, validator: dict | None) -> str:
    """Creates the collection with the given validator if missing; updates
    the validator in place (collMod) if it already exists. Returns
    "created" or "updated" for the caller's summary output."""
    if name not in db.list_collection_names():
        db.create_collection(name, validator=validator, validationLevel="strict", validationAction="error")
        return "created"

    db.command("collMod", name, validator=validator or {}, validationLevel="strict", validationAction="error")
    return "updated"


def ensure_indexes(db, name: str, index_specs: list[dict]) -> int:
    collection = db[name]
    count = 0

    for spec in index_specs:
        spec = dict(spec)
        keys = spec.pop("keys")
        collection.create_index(keys, **spec)
        count += 1

    return count
