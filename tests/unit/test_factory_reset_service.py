from elysium.services import factory_reset_service


class FakeDeleteResult:
    def __init__(self, count):
        self.deleted_count = count


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = docs or []
        self.delete_many_calls = 0

    def delete_many(self, query):
        self.delete_many_calls += 1
        count = len(self.docs)
        self.docs = []
        return FakeDeleteResult(count)

    def find(self, query, projection=None):
        return list(self.docs)

    def update_one(self, query, update):
        self.last_update = update


class FakeDb:
    def __init__(self, collections: dict):
        self._collections = collections

    def __getitem__(self, name):
        return self._collections.setdefault(name, FakeCollection())

    def __getattr__(self, name):
        return self._collections.setdefault(name, FakeCollection())


class FakeClient:
    def __init__(self):
        self.dropped = []

    def drop_database(self, name):
        self.dropped.append(name)


def test_wipe_all_data_deletes_every_master_and_prices_collection(monkeypatch):
    master_collections = {}
    prices_collections = {}
    master_db = FakeDb(master_collections)
    prices_db = FakeDb(prices_collections)
    client = FakeClient()

    master_db.users.docs = [{"_id": "u1", "streamer_database_name": "elysium_s_abc"}]

    monkeypatch.setattr(factory_reset_service, "get_client", lambda: client)
    monkeypatch.setattr(factory_reset_service, "get_master_db", lambda: master_db)
    monkeypatch.setattr(factory_reset_service, "get_prices_db", lambda: prices_db)

    summary = factory_reset_service.wipe_all_data(confirmed_by="admin-1")

    for name in factory_reset_service.MASTER_DATA_COLLECTIONS:
        assert master_collections[name].delete_many_calls == 1

    for name in factory_reset_service.PRICES_DATA_COLLECTIONS:
        assert prices_collections[name].delete_many_calls == 1

    assert summary["deleted_counts"]["users"] == 1


def test_wipe_all_data_drops_every_streamer_database(monkeypatch):
    master_collections = {}
    master_db = FakeDb(master_collections)
    prices_db = FakeDb({})
    client = FakeClient()

    master_db.users.docs = [
        {"_id": "u1", "streamer_database_name": "elysium_s_aaa"},
        {"_id": "u2", "streamer_database_name": "elysium_s_bbb"},
        {"_id": "u3"},  # non-streamer admin, no streamer_database_name field
    ]

    monkeypatch.setattr(factory_reset_service, "get_client", lambda: client)
    monkeypatch.setattr(factory_reset_service, "get_master_db", lambda: master_db)
    monkeypatch.setattr(factory_reset_service, "get_prices_db", lambda: prices_db)

    summary = factory_reset_service.wipe_all_data(confirmed_by="admin-1")

    assert set(client.dropped) == {"elysium_s_aaa", "elysium_s_bbb"}
    assert set(summary["dropped_databases"]) == {"elysium_s_aaa", "elysium_s_bbb"}


def test_wipe_all_data_resets_global_operations_singleton(monkeypatch):
    master_collections = {}
    master_db = FakeDb(master_collections)
    prices_db = FakeDb({})
    client = FakeClient()

    monkeypatch.setattr(factory_reset_service, "get_client", lambda: client)
    monkeypatch.setattr(factory_reset_service, "get_master_db", lambda: master_db)
    monkeypatch.setattr(factory_reset_service, "get_prices_db", lambda: prices_db)

    factory_reset_service.wipe_all_data(confirmed_by="admin-1")

    update = master_collections["global_operations"].last_update
    assert update["$set"]["stream_active"] is False
    assert update["$set"]["price_refresh_active"] is False
    assert update["$set"]["streamer_id"] is None
