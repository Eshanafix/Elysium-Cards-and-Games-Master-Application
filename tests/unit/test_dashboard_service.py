from datetime import datetime, timedelta, timezone
from decimal import Decimal

from elysium.models.streams import STATUS_COMPLETED
from elysium.models.users import ROLE_STREAMER, User
from elysium.services import dashboard_service


class FakePrice:
    def __init__(self, resolved_pack_price):
        self.resolved_pack_price = resolved_pack_price


def make_stream(final_stream_gross, stream_profit, start_time):
    return type("FakeStream", (), {
        "final_stream_gross": final_stream_gross,
        "stream_profit": stream_profit,
        "start_time": start_time,
        "status": STATUS_COMPLETED,
    })()


def test_get_admin_summary_totals_packs_and_value(monkeypatch):
    monkeypatch.setattr(dashboard_service.repo, "list_inventory_current", lambda: {
        "p1": {"total_packs": 10}, "p2": {"total_packs": 5},
    })
    monkeypatch.setattr(dashboard_service.price_repo, "list_all_current_prices", lambda: {
        "p1": FakePrice(Decimal("2.00")), "p2": FakePrice(Decimal("3.00")),
    })
    monkeypatch.setattr(dashboard_service.repo, "list_users", lambda: [])

    summary = dashboard_service.get_admin_summary()

    assert summary["total_packs"] == 15
    assert summary["total_value"] == Decimal("35.00")  # 10*2 + 5*3


def test_get_admin_summary_skips_products_with_no_resolved_price(monkeypatch):
    monkeypatch.setattr(dashboard_service.repo, "list_inventory_current", lambda: {
        "p1": {"total_packs": 10}, "p2": {"total_packs": 5},
    })
    monkeypatch.setattr(dashboard_service.price_repo, "list_all_current_prices", lambda: {
        "p1": FakePrice(Decimal("2.00")), "p2": FakePrice(None),
    })
    monkeypatch.setattr(dashboard_service.repo, "list_users", lambda: [])

    summary = dashboard_service.get_admin_summary()

    assert summary["total_value"] == Decimal("20.00")  # only p1 counted


def test_get_admin_summary_computes_overall_profit_margin_across_streamers(monkeypatch):
    monkeypatch.setattr(dashboard_service.repo, "list_inventory_current", lambda: {})
    monkeypatch.setattr(dashboard_service.price_repo, "list_all_current_prices", lambda: {})

    streamer1 = User(id="s1", username="s1", password_hash="x", roles=[ROLE_STREAMER], streamer_database_name="elysium_s_a")
    streamer2 = User(id="s2", username="s2", password_hash="x", roles=[ROLE_STREAMER], streamer_database_name="elysium_s_b")
    monkeypatch.setattr(dashboard_service.repo, "list_users", lambda: [streamer1, streamer2])

    streams_by_db = {
        "elysium_s_a": [make_stream(Decimal("100"), Decimal("40"), datetime.now(timezone.utc))],
        "elysium_s_b": [make_stream(Decimal("100"), Decimal("20"), datetime.now(timezone.utc))],
    }
    monkeypatch.setattr(dashboard_service.streamer_repo, "list_streams", lambda db_name, status=None: streams_by_db[db_name])

    summary = dashboard_service.get_admin_summary()

    assert summary["total_gross"] == Decimal("200")
    assert summary["total_profit"] == Decimal("60")
    assert summary["overall_profit_margin"] == Decimal("60") / Decimal("200")


def test_get_admin_summary_margin_is_none_with_zero_gross(monkeypatch):
    monkeypatch.setattr(dashboard_service.repo, "list_inventory_current", lambda: {})
    monkeypatch.setattr(dashboard_service.price_repo, "list_all_current_prices", lambda: {})
    monkeypatch.setattr(dashboard_service.repo, "list_users", lambda: [])

    summary = dashboard_service.get_admin_summary()

    assert summary["overall_profit_margin"] is None


def test_get_streamer_weekly_summary_only_counts_this_week(monkeypatch):
    # Naive, matching real Mongo reads (the client isn't tz_aware) -- using
    # an aware "now" here would hide the naive/aware TypeError this test
    # exists to guard against.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    this_week_stream = make_stream(Decimal("50"), Decimal("20"), now)
    last_week_stream = make_stream(Decimal("999"), Decimal("999"), now - timedelta(days=10))

    monkeypatch.setattr(
        dashboard_service.streamer_repo, "list_streams",
        lambda db_name, status=None: [this_week_stream, last_week_stream],
    )

    summary = dashboard_service.get_streamer_weekly_summary("elysium_s_a")

    assert summary["streams_this_week"] == 1
    assert summary["gross_this_week"] == Decimal("50")
    assert summary["profit_this_week"] == Decimal("20")
    assert summary["profit_margin_this_week"] == Decimal("20") / Decimal("50")


def test_get_streamer_weekly_summary_no_streams_this_week(monkeypatch):
    monkeypatch.setattr(dashboard_service.streamer_repo, "list_streams", lambda db_name, status=None: [])

    summary = dashboard_service.get_streamer_weekly_summary("elysium_s_a")

    assert summary["streams_this_week"] == 0
    assert summary["profit_margin_this_week"] is None
