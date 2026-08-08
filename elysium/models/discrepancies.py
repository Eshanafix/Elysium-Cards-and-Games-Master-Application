"""
Discrepancy model, matching elysium_master.inventory_discrepancies
(docs/IMPLEMENTATION_PLAN.md section 2.1). Semantics for the two types are
defined precisely in plan section 4.6:

- NEGATIVE_INVENTORY: a correction (choice A) let the streamer's ledger
  balance go negative; this record's quantity always equals the magnitude
  of that negative balance (the master-invariant consistency check).
- UNDEDUCTED_SHORTAGE: a correction (choice C) clamped the streamer's
  ledger at zero instead of going negative; this record is the only place
  the shortage is tracked.
"""

from dataclasses import dataclass
from datetime import datetime

TYPE_NEGATIVE_INVENTORY = "NEGATIVE_INVENTORY"
TYPE_UNDEDUCTED_SHORTAGE = "UNDEDUCTED_SHORTAGE"

SOURCE_STREAM_CORRECTION = "STREAM_CORRECTION"
SOURCE_DECOMMISSION = "DECOMMISSION"
SOURCE_MANUAL = "MANUAL"

STATUS_OPEN = "OPEN"
STATUS_RESOLVED = "RESOLVED"


@dataclass
class Discrepancy:
    id: str
    streamer_id: str
    product_id: str
    type: str
    quantity: int
    source: str
    status: str = STATUS_OPEN
    related_stream_id: str | None = None
    created_at: datetime | None = None
    created_by: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_note: str | None = None

    def to_document(self) -> dict:
        return {
            "discrepancy_id": self.id,
            "streamer_id": self.streamer_id,
            "product_id": self.product_id,
            "type": self.type,
            "quantity": self.quantity,
            "source": self.source,
            "status": self.status,
            "related_stream_id": self.related_stream_id,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
            "resolution_note": self.resolution_note,
        }

    @staticmethod
    def from_document(doc: dict) -> "Discrepancy":
        return Discrepancy(
            id=doc.get("discrepancy_id", str(doc.get("_id"))),
            streamer_id=doc["streamer_id"],
            product_id=doc["product_id"],
            type=doc["type"],
            quantity=doc["quantity"],
            source=doc["source"],
            status=doc.get("status", STATUS_OPEN),
            related_stream_id=doc.get("related_stream_id"),
            created_at=doc.get("created_at"),
            created_by=doc.get("created_by"),
            resolved_at=doc.get("resolved_at"),
            resolved_by=doc.get("resolved_by"),
            resolution_note=doc.get("resolution_note"),
        )
