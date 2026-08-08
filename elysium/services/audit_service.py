"""
Writes elysium_master.audit_events (LLD section 19). Append-only: every
call here is an insert, never an update -- see docs/IMPLEMENTATION_PLAN.md
section 4.5 for why that stays true even once reason-editing exists.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from elysium.models.prices import convert_decimals_to_decimal128
from elysium.models.users import ROLE_ADMIN
from elysium.repositories import master_repository as repo
from elysium.repositories import streamer_repository as streamer_repo
from elysium.services.mongo_client import get_client, get_master_db

RELATED_TYPE_REASON_NOTE = "reason_note"
RELATED_TYPE_STREAM_CORRECTION = "stream_correction"
RELATED_TYPE_FORCE_CANCEL = "force_cancel"
RELATED_TYPE_DISCREPANCY = "discrepancy"


class ReasonEditPermissionError(Exception):
    pass


class ReasonEditValidationError(Exception):
    pass


def _actor_role(performed_by: str) -> str | None:
    """Best-effort lookup of the acting user's role, for the audit record's
    optional `role` field. performed_by is sometimes a non-user sentinel
    (e.g. "BOOTSTRAP" from create_admin.py), which just resolves to None."""
    user = repo.find_user_by_id(performed_by)
    return ", ".join(user.roles) if user else None


def record_event(
    action_type: str,
    performed_by: str,
    product_id: str | None = None,
    streamer_id: str | None = None,
    stream_id: str | None = None,
    break_id: str | None = None,
    quantity_change: int | None = None,
    amount_change: Decimal | None = None,
    before_values: dict | None = None,
    after_values: dict | None = None,
    reason: str | None = None,
    reason_note_id: str | None = None,
    related_transaction_id: str | None = None,
    status: str = "SUCCESS",
    session=None,
) -> str:
    """
    Pass `session` when called from inside an existing multi-document
    transaction (e.g. inventory_service's claim/return/add/reduce), so the
    audit record commits or rolls back atomically with the change it
    describes (plan section 4.1) instead of being a separate, unguarded
    write. Omit it for standalone calls (Phase 2/3 account/product actions
    that aren't part of a larger transaction).
    """
    event_id = str(uuid.uuid4())

    # before_values/after_values are arbitrary caller-supplied dicts (e.g.
    # a break's pack_lines, full of Decimal money fields) -- converting the
    # whole document once here, rather than trusting each call site to
    # pre-convert every nested Decimal, is what actually closes this class
    # of bug off for good (it has shipped three times: amount_change alone
    # wasn't enough).
    doc = convert_decimals_to_decimal128({
        "event_id": event_id,
        "action_type": action_type,
        "performed_by": performed_by,
        "role": _actor_role(performed_by),
        "timestamp": datetime.now(timezone.utc),
        "product_id": product_id,
        "streamer_id": streamer_id,
        "stream_id": stream_id,
        "break_id": break_id,
        "quantity_change": quantity_change,
        "amount_change": amount_change,
        "before_values": before_values,
        "after_values": after_values,
        "reason": reason,
        "reason_note_id": reason_note_id,
        "related_transaction_id": related_transaction_id,
        "status": status,
    })

    get_master_db().audit_events.insert_one(doc, session=session)

    return event_id


def list_events(
    action_type: str | None = None,
    streamer_id: str | None = None,
    product_id: str | None = None,
    start_date=None,
    end_date=None,
    limit: int = 1000,
) -> list[dict]:
    """Backs the admin Audit History browser (LLD 6.16, admin-only per
    19.2) and the inventory_audit report dataset (LLD 20.5)."""
    return repo.list_audit_events(
        action_type=action_type, streamer_id=streamer_id, product_id=product_id,
        start_date=start_date, end_date=end_date, limit=limit,
    )


_REASON_NOTE_ACTIONS = {"MASTER_INVENTORY_REMOVED", "STREAMER_INVENTORY_RETURNED"}
_STREAM_CORRECTION_ACTIONS = {"STREAM_BREAK_CORRECTED", "STREAM_GROSS_CORRECTED"}
_FORCE_CANCEL_ACTIONS = {"STREAM_FORCE_CANCELED"}
_DISCREPANCY_ACTIONS = {"INVENTORY_DISCREPANCY_RESOLVED"}


def editable_reason_target(event: dict) -> dict | None:
    """Maps a raw audit_events document to the (related_record_type,
    related_record_id, stream_id, streamer_id) edit_reason() needs, or None
    if this event's action type has no editable reason at all, or the
    specific document is missing the linkage it would need (e.g. an older
    event predating reason_note_id). Used by the Audit History browser to
    decide whether to show an Edit Reason action for a given row."""
    action_type = event.get("action_type")

    if action_type in _REASON_NOTE_ACTIONS:
        reason_note_id = event.get("reason_note_id")
        if not reason_note_id:
            return None
        return {"related_record_type": RELATED_TYPE_REASON_NOTE, "related_record_id": reason_note_id}

    if action_type in _STREAM_CORRECTION_ACTIONS:
        correction_id = event.get("related_transaction_id")
        stream_id = event.get("stream_id")
        streamer_id = event.get("streamer_id")
        if not (correction_id and stream_id and streamer_id):
            return None
        return {
            "related_record_type": RELATED_TYPE_STREAM_CORRECTION, "related_record_id": correction_id,
            "stream_id": stream_id, "streamer_id": streamer_id,
        }

    if action_type in _FORCE_CANCEL_ACTIONS:
        stream_id = event.get("stream_id")
        streamer_id = event.get("streamer_id")
        if not (stream_id and streamer_id):
            return None
        return {
            "related_record_type": RELATED_TYPE_FORCE_CANCEL, "related_record_id": stream_id,
            "stream_id": stream_id, "streamer_id": streamer_id,
        }

    if action_type in _DISCREPANCY_ACTIONS:
        discrepancy_id = event.get("related_transaction_id")
        if not discrepancy_id:
            return None
        return {"related_record_type": RELATED_TYPE_DISCREPANCY, "related_record_id": discrepancy_id}

    return None


def _is_admin(user_id: str) -> bool:
    user = repo.find_user_by_id(user_id)
    return bool(user and ROLE_ADMIN in user.roles)


def _edit_reason_note(related_record_id: str, new_text: str, edited_by: str, now, session) -> str:
    note = repo.find_reason_note(related_record_id)

    if note is None:
        raise ReasonEditValidationError(f"No such reason note: {related_record_id}")

    if note.streamer_id is not None:
        if edited_by != note.streamer_id and not _is_admin(edited_by):
            raise ReasonEditPermissionError("You may only edit reasons on your own records.")
    elif not _is_admin(edited_by):
        raise ReasonEditPermissionError("Only an admin may edit this reason.")

    old_text = note.current_text
    repo.update_reason_note_text(related_record_id, new_text, edited_by, now)
    return old_text


def _edit_stream_correction_reason(
    streamer_database_name: str, stream_id: str, related_record_id: str, new_text: str, edited_by: str, now, session
) -> str:
    if not _is_admin(edited_by):
        raise ReasonEditPermissionError("Only an admin may edit a stream correction's reason.")

    stream = streamer_repo.find_stream_by_id(streamer_database_name, stream_id, session=session)

    if stream is None:
        raise ReasonEditValidationError(f"No such stream: {stream_id}")

    corrections = list(stream.corrections)
    target = next((c for c in corrections if c.get("correction_id") == related_record_id), None)

    if target is None:
        raise ReasonEditValidationError(f"No such correction: {related_record_id}")

    old_text = target.get("reason")
    target["reason"] = new_text

    streamer_repo.update_stream_fields(
        streamer_database_name, stream_id, {"corrections": corrections, "updated_at": now}, session=session
    )
    return old_text


def _edit_force_cancel_reason(
    streamer_database_name: str, stream_id: str, new_text: str, edited_by: str, now, session
) -> str:
    if not _is_admin(edited_by):
        raise ReasonEditPermissionError("Only an admin may edit a force-cancel reason.")

    stream = streamer_repo.find_stream_by_id(streamer_database_name, stream_id, session=session)

    if stream is None:
        raise ReasonEditValidationError(f"No such stream: {stream_id}")

    old_text = stream.force_cancel_reason
    streamer_repo.update_stream_fields(
        streamer_database_name, stream_id, {"force_cancel_reason": new_text, "updated_at": now}, session=session
    )
    return old_text


def _edit_discrepancy_reason(related_record_id: str, new_text: str, edited_by: str, now, session) -> str:
    if not _is_admin(edited_by):
        raise ReasonEditPermissionError("Only an admin may edit a discrepancy's resolution note.")

    discrepancy = repo.find_discrepancy(related_record_id)

    if discrepancy is None:
        raise ReasonEditValidationError(f"No such discrepancy: {related_record_id}")

    if discrepancy.resolution_note is None:
        raise ReasonEditValidationError("This discrepancy has no resolution note yet to edit.")

    old_text = discrepancy.resolution_note
    repo.update_discrepancy_fields(related_record_id, {"resolution_note": new_text})
    return old_text


def edit_reason(
    related_record_type: str,
    related_record_id: str,
    new_text: str,
    edited_by: str,
    streamer_database_name: str | None = None,
    stream_id: str | None = None,
) -> None:
    """
    Plan section 4.5's edit_reason: loads whichever live document actually
    holds this action's editable reason, updates it in place, and inserts a
    brand-new (never an update) REASON_EDITED audit event referencing it --
    audit_events for the *original* action is never touched.
    """
    if not new_text or not new_text.strip():
        raise ReasonEditValidationError("The new reason text cannot be empty.")

    client = get_client()
    now = datetime.now(timezone.utc)
    result = {}

    def callback(session):
        if related_record_type == RELATED_TYPE_REASON_NOTE:
            old_text = _edit_reason_note(related_record_id, new_text, edited_by, now, session)
        elif related_record_type == RELATED_TYPE_STREAM_CORRECTION:
            old_text = _edit_stream_correction_reason(
                streamer_database_name, stream_id, related_record_id, new_text, edited_by, now, session
            )
        elif related_record_type == RELATED_TYPE_FORCE_CANCEL:
            old_text = _edit_force_cancel_reason(streamer_database_name, stream_id, new_text, edited_by, now, session)
        elif related_record_type == RELATED_TYPE_DISCREPANCY:
            old_text = _edit_discrepancy_reason(related_record_id, new_text, edited_by, now, session)
        else:
            raise ReasonEditValidationError(f"Unknown related_record_type: {related_record_type}")

        result["old_text"] = old_text

        get_master_db().audit_events.insert_one({
            "event_id": str(uuid.uuid4()),
            "action_type": "REASON_EDITED",
            "performed_by": edited_by,
            "role": _actor_role(edited_by),
            "timestamp": now,
            "product_id": None,
            "streamer_id": None,
            "stream_id": stream_id,
            "break_id": None,
            "quantity_change": None,
            "amount_change": None,
            "before_values": {"reason": old_text},
            "after_values": {"reason": new_text},
            "reason": None,
            "reason_note_id": related_record_id if related_record_type == RELATED_TYPE_REASON_NOTE else None,
            "related_transaction_id": related_record_id,
            "status": "SUCCESS",
        }, session=session)

    with client.start_session() as session:
        session.with_transaction(callback)
