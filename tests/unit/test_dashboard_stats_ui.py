"""
Regression tests: admin dashboard shows company stat tiles, streamer
dashboard shows their own weekly stats, and Factory Reset stays admin-only
while sitting below the stat widgets.
"""

from decimal import Decimal

from elysium.models.users import ROLE_ADMIN, ROLE_STREAMER, User
from elysium.ui import dashboard


def connected_status():
    return type("S", (), {"is_connected": True, "detail": "ok"})()


def test_admin_dashboard_shows_company_stats(qtbot, monkeypatch):
    monkeypatch.setattr(dashboard.mongo_client, "check_connection", connected_status)
    monkeypatch.setattr(dashboard.lock_service, "get_lock_state", lambda: {"stream_active": False, "price_refresh_active": False})
    monkeypatch.setattr(dashboard.dashboard_service, "get_admin_summary", lambda: {
        "total_packs": 150, "total_value": Decimal("450.00"), "overall_profit_margin": Decimal("0.25"),
    })

    admin = User(id="a1", username="admin", password_hash="x", roles=[ROLE_ADMIN])
    screen = dashboard.DashboardScreen(admin)
    qtbot.addWidget(screen)

    assert screen.total_packs_tile.value_label.text() == "150"
    assert screen.total_value_tile.value_label.text() == "$450.00"
    assert screen.overall_margin_tile.value_label.text() == "25.0%"


def test_streamer_dashboard_shows_weekly_stats(qtbot, monkeypatch):
    monkeypatch.setattr(dashboard.mongo_client, "check_connection", connected_status)
    monkeypatch.setattr(dashboard.lock_service, "get_lock_state", lambda: {"stream_active": False, "price_refresh_active": False})
    monkeypatch.setattr(dashboard.dashboard_service, "get_streamer_weekly_summary", lambda db_name: {
        "streams_this_week": 3, "profit_margin_this_week": Decimal("0.4"),
    })

    streamer = User(id="s1", username="streamer1", password_hash="x", roles=[ROLE_STREAMER], streamer_database_name="elysium_s_a")
    screen = dashboard.DashboardScreen(streamer)
    qtbot.addWidget(screen)

    assert screen.streams_this_week_tile.value_label.text() == "3"
    assert screen.weekly_margin_tile.value_label.text() == "40.0%"


def test_streamer_only_user_does_not_see_admin_stats_or_factory_reset(qtbot, monkeypatch):
    monkeypatch.setattr(dashboard.mongo_client, "check_connection", connected_status)
    monkeypatch.setattr(dashboard.lock_service, "get_lock_state", lambda: {"stream_active": False, "price_refresh_active": False})
    monkeypatch.setattr(dashboard.dashboard_service, "get_streamer_weekly_summary", lambda db_name: {
        "streams_this_week": 0, "profit_margin_this_week": None,
    })

    streamer = User(id="s1", username="streamer1", password_hash="x", roles=[ROLE_STREAMER], streamer_database_name="elysium_s_a")
    screen = dashboard.DashboardScreen(streamer)
    qtbot.addWidget(screen)

    assert screen.admin_stats_container.parent() is None
    assert screen.factory_reset_button.parent() is None


def test_format_margin_none_shows_na():
    assert dashboard._format_margin(None) == "N/A"


def test_factory_reset_button_placed_after_stat_widgets_in_layout(qtbot, monkeypatch):
    monkeypatch.setattr(dashboard.mongo_client, "check_connection", connected_status)
    monkeypatch.setattr(dashboard.lock_service, "get_lock_state", lambda: {"stream_active": False, "price_refresh_active": False})
    monkeypatch.setattr(dashboard.dashboard_service, "get_admin_summary", lambda: {
        "total_packs": 0, "total_value": Decimal("0"), "overall_profit_margin": None,
    })

    admin = User(id="a1", username="admin", password_hash="x", roles=[ROLE_ADMIN])
    screen = dashboard.DashboardScreen(admin)
    qtbot.addWidget(screen)

    layout = screen.layout()
    indices = {}
    for i in range(layout.count()):
        widget = layout.itemAt(i).widget()
        if widget is screen.admin_stats_container:
            indices["stats"] = i
        if widget is screen.factory_reset_button:
            indices["reset"] = i

    assert indices["stats"] < indices["reset"]
