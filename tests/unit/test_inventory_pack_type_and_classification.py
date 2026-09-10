"""
Regression tests for two docs-feedback additions to the inventory screens:

1. A "Pack Type" column (Master Inventory, My Inventory, Streamer Inventory)
   that sorts by a fixed priority -- Collector, Play, Draft, Set, Jumpstart,
   Classic -- rather than plain alphabetical, since alphabetical order
   doesn't track what these teams actually care about first.
2. A "Classification" column (My Inventory, Streamer Inventory) matching
   the Shared Sealed Prices one -- LOW/MID/HIGH, color-coded with the exact
   same banner colors as the live pack-selection grid (BreakProductTile),
   sharing elysium.models.prices.CLASSIFICATION_COLOR so the two can never
   drift out of sync.
"""

from decimal import Decimal

from elysium.ui import inventory_master, inventory_streamer


class FakeUser:
    id = "streamer-1"
    streamer_database_name = "elysium_s_abc"
    roles = []


class FakeProduct:
    def __init__(self, id, name, booster_type):
        self.id = id
        self.name = name
        self.booster_type = booster_type


def _headers(table):
    return [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]


def _pack_types_in_row_order(table, column):
    return [table.item(r, column).text() for r in range(table.rowCount())]


# --- My Inventory ---


def test_my_inventory_has_pack_type_and_classification_columns(qtbot, monkeypatch):
    rows = [{
        "product": FakeProduct("p1", "Kaladesh Booster", "CLASSIC"), "current_packs": 1,
        "resolved_pack_price": Decimal("4.00"), "price_status": "OK",
    }]
    monkeypatch.setattr(inventory_streamer.inventory_service, "get_streamer_inventory_view", lambda db: rows)

    screen = inventory_streamer.MyInventoryScreen(FakeUser())
    qtbot.addWidget(screen)

    assert _headers(screen.table) == [
        "Product", "Pack Type", "Current Packs", "Price", "Classification", "Market Value",
    ]
    assert screen.table.item(0, 1).text() == "CLASSIC"
    assert screen.table.item(0, 4).text() == "LOW"


def test_my_inventory_pack_type_sorts_collector_before_draft_before_classic(qtbot, monkeypatch):
    rows = [
        {"product": FakeProduct("p1", "Draft Set", "DRAFT"), "current_packs": 1,
         "resolved_pack_price": Decimal("4.00"), "price_status": "OK"},
        {"product": FakeProduct("p2", "Classic Set", "CLASSIC"), "current_packs": 1,
         "resolved_pack_price": Decimal("4.00"), "price_status": "OK"},
        {"product": FakeProduct("p3", "Collector Set", "COLLECTOR"), "current_packs": 1,
         "resolved_pack_price": Decimal("4.00"), "price_status": "OK"},
    ]
    monkeypatch.setattr(inventory_streamer.inventory_service, "get_streamer_inventory_view", lambda db: rows)

    screen = inventory_streamer.MyInventoryScreen(FakeUser())
    qtbot.addWidget(screen)

    screen.table.sortItems(1)  # Pack Type column, ascending

    assert _pack_types_in_row_order(screen.table, 1) == ["COLLECTOR", "DRAFT", "CLASSIC"]


def test_my_inventory_classification_cell_is_color_coded(qtbot, monkeypatch):
    rows = [
        {"product": FakeProduct("p1", "Cheap Booster", "DRAFT"), "current_packs": 1,
         "resolved_pack_price": Decimal("4.00"), "price_status": "OK"},
        {"product": FakeProduct("p2", "Mid Booster", "DRAFT"), "current_packs": 1,
         "resolved_pack_price": Decimal("15.00"), "price_status": "OK"},
        {"product": FakeProduct("p3", "Pricey Booster", "DRAFT"), "current_packs": 1,
         "resolved_pack_price": Decimal("25.00"), "price_status": "OK"},
        {"product": FakeProduct("p4", "Unpriced Booster", "DRAFT"), "current_packs": 1,
         "resolved_pack_price": None, "price_status": "UNRESOLVED"},
    ]
    monkeypatch.setattr(inventory_streamer.inventory_service, "get_streamer_inventory_view", lambda db: rows)

    screen = inventory_streamer.MyInventoryScreen(FakeUser())
    qtbot.addWidget(screen)

    by_name = {screen.table.item(r, 0).text(): r for r in range(screen.table.rowCount())}
    assert screen.table.item(by_name["Cheap Booster"], 4).background().color().name() == "#bdc05c"
    assert screen.table.item(by_name["Mid Booster"], 4).background().color().name() == "#fa9246"
    assert screen.table.item(by_name["Pricey Booster"], 4).background().color().name() == "#fb5445"
    assert screen.table.item(by_name["Unpriced Booster"], 4).text() == ""


def test_my_inventory_classification_sorts_low_mid_high_not_alphabetically(qtbot, monkeypatch):
    rows = [
        {"product": FakeProduct("p1", "Pricey Booster", "DRAFT"), "current_packs": 1,
         "resolved_pack_price": Decimal("25.00"), "price_status": "OK"},
        {"product": FakeProduct("p2", "Cheap Booster", "DRAFT"), "current_packs": 1,
         "resolved_pack_price": Decimal("4.00"), "price_status": "OK"},
        {"product": FakeProduct("p3", "Mid Booster", "DRAFT"), "current_packs": 1,
         "resolved_pack_price": Decimal("15.00"), "price_status": "OK"},
    ]
    monkeypatch.setattr(inventory_streamer.inventory_service, "get_streamer_inventory_view", lambda db: rows)

    screen = inventory_streamer.MyInventoryScreen(FakeUser())
    qtbot.addWidget(screen)

    screen.table.sortItems(4)  # Classification column, ascending

    # Alphabetical would give HIGH, LOW, MID -- this must give LOW, MID, HIGH.
    assert _pack_types_in_row_order(screen.table, 4) == ["LOW", "MID", "HIGH"]


# --- Streamer Inventory (admin view) ---


def test_streamer_inventory_admin_has_pack_type_and_classification_columns(qtbot, monkeypatch):
    rows = [{
        "product": FakeProduct("p1", "Jumpstart Booster", "JUMPSTART"), "current_packs": 3,
        "resolved_pack_price": Decimal("30.00"), "price_status": "OK",
    }]
    monkeypatch.setattr(inventory_streamer.repo, "list_users", lambda: [])
    monkeypatch.setattr(inventory_streamer.inventory_service, "get_streamer_inventory_view", lambda db: rows)

    screen = inventory_streamer.StreamerInventoryAdminScreen(FakeUser())
    qtbot.addWidget(screen)
    screen.streamer_combo.addItem("streamer1", FakeUser())
    screen.reload()

    assert _headers(screen.table) == ["Product", "Pack Type", "Current Packs", "Price", "Classification"]
    assert screen.table.item(0, 1).text() == "JUMPSTART"
    assert screen.table.item(0, 4).text() == "HIGH"
    assert screen.table.item(0, 4).background().color().name() == "#fb5445"


# --- Master Inventory ---


def test_master_inventory_has_pack_type_column_without_classification(qtbot, monkeypatch):
    rows = [{
        "product": FakeProduct("p1", "Collector Booster", "COLLECTOR"), "total_packs": 5, "unassigned_packs": 5,
        "assigned_packs": 0, "resolved_pack_price": Decimal("50.00"), "price_status": "OK", "allocations": [],
    }]
    monkeypatch.setattr(inventory_master.inventory_service, "get_master_inventory_view", lambda: rows)

    screen = inventory_master.MasterInventoryScreen(FakeUser())
    qtbot.addWidget(screen)

    assert _headers(screen.table) == [
        "Product", "Pack Type", "Total", "Unassigned", "Assigned", "Price", "Market Value", "Allocations",
    ]
    assert screen.table.item(0, 1).text() == "COLLECTOR"


def test_master_inventory_pack_type_sorts_collector_before_play_before_set(qtbot, monkeypatch):
    rows = [
        {"product": FakeProduct("p1", "Set A", "SET"), "total_packs": 1, "unassigned_packs": 1,
         "assigned_packs": 0, "resolved_pack_price": Decimal("4.00"), "price_status": "OK", "allocations": []},
        {"product": FakeProduct("p2", "Play A", "PLAY"), "total_packs": 1, "unassigned_packs": 1,
         "assigned_packs": 0, "resolved_pack_price": Decimal("4.00"), "price_status": "OK", "allocations": []},
        {"product": FakeProduct("p3", "Collector A", "COLLECTOR"), "total_packs": 1, "unassigned_packs": 1,
         "assigned_packs": 0, "resolved_pack_price": Decimal("4.00"), "price_status": "OK", "allocations": []},
    ]
    monkeypatch.setattr(inventory_master.inventory_service, "get_master_inventory_view", lambda: rows)

    screen = inventory_master.MasterInventoryScreen(FakeUser())
    qtbot.addWidget(screen)

    screen.table.sortItems(1)  # Pack Type column, ascending

    assert _pack_types_in_row_order(screen.table, 1) == ["COLLECTOR", "PLAY", "SET"]


def test_master_inventory_selected_row_survives_pack_type_sort(qtbot, monkeypatch):
    rows = [
        {"product": FakeProduct("cheap", "Set A", "SET"), "total_packs": 1, "unassigned_packs": 1,
         "assigned_packs": 0, "resolved_pack_price": Decimal("4.00"), "price_status": "OK", "allocations": []},
        {"product": FakeProduct("pricey", "Collector A", "COLLECTOR"), "total_packs": 1, "unassigned_packs": 1,
         "assigned_packs": 0, "resolved_pack_price": Decimal("50.00"), "price_status": "OK", "allocations": []},
    ]
    monkeypatch.setattr(inventory_master.inventory_service, "get_master_inventory_view", lambda: rows)

    screen = inventory_master.MasterInventoryScreen(FakeUser())
    qtbot.addWidget(screen)

    screen.table.sortItems(1)  # Collector Booster ("pricey") now sorts to row 0
    screen.table.selectRow(0)

    selected = screen.selected_row()
    assert selected["product"].id == "pricey"
