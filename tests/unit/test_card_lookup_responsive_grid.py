"""
Regression tests: Card Lookup's grid used to compute its column count once,
at construction time, before the widget had real layout geometry (both the
guest-mode and logged-in-mode copies are built before the main window is
ever shown) -- it started at ~2 columns and only self-corrected on a manual
window resize. It now rebuilds once the widget is actually shown, and
debounces/coalesces resize-triggered rebuilds instead of doing one per pixel
of a live window drag.
"""

from elysium.ui import card_lookup


def make_tab(qtbot, monkeypatch):
    monkeypatch.setattr(card_lookup.db, "get_set_options", lambda db_path: [])
    monkeypatch.setattr(card_lookup.db, "get_last_successful_refresh_at", lambda db_path: None)
    monkeypatch.setattr(card_lookup.db, "search_cards", lambda *a, **k: ([], 0))
    monkeypatch.setattr(card_lookup.paths, "ensure_app_dirs", lambda: None)

    tab = card_lookup.CardLookupTab()
    qtbot.addWidget(tab)
    return tab


def test_only_one_refresh_button_exists(qtbot, monkeypatch):
    tab = make_tab(qtbot, monkeypatch)
    assert not hasattr(tab, "stale_refresh_button")


def test_show_event_rebuilds_when_column_count_changed(qtbot, monkeypatch):
    tab = make_tab(qtbot, monkeypatch)

    tab._last_grid_columns = 2
    monkeypatch.setattr(tab, "_compute_grid_columns", lambda: 6)
    rebuild_calls = []
    monkeypatch.setattr(tab, "rebuild_grid", lambda: rebuild_calls.append(True))

    tab.show()

    assert rebuild_calls == [True]


def test_show_event_skips_rebuild_when_column_count_unchanged(qtbot, monkeypatch):
    tab = make_tab(qtbot, monkeypatch)

    tab._last_grid_columns = 6
    monkeypatch.setattr(tab, "_compute_grid_columns", lambda: 6)
    rebuild_calls = []
    monkeypatch.setattr(tab, "rebuild_grid", lambda: rebuild_calls.append(True))

    tab.show()

    assert rebuild_calls == []


def test_resize_event_coalesces_into_one_debounced_call(qtbot, monkeypatch):
    tab = make_tab(qtbot, monkeypatch)

    scheduled = []
    monkeypatch.setattr(card_lookup.QTimer, "singleShot", staticmethod(lambda ms, callback: scheduled.append(callback)))

    tab.resizeEvent(None)
    tab.resizeEvent(None)

    assert len(scheduled) == 1
    assert tab._regrid_pending is True


def test_scheduled_regrid_rebuilds_only_when_columns_changed(qtbot, monkeypatch):
    tab = make_tab(qtbot, monkeypatch)
    tab._last_grid_columns = 4

    monkeypatch.setattr(tab, "_compute_grid_columns", lambda: 4)
    rebuild_calls = []
    monkeypatch.setattr(tab, "rebuild_grid", lambda: rebuild_calls.append(True))

    tab._regrid_pending = True
    tab._run_scheduled_regrid()

    assert rebuild_calls == []
    assert tab._regrid_pending is False
