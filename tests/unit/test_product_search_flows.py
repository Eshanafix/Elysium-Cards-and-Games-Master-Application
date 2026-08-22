"""
Regression tests: Add Inventory (Master Inventory) and Claim Received
Inventory (My Inventory) used to require picking the product from a table
row or a giant dropdown before/inside the action. Both now open a
ProductSearchDialog first -- press the button, then search -- so neither
requires the underlying table to already have the right row selected/visible.
"""

from PySide6.QtWidgets import QDialog

from elysium.ui import inventory_master, inventory_streamer


class FakeProduct:
    def __init__(self, id, name, packs_per_box=36, is_active=True):
        self.id = id
        self.name = name
        self.packs_per_box = packs_per_box
        self.is_active = is_active


class FakeAdmin:
    id = "admin-1"
    roles = ["admin"]


class FakeStreamer:
    id = "streamer-1"
    streamer_database_name = "elysium_s_abc"
    roles = ["streamer"]


def test_master_inventory_add_opens_search_picker_without_a_preselected_row(qtbot, monkeypatch):
    rows = [
        {
            "product": FakeProduct("p1", "Foundations Play Booster"), "total_packs": 0, "unassigned_packs": 0,
            "assigned_packs": 0, "resolved_pack_price": None, "price_status": "UNRESOLVED", "allocations": [],
        },
    ]
    monkeypatch.setattr(inventory_master.inventory_service, "get_master_inventory_view", lambda: rows)

    screen = inventory_master.MasterInventoryScreen(FakeAdmin())
    qtbot.addWidget(screen)

    # No row selected on the table -- the old flow required this.
    assert screen.table.selectionModel().selectedRows() == []

    class FakePicker:
        def __init__(self, products, parent=None, title=""):
            self.products = products

        def exec(self):
            return QDialog.Accepted

        def selected_product(self):
            return self.products[0]

    monkeypatch.setattr(inventory_master, "ProductSearchDialog", FakePicker)

    class FakeAddDialog:
        def __init__(self, product_name, packs_per_box, parent=None):
            self.product_name = product_name

        def exec(self):
            return QDialog.Rejected  # cancel before actually adding -- just proving the flow reached here

    monkeypatch.setattr(inventory_master, "AddInventoryDialog", FakeAddDialog)

    screen.add_inventory()  # should not error/short-circuit despite no row selection


def test_claim_inventory_opens_search_picker_then_quantity_dialog(qtbot, monkeypatch):
    monkeypatch.setattr(inventory_streamer.inventory_service, "get_streamer_inventory_view", lambda db: [])
    monkeypatch.setattr(inventory_streamer.product_service, "list_products", lambda: [
        FakeProduct("p1", "Foundations Play Booster"),
    ])

    screen = inventory_streamer.MyInventoryScreen(FakeStreamer())
    qtbot.addWidget(screen)

    picked = {}

    class FakePicker:
        def __init__(self, products, parent=None, title=""):
            picked["products"] = products

        def exec(self):
            return QDialog.Accepted

        def selected_product(self):
            return products_by_id["p1"]

    products_by_id = {"p1": FakeProduct("p1", "Foundations Play Booster")}
    monkeypatch.setattr(inventory_streamer, "ProductSearchDialog", FakePicker)

    claimed = {}
    monkeypatch.setattr(
        inventory_streamer.inventory_service, "streamer_claim",
        lambda *a, **k: claimed.setdefault("called", (a, k)),
    )

    class FakeClaimDialog:
        def __init__(self, product, parent=None):
            self.product = product

        def exec(self):
            return QDialog.Accepted

        def converted_packs(self):
            return 5

    monkeypatch.setattr(inventory_streamer, "ClaimInventoryDialog", FakeClaimDialog)

    screen.claim_inventory()

    assert picked["products"][0].id == "p1"
    assert claimed["called"][0][2] == "p1"  # product_id positional arg
    assert claimed["called"][0][3] == 5  # packs
