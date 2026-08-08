"""
Decommission request model, matching elysium_master.decommission_requests
(docs/IMPLEMENTATION_PLAN.md section 2.1). A decommission is the two-step
process (initiate -> approve) that clears out a streamer account: initiate()
snapshots the streamer's current allocation without moving anything;
approve() actually sweeps positive balances back to unassigned inventory in
a single cross-database transaction and disables login. Negative balances
are never auto-resolved by this flow -- see inventory_discrepancies.
"""

from dataclasses import dataclass, field
from datetime import datetime

STATUS_PENDING = "PENDING"
STATUS_APPROVED = "APPROVED"
STATUS_CANCELED = "CANCELED"


@dataclass
class DecommissionRequest:
    id: str
    streamer_id: str
    initiated_by: str
    initiated_at: datetime
    snapshot_of_allocations_at_initiation: list[dict] = field(default_factory=list)
    status: str = STATUS_PENDING
    approved_by: str | None = None
    approved_at: datetime | None = None
    canceled_by: str | None = None
    canceled_at: datetime | None = None
    notes: str | None = None

    def to_document(self) -> dict:
        return {
            "request_id": self.id,
            "streamer_id": self.streamer_id,
            "initiated_by": self.initiated_by,
            "initiated_at": self.initiated_at,
            "snapshot_of_allocations_at_initiation": self.snapshot_of_allocations_at_initiation,
            "status": self.status,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "canceled_by": self.canceled_by,
            "canceled_at": self.canceled_at,
            "notes": self.notes,
        }

    @staticmethod
    def from_document(doc: dict) -> "DecommissionRequest":
        return DecommissionRequest(
            id=doc.get("request_id", str(doc.get("_id"))),
            streamer_id=doc["streamer_id"],
            initiated_by=doc["initiated_by"],
            initiated_at=doc["initiated_at"],
            snapshot_of_allocations_at_initiation=doc.get("snapshot_of_allocations_at_initiation", []),
            status=doc.get("status", STATUS_PENDING),
            approved_by=doc.get("approved_by"),
            approved_at=doc.get("approved_at"),
            canceled_by=doc.get("canceled_by"),
            canceled_at=doc.get("canceled_at"),
            notes=doc.get("notes"),
        )
