"""
Regression tests: the holdings/pack tile grids used to be pinned to a
hardcoded column count (6), which meant a wide monitor with room for 8+
tiles per row still wrapped after 6, and a narrow window could overflow.
Columns are now derived from the actual scroll area width, and a resize
only triggers a grid rebuild when the column count would actually change.
"""

from decimal import Decimal

from elysium.ui import streams


class FakeUser:
    id = "streamer-1"
    streamer_database_name = "elysium_s_abc"


def test_columns_for_width_fits_as_many_tiles_as_the_width_allows():
    # tile 120 + spacing 10 => 130px per column.
    assert streams._columns_for_width(130 * 8) == 8
    assert streams._columns_for_width(130 * 4 + 5) == 4


def test_columns_for_width_never_drops_below_minimum():
    assert streams._columns_for_width(0) == streams.MIN_GRID_COLUMNS
    assert streams._columns_for_width(-100) == streams.MIN_GRID_COLUMNS


def test_reload_pack_tiles_tracks_last_columns_used(qtbot, monkeypatch):
    stream = type("S", (), {
        "date": "2026-08-08", "start_time": "now", "id": "stream-1",
        "price_snapshot": [
            {"product_id": "p1", "product_name_at_snapshot": "Kaladesh Booster", "set_code": "KLD", "resolved_pack_price": Decimal("3.00")},
        ],
    })()

    monkeypatch.setattr(streams.stream_service, "resume_check", lambda db_name: stream)
    monkeypatch.setattr(streams.inventory_service, "get_streamer_inventory_view", lambda db_name: [])
    monkeypatch.setattr(streams.streamer_repo, "find_active_break", lambda db_name, sid: None)
    monkeypatch.setattr(streams.streamer_repo, "list_breaks_for_stream", lambda db_name, sid, **k: [])
    monkeypatch.setattr(streams.break_service, "get_availability", lambda s, b, db_name: {"p1": 5})
    monkeypatch.setattr(streams.product_service, "list_products", lambda: [])

    screen = streams.StreamsScreen(FakeUser())
    qtbot.addWidget(screen)

    assert screen._last_pack_columns == screen._compute_pack_columns()


def test_regrid_skipped_when_column_count_unchanged(qtbot, monkeypatch):
    stream = type("S", (), {
        "date": "2026-08-08", "start_time": "now", "id": "stream-1", "price_snapshot": [],
    })()

    monkeypatch.setattr(streams.stream_service, "resume_check", lambda db_name: stream)
    monkeypatch.setattr(streams.inventory_service, "get_streamer_inventory_view", lambda db_name: [])
    monkeypatch.setattr(streams.streamer_repo, "find_active_break", lambda db_name, sid: None)
    monkeypatch.setattr(streams.streamer_repo, "list_breaks_for_stream", lambda db_name, sid, **k: [])
    monkeypatch.setattr(streams.break_service, "get_availability", lambda s, b, db_name: {})
    monkeypatch.setattr(streams.product_service, "list_products", lambda: [])

    screen = streams.StreamsScreen(FakeUser())
    qtbot.addWidget(screen)

    reload_calls = []
    monkeypatch.setattr(screen, "reload_pack_tiles", lambda: reload_calls.append(True))
    monkeypatch.setattr(screen, "_compute_pack_columns", lambda: screen._last_pack_columns)

    screen._run_scheduled_regrid()

    assert reload_calls == []


def test_regrid_rebuilds_when_column_count_changes(qtbot, monkeypatch):
    stream = type("S", (), {
        "date": "2026-08-08", "start_time": "now", "id": "stream-1", "price_snapshot": [],
    })()

    monkeypatch.setattr(streams.stream_service, "resume_check", lambda db_name: stream)
    monkeypatch.setattr(streams.inventory_service, "get_streamer_inventory_view", lambda db_name: [])
    monkeypatch.setattr(streams.streamer_repo, "find_active_break", lambda db_name, sid: None)
    monkeypatch.setattr(streams.streamer_repo, "list_breaks_for_stream", lambda db_name, sid, **k: [])
    monkeypatch.setattr(streams.break_service, "get_availability", lambda s, b, db_name: {})
    monkeypatch.setattr(streams.product_service, "list_products", lambda: [])

    screen = streams.StreamsScreen(FakeUser())
    qtbot.addWidget(screen)

    reload_calls = []
    monkeypatch.setattr(screen, "reload_pack_tiles", lambda: reload_calls.append(True))
    monkeypatch.setattr(screen, "_compute_pack_columns", lambda: (screen._last_pack_columns or 0) + 1)

    screen._run_scheduled_regrid()

    assert reload_calls == [True]


def test_resize_event_schedules_a_debounced_regrid(qtbot, monkeypatch):
    stream = type("S", (), {
        "date": "2026-08-08", "start_time": "now", "id": "stream-1", "price_snapshot": [],
    })()

    monkeypatch.setattr(streams.stream_service, "resume_check", lambda db_name: stream)
    monkeypatch.setattr(streams.inventory_service, "get_streamer_inventory_view", lambda db_name: [])
    monkeypatch.setattr(streams.streamer_repo, "find_active_break", lambda db_name, sid: None)
    monkeypatch.setattr(streams.streamer_repo, "list_breaks_for_stream", lambda db_name, sid, **k: [])
    monkeypatch.setattr(streams.break_service, "get_availability", lambda s, b, db_name: {})
    monkeypatch.setattr(streams.product_service, "list_products", lambda: [])

    screen = streams.StreamsScreen(FakeUser())
    qtbot.addWidget(screen)

    scheduled = []
    monkeypatch.setattr(streams.QTimer, "singleShot", staticmethod(lambda ms, callback: scheduled.append(callback)))

    screen._schedule_responsive_regrid()
    screen._schedule_responsive_regrid()  # coalesced -- still just one pending call

    assert len(scheduled) == 1
    assert screen._regrid_pending is True
