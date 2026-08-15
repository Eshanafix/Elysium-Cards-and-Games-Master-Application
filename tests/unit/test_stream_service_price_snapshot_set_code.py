"""
Regression test: the stream's price_snapshot -- the only per-pack data
available to the Streams screen's search box during a live stream -- now
carries each product's set_code, so a streamer can search "KLD" and match
"Kaladesh Booster" the same way they could already search "Kaladesh".
"""

from decimal import Decimal

from elysium.models.prices import STATUS_OK
from elysium.services import stream_service


class FakeProduct:
    def __init__(self, id, name, set_code, packs_per_box=36):
        self.id = id
        self.name = name
        self.set_code = set_code
        self.packs_per_box = packs_per_box


class FakePrice:
    def __init__(self):
        self.price_status = STATUS_OK
        self.resolved_pack_price = Decimal("3.00")
        self.resolved_price_source = "LOOSE_PACK_MARKET"
        self.raw_loose_pack_market_price = Decimal("3.00")
        self.raw_box_market_price = None
        self.packs_per_box = 36
        self.version = 1


def test_build_price_snapshot_carries_set_code(monkeypatch):
    monkeypatch.setattr(
        stream_service.streamer_repo, "list_inventory_current",
        lambda db_name: {"kld-booster": {"current_packs": 5}},
    )
    monkeypatch.setattr(
        stream_service.product_service, "list_products",
        lambda: [FakeProduct("kld-booster", "Kaladesh Booster", "KLD")],
    )
    monkeypatch.setattr(
        stream_service.price_repo, "find_current_prices",
        lambda product_ids: {"kld-booster": FakePrice()},
    )

    snapshot, blocked = stream_service._build_price_snapshot("elysium_s_a")

    assert blocked == []
    assert snapshot[0]["set_code"] == "KLD"


def test_build_price_snapshot_set_code_none_when_product_missing(monkeypatch):
    monkeypatch.setattr(
        stream_service.streamer_repo, "list_inventory_current",
        lambda db_name: {"ghost-product": {"current_packs": 2}},
    )
    monkeypatch.setattr(stream_service.product_service, "list_products", lambda: [])
    monkeypatch.setattr(
        stream_service.price_repo, "find_current_prices",
        lambda product_ids: {"ghost-product": FakePrice()},
    )

    snapshot, blocked = stream_service._build_price_snapshot("elysium_s_a")

    assert snapshot[0]["set_code"] is None
