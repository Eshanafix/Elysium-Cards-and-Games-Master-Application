"""
Regression test: resizeColumnsToContents() ran on every reload(), which
silently snapped a manually-widened "Product" column back down to its
auto-fit width. StreamerInventoryAdminScreen's streamer dropdown calls
reload() on every selection change, so an admin resizing the column would
have it reset the next time they picked a different streamer ("why do I
have to keep resizing the Product column"). Columns should only auto-size
once; a user's manual resize should survive later reload()s.
"""

from decimal import Decimal

from elysium.ui import inventory_streamer


class FakeUser:
    id = "streamer-1"
    streamer_database_name = "elysium_s_abc"
    roles = []


class FakeProduct:
    def __init__(self, id, name):
        self.id = id
        self.name = name


def make_rows():
    return [{
        "product": FakeProduct("p1", "Marvel Super Heroes Collector Booster"),
        "current_packs": 5, "resolved_pack_price": Decimal("4.60"), "price_status": "OK",
    }]


def test_my_inventory_screen_preserves_manual_column_width_across_reload(qtbot, monkeypatch):
    monkeypatch.setattr(inventory_streamer.inventory_service, "get_streamer_inventory_view", lambda db: make_rows())

    screen = inventory_streamer.MyInventoryScreen(FakeUser())
    qtbot.addWidget(screen)

    screen.table.setColumnWidth(0, 400)
    screen.reload()

    assert screen.table.columnWidth(0) == 400


def test_streamer_inventory_admin_screen_preserves_manual_column_width_when_switching_streamers(qtbot, monkeypatch):
    monkeypatch.setattr(inventory_streamer.repo, "list_users", lambda: [])
    monkeypatch.setattr(inventory_streamer.inventory_service, "get_streamer_inventory_view", lambda db: make_rows())

    screen = inventory_streamer.StreamerInventoryAdminScreen(FakeUser())
    qtbot.addWidget(screen)
    screen.streamer_combo.addItem("streamer1", FakeUser())
    screen.reload()

    screen.table.setColumnWidth(0, 400)

    # Simulate switching to a different streamer -- the combo's
    # currentIndexChanged signal calls reload() again.
    screen.reload()

    assert screen.table.columnWidth(0) == 400
