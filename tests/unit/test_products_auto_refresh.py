"""
Regression test: creating a product used to kick off a background,
full-catalog price refresh automatically. That was removed after a
crash-dump-confirmed native Qt crash (STATUS_STACK_BUFFER_OVERRUN) while
rapidly adding sets -- each add started its own PriceRefreshWorker QThread,
and since a refresh isn't scoped to the new product (it refetches every
set from TCGCSV), adding several products in a row piled up overlapping
background refreshes under heavy native dialog churn. Creating a product
now only ever writes to the catalog; refreshing prices is a separate,
manual action on Shared Sealed Prices.
"""

from PySide6.QtWidgets import QDialog

from elysium.ui import products


class FakeUser:
    id = "admin-1"


def make_screen(qtbot, monkeypatch):
    monkeypatch.setattr(products.product_service, "list_products", lambda: [])
    screen = products.ProductsScreen(FakeUser())
    qtbot.addWidget(screen)
    return screen


def test_open_create_dialog_does_not_start_a_price_refresh(qtbot, monkeypatch):
    screen = make_screen(qtbot, monkeypatch)

    fake_product = type("P", (), {"id": "kld-booster"})()
    monkeypatch.setattr(products.product_service, "create_product", lambda created_by, **values: fake_product)

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

    assert not hasattr(screen, "_auto_refresh_prices_after_create")

    screen.open_create_dialog()

    text = screen.message_label.text()
    assert "Kaladesh Booster" in text
    assert "created" in text
    assert "Refresh prices from Shared Sealed Prices" in text
    assert not hasattr(screen, "_price_refresh_worker")


def test_adding_several_products_in_a_row_never_touches_price_refresh(qtbot, monkeypatch):
    """The actual crash scenario: adding many products back-to-back used to
    fire overlapping background PriceRefreshWorker threads. Confirm none of
    that machinery is reachable from the create path anymore."""
    screen = make_screen(qtbot, monkeypatch)

    products_created = []
    monkeypatch.setattr(
        products.product_service, "create_product",
        lambda created_by, **values: products_created.append(values["name"]) or type("P", (), {"id": values["name"]})(),
    )

    class FakeDialog:
        def __init__(self, parent):
            pass

        def exec(self):
            return QDialog.Accepted

        def field_values(self):
            return {
                "name": f"Set {len(products_created)} Booster", "set_name": "Set", "set_code": "SET",
                "booster_type": "CLASSIC", "packs_per_box": 36,
                "tcgcsv_category_id": "1", "tcgcsv_group_id": "1791",
                "loose_pack_tcgcsv_product_id": "1", "box_tcgcsv_product_id": "2",
                "image_url": "", "english_confirmed": True,
            }

    monkeypatch.setattr(products, "ProductDialog", FakeDialog)

    for _ in range(15):
        screen.open_create_dialog()

    assert len(products_created) == 15
    assert not hasattr(screen, "_price_refresh_worker")
