"""
Regression tests: Product Catalog, Audit History, Decommissioning,
Discrepancies, and Users now all support clicking a column header to sort
(previously only Prices/Master Inventory/My Inventory did) -- and each
screen's "selected X" lookup must resolve by a stable id stored on the row,
not by table-row position, so the right row is still selected after a sort
reorders the table.
"""

from datetime import datetime, timezone

from elysium.ui import audit, decommissioning, discrepancies, products, users


class FakeProduct:
    def __init__(self, id, name, booster_type="DRAFT", packs_per_box=36, is_active=True, set_name="", set_code=""):
        self.id = id
        self.name = name
        self.booster_type = booster_type
        self.packs_per_box = packs_per_box
        self.is_active = is_active
        self.set_name = set_name
        self.set_code = set_code


class FakeUserRecord:
    def __init__(self, id, username, roles=None, is_active=True, decommission_status=None, streamer_database_name=None):
        self.id = id
        self.username = username
        self.roles = roles or []
        self.is_active = is_active
        self.decommission_status = decommission_status
        self.streamer_database_name = streamer_database_name


class FakeCurrentUser:
    id = "admin-1"
    roles = ["admin"]


def test_products_screen_sorting_enabled_and_selection_survives_sort(qtbot, monkeypatch):
    monkeypatch.setattr(products.product_service, "list_products", lambda: [
        FakeProduct("zeta", "Zeta Booster"), FakeProduct("alpha", "Alpha Booster"),
    ])

    screen = products.ProductsScreen(FakeCurrentUser())
    qtbot.addWidget(screen)

    assert screen.table.isSortingEnabled()

    screen.table.sortItems(0)  # Name column, ascending
    assert screen.table.item(0, 0).text() == "Alpha Booster"

    screen.table.selectRow(0)
    selected = screen.selected_product()
    assert selected.id == "alpha"


def test_audit_screen_sorting_enabled_and_selection_survives_sort(qtbot, monkeypatch):
    events = [
        {"event_id": "e-zeta", "action_type": "ZZZ_ACTION", "timestamp": datetime(2026, 1, 2, tzinfo=timezone.utc)},
        {"event_id": "e-alpha", "action_type": "AAA_ACTION", "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc)},
    ]
    monkeypatch.setattr(audit.repo, "list_users", lambda: [])
    monkeypatch.setattr(audit.audit_service, "list_events", lambda **kwargs: events)

    screen = audit.AuditHistoryScreen(FakeCurrentUser())
    qtbot.addWidget(screen)

    assert screen.table.isSortingEnabled()

    screen.table.sortItems(1)  # action_type column, ascending
    assert screen.table.item(0, 1).text() == "AAA_ACTION"

    screen.table.selectRow(0)
    selected = screen.selected_event()
    assert selected["event_id"] == "e-alpha"


def test_decommissioning_screen_sorting_enabled_and_selection_survives_sort(qtbot, monkeypatch):
    class FakeRequest:
        def __init__(self, id, streamer_id, status="PENDING", initiated_by="admin-1", initiated_at="2026-01-01", notes=""):
            self.id = id
            self.streamer_id = streamer_id
            self.status = status
            self.initiated_by = initiated_by
            self.initiated_at = initiated_at
            self.notes = notes

    requests = [FakeRequest("r-zeta", "u-zeta"), FakeRequest("r-alpha", "u-alpha")]
    monkeypatch.setattr(decommissioning.repo, "list_users", lambda: [
        FakeUserRecord("u-zeta", "zeta_streamer"), FakeUserRecord("u-alpha", "alpha_streamer"),
    ])
    monkeypatch.setattr(decommissioning.decommission_service, "list_pending", lambda: requests)

    screen = decommissioning.DecommissioningScreen(FakeCurrentUser())
    qtbot.addWidget(screen)

    assert screen.table.isSortingEnabled()

    screen.table.sortItems(0)  # Streamer column, ascending
    assert screen.table.item(0, 0).text() == "alpha_streamer"

    screen.table.selectRow(0)
    selected = screen.selected_request()
    assert selected.id == "r-alpha"


def test_discrepancies_screen_sorting_enabled_and_selection_survives_sort(qtbot, monkeypatch):
    class FakeDiscrepancy:
        def __init__(self, id, streamer_id, product_id, type="NEGATIVE_INVENTORY", quantity=1, source="STREAM_CORRECTION", status="OPEN", resolution_note=None):
            self.id = id
            self.streamer_id = streamer_id
            self.product_id = product_id
            self.type = type
            self.quantity = quantity
            self.source = source
            self.status = status
            self.resolution_note = resolution_note

    discrepancy_rows = [FakeDiscrepancy("d-zeta", "u-zeta", "p1"), FakeDiscrepancy("d-alpha", "u-alpha", "p1")]
    monkeypatch.setattr(discrepancies.repo, "list_users", lambda: [
        FakeUserRecord("u-zeta", "zeta_streamer"), FakeUserRecord("u-alpha", "alpha_streamer"),
    ])
    monkeypatch.setattr(discrepancies.repo, "list_products", lambda: [FakeProduct("p1", "Some Booster")])
    monkeypatch.setattr(discrepancies.discrepancy_service, "list_discrepancies", lambda status=None: discrepancy_rows)

    screen = discrepancies.DiscrepanciesScreen(FakeCurrentUser())
    qtbot.addWidget(screen)

    assert screen.table.isSortingEnabled()

    screen.table.sortItems(0)  # Streamer column, ascending
    assert screen.table.item(0, 0).text() == "alpha_streamer"

    screen.table.selectRow(0)
    selected = screen.selected_discrepancy()
    assert selected.id == "d-alpha"


def test_users_screen_sorting_enabled_and_selection_survives_sort(qtbot, monkeypatch):
    monkeypatch.setattr(users.repo, "list_users", lambda: [
        FakeUserRecord("u-zeta", "zeta_user"), FakeUserRecord("u-alpha", "alpha_user"),
    ])

    screen = users.UsersScreen(FakeCurrentUser())
    qtbot.addWidget(screen)

    assert screen.table.isSortingEnabled()

    screen.table.sortItems(0)  # Username column, ascending
    assert screen.table.item(0, 0).text() == "alpha_user"

    screen.table.selectRow(0)
    user_id, username = screen.selected_user()
    assert user_id == "u-alpha"
    assert username == "alpha_user"
