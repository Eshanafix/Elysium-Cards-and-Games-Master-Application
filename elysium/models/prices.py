"""
Price model, matching elysium_prices.current_prices (docs/IMPLEMENTATION_
PLAN.md section 2.2). Money fields are Decimal128 end-to-end (LLD 23.1) --
Python-side that's `decimal.Decimal`, converted to/from bson.Decimal128
only at the document boundary.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from bson import Decimal128

SOURCE_LOOSE_PACK_MARKET = "LOOSE_PACK_MARKET"
SOURCE_DERIVED_FROM_BOX_MARKET = "DERIVED_FROM_BOX_MARKET"
SOURCE_MANUAL = "MANUAL"
SOURCE_PREVIOUS_VALUE = "PREVIOUS_VALUE"

STATUS_OK = "OK"
STATUS_STALE = "STALE"
STATUS_MANUAL = "MANUAL"
STATUS_UNRESOLVED = "UNRESOLVED"
STATUS_AMBIGUOUS = "AMBIGUOUS"

CLASSIFICATION_LOW = "LOW"
CLASSIFICATION_MID = "MID"
CLASSIFICATION_HIGH = "HIGH"


def classify_price(price: Decimal | None) -> str | None:
    """Buckets a resolved pack price for at-a-glance value scanning (Shared
    Sealed Prices' Classification column; the live pack-selection grid's
    badge and banner color) -- local feature request, no LLD section.
    Boundaries: under $10 is LOW, $10-$20 inclusive is MID, over $20 is
    HIGH. None (no resolved price yet) has no classification."""
    if price is None:
        return None
    if price < 10:
        return CLASSIFICATION_LOW
    if price <= 20:
        return CLASSIFICATION_MID
    return CLASSIFICATION_HIGH


def to_decimal128(value: Decimal | None) -> Decimal128 | None:
    return Decimal128(value) if value is not None else None


def from_decimal128(value: Decimal128 | None) -> Decimal | None:
    return value.to_decimal() if value is not None else None


def convert_decimals_to_decimal128(value):
    """
    Recursively converts any decimal.Decimal in `value` (including nested
    dicts/lists) to bson.Decimal128. pymongo cannot encode a raw Decimal at
    all -- this exact bug has already shipped twice (audit_service's
    amount_change; break/stream field updates), both times because a raw
    $set dict was built by hand instead of going through a model's
    to_document(). Repository functions that accept an arbitrary fields
    dict for $set should run it through this rather than trust every
    caller to remember per-field conversion.
    """
    if isinstance(value, Decimal):
        return Decimal128(value)
    if isinstance(value, dict):
        return {key: convert_decimals_to_decimal128(v) for key, v in value.items()}
    if isinstance(value, list):
        return [convert_decimals_to_decimal128(v) for v in value]
    return value


@dataclass
class ManualPriceMetadata:
    entered_by: str
    entered_at: datetime
    note: str | None = None

    def to_document(self) -> dict:
        return {"entered_by": self.entered_by, "entered_at": self.entered_at, "note": self.note}

    @staticmethod
    def from_document(doc: dict | None) -> "ManualPriceMetadata | None":
        if not doc:
            return None
        return ManualPriceMetadata(entered_by=doc["entered_by"], entered_at=doc["entered_at"], note=doc.get("note"))


@dataclass
class CurrentPrice:
    product_id: str
    tcgcsv_category_id: str
    tcgcsv_group_id: str
    loose_pack_tcgcsv_product_id: str
    box_tcgcsv_product_id: str
    packs_per_box: int
    price_status: str
    raw_loose_pack_market_price: Decimal | None = None
    raw_box_market_price: Decimal | None = None
    resolved_pack_price: Decimal | None = None
    resolved_price_source: str | None = None
    last_successful_refresh_at: datetime | None = None
    last_attempted_refresh_at: datetime | None = None
    last_modified_by: str | None = None
    previous_resolved_price: Decimal | None = None
    manual_price_metadata: ManualPriceMetadata | None = None
    version: int = 0
    updated_at: datetime | None = None

    def to_document(self) -> dict:
        return {
            "_id": self.product_id,
            "product_id": self.product_id,
            "tcgcsv_category_id": self.tcgcsv_category_id,
            "tcgcsv_group_id": self.tcgcsv_group_id,
            "loose_pack_tcgcsv_product_id": self.loose_pack_tcgcsv_product_id,
            "box_tcgcsv_product_id": self.box_tcgcsv_product_id,
            "packs_per_box": self.packs_per_box,
            "raw_loose_pack_market_price": to_decimal128(self.raw_loose_pack_market_price),
            "raw_box_market_price": to_decimal128(self.raw_box_market_price),
            "resolved_pack_price": to_decimal128(self.resolved_pack_price),
            "resolved_price_source": self.resolved_price_source,
            "price_status": self.price_status,
            "last_successful_refresh_at": self.last_successful_refresh_at,
            "last_attempted_refresh_at": self.last_attempted_refresh_at,
            "last_modified_by": self.last_modified_by,
            "previous_resolved_price": to_decimal128(self.previous_resolved_price),
            "manual_price_metadata": self.manual_price_metadata.to_document() if self.manual_price_metadata else None,
            "version": self.version,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_document(doc: dict) -> "CurrentPrice":
        return CurrentPrice(
            product_id=doc["product_id"],
            tcgcsv_category_id=doc.get("tcgcsv_category_id"),
            tcgcsv_group_id=doc.get("tcgcsv_group_id"),
            loose_pack_tcgcsv_product_id=doc.get("loose_pack_tcgcsv_product_id"),
            box_tcgcsv_product_id=doc.get("box_tcgcsv_product_id"),
            packs_per_box=doc.get("packs_per_box"),
            raw_loose_pack_market_price=from_decimal128(doc.get("raw_loose_pack_market_price")),
            raw_box_market_price=from_decimal128(doc.get("raw_box_market_price")),
            resolved_pack_price=from_decimal128(doc.get("resolved_pack_price")),
            resolved_price_source=doc.get("resolved_price_source"),
            price_status=doc["price_status"],
            last_successful_refresh_at=doc.get("last_successful_refresh_at"),
            last_attempted_refresh_at=doc.get("last_attempted_refresh_at"),
            last_modified_by=doc.get("last_modified_by"),
            previous_resolved_price=from_decimal128(doc.get("previous_resolved_price")),
            manual_price_metadata=ManualPriceMetadata.from_document(doc.get("manual_price_metadata")),
            version=doc.get("version", 0),
            updated_at=doc.get("updated_at"),
        )
