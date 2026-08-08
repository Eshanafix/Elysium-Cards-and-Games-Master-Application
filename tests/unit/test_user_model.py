from datetime import datetime, timezone

from elysium.models.users import ROLE_ADMIN, ROLE_STREAMER, User


def make_user(**overrides):
    defaults = dict(
        id="user-1",
        username="alice",
        password_hash="hashed",
        roles=[ROLE_STREAMER],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return User(**defaults)


def test_to_document_and_back_round_trips():
    user = make_user(
        roles=[ROLE_ADMIN, ROLE_STREAMER],
        streamer_database_key="abc123",
        streamer_database_name="elysium_s_abc123",
    )

    doc = user.to_document()
    restored = User.from_document(doc)

    assert restored.id == user.id
    assert restored.username == user.username
    assert restored.roles == user.roles
    assert restored.streamer_database_key == user.streamer_database_key
    assert restored.streamer_database_name == user.streamer_database_name


def test_is_admin_and_is_streamer_flags():
    admin_only = make_user(roles=[ROLE_ADMIN])
    assert admin_only.is_admin is True
    assert admin_only.is_streamer is False

    streamer_only = make_user(roles=[ROLE_STREAMER])
    assert streamer_only.is_admin is False
    assert streamer_only.is_streamer is True

    both = make_user(roles=[ROLE_ADMIN, ROLE_STREAMER])
    assert both.is_admin is True
    assert both.is_streamer is True


def test_from_document_defaults_missing_optional_fields():
    minimal_doc = {
        "_id": "user-2",
        "username": "bob",
        "password_hash": "hashed",
    }

    user = User.from_document(minimal_doc)

    assert user.roles == []
    assert user.is_active is True
    assert user.streamer_database_key is None


def test_to_document_omits_streamer_fields_when_none():
    """Regression test: a sparse unique index on streamer_database_key/
    streamer_database_name only skips documents where the field is
    entirely ABSENT, not documents where it's present with value null.
    Including these as explicit nulls for every non-streamer account
    would mean at most one non-streamer account could ever exist in the
    whole collection (this exact bug shipped once already)."""
    admin_user = make_user(roles=[ROLE_ADMIN], streamer_database_key=None, streamer_database_name=None)

    doc = admin_user.to_document()

    assert "streamer_database_key" not in doc
    assert "streamer_database_name" not in doc


def test_to_document_includes_streamer_fields_when_present():
    streamer_user = make_user(
        roles=[ROLE_STREAMER],
        streamer_database_key="abc123",
        streamer_database_name="elysium_s_abc123",
    )

    doc = streamer_user.to_document()

    assert doc["streamer_database_key"] == "abc123"
    assert doc["streamer_database_name"] == "elysium_s_abc123"
