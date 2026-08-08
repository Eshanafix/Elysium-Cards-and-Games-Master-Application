"""
Repository functions for elysium_master collections.
"""

from elysium.models.decommission import DecommissionRequest
from elysium.models.discrepancies import Discrepancy
from elysium.models.products import Product, normalize_product_name
from elysium.models.reason_notes import ReasonNote
from elysium.models.users import User
from elysium.services.mongo_client import get_master_db


def find_user_by_username(username: str) -> User | None:
    doc = get_master_db().users.find_one({"username": username})
    return User.from_document(doc) if doc else None


def find_user_by_id(user_id: str) -> User | None:
    doc = get_master_db().users.find_one({"_id": user_id})
    return User.from_document(doc) if doc else None


def username_exists(username: str) -> bool:
    return get_master_db().users.count_documents({"username": username}, limit=1) > 0


def get_master_db_users_streamer_key_exists(streamer_database_key: str) -> bool:
    return get_master_db().users.count_documents(
        {"streamer_database_key": streamer_database_key}, limit=1
    ) > 0


def any_admin_exists() -> bool:
    return get_master_db().users.count_documents({"roles": "admin"}, limit=1) > 0


def insert_user(user: User) -> None:
    get_master_db().users.insert_one(user.to_document())


def update_user_fields(user_id: str, fields: dict) -> None:
    get_master_db().users.update_one({"_id": user_id}, {"$set": fields})


def list_users() -> list[User]:
    return [User.from_document(doc) for doc in get_master_db().users.find().sort("username", 1)]


def streamer_has_nonzero_allocation(streamer_id: str) -> bool:
    """
    True if this streamer currently holds (or owes, if negative) any packs
    of any product. Used to decide whether Disable Account may proceed
    directly or must route through Decommissioning (plan section 4.8).
    """
    return get_master_db().streamer_allocations.count_documents(
        {"streamer_id": streamer_id, "current_packs": {"$ne": 0}},
        limit=1,
    ) > 0


# --- Products (Phase 3) ---


def find_product_by_id(product_id: str) -> Product | None:
    doc = get_master_db().products.find_one({"_id": product_id})
    return Product.from_document(doc) if doc else None


def product_id_exists(product_id: str) -> bool:
    return get_master_db().products.count_documents({"_id": product_id}, limit=1) > 0


def loose_tcgcsv_id_exists(loose_pack_tcgcsv_product_id: str) -> bool:
    return get_master_db().products.count_documents(
        {"loose_pack_tcgcsv_product_id": loose_pack_tcgcsv_product_id}, limit=1
    ) > 0


def box_tcgcsv_id_exists(box_tcgcsv_product_id: str) -> bool:
    return get_master_db().products.count_documents(
        {"box_tcgcsv_product_id": box_tcgcsv_product_id}, limit=1
    ) > 0


def normalized_name_and_type_exists(name: str, booster_type: str) -> bool:
    return get_master_db().products.count_documents(
        {"name_normalized": normalize_product_name(name), "booster_type": booster_type}, limit=1
    ) > 0


def insert_product_with_zero_inventory(product: Product) -> None:
    """
    Single transaction: creates the product document and its 1:1
    inventory_current record (total_packs=0, unassigned_packs=0) together,
    so inventory_current is guaranteed to exist for every product from
    creation onward -- Phase 4's master inventory logic never has to treat
    "product exists but inventory_current is missing" as a case to handle.
    """
    client = get_master_db().client
    db = get_master_db()

    with client.start_session() as session:
        def callback(session):
            db.products.insert_one(product.to_document(), session=session)
            db.inventory_current.insert_one(
                {
                    "_id": product.id,
                    "product_id": product.id,
                    "total_packs": 0,
                    "unassigned_packs": 0,
                    "version": 0,
                    "updated_at": product.created_at,
                },
                session=session,
            )

        session.with_transaction(callback)


def update_product_fields(product_id: str, fields: dict) -> None:
    get_master_db().products.update_one({"_id": product_id}, {"$set": fields})


def list_products() -> list[Product]:
    """Positive-stock products first, zero-stock sorted to the bottom (LLD
    8.5), via a $lookup against inventory_current rather than an extra
    round trip per product."""
    pipeline = [
        {
            "$lookup": {
                "from": "inventory_current",
                "localField": "_id",
                "foreignField": "product_id",
                "as": "inventory",
            }
        },
        {
            "$addFields": {
                "_total_packs": {"$ifNull": [{"$first": "$inventory.total_packs"}, 0]},
            }
        },
        {"$sort": {"_total_packs": -1, "name": 1}},
    ]

    docs = get_master_db().products.aggregate(pipeline)
    return [Product.from_document(doc) for doc in docs]


# --- Master inventory (Phase 4) ---


def get_inventory_current(product_id: str) -> dict | None:
    return get_master_db().inventory_current.find_one({"_id": product_id})


def list_inventory_current() -> dict[str, dict]:
    return {doc["_id"]: doc for doc in get_master_db().inventory_current.find()}


def get_streamer_allocation(streamer_id: str, product_id: str) -> dict | None:
    return get_master_db().streamer_allocations.find_one({"streamer_id": streamer_id, "product_id": product_id})


def list_streamer_allocations_for_product(product_id: str) -> list[dict]:
    return list(get_master_db().streamer_allocations.find({"product_id": product_id}))


def list_all_streamer_allocations() -> list[dict]:
    return list(get_master_db().streamer_allocations.find())


def list_streamer_allocations_for_streamer(streamer_id: str) -> list[dict]:
    return list(get_master_db().streamer_allocations.find({"streamer_id": streamer_id}))


# --- Inventory discrepancies (Phase 6) ---


def find_open_discrepancy(streamer_id: str, product_id: str, discrepancy_type: str) -> dict | None:
    """Used by discrepancy_service's create-or-increment pattern so a
    streamer/product/type combination never accumulates more than one open
    discrepancy record."""
    return get_master_db().inventory_discrepancies.find_one({
        "streamer_id": streamer_id,
        "product_id": product_id,
        "type": discrepancy_type,
        "status": "OPEN",
    })


def insert_discrepancy(discrepancy: Discrepancy, session=None) -> None:
    get_master_db().inventory_discrepancies.insert_one(discrepancy.to_document(), session=session)


def increment_discrepancy_quantity(discrepancy_id: str, quantity_delta: int, session=None) -> None:
    get_master_db().inventory_discrepancies.update_one(
        {"discrepancy_id": discrepancy_id},
        {"$inc": {"quantity": quantity_delta}},
        session=session,
    )


def update_discrepancy_fields(discrepancy_id: str, fields: dict) -> None:
    get_master_db().inventory_discrepancies.update_one({"discrepancy_id": discrepancy_id}, {"$set": fields})


def list_discrepancies(status: str | None = None) -> list[Discrepancy]:
    query = {"status": status} if status else {}
    docs = get_master_db().inventory_discrepancies.find(query).sort("created_at", -1)
    return [Discrepancy.from_document(doc) for doc in docs]


def list_discrepancies_for_streamer(streamer_id: str, status: str | None = None) -> list[Discrepancy]:
    query = {"streamer_id": streamer_id}
    if status:
        query["status"] = status
    docs = get_master_db().inventory_discrepancies.find(query).sort("created_at", -1)
    return [Discrepancy.from_document(doc) for doc in docs]


def find_discrepancy(discrepancy_id: str) -> Discrepancy | None:
    doc = get_master_db().inventory_discrepancies.find_one({"discrepancy_id": discrepancy_id})
    return Discrepancy.from_document(doc) if doc else None


# --- Decommission requests (Phase 6) ---


def insert_decommission_request(request: DecommissionRequest) -> None:
    get_master_db().decommission_requests.insert_one(request.to_document())


def find_decommission_request(request_id: str) -> DecommissionRequest | None:
    doc = get_master_db().decommission_requests.find_one({"request_id": request_id})
    return DecommissionRequest.from_document(doc) if doc else None


def find_pending_decommission_request_for_streamer(streamer_id: str) -> DecommissionRequest | None:
    doc = get_master_db().decommission_requests.find_one({"streamer_id": streamer_id, "status": "PENDING"})
    return DecommissionRequest.from_document(doc) if doc else None


def update_decommission_request_fields(request_id: str, fields: dict, session=None) -> None:
    get_master_db().decommission_requests.update_one(
        {"request_id": request_id}, {"$set": fields}, session=session
    )


def list_decommission_requests(status: str | None = None) -> list[DecommissionRequest]:
    query = {"status": status} if status else {}
    docs = get_master_db().decommission_requests.find(query).sort("initiated_at", -1)
    return [DecommissionRequest.from_document(doc) for doc in docs]


# --- Reason notes (Phase 7) ---


def insert_reason_note(reason_note: ReasonNote, session=None) -> None:
    get_master_db().reason_notes.insert_one(reason_note.to_document(), session=session)


def find_reason_note(reason_note_id: str) -> ReasonNote | None:
    doc = get_master_db().reason_notes.find_one({"_id": reason_note_id})
    return ReasonNote.from_document(doc) if doc else None


def update_reason_note_text(reason_note_id: str, new_text: str, edited_by: str, edited_at) -> None:
    get_master_db().reason_notes.update_one(
        {"_id": reason_note_id},
        {
            "$set": {"current_text": new_text, "updated_at": edited_at},
            "$push": {"history": {"text": new_text, "edited_by": edited_by, "edited_at": edited_at}},
        },
    )


# --- App update gate (mandatory update on login) ---

APP_UPDATE_CONFIG_ID = "APP_UPDATE"


def get_app_update_config() -> dict | None:
    return get_master_db().app_config.find_one({"_id": APP_UPDATE_CONFIG_ID})


def set_app_update_config(fields: dict) -> None:
    get_master_db().app_config.update_one(
        {"_id": APP_UPDATE_CONFIG_ID}, {"$set": fields}, upsert=True
    )


def list_audit_events(
    action_type: str | None = None,
    streamer_id: str | None = None,
    product_id: str | None = None,
    start_date=None,
    end_date=None,
    limit: int = 1000,
) -> list[dict]:
    """Backs the admin Audit History browser (LLD 6.16) and the
    inventory_audit report dataset (LLD 20.5) -- admin-only per LLD 19.2."""
    query: dict = {}

    if action_type:
        query["action_type"] = action_type
    if streamer_id:
        query["streamer_id"] = streamer_id
    if product_id:
        query["product_id"] = product_id
    if start_date or end_date:
        timestamp_query = {}
        if start_date:
            timestamp_query["$gte"] = start_date
        if end_date:
            timestamp_query["$lte"] = end_date
        query["timestamp"] = timestamp_query

    docs = get_master_db().audit_events.find(query).sort("timestamp", -1).limit(limit)
    return list(docs)
