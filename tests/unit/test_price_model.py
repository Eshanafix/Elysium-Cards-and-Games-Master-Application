"""
classify_price: buckets a resolved pack price into LOW/MID/HIGH for
at-a-glance value scanning (Shared Sealed Prices' Classification column;
the live pack-selection grid's badge/banner color). Boundaries: under $10
is LOW, $10-$20 inclusive is MID, over $20 is HIGH.
"""

from decimal import Decimal

from elysium.models.prices import (
    CLASSIFICATION_HIGH,
    CLASSIFICATION_LOW,
    CLASSIFICATION_MID,
    classify_price,
)


def test_classify_price_none_has_no_classification():
    assert classify_price(None) is None


def test_classify_price_low_under_ten():
    assert classify_price(Decimal("0.01")) == CLASSIFICATION_LOW
    assert classify_price(Decimal("9.99")) == CLASSIFICATION_LOW


def test_classify_price_mid_ten_to_twenty_inclusive():
    assert classify_price(Decimal("10.00")) == CLASSIFICATION_MID
    assert classify_price(Decimal("15.00")) == CLASSIFICATION_MID
    assert classify_price(Decimal("20.00")) == CLASSIFICATION_MID


def test_classify_price_high_over_twenty():
    assert classify_price(Decimal("20.01")) == CLASSIFICATION_HIGH
    assert classify_price(Decimal("100.00")) == CLASSIFICATION_HIGH
