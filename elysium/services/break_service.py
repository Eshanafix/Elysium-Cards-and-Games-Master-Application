"""
Break workflow (LLD section 14; docs/IMPLEMENTATION_PLAN.md section 4.3,
5). All pricing here uses the stream's locked price snapshot, never live
prices -- that's the whole point of snapshotting at stream start.

Audit scope: BREAK_CREATED/BREAK_ENDED/BREAK_DELETED are always written.
BREAK_EDITED is written for post-end edits (LLD 15.2's "editable before
submission" phase) but not for every +/- click while a break is still
ACTIVE and being drafted -- that would be audit noise for something that
isn't a finalized fact yet.
"""

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from elysium.models.breaks import STATUS_ACTIVE, STATUS_DELETED, STATUS_ENDED_EDITABLE, Break, pack_line_to_document
from elysium.models.streams import STATUS_ACTIVE as STREAM_STATUS_ACTIVE
from elysium.models.streams import Stream
from elysium.repositories import streamer_repository as streamer_repo
from elysium.services import audit_service

logger = logging.getLogger(__name__)


class BreakValidationError(Exception):
    pass


class InsufficientAvailabilityError(Exception):
    pass


def get_availability(stream: Stream, breaks: list[Break] | None, streamer_database_name: str) -> dict[str, int]:
    """
    LLD 14.2: Available = Current Streamer Packs (the stream's locked
    starting snapshot) - Total Packs Selected Across All Nondeleted Breaks.
    Pass `breaks` explicitly when the caller already has a fresh list
    (e.g. to exclude one break's own usage); pass None to fetch fresh.
    """
    if breaks is None:
        breaks = streamer_repo.list_breaks_for_stream(streamer_database_name, stream.id)

    used_by_product: dict[str, int] = {}
    for b in breaks:
        if b.status == STATUS_DELETED:  # defensive: callers should already exclude these, but never double-count
            continue
        for line in b.pack_lines:
            used_by_product[line["product_id"]] = used_by_product.get(line["product_id"], 0) + line["quantity"]

    return {
        entry["product_id"]: entry["packs_at_start"] - used_by_product.get(entry["product_id"], 0)
        for entry in stream.inventory_snapshot
    }


def start_new_break(stream: Stream, streamer_database_name: str, name: str | None = None) -> Break:
    """Only one ACTIVE break per stream at a time (plan section 10 item 5,
    confirmed as a hard rule)."""
    if streamer_repo.find_active_break(streamer_database_name, stream.id) is not None:
        raise BreakValidationError("Another break is already active. End it before starting a new one.")

    now = datetime.now(timezone.utc)
    break_obj = Break(
        id=str(uuid.uuid4()),
        stream_id=stream.id,
        sequence_number=streamer_repo.next_break_sequence_number(streamer_database_name, stream.id),
        status=STATUS_ACTIVE,
        name=name,
        start_time=now,
        created_at=now,
        updated_at=now,
    )

    streamer_repo.insert_break(streamer_database_name, break_obj)

    audit_service.record_event(
        action_type="BREAK_CREATED",
        performed_by=stream.streamer_id,
        stream_id=stream.id,
        break_id=break_obj.id,
    )

    return break_obj


def _recompute_total_pack_market_value(pack_lines: list[dict]) -> Decimal:
    return sum((line["line_market_value"] for line in pack_lines), Decimal("0"))


def _assert_stream_not_completed(streamer_database_name: str, stream_id: str) -> None:
    """LLD 15.2/29.15: a streamer may only edit a break while its stream is
    still ACTIVE -- once end_stream runs, changing recorded figures is an
    admin-only action (correction_service, which never calls into
    break_service and operates on its own transaction instead)."""
    stream = streamer_repo.find_stream_by_id(streamer_database_name, stream_id)

    if stream is not None and stream.status != STREAM_STATUS_ACTIVE:
        raise BreakValidationError(
            "This stream is no longer active -- only an admin correction can change a "
            "completed or canceled stream's breaks."
        )


def set_break_pack_line_quantity(
    stream: Stream,
    streamer_database_name: str,
    break_obj: Break,
    product_id: str,
    new_quantity: int,
    edited_by: str | None = None,
    audit_as_edit: bool = False,
) -> Break:
    """Sets (not increments) the quantity for one product line. Used both
    for live +/- clicks on an ACTIVE break (audit_as_edit=False, drafting)
    and for post-end quantity edits (audit_as_edit=True, LLD 15.2)."""
    if break_obj.status == STATUS_DELETED:
        raise BreakValidationError("Cannot modify a deleted break.")

    if stream.status != STREAM_STATUS_ACTIVE:
        raise BreakValidationError(
            "This stream is no longer active -- only an admin correction can change a "
            "completed or canceled stream's breaks."
        )

    if new_quantity < 0:
        raise BreakValidationError("Quantity cannot be negative.")

    price_entry = stream.price_for_product(product_id)
    if price_entry is None:
        raise BreakValidationError(f"No locked price available for product '{product_id}' in this stream.")

    other_breaks = [
        b for b in streamer_repo.list_breaks_for_stream(streamer_database_name, stream.id) if b.id != break_obj.id
    ]
    availability_excluding_this = get_availability(stream, other_breaks, streamer_database_name)
    available_for_this_line = availability_excluding_this.get(product_id, 0)

    if new_quantity > available_for_this_line:
        raise InsufficientAvailabilityError(
            f"Only {available_for_this_line} packs of '{product_id}' are available."
        )

    before_lines = list(break_obj.pack_lines)
    new_lines = [line for line in break_obj.pack_lines if line["product_id"] != product_id]

    if new_quantity > 0:
        new_lines.append({
            "product_id": product_id,
            "quantity": new_quantity,
            "locked_unit_price": price_entry["resolved_pack_price"],
            "price_source": price_entry["price_source"],
            "line_market_value": price_entry["resolved_pack_price"] * new_quantity,
        })

    total_pack_market_value = _recompute_total_pack_market_value(new_lines)
    now = datetime.now(timezone.utc)

    fields = {
        "pack_lines": [pack_line_to_document(line) for line in new_lines],
        "total_pack_market_value": total_pack_market_value,
        "updated_at": now,
    }

    if break_obj.break_gross is not None:
        profit = break_obj.break_gross - total_pack_market_value
        fields["break_profit"] = profit
        fields["break_profit_margin"] = (profit / break_obj.break_gross) if break_obj.break_gross != 0 else None

    streamer_repo.update_break_fields(streamer_database_name, break_obj.id, fields)

    if audit_as_edit:
        audit_service.record_event(
            action_type="BREAK_EDITED",
            performed_by=edited_by or stream.streamer_id,
            stream_id=stream.id,
            break_id=break_obj.id,
            before_values={"pack_lines": before_lines},
            after_values={"pack_lines": new_lines},
        )

    return streamer_repo.find_break_by_id(streamer_database_name, break_obj.id)


def end_break(streamer_database_name: str, break_obj: Break, break_gross: Decimal, ended_by: str) -> Break:
    """LLD 14.5/14.6: requires break gross; break_profit = break_gross -
    sum(quantity * locked stream pack price)."""
    if break_obj.status != STATUS_ACTIVE:
        raise BreakValidationError("Only an active break can be ended.")

    _assert_stream_not_completed(streamer_database_name, break_obj.stream_id)

    if break_gross < 0:
        raise BreakValidationError("Break gross cannot be negative.")

    profit = break_gross - break_obj.total_pack_market_value
    now = datetime.now(timezone.utc)

    streamer_repo.update_break_fields(streamer_database_name, break_obj.id, {
        "status": STATUS_ENDED_EDITABLE,
        "end_time": now,
        "updated_at": now,
        "break_gross": break_gross,
        "break_profit": profit,
        "break_profit_margin": (profit / break_gross) if break_gross != 0 else None,
    })

    audit_service.record_event(
        action_type="BREAK_ENDED",
        performed_by=ended_by,
        stream_id=break_obj.stream_id,
        break_id=break_obj.id,
        amount_change=break_gross,
    )

    return streamer_repo.find_break_by_id(streamer_database_name, break_obj.id)


def edit_break_gross(streamer_database_name: str, break_obj: Break, new_break_gross: Decimal, edited_by: str) -> Break:
    """LLD 15.2: break gross is editable before final stream submission."""
    if break_obj.status != STATUS_ENDED_EDITABLE:
        raise BreakValidationError("Only an ended (not yet submitted) break can be edited.")

    _assert_stream_not_completed(streamer_database_name, break_obj.stream_id)

    if new_break_gross < 0:
        raise BreakValidationError("Break gross cannot be negative.")

    before_gross = break_obj.break_gross
    profit = new_break_gross - break_obj.total_pack_market_value
    now = datetime.now(timezone.utc)

    streamer_repo.update_break_fields(streamer_database_name, break_obj.id, {
        "break_gross": new_break_gross,
        "break_profit": profit,
        "break_profit_margin": (profit / new_break_gross) if new_break_gross != 0 else None,
        "updated_at": now,
    })

    audit_service.record_event(
        action_type="BREAK_EDITED",
        performed_by=edited_by,
        stream_id=break_obj.stream_id,
        break_id=break_obj.id,
        before_values={"break_gross": before_gross},
        after_values={"break_gross": new_break_gross},
    )

    return streamer_repo.find_break_by_id(streamer_database_name, break_obj.id)


def edit_break_name_and_notes(streamer_database_name: str, break_obj: Break, name: str | None, notes: str, edited_by: str) -> Break:
    _assert_stream_not_completed(streamer_database_name, break_obj.stream_id)

    now = datetime.now(timezone.utc)

    streamer_repo.update_break_fields(streamer_database_name, break_obj.id, {
        "name": name, "notes": notes, "updated_at": now,
    })

    audit_service.record_event(
        action_type="BREAK_EDITED",
        performed_by=edited_by,
        stream_id=break_obj.stream_id,
        break_id=break_obj.id,
        before_values={"name": break_obj.name, "notes": break_obj.notes},
        after_values={"name": name, "notes": notes},
    )

    return streamer_repo.find_break_by_id(streamer_database_name, break_obj.id)


def delete_break(streamer_database_name: str, break_obj: Break, deleted_by: str) -> None:
    """LLD 15.2: soft delete -- removes the break's gross/quantities from
    stream totals and frees its packs back to availability (both are
    automatic side effects of get_availability/aggregate_breaks_for_
    settlement excluding DELETED breaks, not extra bookkeeping here)."""
    if break_obj.status == STATUS_DELETED:
        raise BreakValidationError("This break is already deleted.")

    _assert_stream_not_completed(streamer_database_name, break_obj.stream_id)

    now = datetime.now(timezone.utc)

    streamer_repo.update_break_fields(streamer_database_name, break_obj.id, {
        "status": STATUS_DELETED, "deleted_at": now, "deleted_by": deleted_by, "updated_at": now,
    })

    audit_service.record_event(
        action_type="BREAK_DELETED",
        performed_by=deleted_by,
        stream_id=break_obj.stream_id,
        break_id=break_obj.id,
        before_values={"pack_lines": break_obj.pack_lines, "break_gross": break_obj.break_gross},
    )
