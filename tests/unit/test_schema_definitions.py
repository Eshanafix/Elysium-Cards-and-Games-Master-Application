from elysium.bootstrap.provision_streamer_db import streamer_database_name
from elysium.bootstrap.schema_definitions import (
    MASTER_COLLECTIONS,
    PRICES_COLLECTIONS,
    STREAMER_COLLECTIONS,
    ensure_indexes,
)


def _names(collection_specs):
    return [name for name, _validator, _indexes in collection_specs]


def test_master_collection_names_are_unique():
    names = _names(MASTER_COLLECTIONS)
    assert len(names) == len(set(names))
    assert "users" in names
    assert "global_operations" in names
    assert "reason_notes" in names


def test_prices_collection_names_are_unique():
    names = _names(PRICES_COLLECTIONS)
    assert len(names) == len(set(names))
    assert "current_prices" in names


def test_streamer_collection_names_are_unique():
    names = _names(STREAMER_COLLECTIONS)
    assert len(names) == len(set(names))
    assert "streams" in names
    assert "breaks" in names


def test_every_index_spec_has_keys():
    for collections in (MASTER_COLLECTIONS, PRICES_COLLECTIONS, STREAMER_COLLECTIONS):
        for name, _validator, index_specs in collections:
            for spec in index_specs:
                assert "keys" in spec, f"{name} has an index spec missing 'keys'"


def test_streamer_database_name_format():
    assert streamer_database_name("abc123") == "elysium_s_abc123"


# --- ensure_indexes: must actually be idempotent across an options change,
# not just across re-adding the same index unchanged (module docstring's
# "safe to re-run" claim) -- MongoDB rejects create_index on an existing
# index name whose options differ (IndexOptionsConflict) rather than
# treating it as a no-op, so this has to detect that and drop+recreate. ---


class FakeCollection:
    """Minimal stand-in for a pymongo Collection -- just enough of
    list_indexes/create_index/drop_index to verify ensure_indexes()'s own
    decision logic, without a real MongoDB connection."""

    def __init__(self, existing_indexes):
        self._indexes = {idx["name"]: dict(idx) for idx in existing_indexes}
        self.dropped: list[str] = []
        self.created: list[tuple] = []

    def list_indexes(self):
        return list(self._indexes.values())

    def drop_index(self, name):
        self.dropped.append(name)
        del self._indexes[name]

    def create_index(self, keys, **kwargs):
        name = kwargs["name"]
        self.created.append((keys, kwargs))
        self._indexes[name] = {"name": name, "key": keys, **kwargs}


class FakeDB:
    def __init__(self, collection):
        self._collection = collection

    def __getitem__(self, _name):
        return self._collection


def test_ensure_indexes_creates_a_missing_index_without_dropping_anything():
    collection = FakeCollection(existing_indexes=[])
    db = FakeDB(collection)

    count = ensure_indexes(db, "products", [
        {"keys": [("box_tcgcsv_product_id", 1)], "unique": True, "sparse": True, "name": "uniq_box_tcgcsv_id"},
    ])

    assert count == 1
    assert collection.dropped == []
    assert len(collection.created) == 1


def test_ensure_indexes_leaves_a_matching_index_alone_besides_reasserting_it():
    collection = FakeCollection(existing_indexes=[
        {"name": "uniq_box_tcgcsv_id", "key": [("box_tcgcsv_product_id", 1)], "unique": True},
    ])
    db = FakeDB(collection)

    ensure_indexes(db, "products", [
        {"keys": [("box_tcgcsv_product_id", 1)], "unique": True, "name": "uniq_box_tcgcsv_id"},
    ])

    assert collection.dropped == []  # options match -- no drop needed


def test_ensure_indexes_drops_and_recreates_when_sparse_option_is_added():
    """The exact real-world case this fix is for: an index created non-
    sparse (every product used to require box_tcgcsv_product_id) later
    needs sparse:True (so a box-less product -- Secret Lair-style packs
    with no booster box SKU -- can omit the field without colliding with
    every other product also omitting it)."""
    collection = FakeCollection(existing_indexes=[
        {"name": "uniq_box_tcgcsv_id", "key": [("box_tcgcsv_product_id", 1)], "unique": True},
    ])
    db = FakeDB(collection)

    ensure_indexes(db, "products", [
        {"keys": [("box_tcgcsv_product_id", 1)], "unique": True, "sparse": True, "name": "uniq_box_tcgcsv_id"},
    ])

    assert collection.dropped == ["uniq_box_tcgcsv_id"]
    assert len(collection.created) == 1
    _keys, kwargs = collection.created[0]
    assert kwargs["sparse"] is True


def test_ensure_indexes_drops_and_recreates_when_unique_option_changes():
    collection = FakeCollection(existing_indexes=[
        {"name": "idx_example", "key": [("field", 1)]},
    ])
    db = FakeDB(collection)

    ensure_indexes(db, "products", [
        {"keys": [("field", 1)], "unique": True, "name": "idx_example"},
    ])

    assert collection.dropped == ["idx_example"]
