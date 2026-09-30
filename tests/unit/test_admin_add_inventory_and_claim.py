"""
Regression tests for Master Inventory's "Add Inventory" combined
add-and-claim flow (docs feedback: an admin who's also a streamer
shouldn't have to add to master inventory and then separately go claim it
themselves -- and more generally, an admin can now stock up directly for
any streamer). Add Inventory's dialog gained an optional "Streamer" combo
(default: none, unchanged behavior) -- picking one routes through
inventory_service.admin_add_inventory_and_claim() instead of the plain
admin_add_inventory().
"""

from PySide6.QtWidgets import QDialog

from elysium.models.users import ROLE_ADMIN, ROLE_STREAMER, User
from elysium.ui import inventory_master


class FakeProduct:
    def __init__(self, id, name, packs_per_box=36, booster_type="DRAFT"):
        self.id = id
        self.name = name
        self.packs_per_box = packs_per_box
        self.booster_type = booster_type


ADMIN = User(id="admin-1", username="admin1", password_hash="x", roles=[ROLE_ADMIN])
STREAMER_A = User(
    id="streamer-a", username="streamerA", password_hash="x", roles=[ROLE_STREAMER],
    streamer_database_name="elysium_s_a",
)
STREAMER_B = User(
    id="streamer-b", username="streamerB", password_hash="x", roles=[ROLE_STREAMER],
    streamer_database_name="elysium_s_b",
)


def make_screen(qtbot, monkeypatch, rows=None, streamers=None):
    monkeypatch.setattr(inventory_master.inventory_service, "get_master_inventory_view", lambda: rows or [])
    monkeypatch.setattr(inventory_master.repo, "list_users", lambda: (streamers or []) + [ADMIN])

    screen = inventory_master.MasterInventoryScreen(ADMIN)
    qtbot.addWidget(screen)
    return screen


# --- AddInventoryDialog: streamer combo itself ---


def test_add_inventory_dialog_defaults_to_no_streamer(qtbot):
    dialog = inventory_master.AddInventoryDialog("Foundations Play Booster", 36, [STREAMER_A, STREAMER_B])
    qtbot.addWidget(dialog)

    assert dialog.streamer_combo.count() == 3  # "-- none --" + 2 streamers
    assert dialog.selected_streamer() is None


def test_add_inventory_dialog_lists_streamers_by_username(qtbot):
    dialog = inventory_master.AddInventoryDialog("Foundations Play Booster", 36, [STREAMER_A, STREAMER_B])
    qtbot.addWidget(dialog)

    labels = [dialog.streamer_combo.itemText(i) for i in range(dialog.streamer_combo.count())]
    assert "streamerA" in labels
    assert "streamerB" in labels


def test_add_inventory_dialog_selected_streamer_reflects_combo_choice(qtbot):
    dialog = inventory_master.AddInventoryDialog("Foundations Play Booster", 36, [STREAMER_A, STREAMER_B])
    qtbot.addWidget(dialog)

    dialog.streamer_combo.setCurrentIndex(dialog.streamer_combo.findText("streamerB"))

    assert dialog.selected_streamer() is STREAMER_B


# --- MasterInventoryScreen.add_inventory(): routing ---


def _install_pickers(monkeypatch, product, chosen_streamer):
    class FakePicker:
        def __init__(self, products, parent=None, title=""):
            pass

        def exec(self):
            return QDialog.Accepted

        def selected_product(self):
            return product

    class FakeAddDialog:
        def __init__(self, product_name, packs_per_box, streamers, parent=None):
            pass

        def exec(self):
            return QDialog.Accepted

        def converted_packs(self):
            return 10

        def selected_streamer(self):
            return chosen_streamer

    monkeypatch.setattr(inventory_master, "ProductSearchDialog", FakePicker)
    monkeypatch.setattr(inventory_master, "AddInventoryDialog", FakeAddDialog)


def test_add_inventory_with_no_streamer_selected_uses_plain_add(qtbot, monkeypatch):
    product = FakeProduct("p1", "Foundations Play Booster")
    screen = make_screen(qtbot, monkeypatch, streamers=[STREAMER_A])
    _install_pickers(monkeypatch, product, chosen_streamer=None)

    calls = []
    monkeypatch.setattr(
        inventory_master.inventory_service, "admin_add_inventory",
        lambda product_id, packs, admin_id: calls.append((product_id, packs, admin_id)),
    )
    monkeypatch.setattr(
        inventory_master.inventory_service, "admin_add_inventory_and_claim",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    screen.add_inventory()

    assert calls == [("p1", 10, "admin-1")]
    assert "Added 10 packs to 'Foundations Play Booster'" in screen.message_label.text()


def test_add_inventory_with_streamer_selected_uses_add_and_claim(qtbot, monkeypatch):
    product = FakeProduct("p1", "Foundations Play Booster")
    screen = make_screen(qtbot, monkeypatch, streamers=[STREAMER_A])
    _install_pickers(monkeypatch, product, chosen_streamer=STREAMER_A)

    calls = []
    monkeypatch.setattr(
        inventory_master.inventory_service, "admin_add_inventory_and_claim",
        lambda product_id, packs, admin_id, streamer_id, streamer_db: calls.append(
            (product_id, packs, admin_id, streamer_id, streamer_db)
        ),
    )
    monkeypatch.setattr(
        inventory_master.inventory_service, "admin_add_inventory",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    screen.add_inventory()

    assert calls == [("p1", 10, "admin-1", "streamer-a", "elysium_s_a")]
    message = screen.message_label.text()
    assert "10 packs" in message and "Foundations Play Booster" in message and "streamerA" in message


def test_add_inventory_and_claim_surfaces_streamer_locked_error(qtbot, monkeypatch):
    """A streamer with an active stream can't have inventory pushed into
    them mid-stream -- same protection as a normal claim, must surface as
    an error message rather than crash or silently no-op."""
    product = FakeProduct("p1", "Foundations Play Booster")
    screen = make_screen(qtbot, monkeypatch, streamers=[STREAMER_A])
    _install_pickers(monkeypatch, product, chosen_streamer=STREAMER_A)

    def boom(*a, **k):
        raise inventory_master.inventory_service.StreamerLockedError("locked mid-stream")

    monkeypatch.setattr(inventory_master.inventory_service, "admin_add_inventory_and_claim", boom)

    screen.add_inventory()  # must not raise

    assert "locked mid-stream" in screen.message_label.text()
