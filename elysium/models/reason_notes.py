"""
Reason-note model, matching elysium_master.reason_notes (docs/
IMPLEMENTATION_PLAN.md section 2.1, 4.5). This is the one place a "reason"
is allowed to change so audit_events itself never needs an UpdateOne --
created only for the two action types with no other live document to hold
an editable reason (MASTER_INVENTORY_REMOVED, STREAMER_INVENTORY_RETURNED).
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ReasonNote:
    id: str
    action_type: str
    current_text: str
    streamer_id: str | None = None
    product_id: str | None = None
    history: list[dict] = field(default_factory=list)
    created_at: datetime | None = None
    created_by: str | None = None
    updated_at: datetime | None = None

    def to_document(self) -> dict:
        return {
            "_id": self.id,
            "action_type": self.action_type,
            "streamer_id": self.streamer_id,
            "product_id": self.product_id,
            "current_text": self.current_text,
            "history": self.history,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_document(doc: dict) -> "ReasonNote":
        return ReasonNote(
            id=doc["_id"],
            action_type=doc["action_type"],
            current_text=doc["current_text"],
            streamer_id=doc.get("streamer_id"),
            product_id=doc.get("product_id"),
            history=doc.get("history", []),
            created_at=doc.get("created_at"),
            created_by=doc.get("created_by"),
            updated_at=doc.get("updated_at"),
        )
