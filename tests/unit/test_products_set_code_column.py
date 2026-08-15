"""
Regression test: Product.set_code has existed on the model (and been
populated from TCGCSV's group "abbreviation" field via the New Product
search flow) since Phase 3, but the Product Catalog table never actually
showed it -- an admin had to open Edit on a product to see its set code
at all. It's now a visible column.
"""

from datetime import date, datetime

from elysium.models.products import BOOSTER_TYPE_CLASSIC, Product
from elysium.ui import products


class FakeUser:
    id = "admin-1"


def make_product(id, name, set_name, set_code):
    return Product(
        id=id, name=name, booster_type=BOOSTER_TYPE_CLASSIC, packs_per_box=36,
        tcgcsv_category_id="1", tcgcsv_group_id="1", loose_pack_tcgcsv_product_id="1",
        box_tcgcsv_product_id="2", image_url="https://example.com/x.jpg",
        set_name=set_name, set_code=set_code, release_date=date(2026, 1, 1),
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
    )


def test_product_catalog_shows_set_code_column(qtbot, monkeypatch):
    monkeypatch.setattr(
        products.product_service, "list_products",
        lambda: [make_product("kld-booster", "Kaladesh Booster", "Kaladesh", "KLD")],
    )

    screen = products.ProductsScreen(FakeUser())
    qtbot.addWidget(screen)

    header_labels = [screen.table.horizontalHeaderItem(i).text() for i in range(screen.table.columnCount())]
    assert "Set Code" in header_labels

    set_code_column = header_labels.index("Set Code")
    assert screen.table.item(0, set_code_column).text() == "KLD"


def test_product_catalog_set_code_blank_when_none(qtbot, monkeypatch):
    monkeypatch.setattr(
        products.product_service, "list_products",
        lambda: [make_product("p2", "Some Booster", None, None)],
    )

    screen = products.ProductsScreen(FakeUser())
    qtbot.addWidget(screen)

    header_labels = [screen.table.horizontalHeaderItem(i).text() for i in range(screen.table.columnCount())]
    set_code_column = header_labels.index("Set Code")
    assert screen.table.item(0, set_code_column).text() == ""
