"""
Stream model, matching elysium_s_<key>.streams (docs/IMPLEMENTATION_PLAN.md
section 2.3). Money fields are Decimal128 end-to-end (LLD 23.1); snapshot
arrays (inventory_snapshot, price_snapshot) are kept as plain dicts since
they're write-once records copied at stream-start time, not independently
queried documents.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from elysium.models.prices import from_decimal128, to_decimal128

STATUS_ACTIVE = "ACTIVE"
STATUS_COMPLETED = "COMPLETED"
STATUS_CANCELED = "CANCELED"


def _snapshot_price_entry_to_document(entry: dict) -> dict:
    doc = dict(entry)
    doc["resolved_pack_price"] = to_decimal128(entry.get("resolved_pack_price"))
    doc["raw_loose_price"] = to_decimal128(entry.get("raw_loose_price"))
    doc["raw_box_price"] = to_decimal128(entry.get("raw_box_price"))
    return doc


def _snapshot_price_entry_from_document(doc: dict) -> dict:
    entry = dict(doc)
    entry["resolved_pack_price"] = from_decimal128(doc.get("resolved_pack_price"))
    entry["raw_loose_price"] = from_decimal128(doc.get("raw_loose_price"))
    entry["raw_box_price"] = from_decimal128(doc.get("raw_box_price"))
    return entry


@dataclass
class Stream:
    id: str
    streamer_id: str
    status: str
    start_time: datetime
    date: str | None = None
    end_time: datetime | None = None
    inventory_snapshot: list[dict] = field(default_factory=list)
    price_snapshot: list[dict] = field(default_factory=list)
    final_stream_gross: Decimal | None = None
    sum_of_break_gross: Decimal = Decimal("0")
    gross_difference: Decimal | None = None
    stream_pack_market_value: Decimal = Decimal("0")
    stream_profit: Decimal | None = None
    stream_profit_margin: Decimal | None = None
    notes: str = ""
    force_canceled: bool = False
    force_cancel_reason: str | None = None
    force_canceled_by: str | None = None
    force_canceled_at: datetime | None = None
    corrections: list[dict] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    lock_heartbeat_at: datetime | None = None

    def price_for_product(self, product_id: str) -> dict | None:
        return next((entry for entry in self.price_snapshot if entry["product_id"] == product_id), None)

    def to_document(self) -> dict:
        return {
            "_id": self.id,
            "streamer_id": self.streamer_id,
            "status": self.status,
            "date": self.date,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "inventory_snapshot": self.inventory_snapshot,
            "price_snapshot": [_snapshot_price_entry_to_document(e) for e in self.price_snapshot],
            "final_stream_gross": to_decimal128(self.final_stream_gross),
            "sum_of_break_gross": to_decimal128(self.sum_of_break_gross),
            "gross_difference": to_decimal128(self.gross_difference),
            "stream_pack_market_value": to_decimal128(self.stream_pack_market_value),
            "stream_profit": to_decimal128(self.stream_profit),
            "stream_profit_margin": to_decimal128(self.stream_profit_margin),
            "notes": self.notes,
            "force_canceled": self.force_canceled,
            "force_cancel_reason": self.force_cancel_reason,
            "force_canceled_by": self.force_canceled_by,
            "force_canceled_at": self.force_canceled_at,
            "corrections": self.corrections,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "lock_heartbeat_at": self.lock_heartbeat_at,
        }

    @staticmethod
    def from_document(doc: dict) -> "Stream":
        return Stream(
            id=doc["_id"],
            streamer_id=doc["streamer_id"],
            status=doc["status"],
            date=doc.get("date"),
            start_time=doc["start_time"],
            end_time=doc.get("end_time"),
            inventory_snapshot=doc.get("inventory_snapshot", []),
            price_snapshot=[_snapshot_price_entry_from_document(e) for e in doc.get("price_snapshot", [])],
            final_stream_gross=from_decimal128(doc.get("final_stream_gross")),
            sum_of_break_gross=from_decimal128(doc.get("sum_of_break_gross")) or Decimal("0"),
            gross_difference=from_decimal128(doc.get("gross_difference")),
            stream_pack_market_value=from_decimal128(doc.get("stream_pack_market_value")) or Decimal("0"),
            stream_profit=from_decimal128(doc.get("stream_profit")),
            stream_profit_margin=from_decimal128(doc.get("stream_profit_margin")),
            notes=doc.get("notes", ""),
            force_canceled=doc.get("force_canceled", False),
            force_cancel_reason=doc.get("force_cancel_reason"),
            force_canceled_by=doc.get("force_canceled_by"),
            force_canceled_at=doc.get("force_canceled_at"),
            corrections=doc.get("corrections", []),
            created_at=doc.get("created_at"),
            updated_at=doc.get("updated_at"),
            lock_heartbeat_at=doc.get("lock_heartbeat_at"),
        )
