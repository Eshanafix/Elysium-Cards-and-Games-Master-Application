"""
Regression test: creating a product used to require a separate manual
click on Shared Sealed Prices to get an actual price -- it now kicks off
a background refresh automatically.
"""

from PySide6.QtCore import QThread, Signal

from elysium.ui import products


class FakeUser:
    id = "admin-1"


class FakeWorker(QThread):
    finished_success = Signal(str)
    failed = Signal(str)

    def __init__(self, started_by):
        super().__init__()
        self.started_by = started_by

    def run(self):
        pass


def make_screen(qtbot, monkeypatch):
    monkeypatch.setattr(products.product_service, "list_products", lambda: [])
    screen = products.ProductsScreen(FakeUser())
    qtbot.addWidget(screen)
    return screen


def test_auto_refresh_shows_refreshing_message_immediately(qtbot, monkeypatch):
    monkeypatch.setattr(products, "PriceRefreshWorker", FakeWorker)
    monkeypatch.setattr(products, "run_worker", lambda worker: None)  # don't actually start the thread
    screen = make_screen(qtbot, monkeypatch)

    screen._auto_refresh_prices_after_create("Kaladesh Booster")

    assert "Kaladesh Booster" in screen.message_label.text()
    assert "Refreshing prices" in screen.message_label.text()


def test_auto_refresh_success_updates_message(qtbot, monkeypatch):
    monkeypatch.setattr(products, "PriceRefreshWorker", FakeWorker)
    monkeypatch.setattr(products, "run_worker", lambda worker: None)
    screen = make_screen(qtbot, monkeypatch)

    screen._auto_refresh_prices_after_create("Kaladesh Booster")
    screen._price_refresh_worker.finished_success.emit("session-1")

    assert "prices refreshed" in screen.message_label.text()
    assert "Kaladesh Booster" in screen.message_label.text()


def test_auto_refresh_failure_shows_error_but_mentions_product_created(qtbot, monkeypatch):
    monkeypatch.setattr(products, "PriceRefreshWorker", FakeWorker)
    monkeypatch.setattr(products, "run_worker", lambda worker: None)
    screen = make_screen(qtbot, monkeypatch)

    screen._auto_refresh_prices_after_create("Kaladesh Booster")
    screen._price_refresh_worker.failed.emit("a stream is active")

    text = screen.message_label.text()
    assert "Kaladesh Booster" in text
    assert "created" in text
    assert "a stream is active" in text


def test_open_create_dialog_triggers_auto_refresh_on_success(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    monkeypatch.setattr(products, "PriceRefreshWorker", FakeWorker)
    monkeypatch.setattr(products, "run_worker", lambda worker: None)
    screen = make_screen(qtbot, monkeypatch)

    fake_product = type("P", (), {"id": "kld-booster"})()
    monkeypatch.setattr(products.product_service, "create_product", lambda created_by, **values: fake_product)

    called = {}
    monkeypatch.setattr(screen, "_auto_refresh_prices_after_create", lambda name: called.setdefault("name", name))

    class FakeDialog:
        def __init__(self, parent):
            pass

        def exec(self):
            return QDialog.Accepted

        def field_values(self):
            return {
                "name": "Kaladesh Booster", "set_name": "Kaladesh", "set_code": "KLD",
                "booster_type": "CLASSIC", "packs_per_box": 36,
                "tcgcsv_category_id": "1", "tcgcsv_group_id": "1791",
                "loose_pack_tcgcsv_product_id": "121529", "box_tcgcsv_product_id": "121530",
                "image_url": "https://example.com/x.jpg", "english_confirmed": True,
            }

    monkeypatch.setattr(products, "ProductDialog", FakeDialog)

    screen.open_create_dialog()

    assert called["name"] == "Kaladesh Booster"
