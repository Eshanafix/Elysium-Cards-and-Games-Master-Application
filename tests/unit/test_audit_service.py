from decimal import Decimal

from bson import Decimal128

from elysium.services import audit_service


def test_record_event_converts_decimal_amount_to_decimal128(monkeypatch):
    """Regression test: pymongo cannot encode a raw decimal.Decimal --
    passing one through as amount_change must not reach insert_one() as a
    Decimal (this exact bug shipped once already, breaking every
    manual-price/previous-price audit event)."""
    captured = {}

    class FakeCollection:
        def insert_one(self, doc, session=None):
            captured["doc"] = doc
            captured["session"] = session

    class FakeDb:
        audit_events = FakeCollection()

    monkeypatch.setattr(audit_service, "get_master_db", lambda: FakeDb())
    monkeypatch.setattr(audit_service, "_actor_role", lambda performed_by: None)

    audit_service.record_event(
        action_type="MANUAL_PRICE_ENTERED",
        performed_by="someone",
        amount_change=Decimal("2.00"),
    )

    assert isinstance(captured["doc"]["amount_change"], Decimal128)
    assert captured["doc"]["amount_change"].to_decimal() == Decimal("2.00")


def test_record_event_converts_decimals_nested_in_before_after_values(monkeypatch):
    """Regression test: amount_change alone wasn't enough -- before_values/
    after_values are arbitrary caller-supplied dicts (e.g. a break's
    pack_lines full of Decimal money fields) that shipped completely
    unconverted, breaking BREAK_DELETED (and any other) audit event whose
    before/after payload carries money."""
    captured = {}

    class FakeCollection:
        def insert_one(self, doc, session=None):
            captured["doc"] = doc

    class FakeDb:
        audit_events = FakeCollection()

    monkeypatch.setattr(audit_service, "get_master_db", lambda: FakeDb())
    monkeypatch.setattr(audit_service, "_actor_role", lambda performed_by: None)

    audit_service.record_event(
        action_type="BREAK_DELETED",
        performed_by="someone",
        before_values={
            "break_gross": Decimal("30.00"),
            "pack_lines": [{"product_id": "p1", "line_market_value": Decimal("10.50")}],
        },
    )

    before = captured["doc"]["before_values"]
    assert isinstance(before["break_gross"], Decimal128)
    assert isinstance(before["pack_lines"][0]["line_market_value"], Decimal128)


def test_record_event_handles_none_amount_change(monkeypatch):
    captured = {}

    class FakeCollection:
        def insert_one(self, doc, session=None):
            captured["doc"] = doc
            captured["session"] = session

    class FakeDb:
        audit_events = FakeCollection()

    monkeypatch.setattr(audit_service, "get_master_db", lambda: FakeDb())
    monkeypatch.setattr(audit_service, "_actor_role", lambda performed_by: None)

    audit_service.record_event(action_type="USER_CREATED", performed_by="someone")

    assert captured["doc"]["amount_change"] is None
    assert captured["session"] is None


def test_record_event_passes_session_through_for_transactional_callers(monkeypatch):
    """inventory_service's claim/return/add/reduce transactions rely on the
    audit write happening inside their session so it commits/rolls back
    atomically with the inventory change (plan section 4.1) -- if session
    silently didn't propagate, audit records could survive a rolled-back
    transaction or vice versa."""
    captured = {}

    class FakeCollection:
        def insert_one(self, doc, session=None):
            captured["session"] = session

    class FakeDb:
        audit_events = FakeCollection()

    monkeypatch.setattr(audit_service, "get_master_db", lambda: FakeDb())
    monkeypatch.setattr(audit_service, "_actor_role", lambda performed_by: None)

    sentinel_session = object()
    audit_service.record_event(action_type="MASTER_INVENTORY_ADDED", performed_by="someone", session=sentinel_session)

    assert captured["session"] is sentinel_session
