"""
Admin correction of a completed stream (LLD section 17.6; docs/
IMPLEMENTATION_PLAN.md section 4.6). Corrections only apply after
end_stream has already run its one-time permanent deduction -- a
correction's job is to adjust that deduction by a *delta* against
whatever the streamer's live ledger balance is right now, using the
physically_deductible/unbacked split so master.inventory_current.total_packs
can never go negative while the streamer's ledger absorbs the rest (or is
capped at zero, per shortage_choice).

Stored break/stream historical figures (pack usage, market value, profit)
always reflect the full corrected quantity -- only the inventory-side
deduction is split/capped by shortage_choice (plan section 4.6, "important
nuance").
"""

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from elysium.models.breaks import STATUS_DELETED as BREAK_STATUS_DELETED
from elysium.models.discrepancies import (
    SOURCE_STREAM_CORRECTION,
    TYPE_NEGATIVE_INVENTORY,
    TYPE_UNDEDUCTED_SHORTAGE,
)
from elysium.models.prices import convert_decimals_to_decimal128
from elysium.models.streams import STATUS_COMPLETED
from elysium.repositories import streamer_repository as streamer_repo
from elysium.services import audit_service, discrepancy_service
from elysium.services.mongo_client import get_client, get_master_db, get_streamer_db
from elysium.services.stream_service import aggregate_breaks_for_settlement, compute_stream_profit

logger = logging.getLogger(__name__)

CHOICE_A_NEGATIVE = "A_NEGATIVE"
CHOICE_B_BLOCKED = "B_BLOCKED"
CHOICE_C_PARTIAL = "C_PARTIAL"
CHOICE_D_CANCELED = "D_CANCELED"

_WRITABLE_CHOICES = (CHOICE_A_NEGATIVE, CHOICE_C_PARTIAL)


class CorrectionValidationError(Exception):
    pass


class CorrectionBlockedError(Exception):
    pass


def _require_completed_stream(streamer_database_name: str, stream_id: str, session=None):
    stream = streamer_repo.find_stream_by_id(streamer_database_name, stream_id, session=session)

    if stream is None:
        raise CorrectionValidationError(f"No such stream: {stream_id}")

    if stream.status != STATUS_COMPLETED:
        raise CorrectionValidationError(
            "Only a completed stream can be corrected -- this stream is still "
            f"{stream.status}."
        )

    return stream


def _resolve_unit_price(stream, old_line: dict | None, product_id: str, historical_prices: dict[str, Decimal] | None):
    if old_line is not None:
        return old_line["locked_unit_price"], old_line["price_source"]

    snapshot_entry = stream.price_for_product(product_id)
    if snapshot_entry is not None:
        return snapshot_entry["resolved_pack_price"], snapshot_entry["price_source"]

    if historical_prices and product_id in historical_prices:
        return historical_prices[product_id], "MANUAL_HISTORICAL"

    raise CorrectionValidationError(
        f"Product '{product_id}' was not part of this stream's original price snapshot -- "
        "supply a historical price for it to add it via correction."
    )


def _build_corrected_pack_lines(stream, break_obj, pack_line_changes: dict[str, int], historical_prices: dict[str, Decimal] | None):
    """Returns (new_pack_lines, deltas_by_product) where deltas_by_product
    is new_quantity - old_quantity for every product touched by this
    correction (0 excluded)."""
    lines_by_product = {line["product_id"]: dict(line) for line in break_obj.pack_lines}
    deltas: dict[str, int] = {}

    for product_id, new_qty in pack_line_changes.items():
        if new_qty < 0:
            raise CorrectionValidationError("Corrected pack quantities cannot be negative.")

        old_line = lines_by_product.get(product_id)
        old_qty = old_line["quantity"] if old_line else 0
        delta = new_qty - old_qty

        if delta == 0:
            continue

        deltas[product_id] = delta

        if new_qty == 0:
            lines_by_product.pop(product_id, None)
            continue

        unit_price, price_source = _resolve_unit_price(stream, old_line, product_id, historical_prices)
        lines_by_product[product_id] = {
            "product_id": product_id,
            "quantity": new_qty,
            "locked_unit_price": unit_price,
            "price_source": price_source,
            "line_market_value": unit_price * new_qty,
        }

    return list(lines_by_product.values()), deltas


def compute_shortage_split(shortage: int, current_balance: int, choice: str) -> tuple[int, int, int]:
    """Pure math for plan section 4.6's physical-vs-ledger split. Returns
    (physically_deductible, unbacked, new_balance).

    physically_deductible = max(0, min(shortage, current_balance)) -- always
    provably <= current_balance, which is itself already counted inside
    master.total_packs under the invariant, so total_packs can never be
    pushed negative by a correction.
    """
    physically_deductible = max(0, min(shortage, current_balance))
    unbacked = shortage - physically_deductible
    new_balance = (current_balance - shortage) if choice == CHOICE_A_NEGATIVE else max(0, current_balance - shortage)
    return physically_deductible, unbacked, new_balance


def _apply_shortage_split(
    master_db, streamer_db, streamer_id: str, streamer_database_name: str,
    positive_deltas: dict[str, int], shortage_choice: str | None, admin_id: str,
    stream_id: str, now, session,
) -> tuple[int, dict[str, int]]:
    """Applies choice A/C physical-vs-ledger split (plan section 4.6) for
    every product whose corrected usage increased. Returns
    (physically_deducted_total, unbacked_by_product)."""
    shortage_total = sum(positive_deltas.values())

    if shortage_total <= 0:
        return 0, {}

    if shortage_choice == CHOICE_B_BLOCKED:
        raise CorrectionBlockedError(
            "Correction blocked: add or return inventory for the shortfall before "
            "re-attempting this correction."
        )

    if shortage_choice not in _WRITABLE_CHOICES:
        raise CorrectionValidationError(
            "This correction increases pack usage beyond the streamer's current balance "
            "for at least one product -- a shortage choice (allow negative, or deduct "
            "available and record a discrepancy) is required."
        )

    physically_deducted_total = 0
    unbacked_by_product: dict[str, int] = {}

    for product_id, shortage in positive_deltas.items():
        allocation = master_db.streamer_allocations.find_one(
            {"streamer_id": streamer_id, "product_id": product_id}, session=session
        )
        current_balance = allocation["current_packs"] if allocation else 0

        physically_deductible, unbacked, new_balance = compute_shortage_split(shortage, current_balance, shortage_choice)

        master_db.streamer_allocations.update_one(
            {"streamer_id": streamer_id, "product_id": product_id},
            {"$set": {"current_packs": new_balance, "updated_at": now}, "$inc": {"version": 1}},
            upsert=True,
            session=session,
        )
        streamer_db.inventory_current.update_one(
            {"_id": product_id},
            {"$set": {"current_packs": new_balance, "updated_at": now, "product_id": product_id}},
            upsert=True,
            session=session,
        )

        if physically_deductible:
            master_db.inventory_current.update_one(
                {"_id": product_id},
                {"$inc": {"total_packs": -physically_deductible, "version": 1}, "$set": {"updated_at": now}},
                session=session,
            )
            physically_deducted_total += physically_deductible

        if unbacked > 0:
            discrepancy_type = TYPE_NEGATIVE_INVENTORY if shortage_choice == CHOICE_A_NEGATIVE else TYPE_UNDEDUCTED_SHORTAGE
            discrepancy_service.open_or_increment_discrepancy(
                streamer_id, product_id, discrepancy_type, unbacked,
                SOURCE_STREAM_CORRECTION, admin_id, related_stream_id=stream_id, session=session,
            )
            unbacked_by_product[product_id] = unbacked

    return physically_deducted_total, unbacked_by_product


def _apply_usage_decreases(master_db, streamer_db, streamer_id: str, negative_deltas: dict[str, int], now, session) -> None:
    """A downward correction means those packs were never actually used --
    the exact inverse of end_stream's original deduction (plan section
    4.6): they're restored to the streamer's live ledger and back into
    master.total_packs (they never left physical existence, so this never
    risks the non-negative invariant)."""
    for product_id, delta in negative_deltas.items():
        restored = -delta

        streamer_db.inventory_current.update_one(
            {"_id": product_id},
            {"$inc": {"current_packs": restored}, "$set": {"updated_at": now, "product_id": product_id}},
            upsert=True,
            session=session,
        )
        master_db.streamer_allocations.update_one(
            {"streamer_id": streamer_id, "product_id": product_id},
            {"$inc": {"current_packs": restored, "version": 1}, "$set": {"updated_at": now}},
            upsert=True,
            session=session,
        )
        master_db.inventory_current.update_one(
            {"_id": product_id},
            {"$inc": {"total_packs": restored}, "$set": {"updated_at": now}},
            session=session,
        )


def _recompute_and_push_stream_correction(
    streamer_db, stream_id: str, streamer_database_name: str, correction_record: dict, now, session,
) -> None:
    breaks = streamer_repo.list_breaks_for_stream(streamer_database_name, stream_id, session=session)
    aggregates = aggregate_breaks_for_settlement(breaks)
    stream = streamer_repo.find_stream_by_id(streamer_database_name, stream_id, session=session)

    fields = {
        "sum_of_break_gross": aggregates["sum_of_break_gross"],
        "stream_pack_market_value": aggregates["stream_pack_market_value"],
        "updated_at": now,
    }

    if stream.final_stream_gross is not None:
        fields["gross_difference"] = stream.final_stream_gross - aggregates["sum_of_break_gross"]
        stream_profit = compute_stream_profit(stream.final_stream_gross, aggregates["stream_pack_market_value"])
        fields["stream_profit"] = stream_profit
        fields["stream_profit_margin"] = (stream_profit / stream.final_stream_gross) if stream.final_stream_gross != 0 else None

    update = convert_decimals_to_decimal128({"$set": fields, "$push": {"corrections": correction_record}})

    streamer_db.streams.update_one({"_id": stream_id}, update, session=session)


def correct_break(
    stream_id: str,
    streamer_id: str,
    streamer_database_name: str,
    break_id: str,
    admin_id: str,
    reason: str,
    pack_line_changes: dict[str, int] | None = None,
    new_break_gross: Decimal | None = None,
    historical_prices: dict[str, Decimal] | None = None,
    shortage_choice: str | None = None,
):
    if not reason or not reason.strip():
        raise CorrectionValidationError("A reason is required to correct a break.")

    if not pack_line_changes and new_break_gross is None:
        raise CorrectionValidationError("Nothing to correct: no pack line changes or gross override given.")

    client = get_client()
    master_db = get_master_db()
    streamer_db = get_streamer_db(streamer_database_name)
    now = datetime.now(timezone.utc)

    def callback(session):
        stream = _require_completed_stream(streamer_database_name, stream_id, session=session)
        break_obj = streamer_repo.find_break_by_id(streamer_database_name, break_id, session=session)

        if break_obj is None or break_obj.stream_id != stream_id:
            raise CorrectionValidationError(f"No such break '{break_id}' on stream '{stream_id}'.")

        if break_obj.status == BREAK_STATUS_DELETED:
            raise CorrectionValidationError("Cannot correct a deleted break.")

        before = {
            "pack_lines": break_obj.pack_lines,
            "total_pack_market_value": break_obj.total_pack_market_value,
            "break_gross": break_obj.break_gross,
            "break_profit": break_obj.break_profit,
        }

        if pack_line_changes:
            new_pack_lines, deltas = _build_corrected_pack_lines(stream, break_obj, pack_line_changes, historical_prices)
        else:
            new_pack_lines, deltas = list(break_obj.pack_lines), {}

        positive_deltas = {pid: d for pid, d in deltas.items() if d > 0}
        negative_deltas = {pid: d for pid, d in deltas.items() if d < 0}

        physically_deducted_total, unbacked_by_product = _apply_shortage_split(
            master_db, streamer_db, streamer_id, streamer_database_name,
            positive_deltas, shortage_choice, admin_id, stream_id, now, session,
        )
        _apply_usage_decreases(master_db, streamer_db, streamer_id, negative_deltas, now, session)

        total_pack_market_value = sum((line["line_market_value"] for line in new_pack_lines), Decimal("0"))
        break_gross = new_break_gross if new_break_gross is not None else break_obj.break_gross
        break_profit = (break_gross - total_pack_market_value) if break_gross is not None else None
        break_profit_margin = (break_profit / break_gross) if (break_gross not in (None, Decimal("0")) and break_profit is not None) else None

        streamer_repo.update_break_fields(
            streamer_database_name, break_id,
            {
                "pack_lines": new_pack_lines,
                "total_pack_market_value": total_pack_market_value,
                "break_gross": break_gross,
                "break_profit": break_profit,
                "break_profit_margin": break_profit_margin,
                "updated_at": now,
            },
            session=session,
        )

        after = {
            "pack_lines": new_pack_lines,
            "total_pack_market_value": total_pack_market_value,
            "break_gross": break_gross,
            "break_profit": break_profit,
        }

        unbacked_total = sum(unbacked_by_product.values())
        correction_record = {
            "correction_id": str(uuid.uuid4()),
            "admin_id": admin_id,
            "timestamp": now,
            "reason": reason,
            "before": before,
            "after": after,
            "inventory_effect": {"deltas_by_product": deltas} if deltas else None,
            "profit_effect": {"before": before["break_profit"], "after": break_profit},
            "affected_break_ids": [break_id],
            "affected_product_ids": list(deltas.keys()),
            "shortage_choice": shortage_choice if positive_deltas else None,
            "shortage_quantity": unbacked_total if unbacked_by_product else None,
            "physically_deducted_quantity": physically_deducted_total if deltas else None,
        }

        _recompute_and_push_stream_correction(streamer_db, stream_id, streamer_database_name, correction_record, now, session)

        audit_service.record_event(
            action_type="STREAM_BREAK_CORRECTED",
            performed_by=admin_id,
            streamer_id=streamer_id,
            stream_id=stream_id,
            break_id=break_id,
            reason=reason,
            before_values=before,
            after_values=after,
            related_transaction_id=correction_record["correction_id"],
            session=session,
        )

    with client.start_session() as session:
        session.with_transaction(callback)

    logger.info("Admin '%s' corrected break '%s' on stream '%s' (reason: %s)", admin_id, break_id, stream_id, reason)
    return streamer_repo.find_stream_by_id(streamer_database_name, stream_id)


def correct_final_stream_gross(
    stream_id: str,
    streamer_id: str,
    streamer_database_name: str,
    admin_id: str,
    reason: str,
    new_final_stream_gross: Decimal,
):
    if not reason or not reason.strip():
        raise CorrectionValidationError("A reason is required to correct final stream gross.")

    if new_final_stream_gross < 0:
        raise CorrectionValidationError("Final stream gross cannot be negative.")

    client = get_client()
    now = datetime.now(timezone.utc)

    def callback(session):
        stream = _require_completed_stream(streamer_database_name, stream_id, session=session)

        before = {"final_stream_gross": stream.final_stream_gross, "stream_profit": stream.stream_profit}

        gross_difference = new_final_stream_gross - stream.sum_of_break_gross
        stream_profit = compute_stream_profit(new_final_stream_gross, stream.stream_pack_market_value)
        stream_profit_margin = (stream_profit / new_final_stream_gross) if new_final_stream_gross != 0 else None

        after = {"final_stream_gross": new_final_stream_gross, "stream_profit": stream_profit}

        correction_record = {
            "correction_id": str(uuid.uuid4()),
            "admin_id": admin_id,
            "timestamp": now,
            "reason": reason,
            "before": before,
            "after": after,
            "inventory_effect": None,
            "profit_effect": {"before": before["stream_profit"], "after": stream_profit},
            "affected_break_ids": [],
            "affected_product_ids": [],
            "shortage_choice": None,
            "shortage_quantity": None,
            "physically_deducted_quantity": None,
        }

        fields = {
            "final_stream_gross": new_final_stream_gross,
            "gross_difference": gross_difference,
            "stream_profit": stream_profit,
            "stream_profit_margin": stream_profit_margin,
            "updated_at": now,
        }
        update = convert_decimals_to_decimal128({"$set": fields, "$push": {"corrections": correction_record}})
        get_streamer_db(streamer_database_name).streams.update_one({"_id": stream_id}, update, session=session)

        audit_service.record_event(
            action_type="STREAM_GROSS_CORRECTED",
            performed_by=admin_id,
            streamer_id=streamer_id,
            stream_id=stream_id,
            reason=reason,
            before_values=before,
            after_values=after,
            related_transaction_id=correction_record["correction_id"],
            session=session,
        )

    with client.start_session() as session:
        session.with_transaction(callback)

    logger.info("Admin '%s' corrected final stream gross on stream '%s' (reason: %s)", admin_id, stream_id, reason)
    return streamer_repo.find_stream_by_id(streamer_database_name, stream_id)
