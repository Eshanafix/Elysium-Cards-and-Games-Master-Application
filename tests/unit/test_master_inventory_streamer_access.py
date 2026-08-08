"""
Regression tests: streamers can now browse Master Inventory (read-only),
but the LLD hard rule "only admin changes master total" must still hold --
the Add/Reduce actions stay admin-only both visually and functionally.
"""

from elysium.models.users import ROLE_ADMIN, ROLE_STREAMER, User
from elysium.ui import inventory_master


def make_screen(qtbot, monkeypatch, user):
    monkeypatch.setattr(inventory_master.inventory_service, "get_master_inventory_view", lambda: [])
    screen = inventory_master.MasterInventoryScreen(user)
    qtbot.addWidget(screen)
    return screen


def test_streamer_does_not_see_add_or_reduce_buttons(qtbot, monkeypatch):
    streamer = User(id="s1", username="streamer1", password_hash="x", roles=[ROLE_STREAMER])
    screen = make_screen(qtbot, monkeypatch, streamer)

    assert screen.add_button.isVisibleTo(screen) is False
    assert screen.reduce_button.isVisibleTo(screen) is False


def test_admin_buttons_visible_flag_true(qtbot, monkeypatch):
    admin = User(id="a1", username="admin", password_hash="x", roles=[ROLE_ADMIN])
    screen = make_screen(qtbot, monkeypatch, admin)

    # isVisible() alone depends on the whole widget tree being shown; check
    # the flag Qt actually stores for this widget's own visibility intent.
    assert screen.add_button.isVisibleTo(screen)
    assert screen.reduce_button.isVisibleTo(screen)


def test_streamer_add_inventory_is_a_noop_even_if_called_directly(qtbot, monkeypatch):
    """Defense in depth: even if something bypasses the hidden button."""
    streamer = User(id="s1", username="streamer1", password_hash="x", roles=[ROLE_STREAMER])
    screen = make_screen(qtbot, monkeypatch, streamer)

    called = {}
    monkeypatch.setattr(inventory_master.inventory_service, "admin_add_inventory", lambda *a, **k: called.setdefault("ran", True))

    screen.add_inventory()

    assert "ran" not in called


def test_streamer_reduce_inventory_is_a_noop_even_if_called_directly(qtbot, monkeypatch):
    streamer = User(id="s1", username="streamer1", password_hash="x", roles=[ROLE_STREAMER])
    screen = make_screen(qtbot, monkeypatch, streamer)

    called = {}
    monkeypatch.setattr(inventory_master.inventory_service, "admin_reduce_inventory", lambda *a, **k: called.setdefault("ran", True))

    screen.reduce_inventory()

    assert "ran" not in called
