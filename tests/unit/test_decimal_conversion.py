from decimal import Decimal

from bson import Decimal128

from elysium.models.prices import convert_decimals_to_decimal128


def test_converts_bare_decimal():
    result = convert_decimals_to_decimal128(Decimal("4.25"))
    assert isinstance(result, Decimal128)
    assert result.to_decimal() == Decimal("4.25")


def test_converts_decimal_in_flat_dict():
    """Regression test: raw $set dicts built by hand (break/stream field
    updates) shipped with un-converted Decimal values twice already --
    pymongo cannot encode decimal.Decimal at all."""
    fields = {"break_gross": Decimal("30.00"), "status": "ENDED_EDITABLE"}
    result = convert_decimals_to_decimal128(fields)

    assert isinstance(result["break_gross"], Decimal128)
    assert result["break_gross"].to_decimal() == Decimal("30.00")
    assert result["status"] == "ENDED_EDITABLE"


def test_converts_decimal_nested_in_list_of_dicts():
    fields = {
        "pack_lines": [
            {"product_id": "p1", "quantity": 3, "line_market_value": Decimal("10.50")},
        ]
    }
    result = convert_decimals_to_decimal128(fields)

    assert isinstance(result["pack_lines"][0]["line_market_value"], Decimal128)
    assert result["pack_lines"][0]["quantity"] == 3  # ints untouched


def test_leaves_none_and_other_types_unchanged():
    fields = {"a": None, "b": "text", "c": 5, "d": True}
    result = convert_decimals_to_decimal128(fields)
    assert result == fields
