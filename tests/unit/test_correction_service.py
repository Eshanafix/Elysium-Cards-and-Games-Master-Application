from datetime import datetime, timezone
from decimal import Decimal

import pytest

from elysium.models.breaks import STATUS_ENDED_EDITABLE, Break
from elysium.models.streams import STATUS_COMPLETED, Stream
from elysium.services import correction_service


# --- compute_shortage_split (plan section 4.6 physical/ledger split) ---


def test_shortage_split_choice_a_matches_plan_worked_example():
    """Plan section 4.6's canonical example: streamer has 2, correction
    adds 5 more used, admin chooses 'allow negative' -- physically_deductible
    = min(5, 2) = 2, unbacked = 3, ledger becomes 2 - 5 = -3."""
    physically_deductible, unbacked, new_balance = correction_service.compute_shortage_split(
        shortage=5, current_balance=2, choice=correction_service.CHOICE_A_NEGATIVE
    )

    assert physically_deductible == 2
    assert unbacked == 3
    assert new_balance == -3


def test_shortage_split_choice_c_clamps_ledger_at_zero():
    physically_deductible, unbacked, new_balance = correction_service.compute_shortage_split(
        shortage=5, current_balance=2, choice=correction_service.CHOICE_C_PARTIAL
    )

    assert physically_deductible == 2
    assert unbacked == 3
    assert new_balance == 0


def test_shortage_split_fully_covered_by_balance():
    physically_deductible, unbacked, new_balance = correction_service.compute_shortage_split(
        shortage=2, current_balance=5, choice=correction_service.CHOICE_A_NEGATIVE
    )

    assert physically_deductible == 2
    assert unbacked == 0
    assert new_balance == 3


def test_shortage_split_zero_balance():
    physically_deductible, unbacked, new_balance = correction_service.compute_shortage_split(
        shortage=4, current_balance=0, choice=correction_service.CHOICE_C_PARTIAL
    )

    assert physically_deductible == 0
    assert unbacked == 4
    assert new_balance == 0


# --- _build_corrected_pack_lines ---


def _make_stream(price_snapshot=None):
    return Stream(
        id="stream-1",
        streamer_id="streamer-1",
        status=STATUS_COMPLETED,
        start_time=datetime.now(timezone.utc),
        price_snapshot=price_snapshot or [],
    )


def _make_break(pack_lines):
    return Break(
        id="break-1",
        stream_id="stream-1",
        sequence_number=1,
        status=STATUS_ENDED_EDITABLE,
        pack_lines=pack_lines,
    )


def test_build_corrected_pack_lines_edits_existing_line():
    break_obj = _make_break([
        {"product_id": "p1", "quantity": 3, "locked_unit_price": Decimal("10.00"),
         "price_source": "LOOSE_PACK_MARKET", "line_market_value": Decimal("30.00")},
    ])
    stream = _make_stream()

    new_lines, deltas = correction_service._build_corrected_pack_lines(stream, break_obj, {"p1": 5}, None)

    assert deltas == {"p1": 2}
    line = next(l for l in new_lines if l["product_id"] == "p1")
    assert line["quantity"] == 5
    assert line["locked_unit_price"] == Decimal("10.00")
    assert line["line_market_value"] == Decimal("50.00")


def test_build_corrected_pack_lines_zero_quantity_removes_line():
    break_obj = _make_break([
        {"product_id": "p1", "quantity": 3, "locked_unit_price": Decimal("10.00"),
         "price_source": "LOOSE_PACK_MARKET", "line_market_value": Decimal("30.00")},
    ])
    stream = _make_stream()

    new_lines, deltas = correction_service._build_corrected_pack_lines(stream, break_obj, {"p1": 0}, None)

    assert new_lines == []
    assert deltas == {"p1": -3}


def test_build_corrected_pack_lines_new_product_uses_stream_snapshot_price():
    break_obj = _make_break([])
    stream = _make_stream(price_snapshot=[{
        "product_id": "p2", "resolved_pack_price": Decimal("7.50"), "price_source": "DERIVED_FROM_BOX_MARKET",
    }])

    new_lines, deltas = correction_service._build_corrected_pack_lines(stream, break_obj, {"p2": 4}, None)

    assert deltas == {"p2": 4}
    line = new_lines[0]
    assert line["locked_unit_price"] == Decimal("7.50")
    assert line["price_source"] == "DERIVED_FROM_BOX_MARKET"
    assert line["line_market_value"] == Decimal("30.00")


def test_build_corrected_pack_lines_new_product_uses_historical_price_when_no_snapshot():
    break_obj = _make_break([])
    stream = _make_stream()

    new_lines, deltas = correction_service._build_corrected_pack_lines(
        stream, break_obj, {"p3": 2}, {"p3": Decimal("12.00")}
    )

    line = new_lines[0]
    assert line["locked_unit_price"] == Decimal("12.00")
    assert line["price_source"] == "MANUAL_HISTORICAL"
    assert line["line_market_value"] == Decimal("24.00")


def test_build_corrected_pack_lines_new_product_without_any_price_raises():
    break_obj = _make_break([])
    stream = _make_stream()

    with pytest.raises(correction_service.CorrectionValidationError):
        correction_service._build_corrected_pack_lines(stream, break_obj, {"p4": 1}, None)


def test_build_corrected_pack_lines_negative_quantity_raises():
    break_obj = _make_break([])
    stream = _make_stream()

    with pytest.raises(correction_service.CorrectionValidationError):
        correction_service._build_corrected_pack_lines(stream, break_obj, {"p1": -1}, None)


# --- _apply_shortage_split (choice validation / discrepancy creation) ---


class FakeCollection:
    def __init__(self, docs_by_id=None):
        self.docs_by_id = docs_by_id or {}
        self.update_calls = []

    def find_one(self, query, session=None):
        key = (query.get("streamer_id"), query.get("product_id")) if "streamer_id" in query else query.get("_id")
        return self.docs_by_id.get(key)

    def update_one(self, query, update, upsert=False, session=None):
        self.update_calls.append((query, update))


class FakeDb:
    def __init__(self, streamer_allocations=None, inventory_current=None):
        self.streamer_allocations = streamer_allocations or FakeCollection()
        self.inventory_current = inventory_current or FakeCollection()


def test_apply_shortage_split_requires_a_choice_when_shortage_exists(monkeypatch):
    master_db = FakeDb(streamer_allocations=FakeCollection({("streamer-1", "p1"): {"current_packs": 2}}))
    streamer_db = FakeDb()

    with pytest.raises(correction_service.CorrectionValidationError):
        correction_service._apply_shortage_split(
            master_db, streamer_db, "streamer-1", "db-name", {"p1": 5}, None, "admin-1", "stream-1",
            datetime.now(timezone.utc), session=None,
        )


def test_apply_shortage_split_choice_b_always_blocks():
    master_db = FakeDb(streamer_allocations=FakeCollection({("streamer-1", "p1"): {"current_packs": 2}}))
    streamer_db = FakeDb()

    with pytest.raises(correction_service.CorrectionBlockedError):
        correction_service._apply_shortage_split(
            master_db, streamer_db, "streamer-1", "db-name", {"p1": 5},
            correction_service.CHOICE_B_BLOCKED, "admin-1", "stream-1", datetime.now(timezone.utc), session=None,
        )


def test_apply_shortage_split_choice_a_opens_negative_inventory_discrepancy(monkeypatch):
    captured = {}

    def fake_open_or_increment(streamer_id, product_id, discrepancy_type, quantity, source, created_by, related_stream_id=None, session=None):
        captured["type"] = discrepancy_type
        captured["quantity"] = quantity
        return "discrepancy-id"

    monkeypatch.setattr(correction_service.discrepancy_service, "open_or_increment_discrepancy", fake_open_or_increment)

    master_db = FakeDb(streamer_allocations=FakeCollection({("streamer-1", "p1"): {"current_packs": 2}}))
    streamer_db = FakeDb()

    physically_deducted_total, unbacked_by_product = correction_service._apply_shortage_split(
        master_db, streamer_db, "streamer-1", "db-name", {"p1": 5},
        correction_service.CHOICE_A_NEGATIVE, "admin-1", "stream-1", datetime.now(timezone.utc), session=None,
    )

    assert physically_deducted_total == 2
    assert unbacked_by_product == {"p1": 3}
    assert captured["type"] == "NEGATIVE_INVENTORY"
    assert captured["quantity"] == 3


def test_apply_shortage_split_no_shortage_is_a_noop():
    master_db = FakeDb()
    streamer_db = FakeDb()

    physically_deducted_total, unbacked_by_product = correction_service._apply_shortage_split(
        master_db, streamer_db, "streamer-1", "db-name", {}, None, "admin-1", "stream-1",
        datetime.now(timezone.utc), session=None,
    )

    assert physically_deducted_total == 0
    assert unbacked_by_product == {}
