from datetime import datetime, timedelta, timezone

import pytest

from elysium.local_card import db


def make_card(suffix, name, set_code="tst", collector_number="1", price=1.23):
    return {
        "id": f"11111111-1111-1111-1111-{suffix:0>12}",
        "oracle_id": f"oracle-{suffix}",
        "name": name,
        "set": set_code,
        "set_name": "Test Set",
        "collector_number": collector_number,
        "rarity": "common",
        "lang": "en",
        "released_at": "2024-01-01",
        "frame": "2015",
        "border_color": "black",
        "prices": {"usd": str(price)},
        "image_uris": {"small": f"https://example.com/{suffix}.jpg"},
    }


def test_insert_cards_and_search_by_name(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    db.create_database(db_path)

    db.insert_cards(db_path, [
        make_card("1", "Lightning Bolt", price=0.50),
        make_card("2", "Lightning Strike", price=1.00),
        make_card("3", "Counterspell", price=2.00),
    ])

    rows, total = db.search_cards(db_path, search_text="Lightning")

    assert total == 2
    assert {row[1] for row in rows} == {"Lightning Bolt", "Lightning Strike"}


def test_search_cards_orders_by_price_desc(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    db.create_database(db_path)

    db.insert_cards(db_path, [
        make_card("1", "Cheap Card", price=0.50),
        make_card("2", "Expensive Card", price=25.00),
    ])

    rows, total = db.search_cards(db_path)

    assert total == 2
    assert rows[0][1] == "Expensive Card"
    assert rows[1][1] == "Cheap Card"


def test_search_cards_filters_by_set_code_and_collector_number(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    db.create_database(db_path)

    db.insert_cards(db_path, [
        make_card("1", "Card A", set_code="aaa", collector_number="1"),
        make_card("2", "Card B", set_code="bbb", collector_number="2"),
        make_card("3", "Card C", set_code="aaa", collector_number="3"),
    ])

    rows, total = db.search_cards(db_path, set_codes={"aaa"})
    assert total == 2

    rows, total = db.search_cards(db_path, set_codes={"aaa"}, collector_numbers={"1"})
    assert total == 1
    assert rows[0][1] == "Card A"


def test_search_cards_respects_limit_but_reports_full_total(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    db.create_database(db_path)

    db.insert_cards(db_path, [make_card(str(i), f"Card {i}") for i in range(5)])

    rows, total = db.search_cards(db_path, limit=2)

    assert total == 5
    assert len(rows) == 2


def test_search_cards_no_matches_returns_empty_without_error(tmp_path):
    """Regression test for the two-step winning-ids query: a search with
    zero matches must not error out on the second (IN (...)) fetch."""
    db_path = tmp_path / "cards.sqlite"
    db.create_database(db_path)

    db.insert_cards(db_path, [make_card("1", "Lightning Bolt")])

    rows, total = db.search_cards(db_path, search_text="Nonexistent Card Name")

    assert rows == []
    assert total == 0


def test_create_database_adds_search_indexes(tmp_path):
    import sqlite3

    db_path = tmp_path / "cards.sqlite"
    db.create_database(db_path)

    conn = sqlite3.connect(db_path)
    index_names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    conn.close()

    assert "idx_cards_name" in index_names
    assert "idx_cards_name_price_id" in index_names


def test_search_cards_on_missing_database_returns_empty(tmp_path):
    rows, total = db.search_cards(tmp_path / "does_not_exist.sqlite")

    assert rows == []
    assert total == 0


def test_rebuild_database_safely_sets_refresh_meta(tmp_path):
    real_db_path = tmp_path / "cards.sqlite"

    db.rebuild_database_safely(real_db_path, [make_card("1", "Card A")])

    assert real_db_path.exists()

    last_refresh = db.get_last_successful_refresh_at(real_db_path)
    assert last_refresh is not None
    assert not db.is_stale(last_refresh, hours=24)

    rows, total = db.search_cards(real_db_path)
    assert total == 1


def test_rebuild_database_safely_preserves_old_db_on_failure(tmp_path, monkeypatch):
    real_db_path = tmp_path / "cards.sqlite"

    # Establish a known-good working database first.
    db.rebuild_database_safely(real_db_path, [make_card("1", "Original Card")])
    original_bytes = real_db_path.read_bytes()

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure mid-rebuild")

    monkeypatch.setattr(db, "insert_cards", boom)

    with pytest.raises(RuntimeError):
        db.rebuild_database_safely(real_db_path, [make_card("2", "Should Not Appear")])

    # The working database must be completely untouched (LLD 26.3).
    assert real_db_path.read_bytes() == original_bytes

    temp_path = real_db_path.with_name(real_db_path.stem + ".rebuilding.sqlite")
    assert not temp_path.exists()

    rows, total = db.search_cards(real_db_path)
    assert total == 1
    assert rows[0][1] == "Original Card"


def test_is_stale_never_refreshed_is_not_stale():
    assert db.is_stale(None, hours=24) is False


def test_is_stale_recent_refresh_is_not_stale():
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    assert db.is_stale(recent, hours=24) is False


def test_is_stale_old_refresh_is_stale():
    old = datetime.now(timezone.utc) - timedelta(hours=25)
    assert db.is_stale(old, hours=24) is True
