from datetime import date, datetime, timezone
from decimal import Decimal

from elysium.models.streams import STATUS_COMPLETED
from elysium.models.users import ROLE_STREAMER, User
from elysium.services import dashboard_service


class FakePrice:
    def __init__(self, resolved_pack_price):
        self.resolved_pack_price = resolved_pack_price


def make_stream(id, final_stream_gross, stream_profit, start_time):
    return type("FakeStream", (), {
        "id": id,
        "final_stream_gross": final_stream_gross,
        "stream_profit": stream_profit,
        "start_time": start_time,
        "status": STATUS_COMPLETED,
    })()


def make_break(break_gross, break_profit):
    return type("FakeBreak", (), {
        "break_gross": break_gross,
        "break_profit": break_profit,
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
        "elysium_s_a": [make_stream("st1", Decimal("100"), Decimal("40"), datetime.now(timezone.utc))],
        "elysium_s_b": [make_stream("st2", Decimal("100"), Decimal("20"), datetime.now(timezone.utc))],
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


def test_get_streamer_stats_all_time_averages_streams_and_breaks(monkeypatch):
    # Naive, matching real Mongo reads (the client isn't tz_aware).
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    streams = [
        make_stream("st1", Decimal("50"), Decimal("20"), now),
        make_stream("st2", Decimal("150"), Decimal("60"), now),
    ]
    breaks = [make_break(Decimal("30"), Decimal("10")), make_break(Decimal("50"), Decimal("20"))]

    monkeypatch.setattr(dashboard_service.streamer_repo, "list_streams", lambda db_name, status=None: streams)
    monkeypatch.setattr(
        dashboard_service.streamer_repo, "list_breaks_for_streams", lambda db_name, stream_ids: breaks,
    )

    stats = dashboard_service.get_streamer_stats("elysium_s_a")

    assert stats["stream_count"] == 2
    assert stats["avg_stream_gross"] == Decimal("100")  # (50+150)/2
    assert stats["avg_stream_profit"] == Decimal("40")  # (20+60)/2
    assert stats["break_count"] == 2
    assert stats["avg_break_gross"] == Decimal("40")  # (30+50)/2
    assert stats["avg_break_profit"] == Decimal("15")  # (10+20)/2
    assert stats["profit_margin"] == Decimal("80") / Decimal("200")


def test_get_streamer_stats_no_streams(monkeypatch):
    monkeypatch.setattr(dashboard_service.streamer_repo, "list_streams", lambda db_name, status=None: [])
    monkeypatch.setattr(
        dashboard_service.streamer_repo, "list_breaks_for_streams", lambda db_name, stream_ids: [],
    )

    stats = dashboard_service.get_streamer_stats("elysium_s_a")

    assert stats["stream_count"] == 0
    assert stats["avg_stream_gross"] is None
    assert stats["avg_break_gross"] is None
    assert stats["profit_margin"] is None


def test_get_streamer_stats_truncates_by_date_range(monkeypatch):
    in_range = make_stream("st1", Decimal("50"), Decimal("20"), datetime(2026, 6, 15))
    before_range = make_stream("st2", Decimal("999"), Decimal("999"), datetime(2026, 5, 1))
    after_range = make_stream("st3", Decimal("999"), Decimal("999"), datetime(2026, 7, 1))

    monkeypatch.setattr(
        dashboard_service.streamer_repo, "list_streams",
        lambda db_name, status=None: [in_range, before_range, after_range],
    )
    captured_stream_ids = {}
    monkeypatch.setattr(
        dashboard_service.streamer_repo, "list_breaks_for_streams",
        lambda db_name, stream_ids: captured_stream_ids.setdefault("ids", stream_ids) and [],
    )

    stats = dashboard_service.get_streamer_stats(
        "elysium_s_a", start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
    )

    assert stats["stream_count"] == 1
    assert stats["avg_stream_gross"] == Decimal("50")
    assert captured_stream_ids["ids"] == ["st1"]
