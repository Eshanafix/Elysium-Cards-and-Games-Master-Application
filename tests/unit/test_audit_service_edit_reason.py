from datetime import datetime, timezone

import pytest

from elysium.models.discrepancies import SOURCE_MANUAL, STATUS_RESOLVED, Discrepancy
from elysium.models.reason_notes import ReasonNote
from elysium.models.streams import STATUS_COMPLETED, Stream
from elysium.models.users import ROLE_ADMIN, ROLE_STREAMER, User
from elysium.services import audit_service


# --- editable_reason_target: pure mapping, no mocking needed ---


def test_editable_reason_target_reason_note_action():
    event = {"action_type": "MASTER_INVENTORY_REMOVED", "reason_note_id": "note-1"}
    target = audit_service.editable_reason_target(event)
    assert target == {"related_record_type": "reason_note", "related_record_id": "note-1"}


def test_editable_reason_target_missing_reason_note_id_returns_none():
    event = {"action_type": "STREAMER_INVENTORY_RETURNED"}
    assert audit_service.editable_reason_target(event) is None


def test_editable_reason_target_stream_correction_action():
    event = {
        "action_type": "STREAM_BREAK_CORRECTED", "related_transaction_id": "corr-1",
        "stream_id": "stream-1", "streamer_id": "streamer-1",
    }
    target = audit_service.editable_reason_target(event)
    assert target == {
        "related_record_type": "stream_correction", "related_record_id": "corr-1",
        "stream_id": "stream-1", "streamer_id": "streamer-1",
    }


def test_editable_reason_target_force_cancel_action():
    event = {"action_type": "STREAM_FORCE_CANCELED", "stream_id": "stream-1", "streamer_id": "streamer-1"}
    target = audit_service.editable_reason_target(event)
    assert target["related_record_type"] == "force_cancel"
    assert target["related_record_id"] == "stream-1"


def test_editable_reason_target_discrepancy_action():
    event = {"action_type": "INVENTORY_DISCREPANCY_RESOLVED", "related_transaction_id": "disc-1"}
    target = audit_service.editable_reason_target(event)
    assert target == {"related_record_type": "discrepancy", "related_record_id": "disc-1"}


def test_editable_reason_target_unknown_action_returns_none():
    assert audit_service.editable_reason_target({"action_type": "USER_CREATED"}) is None


# --- edit_reason: permission dispatch and transaction plumbing ---


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def with_transaction(self, callback):
        callback(self)


class FakeClient:
    def start_session(self):
        return FakeSession()


class FakeAuditEvents:
    def __init__(self):
        self.inserted = []

    def insert_one(self, doc, session=None):
        self.inserted.append(doc)


class FakeMasterDb:
    def __init__(self):
        self.audit_events = FakeAuditEvents()


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeMasterDb()
    monkeypatch.setattr(audit_service, "get_client", lambda: FakeClient())
    monkeypatch.setattr(audit_service, "get_master_db", lambda: db)
    monkeypatch.setattr(audit_service, "_actor_role", lambda performed_by: None)
    return db


ADMIN_USER = User(id="admin-1", username="admin", password_hash="x", roles=[ROLE_ADMIN])
STREAMER_USER = User(id="streamer-1", username="s1", password_hash="x", roles=[ROLE_STREAMER])
OTHER_STREAMER = User(id="streamer-2", username="s2", password_hash="x", roles=[ROLE_STREAMER])


def _user_lookup(users_by_id):
    return lambda user_id: users_by_id.get(user_id)


def test_edit_reason_note_owner_may_edit_own(monkeypatch, fake_db):
    note = ReasonNote(id="note-1", action_type="STREAMER_INVENTORY_RETURNED", current_text="old", streamer_id="streamer-1")
    monkeypatch.setattr(audit_service.repo, "find_reason_note", lambda note_id: note)
    monkeypatch.setattr(audit_service.repo, "find_user_by_id", _user_lookup({"streamer-1": STREAMER_USER}))
    captured = {}
    monkeypatch.setattr(audit_service.repo, "update_reason_note_text", lambda *a, **k: captured.update(args=a))

    audit_service.edit_reason("reason_note", "note-1", "new text", edited_by="streamer-1")

    assert captured["args"][0] == "note-1"
    assert fake_db.audit_events.inserted[0]["action_type"] == "REASON_EDITED"
    assert fake_db.audit_events.inserted[0]["before_values"] == {"reason": "old"}


def test_edit_reason_note_other_streamer_blocked(monkeypatch, fake_db):
    note = ReasonNote(id="note-1", action_type="STREAMER_INVENTORY_RETURNED", current_text="old", streamer_id="streamer-1")
    monkeypatch.setattr(audit_service.repo, "find_reason_note", lambda note_id: note)
    monkeypatch.setattr(audit_service.repo, "find_user_by_id", _user_lookup({"streamer-2": OTHER_STREAMER}))

    with pytest.raises(audit_service.ReasonEditPermissionError):
        audit_service.edit_reason("reason_note", "note-1", "new text", edited_by="streamer-2")


def test_edit_reason_note_admin_may_edit_any(monkeypatch, fake_db):
    note = ReasonNote(id="note-1", action_type="STREAMER_INVENTORY_RETURNED", current_text="old", streamer_id="streamer-1")
    monkeypatch.setattr(audit_service.repo, "find_reason_note", lambda note_id: note)
    monkeypatch.setattr(audit_service.repo, "find_user_by_id", _user_lookup({"admin-1": ADMIN_USER}))
    monkeypatch.setattr(audit_service.repo, "update_reason_note_text", lambda *a, **k: None)

    audit_service.edit_reason("reason_note", "note-1", "new text", edited_by="admin-1")

    assert fake_db.audit_events.inserted[0]["action_type"] == "REASON_EDITED"


def test_edit_reason_note_master_only_requires_admin(monkeypatch, fake_db):
    note = ReasonNote(id="note-1", action_type="MASTER_INVENTORY_REMOVED", current_text="old", streamer_id=None)
    monkeypatch.setattr(audit_service.repo, "find_reason_note", lambda note_id: note)
    monkeypatch.setattr(audit_service.repo, "find_user_by_id", _user_lookup({"streamer-1": STREAMER_USER}))

    with pytest.raises(audit_service.ReasonEditPermissionError):
        audit_service.edit_reason("reason_note", "note-1", "new text", edited_by="streamer-1")


def test_edit_reason_empty_text_raises_before_any_lookup(monkeypatch, fake_db):
    with pytest.raises(audit_service.ReasonEditValidationError):
        audit_service.edit_reason("reason_note", "note-1", "   ", edited_by="admin-1")


def test_edit_reason_stream_correction_requires_admin(monkeypatch, fake_db):
    monkeypatch.setattr(audit_service.repo, "find_user_by_id", _user_lookup({"streamer-1": STREAMER_USER}))

    with pytest.raises(audit_service.ReasonEditPermissionError):
        audit_service.edit_reason(
            "stream_correction", "corr-1", "new text", edited_by="streamer-1",
            streamer_database_name="elysium_s_abc", stream_id="stream-1",
        )


def test_edit_reason_stream_correction_updates_matching_correction(monkeypatch, fake_db):
    stream = Stream(
        id="stream-1", streamer_id="streamer-1", status=STATUS_COMPLETED, start_time=datetime.now(timezone.utc),
        corrections=[{"correction_id": "corr-1", "reason": "old reason"}, {"correction_id": "corr-2", "reason": "other"}],
    )
    monkeypatch.setattr(audit_service.repo, "find_user_by_id", _user_lookup({"admin-1": ADMIN_USER}))
    monkeypatch.setattr(audit_service.streamer_repo, "find_stream_by_id", lambda db, sid, session=None: stream)
    captured = {}
    monkeypatch.setattr(
        audit_service.streamer_repo, "update_stream_fields",
        lambda db, sid, fields, session=None: captured.update(fields=fields),
    )

    audit_service.edit_reason(
        "stream_correction", "corr-1", "new reason", edited_by="admin-1",
        streamer_database_name="elysium_s_abc", stream_id="stream-1",
    )

    updated_corrections = captured["fields"]["corrections"]
    assert next(c for c in updated_corrections if c["correction_id"] == "corr-1")["reason"] == "new reason"
    assert next(c for c in updated_corrections if c["correction_id"] == "corr-2")["reason"] == "other"
    assert fake_db.audit_events.inserted[0]["before_values"] == {"reason": "old reason"}


def test_edit_reason_force_cancel_requires_admin(monkeypatch, fake_db):
    monkeypatch.setattr(audit_service.repo, "find_user_by_id", _user_lookup({"streamer-1": STREAMER_USER}))

    with pytest.raises(audit_service.ReasonEditPermissionError):
        audit_service.edit_reason(
            "force_cancel", "stream-1", "new text", edited_by="streamer-1",
            streamer_database_name="elysium_s_abc", stream_id="stream-1",
        )


def test_edit_reason_discrepancy_requires_existing_resolution_note(monkeypatch, fake_db):
    discrepancy = Discrepancy(
        id="disc-1", streamer_id="streamer-1", product_id="p1", type="NEGATIVE_INVENTORY",
        quantity=3, source=SOURCE_MANUAL, status=STATUS_RESOLVED, resolution_note=None,
    )
    monkeypatch.setattr(audit_service.repo, "find_user_by_id", _user_lookup({"admin-1": ADMIN_USER}))
    monkeypatch.setattr(audit_service.repo, "find_discrepancy", lambda discrepancy_id: discrepancy)

    with pytest.raises(audit_service.ReasonEditValidationError):
        audit_service.edit_reason("discrepancy", "disc-1", "new note", edited_by="admin-1")


def test_edit_reason_discrepancy_updates_resolution_note(monkeypatch, fake_db):
    discrepancy = Discrepancy(
        id="disc-1", streamer_id="streamer-1", product_id="p1", type="NEGATIVE_INVENTORY",
        quantity=3, source=SOURCE_MANUAL, status=STATUS_RESOLVED, resolution_note="old note",
    )
    monkeypatch.setattr(audit_service.repo, "find_user_by_id", _user_lookup({"admin-1": ADMIN_USER}))
    monkeypatch.setattr(audit_service.repo, "find_discrepancy", lambda discrepancy_id: discrepancy)
    captured = {}
    monkeypatch.setattr(audit_service.repo, "update_discrepancy_fields", lambda discrepancy_id, fields: captured.update(fields=fields))

    audit_service.edit_reason("discrepancy", "disc-1", "new note", edited_by="admin-1")

    assert captured["fields"]["resolution_note"] == "new note"
    assert fake_db.audit_events.inserted[0]["before_values"] == {"reason": "old note"}
