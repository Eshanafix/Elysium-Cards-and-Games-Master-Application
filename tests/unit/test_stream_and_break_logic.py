from datetime import datetime, timezone
from decimal import Decimal

from elysium.models.breaks import STATUS_ACTIVE, STATUS_DELETED, STATUS_ENDED_EDITABLE, Break
from elysium.models.streams import Stream
from elysium.services.break_service import get_availability
from elysium.services.stream_service import aggregate_breaks_for_settlement, compute_stream_profit


def make_break(break_id, pack_lines=None, break_gross=None, total_pack_market_value=None, status=STATUS_ENDED_EDITABLE):
    return Break(
        id=break_id,
        stream_id="stream-1",
        sequence_number=1,
        status=status,
        pack_lines=pack_lines or [],
        break_gross=break_gross,
        total_pack_market_value=total_pack_market_value or Decimal("0"),
    )


def make_pack_line(product_id, quantity, unit_price):
    return {
        "product_id": product_id,
        "quantity": quantity,
        "locked_unit_price": unit_price,
        "price_source": "LOOSE_PACK_MARKET",
        "line_market_value": unit_price * quantity,
    }


def make_stream(inventory_snapshot):
    return Stream(
        id="stream-1",
        streamer_id="streamer-1",
        status="ACTIVE",
        start_time=datetime.now(timezone.utc),
        inventory_snapshot=inventory_snapshot,
        price_snapshot=[],
    )


# --- aggregate_breaks_for_settlement (LLD 15.4) ---

def test_aggregate_example_a_single_break_from_lld():
    # LLD 32 Example A: 3 DMU Draft @ $3.50 + 1 RVR Draft @ $5.25.
    lines = [
        make_pack_line("dmu-draft", 3, Decimal("3.50")),
        make_pack_line("rvr-draft", 1, Decimal("5.25")),
    ]
    b = make_break("b1", pack_lines=lines, break_gross=Decimal("30.00"), total_pack_market_value=Decimal("15.75"))

    result = aggregate_breaks_for_settlement([b])

    assert result["sum_of_break_gross"] == Decimal("30.00")
    assert result["stream_pack_market_value"] == Decimal("15.75")
    assert result["used_packs_by_product"] == {"dmu-draft": 3, "rvr-draft": 1}


def test_aggregate_example_b_multiple_breaks_from_lld():
    # LLD 32 Example B: break1 gross=100 mv=60, break2 gross=150 mv=90.
    b1 = make_break("b1", break_gross=Decimal("100.00"), total_pack_market_value=Decimal("60.00"))
    b2 = make_break("b2", break_gross=Decimal("150.00"), total_pack_market_value=Decimal("90.00"))

    result = aggregate_breaks_for_settlement([b1, b2])

    assert result["sum_of_break_gross"] == Decimal("250.00")
    assert result["stream_pack_market_value"] == Decimal("150.00")


def test_aggregate_excludes_nothing_it_is_not_given_deleted_breaks_are_caller_responsibility():
    # aggregate_breaks_for_settlement trusts its input list; callers (stream_service.end_stream)
    # source it from list_breaks_for_stream, which excludes DELETED by default.
    b1 = make_break("b1", break_gross=Decimal("10"), total_pack_market_value=Decimal("5"))
    result = aggregate_breaks_for_settlement([b1])
    assert result["sum_of_break_gross"] == Decimal("10")


def test_aggregate_sums_quantities_for_same_product_across_breaks():
    b1 = make_break("b1", pack_lines=[make_pack_line("p1", 2, Decimal("1.00"))])
    b2 = make_break("b2", pack_lines=[make_pack_line("p1", 3, Decimal("1.00"))])

    result = aggregate_breaks_for_settlement([b1, b2])

    assert result["used_packs_by_product"] == {"p1": 5}


def test_aggregate_empty_breaks_list():
    result = aggregate_breaks_for_settlement([])
    assert result["sum_of_break_gross"] == 0
    assert result["stream_pack_market_value"] == 0
    assert result["used_packs_by_product"] == {}


# --- compute_stream_profit / gross difference (LLD 15.4, 29.12, 32) ---

def test_compute_stream_profit_example_a():
    assert compute_stream_profit(Decimal("30.00"), Decimal("15.75")) == Decimal("14.25")


def test_compute_stream_profit_example_b():
    assert compute_stream_profit(Decimal("235.00"), Decimal("150.00")) == Decimal("85.00")


def test_compute_stream_profit_lld_2912_example():
    # LLD 29.12: break gross total=500, final gross=480, market value=300 -> profit=180
    assert compute_stream_profit(Decimal("480"), Decimal("300")) == Decimal("180")


def test_gross_difference_example_b():
    sum_of_break_gross = Decimal("250.00")
    final_stream_gross = Decimal("235.00")
    assert (final_stream_gross - sum_of_break_gross) == Decimal("-15.00")


# --- get_availability (LLD 14.2) ---

def test_availability_with_no_breaks_equals_snapshot():
    stream = make_stream([{"product_id": "p1", "packs_at_start": 10}])
    availability = get_availability(stream, [], "unused-db-name")
    assert availability == {"p1": 10}


def test_availability_subtracts_active_and_ended_breaks():
    stream = make_stream([{"product_id": "p1", "packs_at_start": 10}])
    b1 = make_break("b1", pack_lines=[make_pack_line("p1", 3, Decimal("1"))], status=STATUS_ACTIVE)
    b2 = make_break("b2", pack_lines=[make_pack_line("p1", 2, Decimal("1"))], status=STATUS_ENDED_EDITABLE)

    availability = get_availability(stream, [b1, b2], "unused-db-name")

    assert availability == {"p1": 5}


def test_availability_ignores_deleted_breaks_even_if_passed_in():
    stream = make_stream([{"product_id": "p1", "packs_at_start": 10}])
    deleted = make_break("b1", pack_lines=[make_pack_line("p1", 7, Decimal("1"))], status=STATUS_DELETED)

    availability = get_availability(stream, [deleted], "unused-db-name")

    assert availability == {"p1": 10}  # deleted break's usage must not count


def test_availability_multiple_products():
    stream = make_stream([
        {"product_id": "p1", "packs_at_start": 10},
        {"product_id": "p2", "packs_at_start": 5},
    ])
    b1 = make_break("b1", pack_lines=[
        make_pack_line("p1", 4, Decimal("1")),
        make_pack_line("p2", 5, Decimal("2")),
    ])

    availability = get_availability(stream, [b1], "unused-db-name")

    assert availability == {"p1": 6, "p2": 0}
