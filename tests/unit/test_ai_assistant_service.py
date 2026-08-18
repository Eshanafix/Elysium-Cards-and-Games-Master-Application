"""
Regression tests for elysium.services.ai_assistant_service: the shared-key
config roundtrip, and the break-profit-by-pack-count aggregation that
directly answers the motivating question ("do I make more profit on breaks
with 3 or 4 packs"). The actual Claude API call in ask() is not
network-tested here -- only its deterministic guard clauses are.
"""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from bson import Decimal128

from elysium.models.breaks import STATUS_ENDED_EDITABLE, Break
from elysium.models.decommission import STATUS_PENDING, DecommissionRequest
from elysium.models.discrepancies import (
    SOURCE_STREAM_CORRECTION,
    STATUS_OPEN,
    TYPE_NEGATIVE_INVENTORY,
    Discrepancy,
)
from elysium.models.products import Product
from elysium.models.streams import STATUS_COMPLETED, Stream
from elysium.models.users import ROLE_ADMIN, ROLE_STREAMER, User
from elysium.services import ai_assistant_service as svc


def make_stream(status, start_time, final_stream_gross=None, stream_profit=None):
    return Stream(id="st1", streamer_id="s1", status=status, start_time=start_time,
                   final_stream_gross=final_stream_gross, stream_profit=stream_profit)


def make_discrepancy(streamer_id, product_id, status=STATUS_OPEN):
    return Discrepancy(
        id="d1", streamer_id=streamer_id, product_id=product_id, type=TYPE_NEGATIVE_INVENTORY,
        quantity=3, source=SOURCE_STREAM_CORRECTION, status=status,
    )


def make_decommission_request(streamer_id, status=STATUS_PENDING):
    return DecommissionRequest(
        id="dr1", streamer_id=streamer_id, initiated_by="admin-1",
        initiated_at=datetime.now(timezone.utc).replace(tzinfo=None), status=status,
    )


def make_product(id, name):
    return Product(
        id=id, name=name, booster_type="PLAY", packs_per_box=36,
        tcgcsv_category_id="1", tcgcsv_group_id="1",
        loose_pack_tcgcsv_product_id="1", box_tcgcsv_product_id="2",
        image_url="https://example.com/img.jpg",
    )


def make_history_entry(product_id, previous_price, new_price, timestamp, source="LOOSE_PACK_MARKET"):
    return {
        "product_id": product_id,
        "previous_price": Decimal128(previous_price) if previous_price is not None else None,
        "new_price": Decimal128(new_price) if new_price is not None else None,
        "new_source": source,
        "timestamp": timestamp,
    }


def make_break(pack_lines, break_gross=None, break_profit=None):
    return Break(
        id="b1", stream_id="st1", sequence_number=1, status=STATUS_ENDED_EDITABLE,
        pack_lines=pack_lines, break_gross=break_gross, break_profit=break_profit,
    )


def three_packs():
    return [{"product_id": "p1", "quantity": 3, "locked_unit_price": None, "line_market_value": None}]


def four_packs():
    return [{"product_id": "p1", "quantity": 4, "locked_unit_price": None, "line_market_value": None}]


# --- is_configured / configure_api_key ---


def test_is_configured_false_when_no_config(monkeypatch):
    monkeypatch.setattr(svc.repo, "get_ai_assistant_config", lambda: None)
    assert svc.is_configured() is False


def test_is_configured_false_when_config_has_no_key(monkeypatch):
    monkeypatch.setattr(svc.repo, "get_ai_assistant_config", lambda: {"configured_by": "a1"})
    assert svc.is_configured() is False


def test_is_configured_true_when_key_present(monkeypatch):
    monkeypatch.setattr(svc.repo, "get_ai_assistant_config", lambda: {"api_key": "sk-ant-x"})
    assert svc.is_configured() is True


def test_configure_api_key_rejects_blank():
    with pytest.raises(ValueError):
        svc.configure_api_key("   ", "admin-1")


def test_configure_api_key_rejects_invalid_key(monkeypatch):
    monkeypatch.setattr(svc, "test_api_key", lambda key: (False, "invalid x-api-key"))

    with pytest.raises(ValueError):
        svc.configure_api_key("sk-ant-bad", "admin-1")


def test_configure_api_key_saves_and_audits_on_valid_key(monkeypatch):
    monkeypatch.setattr(svc, "test_api_key", lambda key: (True, "Connected."))

    written = {}
    audited = {}
    monkeypatch.setattr(svc.repo, "set_ai_assistant_config", lambda fields: written.update(fields))
    monkeypatch.setattr(svc.audit_service, "record_event", lambda **kwargs: audited.update(kwargs) or "event-id")

    svc.configure_api_key("sk-ant-good", "admin-1")

    assert written["api_key"] == "sk-ant-good"
    assert written["configured_by"] == "admin-1"
    assert audited["action_type"] == "AI_ASSISTANT_KEY_CONFIGURED"
    assert audited["performed_by"] == "admin-1"


# --- ask() guard clauses ---


def test_ask_rejects_blank_question():
    with pytest.raises(ValueError):
        svc.ask("   ", "admin-1")


def test_ask_raises_not_configured_when_no_key(monkeypatch):
    monkeypatch.setattr(svc.repo, "get_ai_assistant_config", lambda: None)

    with pytest.raises(svc.AiAssistantNotConfiguredError):
        svc.ask("How am I doing?", "admin-1")


# --- get_break_profit_by_pack_count ---


def test_break_profit_by_pack_count_groups_by_total_pack_quantity(monkeypatch):
    admin = User(id="a1", username="admin", password_hash="x", roles=[ROLE_ADMIN])
    streamer = User(
        id="s1", username="streamer1", password_hash="x", roles=[ROLE_STREAMER],
        streamer_database_name="elysium_s_a",
    )
    monkeypatch.setattr(svc.repo, "list_users", lambda: [admin, streamer])

    breaks = [
        make_break(three_packs(), Decimal("30"), Decimal("10")),
        make_break(three_packs(), Decimal("50"), Decimal("20")),
        make_break(four_packs(), Decimal("60"), Decimal("15")),
    ]
    monkeypatch.setattr(svc.streamer_repo, "list_all_breaks_for_streamer", lambda db_name: breaks)

    result = json.loads(svc.get_break_profit_by_pack_count.func())

    by_count = {row["pack_count"]: row for row in result}
    assert by_count[3]["break_count"] == 2
    assert by_count[3]["avg_break_gross"] == 40.0  # (30+50)/2
    assert by_count[3]["avg_break_profit"] == 15.0  # (10+20)/2
    assert by_count[4]["break_count"] == 1
    assert by_count[4]["avg_break_gross"] == 60.0


def test_break_profit_by_pack_count_excludes_breaks_with_no_gross_yet(monkeypatch):
    streamer = User(
        id="s1", username="streamer1", password_hash="x", roles=[ROLE_STREAMER],
        streamer_database_name="elysium_s_a",
    )
    monkeypatch.setattr(svc.repo, "list_users", lambda: [streamer])

    breaks = [
        make_break(three_packs(), break_gross=None, break_profit=None),  # still active, no gross
        make_break(three_packs(), Decimal("30"), Decimal("10")),
    ]
    monkeypatch.setattr(svc.streamer_repo, "list_all_breaks_for_streamer", lambda db_name: breaks)

    result = json.loads(svc.get_break_profit_by_pack_count.func())

    assert len(result) == 1
    assert result[0]["break_count"] == 1


def test_break_profit_by_pack_count_scopes_to_one_streamer_when_given(monkeypatch):
    streamer1 = User(
        id="s1", username="streamer1", password_hash="x", roles=[ROLE_STREAMER],
        streamer_database_name="elysium_s_a",
    )
    monkeypatch.setattr(svc.repo, "find_user_by_username", lambda username: streamer1 if username == "streamer1" else None)

    calls = []

    def fake_list_all_breaks_for_streamer(db_name):
        calls.append(db_name)
        return [make_break(three_packs(), Decimal("30"), Decimal("10"))]

    monkeypatch.setattr(svc.streamer_repo, "list_all_breaks_for_streamer", fake_list_all_breaks_for_streamer)

    result = json.loads(svc.get_break_profit_by_pack_count.func(streamer_username="streamer1"))

    assert calls == ["elysium_s_a"]
    assert result[0]["break_count"] == 1


def test_break_profit_by_pack_count_reports_error_for_unknown_streamer(monkeypatch):
    monkeypatch.setattr(svc.repo, "find_user_by_username", lambda username: None)

    result = json.loads(svc.get_break_profit_by_pack_count.func(streamer_username="nobody"))

    assert "error" in result


def test_streamer_performance_reports_error_for_unknown_streamer(monkeypatch):
    monkeypatch.setattr(svc.repo, "find_user_by_username", lambda username: None)

    result = json.loads(svc.get_streamer_performance.func(streamer_username="nobody"))

    assert "error" in result


# --- get_price_history / get_recent_price_changes ---


def test_price_history_matches_product_by_case_insensitive_substring(monkeypatch):
    product = make_product("p1", "Foundations Play Booster")
    monkeypatch.setattr(svc.repo, "list_products", lambda: [product])

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    history = [make_history_entry("p1", Decimal("4.00"), Decimal("4.50"), now)]
    monkeypatch.setattr(svc.price_repo, "list_price_history", lambda product_id, limit=500: history)

    result = json.loads(svc.get_price_history.func(product_name="foundations play"))

    assert result["product_name"] == "Foundations Play Booster"
    assert len(result["changes"]) == 1
    assert result["changes"][0]["previous_price"] == 4.0
    assert result["changes"][0]["new_price"] == 4.5


def test_price_history_reports_error_when_no_product_matches(monkeypatch):
    monkeypatch.setattr(svc.repo, "list_products", lambda: [make_product("p1", "Foundations Play Booster")])

    result = json.loads(svc.get_price_history.func(product_name="nonexistent set"))

    assert "error" in result


def test_price_history_reports_ambiguous_matches(monkeypatch):
    monkeypatch.setattr(svc.repo, "list_products", lambda: [
        make_product("p1", "Foundations Play Booster"), make_product("p2", "Foundations Collector Booster"),
    ])

    result = json.loads(svc.get_price_history.func(product_name="Foundations"))

    assert "error" in result
    assert len(result["matching_names"]) == 2


def test_price_history_excludes_changes_older_than_the_window(monkeypatch):
    monkeypatch.setattr(svc.repo, "list_products", lambda: [make_product("p1", "Foundations Play Booster")])

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    history = [
        make_history_entry("p1", Decimal("4.00"), Decimal("4.50"), now),
        make_history_entry("p1", Decimal("3.50"), Decimal("4.00"), now - timedelta(days=30)),
    ]
    monkeypatch.setattr(svc.price_repo, "list_price_history", lambda product_id, limit=500: history)

    result = json.loads(svc.get_price_history.func(product_name="Foundations Play Booster", days=7))

    assert len(result["changes"]) == 1
    assert result["changes"][0]["new_price"] == 4.5


def test_recent_price_changes_covers_every_product_with_names_attached(monkeypatch):
    monkeypatch.setattr(svc.repo, "list_products", lambda: [
        make_product("p1", "Foundations Play Booster"), make_product("p2", "Foundations Collector Booster"),
    ])

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    history = [
        make_history_entry("p1", Decimal("4.00"), Decimal("4.50"), now),
        make_history_entry("p2", Decimal("10.00"), Decimal("9.50"), now),
    ]
    monkeypatch.setattr(svc.price_repo, "list_price_history", lambda limit=2000: history)

    result = json.loads(svc.get_recent_price_changes.func(days=7))

    names = {c["product_name"] for c in result["changes"]}
    assert names == {"Foundations Play Booster", "Foundations Collector Booster"}


# --- list_users / get_product_catalog ---


def test_list_users_includes_roles_and_active_status(monkeypatch):
    admin = User(id="a1", username="admin", password_hash="x", roles=[ROLE_ADMIN], is_active=True)
    streamer = User(id="s1", username="streamer1", password_hash="x", roles=[ROLE_STREAMER], is_active=False)
    monkeypatch.setattr(svc.repo, "list_users", lambda: [admin, streamer])

    result = json.loads(svc.list_users.func())

    assert {"username": "admin", "roles": ["admin"], "is_active": True} in result
    assert {"username": "streamer1", "roles": ["streamer"], "is_active": False} in result


def test_product_catalog_excludes_inactive_by_default(monkeypatch):
    active = make_product("p1", "Foundations Play Booster")
    inactive = make_product("p2", "Retired Set Booster")
    inactive.is_active = False
    monkeypatch.setattr(svc.repo, "list_products", lambda: [active, inactive])

    result = json.loads(svc.get_product_catalog.func())

    assert [p["name"] for p in result] == ["Foundations Play Booster"]


def test_product_catalog_includes_inactive_when_requested(monkeypatch):
    active = make_product("p1", "Foundations Play Booster")
    inactive = make_product("p2", "Retired Set Booster")
    inactive.is_active = False
    monkeypatch.setattr(svc.repo, "list_products", lambda: [active, inactive])

    result = json.loads(svc.get_product_catalog.func(active_only=False))

    assert {p["name"] for p in result} == {"Foundations Play Booster", "Retired Set Booster"}


# --- get_streamer_allocations ---


def test_streamer_allocations_omits_zero_balance_rows(monkeypatch):
    streamer = User(id="s1", username="streamer1", password_hash="x", roles=[ROLE_STREAMER])
    monkeypatch.setattr(svc.repo, "list_users", lambda: [streamer])
    monkeypatch.setattr(svc.repo, "list_products", lambda: [make_product("p1", "Foundations Play Booster")])
    monkeypatch.setattr(svc.repo, "list_all_streamer_allocations", lambda: [
        {"streamer_id": "s1", "product_id": "p1", "current_packs": 12},
        {"streamer_id": "s1", "product_id": "p2", "current_packs": 0},
    ])

    result = json.loads(svc.get_streamer_allocations.func())

    assert len(result) == 1
    assert result[0]["streamer_username"] == "streamer1"
    assert result[0]["product_name"] == "Foundations Play Booster"
    assert result[0]["current_packs"] == 12


def test_streamer_allocations_reports_error_for_unknown_streamer(monkeypatch):
    monkeypatch.setattr(svc.repo, "find_user_by_username", lambda username: None)

    result = json.loads(svc.get_streamer_allocations.func(streamer_username="nobody"))

    assert "error" in result


# --- list_streams ---


def test_list_streams_filters_by_date_range_and_status(monkeypatch):
    streamer = User(id="s1", username="streamer1", password_hash="x", roles=[ROLE_STREAMER], streamer_database_name="elysium_s_a")
    monkeypatch.setattr(svc.repo, "find_user_by_username", lambda username: streamer)

    in_range = make_stream(STATUS_COMPLETED, datetime(2026, 6, 15), Decimal("100"), Decimal("40"))
    out_of_range = make_stream(STATUS_COMPLETED, datetime(2026, 5, 1), Decimal("999"), Decimal("999"))
    monkeypatch.setattr(svc.streamer_repo, "list_streams", lambda db_name, status=None: [in_range, out_of_range])

    result = json.loads(svc.list_streams.func(
        streamer_username="streamer1", start_date="2026-06-01", end_date="2026-06-30",
    ))

    assert len(result) == 1
    assert result[0]["final_stream_gross"] == 100.0


def test_list_streams_reports_error_for_unknown_streamer(monkeypatch):
    monkeypatch.setattr(svc.repo, "find_user_by_username", lambda username: None)

    result = json.loads(svc.list_streams.func(streamer_username="nobody"))

    assert "error" in result


# --- get_discrepancies ---


def test_discrepancies_defaults_to_open_status(monkeypatch):
    streamer = User(id="s1", username="streamer1", password_hash="x", roles=[ROLE_STREAMER])
    monkeypatch.setattr(svc.repo, "list_users", lambda: [streamer])
    monkeypatch.setattr(svc.repo, "list_products", lambda: [make_product("p1", "Foundations Play Booster")])

    captured = {}
    def fake_list_discrepancies(status=None):
        captured["status"] = status
        return [make_discrepancy("s1", "p1")]
    monkeypatch.setattr(svc.repo, "list_discrepancies", fake_list_discrepancies)

    result = json.loads(svc.get_discrepancies.func())

    assert captured["status"] == "OPEN"
    assert result[0]["streamer_username"] == "streamer1"
    assert result[0]["product_name"] == "Foundations Play Booster"


def test_discrepancies_scopes_to_one_streamer(monkeypatch):
    streamer = User(id="s1", username="streamer1", password_hash="x", roles=[ROLE_STREAMER])
    monkeypatch.setattr(svc.repo, "find_user_by_username", lambda username: streamer)
    monkeypatch.setattr(svc.repo, "list_users", lambda: [streamer])
    monkeypatch.setattr(svc.repo, "list_products", lambda: [])

    captured = {}
    def fake_list_for_streamer(streamer_id, status=None):
        captured["streamer_id"] = streamer_id
        captured["status"] = status
        return []
    monkeypatch.setattr(svc.repo, "list_discrepancies_for_streamer", fake_list_for_streamer)

    svc.get_discrepancies.func(status="", streamer_username="streamer1")

    assert captured == {"streamer_id": "s1", "status": None}


# --- get_decommission_requests ---


def test_decommission_requests_maps_streamer_id_to_username(monkeypatch):
    streamer = User(id="s1", username="streamer1", password_hash="x", roles=[ROLE_STREAMER])
    monkeypatch.setattr(svc.repo, "list_users", lambda: [streamer])
    monkeypatch.setattr(svc.repo, "list_decommission_requests", lambda status=None: [make_decommission_request("s1")])

    result = json.loads(svc.get_decommission_requests.func())

    assert result[0]["streamer_username"] == "streamer1"
    assert result[0]["status"] == STATUS_PENDING


# --- get_audit_history ---


def test_audit_history_resolves_streamer_and_product_names(monkeypatch):
    admin = User(id="a1", username="admin", password_hash="x", roles=[ROLE_ADMIN])
    streamer = User(id="s1", username="streamer1", password_hash="x", roles=[ROLE_STREAMER])
    monkeypatch.setattr(svc.repo, "list_users", lambda: [admin, streamer])
    monkeypatch.setattr(svc.repo, "list_products", lambda: [make_product("p1", "Foundations Play Booster")])
    monkeypatch.setattr(svc.repo, "find_user_by_username", lambda username: streamer if username == "streamer1" else None)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    monkeypatch.setattr(svc.audit_service, "list_events", lambda **kwargs: [{
        "action_type": "MASTER_INVENTORY_ADDED",
        "performed_by": "a1",
        "timestamp": now,
        "streamer_id": "s1",
        "product_id": "p1",
        "quantity_change": 10,
        "amount_change": Decimal128(Decimal("50.00")),
        "reason": None,
        "status": "SUCCESS",
    }])

    result = json.loads(svc.get_audit_history.func(streamer_username="streamer1"))

    assert result[0]["performed_by"] == "admin"
    assert result[0]["streamer"] == "streamer1"
    assert result[0]["product"] == "Foundations Play Booster"
    assert result[0]["amount_change"] == 50.0


def test_audit_history_reports_error_for_unknown_product(monkeypatch):
    monkeypatch.setattr(svc.repo, "list_products", lambda: [make_product("p1", "Foundations Play Booster")])

    result = json.loads(svc.get_audit_history.func(product_name="nonexistent"))

    assert "error" in result


def test_audit_history_reports_error_for_unknown_streamer(monkeypatch):
    monkeypatch.setattr(svc.repo, "find_user_by_username", lambda username: None)

    result = json.loads(svc.get_audit_history.func(streamer_username="nobody"))

    assert "error" in result
