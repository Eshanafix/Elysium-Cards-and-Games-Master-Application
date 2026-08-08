"""
Aggregated at-a-glance stats for the Dashboard screen (streamer request:
"cool widgets" -- total packs, total pack value, profit margins -- instead
of just connection/lock status).
"""

from datetime import datetime, timedelta, timezone
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


def _start_of_this_week(now: datetime) -> datetime:
    days_since_monday = now.weekday()
    return (now - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)


def get_streamer_weekly_summary(streamer_database_name: str) -> dict:
    """This streamer's own stream count and profit margin for the current
    calendar week (Monday 00:00 UTC through now)."""
    # PyMongo's default client isn't tz_aware, so every datetime read back
    # from Mongo (stream.start_time included) comes back naive -- but it's
    # still UTC wall-clock time underneath (BSON dates have no timezone
    # concept at all). Comparing against an aware datetime.now(timezone.utc)
    # crashes with "can't compare offset-naive and offset-aware datetimes";
    # stripping tzinfo here keeps the value UTC while making it comparable.
    week_start = _start_of_this_week(datetime.now(timezone.utc).replace(tzinfo=None))

    streams = streamer_repo.list_streams(streamer_database_name, status=STATUS_COMPLETED)
    this_week = [s for s in streams if s.start_time and s.start_time >= week_start]

    total_gross = Decimal("0")
    total_profit = Decimal("0")
    for stream in this_week:
        if stream.final_stream_gross is not None:
            total_gross += stream.final_stream_gross
        if stream.stream_profit is not None:
            total_profit += stream.stream_profit

    profit_margin_this_week = (total_profit / total_gross) if total_gross else None

    return {
        "streams_this_week": len(this_week),
        "gross_this_week": total_gross,
        "profit_this_week": total_profit,
        "profit_margin_this_week": profit_margin_this_week,
    }
