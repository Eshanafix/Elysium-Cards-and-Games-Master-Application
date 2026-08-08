from decimal import Decimal

from elysium.services.pricing_service import group_rows_by_product_id, resolve_single_mapping


def row(product_id=1, market_price=None, sub_type="Normal"):
    return {"productId": product_id, "marketPrice": market_price, "subTypeName": sub_type}


def test_no_rows_is_absent_not_ambiguous():
    price, ambiguous = resolve_single_mapping([])
    assert price is None
    assert ambiguous is False


def test_single_row_resolves_cleanly():
    price, ambiguous = resolve_single_mapping([row(market_price=5.6)])
    assert price == Decimal("5.6")
    assert ambiguous is False


def test_single_row_with_null_market_price_is_absent():
    price, ambiguous = resolve_single_mapping([row(market_price=None)])
    assert price is None
    assert ambiguous is False


def test_normal_and_foil_prefers_normal():
    rows = [row(market_price=1.73, sub_type="Foil"), row(market_price=5.6, sub_type="Normal")]
    price, ambiguous = resolve_single_mapping(rows)
    assert price == Decimal("5.6")
    assert ambiguous is False


def test_two_normal_rows_is_ambiguous():
    rows = [row(market_price=5.6, sub_type="Normal"), row(market_price=6.1, sub_type="Normal")]
    price, ambiguous = resolve_single_mapping(rows)
    assert price is None
    assert ambiguous is True


def test_two_non_normal_rows_with_no_preferred_match_is_ambiguous():
    rows = [row(market_price=5.6, sub_type="1st Edition"), row(market_price=6.1, sub_type="Unlimited")]
    price, ambiguous = resolve_single_mapping(rows)
    assert price is None
    assert ambiguous is True


def test_decimal_conversion_avoids_binary_float_artifacts():
    # str(0.1 + 0.2) == '0.30000000000000004' if constructed via float directly;
    # going through str() first (as resolve_single_mapping does) avoids that.
    price, _ = resolve_single_mapping([row(market_price=5.6)])
    assert str(price) == "5.6"


def test_group_rows_by_product_id_keys_are_strings():
    """Regression test: TCGCSV returns productId as a JSON int, but our
    product.loose_pack_tcgcsv_product_id/box_tcgcsv_product_id are stored
    as strings everywhere else in the schema. Keying this dict by the raw
    int made every single lookup silently miss -- every product refreshed
    as UNRESOLVED regardless of whether TCGCSV actually had a price."""
    rows = [row(product_id=562116, market_price=5.6), row(product_id=562118, market_price=161.18)]

    grouped = group_rows_by_product_id(rows)

    assert set(grouped.keys()) == {"562116", "562118"}
    assert all(isinstance(key, str) for key in grouped.keys())

    # This is exactly the lookup pattern _resolve_and_store_product_price
    # uses against a Product's string-typed TCGCSV id fields.
    assert grouped.get("562116") == [rows[0]]
    assert grouped.get(562116) is None  # the int key must NOT match


def test_group_rows_by_product_id_groups_multiple_rows_per_id():
    rows = [
        row(product_id=1, market_price=1.0, sub_type="Normal"),
        row(product_id=1, market_price=2.0, sub_type="Foil"),
        row(product_id=2, market_price=3.0),
    ]

    grouped = group_rows_by_product_id(rows)

    assert len(grouped["1"]) == 2
    assert len(grouped["2"]) == 1


def test_group_rows_by_product_id_skips_rows_missing_product_id():
    rows = [{"marketPrice": 1.0, "subTypeName": "Normal"}]
    grouped = group_rows_by_product_id(rows)
    assert grouped == {}
