"""
Regression tests: clicking a column header (e.g. Price) now sorts these
tables -- which reorders the table's visual rows without touching the
parallel self._rows list. selected_row() must still resolve to the right
underlying row after a real sort, not just before one.
"""

from decimal import Decimal

from elysium.ui import inventory_master, inventory_streamer, prices


class FakeUser:
    id = "streamer-1"
    streamer_database_name = "elysium_s_abc"
    roles = []


class FakeProduct:
    def __init__(self, id, name):
        self.id = id
        self.name = name


def test_prices_screen_sorting_enabled_and_selection_survives_sort(qtbot, monkeypatch):
    monkeypatch.setattr(prices.product_service, "list_products", lambda: [
        FakeProduct("cheap", "Cheap Booster"), FakeProduct("pricey", "Pricey Booster"),
    ])

    class FakePrice:
        def __init__(self, price):
            self.raw_loose_pack_market_price = price
            self.raw_box_market_price = None
            self.resolved_pack_price = price
            self.resolved_price_source = "LOOSE_PACK_MARKET"
            self.price_status = "OK"
            self.last_successful_refresh_at = None

    monkeypatch.setattr(prices.price_repo, "list_all_current_prices", lambda: {
        "cheap": FakePrice(Decimal("4.60")), "pricey": FakePrice(Decimal("100.00")),
    })

    screen = prices.PricesScreen(FakeUser())
    qtbot.addWidget(screen)

    assert screen.table.isSortingEnabled()

    # Sort ascending by Resolved Price (column 3) -- "Cheap Booster" should
    # now be row 0 regardless of its original insertion order.
    screen.table.sortItems(3)
    assert screen.table.item(0, 0).text() == "Cheap Booster"

    screen.table.selectRow(0)
    selected_product, selected_price = screen.selected_row()
    assert selected_product.id == "cheap"
    assert selected_price.resolved_pack_price == Decimal("4.60")


def test_my_inventory_screen_selection_survives_sort(qtbot, monkeypatch):
    rows = [
        {
            "product": FakeProduct("cheap", "Cheap Booster"), "current_packs": 5,
            "resolved_pack_price": Decimal("4.60"), "price_status": "OK",
        },
        {
            "product": FakeProduct("pricey", "Pricey Booster"), "current_packs": 2,
            "resolved_pack_price": Decimal("100.00"), "price_status": "OK",
        },
    ]
    monkeypatch.setattr(inventory_streamer.inventory_service, "get_streamer_inventory_view", lambda db: rows)

    screen = inventory_streamer.MyInventoryScreen(FakeUser())
    qtbot.addWidget(screen)

    assert screen.table.isSortingEnabled()

    screen.table.sortItems(2)  # Price column, ascending
    assert screen.table.item(0, 0).text() == "Cheap Booster"

    screen.table.selectRow(0)
    selected = screen.selected_row()
    assert selected["product"].id == "cheap"


def test_master_inventory_screen_selection_survives_sort(qtbot, monkeypatch):
    rows = [
        {
            "product": FakeProduct("cheap", "Cheap Booster"), "total_packs": 5, "unassigned_packs": 5,
            "assigned_packs": 0, "resolved_pack_price": Decimal("4.60"), "price_status": "OK", "allocations": [],
        },
        {
            "product": FakeProduct("pricey", "Pricey Booster"), "total_packs": 2, "unassigned_packs": 2,
            "assigned_packs": 0, "resolved_pack_price": Decimal("100.00"), "price_status": "OK", "allocations": [],
        },
    ]
    monkeypatch.setattr(inventory_master.inventory_service, "get_master_inventory_view", lambda: rows)

    screen = inventory_master.MasterInventoryScreen(FakeUser())
    qtbot.addWidget(screen)

    assert screen.table.isSortingEnabled()

    screen.table.sortItems(4)  # Price column, ascending
    assert screen.table.item(0, 0).text() == "Cheap Booster"

    screen.table.selectRow(0)
    selected = screen.selected_row()
    assert selected["product"].id == "cheap"
