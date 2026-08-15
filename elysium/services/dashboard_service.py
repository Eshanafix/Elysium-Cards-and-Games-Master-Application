"""
Aggregated at-a-glance stats for the Dashboard screen (streamer request:
"cool widgets" -- total packs, total pack value, profit margins -- instead
of just connection/lock status).
"""

from datetime import date
from decimal import Decimal

from elysium.models.streams import STATUS_COMPLETED
from elysium.models.users import ROLE_STREAMER
from elysium.repositories import master_repository as repo
from elysium.repositories import price_repository as price_repo
from elysium.repositories import streamer_repository as streamer_repo


def get_admin_summary() -> dict:
    """Company-wide totals: current inventory value plus all-time profit
    margin across every streamer's completed streams."""
    inventory = repo.list_inventory_current()
    prices = price_repo.list_all_current_prices()

    total_packs = sum(doc["total_packs"] for doc in inventory.values())

    total_value = Decimal("0")
    for product_id, doc in inventory.items():
        price = prices.get(product_id)
        if price and price.resolved_pack_price is not None:
            total_value += price.resolved_pack_price * doc["total_packs"]

    total_gross = Decimal("0")
    total_profit = Decimal("0")
    streamer_users = [u for u in repo.list_users() if ROLE_STREAMER in u.roles and u.streamer_database_name]

    for streamer in streamer_users:
        for stream in streamer_repo.list_streams(streamer.streamer_database_name, status=STATUS_COMPLETED):
            if stream.final_stream_gross is not None:
                total_gross += stream.final_stream_gross
            if stream.stream_profit is not None:
                total_profit += stream.stream_profit

    overall_profit_margin = (total_profit / total_gross) if total_gross else None

    return {
        "total_packs": total_packs,
        "total_value": total_value,
        "total_gross": total_gross,
        "total_profit": total_profit,
        "overall_profit_margin": overall_profit_margin,
    }


def _average(values: list[Decimal]) -> Decimal | None:
    return (sum(values, Decimal("0")) / len(values)) if values else None


def get_streamer_stats(
    streamer_database_name: str, start_date: date | None = None, end_date: date | None = None,
) -> dict:
    """This streamer's own stream/break stats -- all-time by default, or
    truncated to [start_date, end_date] (inclusive) when either is given.
    Dates are compared against each stream's start_time; breaks inherit
    their parent stream's date since a break has no independent "when" a
    streamer would filter by."""
    streams = streamer_repo.list_streams(streamer_database_name, status=STATUS_COMPLETED)

    if start_date is not None:
        streams = [s for s in streams if s.start_time and s.start_time.date() >= start_date]
    if end_date is not None:
        streams = [s for s in streams if s.start_time and s.start_time.date() <= end_date]

    stream_grosses = [s.final_stream_gross for s in streams if s.final_stream_gross is not None]
    stream_profits = [s.stream_profit for s in streams if s.stream_profit is not None]
    total_gross = sum(stream_grosses, Decimal("0"))
    total_profit = sum(stream_profits, Decimal("0"))

    breaks = streamer_repo.list_breaks_for_streams(streamer_database_name, [s.id for s in streams])
    break_grosses = [b.break_gross for b in breaks if b.break_gross is not None]
    break_profits = [b.break_profit for b in breaks if b.break_profit is not None]

    return {
        "stream_count": len(streams),
        "avg_stream_gross": _average(stream_grosses),
        "avg_stream_profit": _average(stream_profits),
        "break_count": len(breaks),
        "avg_break_gross": _average(break_grosses),
        "avg_break_profit": _average(break_profits),
        "profit_margin": (total_profit / total_gross) if total_gross else None,
    }
