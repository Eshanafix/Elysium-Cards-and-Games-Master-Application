"""
Inventory discrepancies (LLD section 17.6.A; docs/IMPLEMENTATION_PLAN.md
section 4.6). A discrepancy is opened when a stream correction can't fully
back a shortage against physical/ledger inventory (see correction_service),
or when a decommission approval leaves a residual negative balance. This
module owns the create-or-increment pattern so a given streamer/product/
type combination never accumulates more than one OPEN record, and the
required-note resolve action.
"""

import uuid
from datetime import datetime, timezone

from elysium.models.discrepancies import STATUS_OPEN, STATUS_RESOLVED, Discrepancy
from elysium.repositories import master_repository as repo
from elysium.services import audit_service


class DiscrepancyValidationError(Exception):
    pass


def open_or_increment_discrepancy(
    streamer_id: str,
    product_id: str,
    discrepancy_type: str,
    quantity: int,
    source: str,
    created_by: str,
    related_stream_id: str | None = None,
    session=None,
) -> str:
    """Idempotent-by-key: if an OPEN discrepancy already exists for this
    exact (streamer, product, type), its quantity is incremented rather
    than creating a duplicate. Returns the discrepancy_id."""
    if quantity <= 0:
        raise DiscrepancyValidationError("Discrepancy quantity must be positive.")

    existing = repo.find_open_discrepancy(streamer_id, product_id, discrepancy_type)

    if existing:
        repo.increment_discrepancy_quantity(existing["discrepancy_id"], quantity, session=session)
        return existing["discrepancy_id"]

    now = datetime.now(timezone.utc)
    discrepancy = Discrepancy(
        id=str(uuid.uuid4()),
        streamer_id=streamer_id,
        product_id=product_id,
        type=discrepancy_type,
        quantity=quantity,
        source=source,
        status=STATUS_OPEN,
        related_stream_id=related_stream_id,
        created_at=now,
        created_by=created_by,
    )
    repo.insert_discrepancy(discrepancy, session=session)

    audit_service.record_event(
        action_type="INVENTORY_DISCREPANCY_CREATED",
        performed_by=created_by,
        streamer_id=streamer_id,
        product_id=product_id,
        stream_id=related_stream_id,
        quantity_change=quantity,
        after_values={"discrepancy_id": discrepancy.id, "type": discrepancy_type, "source": source},
        session=session,
    )

    return discrepancy.id


def resolve_discrepancy(discrepancy_id: str, resolved_by: str, resolution_note: str) -> None:
    if not resolution_note or not resolution_note.strip():
        raise DiscrepancyValidationError("A resolution note is required to resolve a discrepancy.")

    discrepancy = repo.find_discrepancy(discrepancy_id)

    if discrepancy is None:
        raise DiscrepancyValidationError(f"No such discrepancy: {discrepancy_id}")

    repo.update_discrepancy_fields(discrepancy_id, {
        "status": STATUS_RESOLVED,
        "resolved_by": resolved_by,
        "resolved_at": datetime.now(timezone.utc),
        "resolution_note": resolution_note,
    })

    audit_service.record_event(
        action_type="INVENTORY_DISCREPANCY_RESOLVED",
        performed_by=resolved_by,
        streamer_id=discrepancy.streamer_id,
        product_id=discrepancy.product_id,
        reason=resolution_note,
        after_values={"discrepancy_id": discrepancy_id},
        related_transaction_id=discrepancy_id,
    )


def list_discrepancies(status: str | None = None) -> list[Discrepancy]:
    return repo.list_discrepancies(status=status)


def list_discrepancies_for_streamer(streamer_id: str, status: str | None = None) -> list[Discrepancy]:
    return repo.list_discrepancies_for_streamer(streamer_id, status=status)
