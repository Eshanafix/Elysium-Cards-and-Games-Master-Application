import pytest

from elysium.models.discrepancies import TYPE_NEGATIVE_INVENTORY
from elysium.services import discrepancy_service


def test_open_or_increment_creates_new_when_none_open(monkeypatch):
    captured = {}

    monkeypatch.setattr(discrepancy_service.repo, "find_open_discrepancy", lambda *a, **k: None)
    monkeypatch.setattr(discrepancy_service.repo, "insert_discrepancy", lambda d, session=None: captured.update(quantity=d.quantity, type=d.type))
    monkeypatch.setattr(discrepancy_service.audit_service, "record_event", lambda *a, **k: "event-id")

    discrepancy_id = discrepancy_service.open_or_increment_discrepancy(
        "streamer-1", "p1", TYPE_NEGATIVE_INVENTORY, 3, "STREAM_CORRECTION", "admin-1",
    )

    assert captured == {"quantity": 3, "type": TYPE_NEGATIVE_INVENTORY}
    assert discrepancy_id


def test_open_or_increment_increments_existing_open_record(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        discrepancy_service.repo, "find_open_discrepancy",
        lambda *a, **k: {"discrepancy_id": "existing-id", "quantity": 2},
    )
    monkeypatch.setattr(
        discrepancy_service.repo, "increment_discrepancy_quantity",
        lambda discrepancy_id, delta, session=None: captured.update(id=discrepancy_id, delta=delta),
    )

    discrepancy_id = discrepancy_service.open_or_increment_discrepancy(
        "streamer-1", "p1", TYPE_NEGATIVE_INVENTORY, 4, "STREAM_CORRECTION", "admin-1",
    )

    assert discrepancy_id == "existing-id"
    assert captured == {"id": "existing-id", "delta": 4}


def test_open_or_increment_rejects_nonpositive_quantity():
    with pytest.raises(discrepancy_service.DiscrepancyValidationError):
        discrepancy_service.open_or_increment_discrepancy(
            "streamer-1", "p1", TYPE_NEGATIVE_INVENTORY, 0, "STREAM_CORRECTION", "admin-1",
        )


def test_resolve_discrepancy_requires_note(monkeypatch):
    monkeypatch.setattr(discrepancy_service.repo, "update_discrepancy_fields", lambda *a, **k: None)

    with pytest.raises(discrepancy_service.DiscrepancyValidationError):
        discrepancy_service.resolve_discrepancy("id-1", "admin-1", "   ")


def _fake_open_discrepancy(discrepancy_id="id-1", streamer_id="streamer-1", product_id="p1"):
    from elysium.models.discrepancies import SOURCE_MANUAL, STATUS_OPEN

    return discrepancy_service.Discrepancy(
        id=discrepancy_id, streamer_id=streamer_id, product_id=product_id,
        type=TYPE_NEGATIVE_INVENTORY, quantity=3, source=SOURCE_MANUAL, status=STATUS_OPEN,
    )


def test_resolve_discrepancy_sets_resolved_status(monkeypatch):
    captured = {}

    monkeypatch.setattr(discrepancy_service.repo, "find_discrepancy", lambda discrepancy_id: _fake_open_discrepancy(discrepancy_id))
    monkeypatch.setattr(
        discrepancy_service.repo, "update_discrepancy_fields",
        lambda discrepancy_id, fields: captured.update(id=discrepancy_id, fields=fields),
    )
    monkeypatch.setattr(discrepancy_service.audit_service, "record_event", lambda *a, **k: "event-id")

    discrepancy_service.resolve_discrepancy("id-1", "admin-1", "packs located and returned")

    assert captured["id"] == "id-1"
    assert captured["fields"]["status"] == "RESOLVED"
    assert captured["fields"]["resolution_note"] == "packs located and returned"
    assert captured["fields"]["resolved_by"] == "admin-1"


def test_resolve_discrepancy_raises_if_not_found(monkeypatch):
    monkeypatch.setattr(discrepancy_service.repo, "find_discrepancy", lambda discrepancy_id: None)

    with pytest.raises(discrepancy_service.DiscrepancyValidationError):
        discrepancy_service.resolve_discrepancy("missing-id", "admin-1", "a note")
