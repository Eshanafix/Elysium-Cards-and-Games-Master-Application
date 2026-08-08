"""
Regression test: rapid pack +/- actions must coalesce into a single
deferred tile-grid rebuild rather than scheduling one QTimer.singleShot(0,
...) per action. Reported crash: typing in the slot tracker, clicking away
to another window (OBS/Discord), then clicking back into the app several
times to regain focus -- overlapping rebuilds destroying/replacing tile
widgets while a stray queued click event still targeted one of them is
what actually crashed the app mid-stream, not any single click.
"""

from decimal import Decimal

from elysium.ui import streams


class FakeUser:
    id = "streamer-1"
    streamer_database_name = "elysium_s_abc"


class FakeBreak:
    def __init__(self):
        self.pack_lines: list = []

    def quantity_for_product(self, product_id):
        line = next((l for l in self.pack_lines if l["product_id"] == product_id), None)
        return line["quantity"] if line else 0

    @property
    def total_pack_market_value(self):
        return Decimal("0")


def make_active_stream_screen(qtbot, monkeypatch):
    stream = type("S", (), {
        "date": "2026-08-08", "start_time": "now", "id": "stream-1", "price_snapshot": [],
    })()
    active_break = FakeBreak()

    monkeypatch.setattr(streams.stream_service, "resume_check", lambda db_name: stream)
    monkeypatch.setattr(streams.inventory_service, "get_streamer_inventory_view", lambda db_name: [])
    monkeypatch.setattr(streams.streamer_repo, "find_active_break", lambda db_name, sid: active_break)
    monkeypatch.setattr(streams.streamer_repo, "list_breaks_for_stream", lambda db_name, sid, **k: [])
    monkeypatch.setattr(streams.break_service, "get_availability", lambda s, b, db_name: {})
    monkeypatch.setattr(streams.product_service, "list_products", lambda: [])
    monkeypatch.setattr(streams.break_service, "set_break_pack_line_quantity", lambda *a, **k: active_break)

    screen = streams.StreamsScreen(FakeUser())
    qtbot.addWidget(screen)
    screen.active_break = active_break
    return screen


def test_rapid_pack_changes_coalesce_into_one_scheduled_reload(qtbot, monkeypatch):
    screen = make_active_stream_screen(qtbot, monkeypatch)

    scheduled = []
    monkeypatch.setattr(streams.QTimer, "singleShot", staticmethod(lambda ms, callback: scheduled.append(callback)))

    screen.on_add_pack("p1")
    screen.on_add_pack("p1")
    screen.on_remove_pack("p1")

    assert len(scheduled) == 1


def test_scheduled_reload_clears_pending_flag_and_rebuilds(qtbot, monkeypatch):
    screen = make_active_stream_screen(qtbot, monkeypatch)

    callbacks = []
    monkeypatch.setattr(streams.QTimer, "singleShot", staticmethod(lambda ms, callback: callbacks.append(callback)))

    reload_calls = []
    monkeypatch.setattr(screen, "reload_pack_tiles", lambda: reload_calls.append(True))

    screen.on_add_pack("p1")
    assert screen._pack_tile_reload_pending is True

    callbacks[0]()

    assert screen._pack_tile_reload_pending is False
    assert reload_calls == [True]


def test_next_click_after_reload_runs_schedules_a_new_reload(qtbot, monkeypatch):
    screen = make_active_stream_screen(qtbot, monkeypatch)

    scheduled = []
    monkeypatch.setattr(streams.QTimer, "singleShot", staticmethod(lambda ms, callback: scheduled.append(callback)))
    monkeypatch.setattr(screen, "reload_pack_tiles", lambda: None)

    screen.on_add_pack("p1")
    scheduled[0]()
    screen.on_add_pack("p1")

    assert len(scheduled) == 2
