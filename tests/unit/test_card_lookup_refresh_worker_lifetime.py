"""
Regression test: Card Lookup's "Refresh Card Data" worker previously called
ScryfallRefreshWorker().start() directly, with the only reference to the
QThread held as a plain instance attribute -- the exact pattern
elysium.ui.background documents as the confirmed cause of a Qt6Core.dll
access-violation crash (worker garbage-collected mid-thread if the screen
that launched it gets torn down first). Every other screen's background
worker was migrated to run_worker()/safe_callback() to fix that; Card
Lookup's refresh worker was missed. This locks in that it now goes through
the same protected path.
"""

from unittest.mock import MagicMock

import pytest

from elysium.ui import card_lookup


@pytest.fixture
def tab(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(card_lookup.db, "get_set_options", lambda db_path: [])
    monkeypatch.setattr(card_lookup.db, "get_last_successful_refresh_at", lambda db_path: None)
    monkeypatch.setattr(card_lookup.db, "search_cards", lambda *a, **k: ([], 0))
    monkeypatch.setattr(card_lookup.paths, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(card_lookup.paths, "get_db_path", lambda: tmp_path / "cards.sqlite")

    widget = card_lookup.CardLookupTab()
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_refresh_card_data_uses_run_worker_instead_of_bare_start(tab, monkeypatch):
    captured = {}
    monkeypatch.setattr(card_lookup, "run_worker", lambda worker: captured.setdefault("worker", worker))

    class FakeWorker:
        def __init__(self):
            self.progress = MagicMock()
            self.status = MagicMock()
            self.finished_success = MagicMock()
            self.failed = MagicMock()
            self.start = MagicMock()

    monkeypatch.setattr(card_lookup, "ScryfallRefreshWorker", FakeWorker)

    tab.refresh_card_data()

    assert captured.get("worker") is tab.refresh_worker
    # start() must never be called directly -- run_worker() owns that, so
    # the worker is tracked (background._active_workers) before it starts.
    tab.refresh_worker.start.assert_not_called()


def test_refresh_card_data_wraps_callbacks_in_safe_callback(tab, monkeypatch):
    class FakeWorker:
        def __init__(self):
            self.progress = MagicMock()
            self.status = MagicMock()
            self.finished_success = MagicMock()
            self.failed = MagicMock()

    monkeypatch.setattr(card_lookup, "ScryfallRefreshWorker", FakeWorker)
    monkeypatch.setattr(card_lookup, "run_worker", lambda worker: None)

    tab.refresh_card_data()

    for signal in (
        tab.refresh_worker.progress, tab.refresh_worker.status,
        tab.refresh_worker.finished_success, tab.refresh_worker.failed,
    ):
        signal.connect.assert_called_once()
        connected_fn = signal.connect.call_args[0][0]
        # safe_callback()-wrapped callables are closures named "wrapped".
        assert connected_fn.__name__ == "wrapped"
