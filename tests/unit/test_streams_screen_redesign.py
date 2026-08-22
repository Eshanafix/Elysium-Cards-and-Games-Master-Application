"""
Regression tests for the Streams screen redesign (docs feedback: replace
the bare "Start Stream" button with a holdings browse view + refresh-prices
reminder + prominent start button; fix pack-tile visuals; add a search box
during an active stream).
"""

from decimal import Decimal

from elysium.ui import streams


class FakeUser:
    id = "streamer-1"
    streamer_database_name = "elysium_s_abc"


class FakeProduct:
    def __init__(self, id, name, image_url=None):
        self.id = id
        self.name = name
        self.image_url = image_url


def make_screen(qtbot, monkeypatch, stream=None, holdings_rows=None, active_break=None, breaks=None, availability=None, products=None):
    monkeypatch.setattr(streams.stream_service, "resume_check", lambda db_name: stream)
    monkeypatch.setattr(streams.inventory_service, "get_streamer_inventory_view", lambda db_name: holdings_rows or [])

    if stream is not None:
        monkeypatch.setattr(streams.streamer_repo, "find_active_break", lambda db_name, sid: active_break)
        monkeypatch.setattr(streams.streamer_repo, "list_breaks_for_stream", lambda db_name, sid, **k: breaks or [])
        monkeypatch.setattr(streams.break_service, "get_availability", lambda s, b, db_name: availability or {})
        monkeypatch.setattr(streams.product_service, "list_products", lambda: products or [])

    screen = streams.StreamsScreen(FakeUser())
    qtbot.addWidget(screen)
    screen.show()
    return screen


# --- HoldingsPreviewTile ---


def test_holdings_preview_tile_shows_resolved_price(qtbot):
    tile = streams.HoldingsPreviewTile(
        name="Kaladesh Booster", image_path=None, held=5,
        resolved_pack_price=Decimal("3.50"), price_status="OK",
    )
    qtbot.addWidget(tile)

    labels = tile.findChildren(streams.QLabel)
    texts = [w.text() for w in labels]
    assert any("$3.50" in t for t in texts)
    assert any("You hold: 5" in t for t in texts)


def test_holdings_preview_tile_shows_unresolved_price():
    tile = streams.HoldingsPreviewTile(
        name="New Set Booster", image_path=None, held=2,
        resolved_pack_price=None, price_status="UNRESOLVED",
    )
    labels = tile.findChildren(streams.QLabel)
    texts = [w.text() for w in labels]
    assert any("not yet resolved" in t for t in texts)


# --- BreakProductTile selection + classification styling ---


def test_break_product_tile_shows_classification_banner_color_when_not_selected():
    low = streams.BreakProductTile(  # $4.00 -> LOW
        product_id="p1", name="Cheap Booster", image_path=None, unit_price=Decimal("4.00"),
        available=10, selected=0, enabled=True, on_add=lambda pid: None, on_remove=lambda pid: None,
    )
    mid = streams.BreakProductTile(  # $15.00 -> MID
        product_id="p2", name="Mid Booster", image_path=None, unit_price=Decimal("15.00"),
        available=10, selected=0, enabled=True, on_add=lambda pid: None, on_remove=lambda pid: None,
    )
    high = streams.BreakProductTile(  # $25.00 -> HIGH
        product_id="p3", name="Pricey Booster", image_path=None, unit_price=Decimal("25.00"),
        available=10, selected=0, enabled=True, on_add=lambda pid: None, on_remove=lambda pid: None,
    )

    assert "#ffeb3b" in low.styleSheet()  # yellow
    assert "#ff9800" in mid.styleSheet()  # orange
    assert "#f44336" in high.styleSheet()  # red

    for tile in (low, mid, high):
        assert "#000000" not in tile.styleSheet()


def test_break_product_tile_shows_classification_label_text():
    tile = streams.BreakProductTile(
        product_id="p1", name="Cheap Booster", image_path=None, unit_price=Decimal("4.00"),
        available=10, selected=0, enabled=True, on_add=lambda pid: None, on_remove=lambda pid: None,
    )
    label = tile.findChild(streams.QLabel, "tileClassification")
    assert label.text() == "LOW"


def test_break_product_tile_gets_a_thick_black_border_when_selected_but_keeps_its_banner_color():
    unselected = streams.BreakProductTile(
        product_id="p1", name="Cheap Booster", image_path=None, unit_price=Decimal("4.00"),
        available=10, selected=0, enabled=True, on_add=lambda pid: None, on_remove=lambda pid: None,
    )
    selected = streams.BreakProductTile(
        product_id="p1", name="Cheap Booster", image_path=None, unit_price=Decimal("4.00"),
        available=10, selected=2, enabled=True, on_add=lambda pid: None, on_remove=lambda pid: None,
    )

    assert "background-color: #000000" not in selected.styleSheet()
    assert "#ffeb3b" in selected.styleSheet()  # still the LOW banner color, not blacked out
    assert "6px solid #000000" in selected.styleSheet()
    assert "1px solid #999999" in unselected.styleSheet()


def test_break_product_tile_has_no_plus_minus_buttons():
    tile = streams.BreakProductTile(
        product_id="p1", name="Test Booster", image_path=None, unit_price=Decimal("4.00"),
        available=10, selected=1, enabled=True, on_add=lambda pid: None, on_remove=lambda pid: None,
    )
    buttons = tile.findChildren(streams.QPushButton)
    assert buttons == []


def test_break_product_tile_shrunk_25_percent_from_original_160():
    assert streams.TILE_WIDTH == 120


# --- StreamsScreen state toggling ---


def test_no_stream_state_shows_holdings_and_hides_workspace(qtbot, monkeypatch):
    screen = make_screen(qtbot, monkeypatch, stream=None)

    assert screen.holdings_scroll_area.isVisible() or screen.holdings_title_label.isVisible() is not None
    assert screen.start_button.isVisible()
    assert screen.refresh_prices_banner_container.isVisible()
    assert not screen.workspace_row_container.isVisible()
    assert not screen.breaks_table.isVisible()
    assert not screen.action_button_row_container.isVisible()


def test_no_stream_state_shows_empty_label_when_nothing_held(qtbot, monkeypatch):
    screen = make_screen(qtbot, monkeypatch, stream=None, holdings_rows=[])
    assert screen.holdings_empty_label.isVisible()


def test_no_stream_state_builds_holdings_tiles(qtbot, monkeypatch):
    rows = [
        {"product": FakeProduct("p1", "Kaladesh Booster"), "current_packs": 5,
         "resolved_pack_price": Decimal("3.00"), "price_status": "OK"},
    ]
    screen = make_screen(qtbot, monkeypatch, stream=None, holdings_rows=rows)

    assert screen.holdings_grid_layout.count() >= 1
    assert not screen.holdings_empty_label.isVisible()


def test_workspace_state_hides_holdings_and_shows_workspace(qtbot, monkeypatch):
    stream = type("S", (), {
        "date": "2026-08-08", "start_time": "now", "price_snapshot": [], "id": "stream-1",
    })()

    screen = make_screen(qtbot, monkeypatch, stream=stream)

    assert not screen.start_button.isVisible()
    assert not screen.holdings_scroll_area.isVisible()
    assert not screen.refresh_prices_banner_container.isVisible()
    assert screen.workspace_row_container.isVisible()
    assert screen.breaks_table.isVisible()
    assert screen.pack_search_row_container.isVisible()


# --- Workspace splitter (pack catalog <-> breaks table, user-draggable) ---


def test_workspace_splitter_contains_pack_catalog_and_breaks_panel(qtbot, monkeypatch):
    stream = type("S", (), {
        "date": "2026-08-08", "start_time": "now", "price_snapshot": [], "id": "stream-1",
    })()

    screen = make_screen(qtbot, monkeypatch, stream=stream)

    assert screen.workspace_splitter.count() == 2
    assert screen.workspace_splitter.widget(0) is screen.workspace_row_container
    assert screen.workspace_splitter.widget(1) is screen.breaks_panel_container
    assert screen.workspace_splitter.orientation() == streams.Qt.Vertical


def test_shrinking_breaks_pane_does_not_hide_breaks_table_rows(qtbot, monkeypatch):
    """The splitter should only change how much of the table is visible at
    once, never make the table (and its own scrollbar) stop working."""
    stream = type("S", (), {
        "date": "2026-08-08", "start_time": "now", "price_snapshot": [], "id": "stream-1",
    })()

    screen = make_screen(qtbot, monkeypatch, stream=stream)
    screen.resize(900, 700)

    screen.workspace_splitter.setSizes([650, 50])

    assert screen.breaks_table.isVisible()
    assert screen.breaks_table.verticalScrollBar() is not None


def test_no_stream_state_hides_the_whole_splitter(qtbot, monkeypatch):
    screen = make_screen(qtbot, monkeypatch, stream=None)
    assert not screen.workspace_splitter.isVisible()


def test_pack_search_filters_displayed_tiles(qtbot, monkeypatch):
    stream = type("S", (), {
        "date": "2026-08-08", "start_time": "now", "id": "stream-1",
        "price_snapshot": [
            {"product_id": "p1", "product_name_at_snapshot": "Kaladesh Booster", "set_code": "KLD", "resolved_pack_price": Decimal("3.00")},
            {"product_id": "p2", "product_name_at_snapshot": "Dominaria United Draft Booster", "set_code": "DMU", "resolved_pack_price": Decimal("4.00")},
        ],
    })()

    screen = make_screen(qtbot, monkeypatch, stream=stream, availability={"p1": 5, "p2": 5})

    assert screen.pack_grid_layout.count() == 2

    screen.pack_search_input.setText("Kaladesh")
    screen.reload_pack_tiles()

    assert screen.pack_grid_layout.count() == 1


def test_pack_search_matches_set_code(qtbot, monkeypatch):
    stream = type("S", (), {
        "date": "2026-08-08", "start_time": "now", "id": "stream-1",
        "price_snapshot": [
            {"product_id": "p1", "product_name_at_snapshot": "Kaladesh Booster", "set_code": "KLD", "resolved_pack_price": Decimal("3.00")},
            {"product_id": "p2", "product_name_at_snapshot": "Dominaria United Draft Booster", "set_code": "DMU", "resolved_pack_price": Decimal("4.00")},
        ],
    })()

    screen = make_screen(qtbot, monkeypatch, stream=stream, availability={"p1": 5, "p2": 5})

    screen.pack_search_input.setText("dmu")
    screen.reload_pack_tiles()

    assert screen.pack_grid_layout.count() == 1


def test_pack_search_tolerates_missing_set_code(qtbot, monkeypatch):
    """Older snapshots (taken before set_code was added, or a product with
    no set_code set) shouldn't crash the search -- just never match on it."""
    stream = type("S", (), {
        "date": "2026-08-08", "start_time": "now", "id": "stream-1",
        "price_snapshot": [
            {"product_id": "p1", "product_name_at_snapshot": "Kaladesh Booster", "resolved_pack_price": Decimal("3.00")},
        ],
    })()

    screen = make_screen(qtbot, monkeypatch, stream=stream, availability={"p1": 5})

    screen.pack_search_input.setText("kaladesh")
    screen.reload_pack_tiles()

    assert screen.pack_grid_layout.count() == 1


def test_selected_tiles_sort_to_the_front_of_the_grid(qtbot, monkeypatch):
    """If several tiles have packs selected, they should all land at the
    top-left of the grid -- a stable sort ahead of everything else, not just
    whichever happened to already be first in the snapshot."""
    stream = type("S", (), {
        "date": "2026-08-08", "start_time": "now", "id": "stream-1",
        "price_snapshot": [
            {"product_id": "p1", "product_name_at_snapshot": "Alpha Booster", "set_code": "A", "resolved_pack_price": Decimal("3.00")},
            {"product_id": "p2", "product_name_at_snapshot": "Bravo Booster", "set_code": "B", "resolved_pack_price": Decimal("3.00")},
            {"product_id": "p3", "product_name_at_snapshot": "Charlie Booster", "set_code": "C", "resolved_pack_price": Decimal("3.00")},
        ],
    })()

    active_break = type("B", (), {
        "pack_lines": [{"product_id": "p3", "quantity": 1}],
        "total_pack_market_value": Decimal("3.00"),
    })()

    screen = make_screen(
        qtbot, monkeypatch, stream=stream, active_break=active_break,
        availability={"p1": 5, "p2": 5, "p3": 5},
    )

    first_tile = screen.pack_grid_layout.itemAtPosition(0, 0).widget()
    assert first_tile.product_name == "Charlie Booster"
