import pytest

from elysium.repositories import master_repository as repo
from elysium.services import auth_service


def test_generated_key_is_12_hex_chars(monkeypatch):
    monkeypatch.setattr(repo, "get_master_db_users_streamer_key_exists", lambda key: False)

    key = auth_service._generate_unique_streamer_database_key()

    assert len(key) == 12
    int(key, 16)  # raises ValueError if not valid hex


def test_retries_on_collision_then_succeeds(monkeypatch):
    calls = {"count": 0}

    def fake_exists(key):
        calls["count"] += 1
        return calls["count"] <= 2  # first two candidates "collide"

    monkeypatch.setattr(repo, "get_master_db_users_streamer_key_exists", fake_exists)

    key = auth_service._generate_unique_streamer_database_key()

    assert calls["count"] == 3
    assert len(key) == 12


def test_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(repo, "get_master_db_users_streamer_key_exists", lambda key: True)

    with pytest.raises(RuntimeError):
        auth_service._generate_unique_streamer_database_key()
