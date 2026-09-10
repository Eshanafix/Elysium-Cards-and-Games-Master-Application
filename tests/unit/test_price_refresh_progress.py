"""
Regression tests: the price-refresh progress bar used to be indeterminate
(range (0, 0), just a spinning bar with no sense of how long it'll take --
docs feedback: "add a progress bar so we know how long refresh will take").
It's now determinate -- total product count is known upfront, and the
refresh session document's products_checked counter (incremented once per
product by pricing_service._resolve_and_store_product_price) is polled via
a QTimer to drive the bar's value while the worker thread runs.

The worker itself (PriceRefreshWorker) is swapped for a no-op QThread
subclass in every test here -- these tests are about the progress-bar
setup/polling/teardown around the worker, not about pricing_service or
Mongo, so nothing here ever starts a real refresh.
"""

from PySide6.QtCore import QThread, Signal

from elysium.ui import prices, streams


class FakeUser:
    id = "admin-1"
    streamer_database_name = "elysium_s_abc"


class FakeProduct:
    def __init__(self, id, name):
        self.id = id
        self.name = name


class DummyRefreshWorker(QThread):
    finished_success = Signal(str)
    failed = Signal(str)

    def __init__(self, started_by: str):
        super().__init__()
        self.started_by = started_by

    def run(self):
        pass  # tests drive the finished/failed callbacks directly


def _no_lock_active():
    return {"price_refresh_active": False, "refresh_session_id": None}


# --- PricesScreen ---


def make_prices_screen(qtbot, monkeypatch, product_count=3):
    monkeypatch.setattr(prices.product_service, "list_products", lambda: [
        FakeProduct(f"p{i}", f"Product {i}") for i in range(product_count)
    ])
    monkeypatch.setattr(prices.price_repo, "list_all_current_prices", lambda: {})
    monkeypatch.setattr(prices, "PriceRefreshWorker", DummyRefreshWorker)

    screen = prices.PricesScreen(FakeUser())
    qtbot.addWidget(screen)
    return screen


def test_start_refresh_sets_a_determinate_progress_bar(qtbot, monkeypatch):
    screen = make_prices_screen(qtbot, monkeypatch, product_count=5)

    screen.start_refresh()

    assert screen.progress_bar.maximum() == 5
    assert screen.progress_bar.value() == 0
    assert screen.progress_bar.isVisibleTo(screen)
    assert screen.progress_bar.minimum() != screen.progress_bar.maximum()  # not the old (0, 0) spinner
    assert screen._progress_timer.isActive()


def test_poll_refresh_progress_updates_bar_from_session_counter(qtbot, monkeypatch):
    screen = make_prices_screen(qtbot, monkeypatch, product_count=10)
    screen.start_refresh()

    monkeypatch.setattr(prices.lock_service, "get_lock_state", lambda: {
        "price_refresh_active": True, "refresh_session_id": "sess-1",
    })
    monkeypatch.setattr(prices.price_repo, "find_refresh_session", lambda sid: {"products_checked": 4})

    screen._poll_refresh_progress()

    assert screen.progress_bar.value() == 4
    assert "4 / 10" in screen.summary_label.text()


def test_poll_refresh_progress_waits_for_lock_before_a_session_id_exists(qtbot, monkeypatch):
    """The refresh session document doesn't exist until the worker thread
    has actually acquired the lock -- polling before that must not crash
    or show a bogus value."""
    screen = make_prices_screen(qtbot, monkeypatch, product_count=10)
    screen.start_refresh()

    monkeypatch.setattr(prices.lock_service, "get_lock_state", _no_lock_active)

    screen._poll_refresh_progress()  # must not raise

    assert screen.progress_bar.value() == 0


def test_refresh_finished_stops_polling_and_hides_the_bar(qtbot, monkeypatch):
    screen = make_prices_screen(qtbot, monkeypatch, product_count=5)
    screen.start_refresh()
    monkeypatch.setattr(prices.price_repo, "find_refresh_session", lambda sid: None)

    screen.on_refresh_finished("sess-1")

    assert not screen._progress_timer.isActive()
    assert not screen.progress_bar.isVisibleTo(screen)
    assert screen.progress_bar.value() == screen.progress_bar.maximum()


def test_refresh_failed_stops_polling_and_hides_the_bar(qtbot, monkeypatch):
    screen = make_prices_screen(qtbot, monkeypatch, product_count=5)
    screen.start_refresh()

    screen.on_refresh_failed("boom")

    assert not screen._progress_timer.isActive()
    assert not screen.progress_bar.isVisibleTo(screen)


# --- StreamsScreen pre-stream "Refresh Prices Now" banner ---


def make_no_stream_screen(qtbot, monkeypatch, product_count=3):
    monkeypatch.setattr(streams.stream_service, "resume_check", lambda db_name: None)
    monkeypatch.setattr(streams.inventory_service, "get_streamer_inventory_view", lambda db_name: [])
    monkeypatch.setattr(streams.product_service, "list_products", lambda: [
        FakeProduct(f"p{i}", f"Product {i}") for i in range(product_count)
    ])
    monkeypatch.setattr(streams, "PriceRefreshWorker", DummyRefreshWorker)

    screen = streams.StreamsScreen(FakeUser())
    qtbot.addWidget(screen)
    return screen


def test_pre_stream_refresh_sets_a_determinate_progress_bar(qtbot, monkeypatch):
    screen = make_no_stream_screen(qtbot, monkeypatch, product_count=7)

    screen.refresh_prices_before_stream()

    assert screen.refresh_prices_progress_bar.maximum() == 7
    assert screen.refresh_prices_progress_bar.value() == 0
    assert screen.refresh_prices_progress_bar.isVisibleTo(screen)
    assert screen._pre_stream_progress_timer.isActive()


def test_pre_stream_refresh_poll_updates_bar_from_session_counter(qtbot, monkeypatch):
    screen = make_no_stream_screen(qtbot, monkeypatch, product_count=20)
    screen.refresh_prices_before_stream()

    monkeypatch.setattr(streams.lock_service, "get_lock_state", lambda: {
        "price_refresh_active": True, "refresh_session_id": "sess-2",
    })
    monkeypatch.setattr(streams.price_repo, "find_refresh_session", lambda sid: {"products_checked": 12})

    screen._poll_pre_stream_refresh_progress()

    assert screen.refresh_prices_progress_bar.value() == 12


def test_pre_stream_refresh_finished_stops_polling_and_hides_the_bar(qtbot, monkeypatch):
    screen = make_no_stream_screen(qtbot, monkeypatch, product_count=7)
    screen.refresh_prices_before_stream()

    screen._on_pre_stream_refresh_finished("sess-2")

    assert not screen._pre_stream_progress_timer.isActive()
    assert not screen.refresh_prices_progress_bar.isVisibleTo(screen)


def test_pre_stream_refresh_failed_stops_polling_and_hides_the_bar(qtbot, monkeypatch):
    screen = make_no_stream_screen(qtbot, monkeypatch, product_count=7)
    screen.refresh_prices_before_stream()

    screen._on_pre_stream_refresh_failed("boom")

    assert not screen._pre_stream_progress_timer.isActive()
    assert not screen.refresh_prices_progress_bar.isVisibleTo(screen)
