from elysium.bootstrap.provision_streamer_db import streamer_database_name
from elysium.bootstrap.schema_definitions import (
    MASTER_COLLECTIONS,
    PRICES_COLLECTIONS,
    STREAMER_COLLECTIONS,
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
