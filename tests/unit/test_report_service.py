from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from elysium.models.users import ROLE_ADMIN, ROLE_STREAMER, User
from elysium.services import report_service

ADMIN_USER = User(id="admin-1", username="admin", password_hash="x", roles=[ROLE_ADMIN])
STREAMER_USER = User(id="streamer-1", username="s1", password_hash="x", roles=[ROLE_STREAMER], streamer_database_name="elysium_s_abc")
OTHER_STREAMER = User(
    id="streamer-2", username="s2", password_hash="x", roles=[ROLE_STREAMER], streamer_database_name="elysium_s_def"
)


def test_require_admin_blocks_streamer():
    with pytest.raises(report_service.ReportPermissionError):
        report_service._require_admin(STREAMER_USER)


def test_require_admin_allows_admin():
    report_service._require_admin(ADMIN_USER)  # no raise


def test_pack_summary_stacks_one_product_per_line():
    """Regression: comma-joining ("A x1, B x2") ran too wide -- one product
    per line so it reads as a stacked list within the same cell."""
    pack_lines = [
        {"product_id": "p1", "quantity": 1},
        {"product_id": "p2", "quantity": 2},
    ]
    products_by_id = {
        "p1": type("P", (), {"name": "Ravnica Allegiance Draft Booster"})(),
        "p2": type("P", (), {"name": "Dominaria United Draft Booster"})(),
    }

    result = report_service._pack_summary(pack_lines, products_by_id)

    assert result == "Ravnica Allegiance Draft Booster x1\nDominaria United Draft Booster x2"


def test_pack_summary_falls_back_to_product_id_when_unknown():
    result = report_service._pack_summary([{"product_id": "missing-id", "quantity": 1}], {})
    assert result == "missing-id x1"


def test_pack_summary_empty_pack_lines():
    assert report_service._pack_summary([], {}) == ""


def test_money_converts_decimal_to_str():
    assert report_service._money(Decimal("12.50")) == "12.50"


def test_money_passes_through_none():
    assert report_service._money(None) is None


def test_in_range_no_bounds_requires_none_value():
    assert report_service._in_range(None, None, None) is True
    assert report_service._in_range(datetime.now(timezone.utc), None, None) is True


def test_in_range_within_bounds():
    now = datetime.now(timezone.utc)
    assert report_service._in_range(now, now - timedelta(days=1), now + timedelta(days=1)) is True


def test_in_range_before_start_excluded():
    now = datetime.now(timezone.utc)
    assert report_service._in_range(now - timedelta(days=2), now - timedelta(days=1), None) is False


def test_in_range_after_end_excluded():
    now = datetime.now(timezone.utc)
    assert report_service._in_range(now + timedelta(days=2), None, now + timedelta(days=1)) is False


def test_in_range_none_value_with_bounds_set_excluded():
    now = datetime.now(timezone.utc)
    assert report_service._in_range(None, now - timedelta(days=1), now) is False


# --- _streamer_scope: the core LLD 20.1 visibility rule ---


def test_streamer_scope_admin_sees_all_streamers(monkeypatch):
    monkeypatch.setattr(report_service.repo, "list_users", lambda: [ADMIN_USER, STREAMER_USER, OTHER_STREAMER])

    scope = report_service._streamer_scope(ADMIN_USER, streamer_id=None)

    assert {u.id for u in scope} == {"streamer-1", "streamer-2"}


def test_streamer_scope_admin_narrowed_by_filter(monkeypatch):
    monkeypatch.setattr(report_service.repo, "list_users", lambda: [ADMIN_USER, STREAMER_USER, OTHER_STREAMER])

    scope = report_service._streamer_scope(ADMIN_USER, streamer_id="streamer-2")

    assert [u.id for u in scope] == ["streamer-2"]


def test_streamer_scope_streamer_always_sees_only_self(monkeypatch):
    """LLD 20.1: a streamer can never widen their own report scope, even by
    passing a streamer_id filter for someone else."""
    monkeypatch.setattr(report_service.repo, "list_users", lambda: [ADMIN_USER, STREAMER_USER, OTHER_STREAMER])

    scope = report_service._streamer_scope(STREAMER_USER, streamer_id="streamer-2")

    assert [u.id for u in scope] == ["streamer-1"]


def test_streamer_scope_non_streamer_non_admin_sees_nothing():
    plain_user = User(id="x", username="x", password_hash="x", roles=[])
    assert report_service._streamer_scope(plain_user, streamer_id=None) == []


# --- report functions enforce admin-only where required ---


def test_master_inventory_report_blocks_streamer():
    with pytest.raises(report_service.ReportPermissionError):
        report_service.master_inventory_report(STREAMER_USER)


def test_users_report_blocks_streamer():
    with pytest.raises(report_service.ReportPermissionError):
        report_service.users_report(STREAMER_USER)


def test_decommission_requests_report_blocks_streamer():
    with pytest.raises(report_service.ReportPermissionError):
        report_service.decommission_requests_report(STREAMER_USER)


def test_streamer_allocations_report_blocks_streamer():
    with pytest.raises(report_service.ReportPermissionError):
        report_service.streamer_allocations_report(STREAMER_USER)


def test_inventory_audit_report_blocks_streamer():
    with pytest.raises(report_service.ReportPermissionError):
        report_service.inventory_audit_report(STREAMER_USER)


def test_users_report_shapes_rows_for_admin(monkeypatch):
    monkeypatch.setattr(report_service.repo, "list_users", lambda: [STREAMER_USER])

    rows = report_service.users_report(ADMIN_USER)

    assert rows == [{
        "user_id": "streamer-1", "username": "s1", "roles": "streamer", "is_active": True,
        "decommission_status": None, "created_at": None, "disabled_at": None,
    }]
