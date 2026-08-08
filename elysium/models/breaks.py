"""
Break model, matching elysium_s_<key>.breaks (docs/IMPLEMENTATION_PLAN.md
section 2.3). pack_lines are grouped quantities per product (LLD 14.3),
never one record per physical pack.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from elysium.models.prices import from_decimal128, to_decimal128

STATUS_ACTIVE = "ACTIVE"
STATUS_ENDED_EDITABLE = "ENDED_EDITABLE"
STATUS_DELETED = "DELETED"


def pack_line_to_document(line: dict) -> dict:
    doc = dict(line)
    doc["locked_unit_price"] = to_decimal128(line.get("locked_unit_price"))
    doc["line_market_value"] = to_decimal128(line.get("line_market_value"))
    return doc


def pack_line_from_document(doc: dict) -> dict:
    line = dict(doc)
    line["locked_unit_price"] = from_decimal128(doc.get("locked_unit_price"))
    line["line_market_value"] = from_decimal128(doc.get("line_market_value"))
    return line


@dataclass
class Break:
    id: str
    stream_id: str
    sequence_number: int
    status: str
    name: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    pack_lines: list[dict] = field(default_factory=list)
    total_pack_market_value: Decimal = Decimal("0")
    break_gross: Decimal | None = None
    break_profit: Decimal | None = None
    break_profit_margin: Decimal | None = None
    notes: str = ""
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def quantity_for_product(self, product_id: str) -> int:
        line = next((entry for entry in self.pack_lines if entry["product_id"] == product_id), None)
        return line["quantity"] if line else 0

    def to_document(self) -> dict:
        return {
            "_id": self.id,
            "stream_id": self.stream_id,
            "sequence_number": self.sequence_number,
            "status": self.status,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "pack_lines": [pack_line_to_document(line) for line in self.pack_lines],
            "total_pack_market_value": to_decimal128(self.total_pack_market_value),
            "break_gross": to_decimal128(self.break_gross),
            "break_profit": to_decimal128(self.break_profit),
            "break_profit_margin": to_decimal128(self.break_profit_margin),
            "notes": self.notes,
            "deleted_at": self.deleted_at,
            "deleted_by": self.deleted_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_document(doc: dict) -> "Break":
        return Break(
            id=doc["_id"],
            stream_id=doc["stream_id"],
            sequence_number=doc["sequence_number"],
            status=doc["status"],
            name=doc.get("name"),
            start_time=doc.get("start_time"),
            end_time=doc.get("end_time"),
            pack_lines=[pack_line_from_document(line) for line in doc.get("pack_lines", [])],
            total_pack_market_value=from_decimal128(doc.get("total_pack_market_value")) or Decimal("0"),
            break_gross=from_decimal128(doc.get("break_gross")),
            break_profit=from_decimal128(doc.get("break_profit")),
            break_profit_margin=from_decimal128(doc.get("break_profit_margin")),
            notes=doc.get("notes", ""),
            deleted_at=doc.get("deleted_at"),
            deleted_by=doc.get("deleted_by"),
            created_at=doc.get("created_at"),
            updated_at=doc.get("updated_at"),
        )
