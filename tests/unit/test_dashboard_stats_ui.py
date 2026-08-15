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


def test_streamer_dashboard_shows_all_time_stats(qtbot, monkeypatch):
    monkeypatch.setattr(dashboard.mongo_client, "check_connection", connected_status)
    monkeypatch.setattr(dashboard.lock_service, "get_lock_state", lambda: {"stream_active": False, "price_refresh_active": False})
    monkeypatch.setattr(dashboard.dashboard_service, "get_streamer_stats", lambda db_name, start_date, end_date: {
        "stream_count": 3, "avg_stream_gross": Decimal("100.00"), "avg_stream_profit": Decimal("40.00"),
        "break_count": 9, "avg_break_gross": Decimal("35.00"), "avg_break_profit": Decimal("14.00"),
        "profit_margin": Decimal("0.4"),
    })

    streamer = User(id="s1", username="streamer1", password_hash="x", roles=[ROLE_STREAMER], streamer_database_name="elysium_s_a")
    screen = dashboard.DashboardScreen(streamer)
    qtbot.addWidget(screen)

    assert screen.stream_count_tile.value_label.text() == "3"
    assert screen.avg_stream_gross_tile.value_label.text() == "$100.00"
    assert screen.avg_stream_profit_tile.value_label.text() == "$40.00"
    assert screen.streamer_profit_margin_tile.value_label.text() == "40.0%"
    assert screen.break_count_tile.value_label.text() == "9"
    assert screen.avg_break_gross_tile.value_label.text() == "$35.00"
    assert screen.avg_break_profit_tile.value_label.text() == "$14.00"
    # All-time by default -- no date range applied unless the checkbox is checked.
    assert screen.date_filter_checkbox.isChecked() is False


def test_date_filter_checkbox_toggles_range_inputs_and_refreshes(qtbot, monkeypatch):
    monkeypatch.setattr(dashboard.mongo_client, "check_connection", connected_status)
    monkeypatch.setattr(dashboard.lock_service, "get_lock_state", lambda: {"stream_active": False, "price_refresh_active": False})

    calls = []
    monkeypatch.setattr(dashboard.dashboard_service, "get_streamer_stats", lambda db_name, start_date, end_date: calls.append(
        (start_date, end_date)
    ) or {
        "stream_count": 0, "avg_stream_gross": None, "avg_stream_profit": None,
        "break_count": 0, "avg_break_gross": None, "avg_break_profit": None, "profit_margin": None,
    })

    streamer = User(id="s1", username="streamer1", password_hash="x", roles=[ROLE_STREAMER], streamer_database_name="elysium_s_a")
    screen = dashboard.DashboardScreen(streamer)
    qtbot.addWidget(screen)

    assert not screen.date_from_input.isEnabled()
    assert calls[-1] == (None, None)

    screen.date_filter_checkbox.setChecked(True)

    assert screen.date_from_input.isEnabled()
    assert screen.date_to_input.isEnabled()
    assert calls[-1] != (None, None)


def test_streamer_only_user_does_not_see_admin_stats_or_factory_reset(qtbot, monkeypatch):
    monkeypatch.setattr(dashboard.mongo_client, "check_connection", connected_status)
    monkeypatch.setattr(dashboard.lock_service, "get_lock_state", lambda: {"stream_active": False, "price_refresh_active": False})
    monkeypatch.setattr(dashboard.dashboard_service, "get_streamer_stats", lambda db_name, start_date, end_date: {
        "stream_count": 0, "avg_stream_gross": None, "avg_stream_profit": None,
        "break_count": 0, "avg_break_gross": None, "avg_break_profit": None, "profit_margin": None,
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
