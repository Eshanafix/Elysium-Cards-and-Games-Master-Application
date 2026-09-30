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
    assert "idx_cards_name_normalized" in index_names
    assert "idx_cards_name_normalized_price_id" in index_names


# --- Forgiving search (docs feedback): case-insensitive, punctuation/
# spacing-insensitive, and tolerant of a slight misspelling. ---


def test_normalize_for_search_strips_punctuation_case_and_spacing():
    assert db.normalize_for_search("70,000 Light-Years From Home") == "70000lightyearsfromhome"
    assert db.normalize_for_search("70000 light years from home") == "70000lightyearsfromhome"


def test_normalize_for_search_handles_none_and_empty():
    assert db.normalize_for_search(None) == ""
    assert db.normalize_for_search("") == ""


def test_normalize_for_search_strips_accents_to_their_base_letter():
    """Regression: v1 of this function deleted an accented letter outright
    (treating it as punctuation) instead of reducing it to its plain base
    letter -- "Lim-Dûl" normalized to "limdl", not "limdul", so a search
    for the plain-typed "lim-dul" could never match it. Real bug report:
    "Lim-Dûl the Necromancer" and "Jötun Grunt" only matched if you typed
    the accented character."""
    assert db.normalize_for_search("Lim-Dûl the Necromancer") == "limdulthenecromancer"
    assert db.normalize_for_search("Lim-Dul the Necromancer") == "limdulthenecromancer"
    assert db.normalize_for_search("Jötun Grunt") == "jotungrunt"
    assert db.normalize_for_search("Jotun Grunt") == "jotungrunt"


def test_search_cards_finds_an_accented_card_name_typed_without_the_accent(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    db.create_database(db_path)

    db.insert_cards(db_path, [
        make_card("1", "Lim-Dûl the Necromancer"),
        make_card("2", "Jötun Grunt"),
    ])

    rows, total = db.search_cards(db_path, search_text="lim-dul the necromancer")
    assert total == 1
    assert rows[0][1] == "Lim-Dûl the Necromancer"

    rows, total = db.search_cards(db_path, search_text="jotun grunt")
    assert total == 1
    assert rows[0][1] == "Jötun Grunt"


def test_create_database_rebackfills_name_normalized_when_the_version_changes(tmp_path):
    """Regression: bumping _NAME_NORMALIZED_VERSION (e.g. the accent-
    stripping fix above) must force a full re-backfill of an already-
    migrated database -- not just databases missing the column outright --
    since the OLD stored values are simply wrong under the new logic, not
    absent. Checks the stored column directly (rather than going through
    search_cards()) so this doesn't get entangled with the separate fuzzy-
    misspelling fallback, which can happen to still find a stale value
    anyway if it's close enough -- that's real, intended behavior, just not
    what this test is about."""
    import sqlite3

    db_path = tmp_path / "cards.sqlite"
    db.create_database(db_path)
    db.insert_cards(db_path, [make_card("1", "Lim-Dûl the Necromancer")])

    # Simulate this row having been backfilled under the old (buggy) v1
    # logic, and the db stamped as v1 -- exactly the state of a database
    # that already ran the v1.0.17 migration before this fix shipped.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE cards SET name_normalized = ? WHERE name = ?",
        ("limdlthenecromancer", "Lim-Dûl the Necromancer"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO local_meta (key, value) VALUES ('name_normalized_version', '1')"
    )
    conn.commit()
    stale_value = conn.execute(
        "SELECT name_normalized FROM cards WHERE name = ?", ("Lim-Dûl the Necromancer",)
    ).fetchone()[0]
    conn.close()
    assert stale_value == "limdlthenecromancer"  # confirms the simulated stale state took effect

    db.create_database(db_path)  # exactly what card_lookup.py's __init__ calls on every launch

    conn = sqlite3.connect(db_path)
    fixed_value = conn.execute(
        "SELECT name_normalized FROM cards WHERE name = ?", ("Lim-Dûl the Necromancer",)
    ).fetchone()[0]
    conn.close()
    assert fixed_value == "limdulthenecromancer"


def test_search_cards_ignores_punctuation_the_stored_name_has_but_the_query_lacks(tmp_path):
    """The exact motivating example: the real card is "70,000 Light-Years
    From Home" -- a search shouldn't need the comma or the hyphen."""
    db_path = tmp_path / "cards.sqlite"
    db.create_database(db_path)

    db.insert_cards(db_path, [make_card("1", "70,000 Light-Years From Home")])

    rows, total = db.search_cards(db_path, search_text="70000 light years from home")

    assert total == 1
    assert rows[0][1] == "70,000 Light-Years From Home"


def test_search_cards_is_case_insensitive_and_ignores_mixed_punctuation(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    db.create_database(db_path)

    db.insert_cards(db_path, [make_card("1", "70,000 Light-Years From Home")])

    rows, total = db.search_cards(db_path, search_text="70,000 LIGHT-years from HOME")

    assert total == 1


def test_search_cards_falls_back_to_a_close_match_for_a_slight_misspelling(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    db.create_database(db_path)

    db.insert_cards(db_path, [make_card("1", "Lightning Bolt")])

    rows, total = db.search_cards(db_path, search_text="Lighning Bolt")

    assert total == 1
    assert rows[0][1] == "Lightning Bolt"


def test_search_cards_fuzzy_fallback_does_not_fire_when_the_exact_search_already_matches(tmp_path):
    """The fuzzy pass should only ever run on a genuinely empty exact
    result -- not silently widen a search that already found something."""
    db_path = tmp_path / "cards.sqlite"
    db.create_database(db_path)

    db.insert_cards(db_path, [
        make_card("1", "Lightning Bolt"),
        make_card("2", "Lightning Strike"),
    ])

    rows, total = db.search_cards(db_path, search_text="Lightning Bolt")

    assert total == 1
    assert rows[0][1] == "Lightning Bolt"


def test_search_cards_fuzzy_fallback_skips_very_short_queries(tmp_path):
    """A short garbled query matches so much of the pool as a substring
    already, or is too short for a meaningful "close match" comparison --
    the fuzzy pass is gated to avoid noisy/expensive short-string fuzzing."""
    db_path = tmp_path / "cards.sqlite"
    db.create_database(db_path)

    db.insert_cards(db_path, [make_card("1", "Lightning Bolt")])

    rows, total = db.search_cards(db_path, search_text="xyz")

    assert total == 0
    assert rows == []


def test_search_cards_fuzzy_fallback_still_respects_set_code_filter(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    db.create_database(db_path)

    db.insert_cards(db_path, [
        make_card("1", "Lightning Bolt", set_code="aaa"),
        make_card("2", "Lightning Bolt", set_code="bbb"),
    ])

    rows, total = db.search_cards(db_path, search_text="Lighning Bolt", set_codes={"aaa"})

    assert total == 1
    assert rows[0][2] == "aaa"


def test_create_database_migrates_a_pre_normalized_column_database_and_backfills_it(tmp_path):
    """A database built by an older app version has no name_normalized
    column -- create_database() (called on every launch, card_lookup.py's
    __init__) must add and backfill it in place, so forgiving search works
    immediately without requiring a full Refresh Card Data re-download."""
    import sqlite3

    db_path = tmp_path / "cards.sqlite"

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE cards (
            row_id TEXT PRIMARY KEY,
            scryfall_id TEXT, oracle_id TEXT,
            name TEXT, printed_name TEXT,
            set_code TEXT, set_name TEXT, collector_number TEXT, rarity TEXT, lang TEXT, released_at TEXT,
            printing_details TEXT, finish TEXT, price REAL,
            frame TEXT, border_color TEXT, security_stamp TEXT,
            promo INTEGER, full_art INTEGER, textless INTEGER, booster INTEGER, story_spotlight INTEGER,
            variation INTEGER, variation_of TEXT, oversized INTEGER,
            mana_cost TEXT, cmc REAL, type_line TEXT, oracle_text TEXT, power TEXT, toughness TEXT,
            colors_text TEXT, color_identity_text TEXT,
            image_small TEXT, image_normal TEXT, image_large TEXT, image_png TEXT
        )
    """)
    conn.execute(
        "INSERT INTO cards (row_id, name, set_code, collector_number, rarity, price) VALUES (?, ?, ?, ?, ?, ?)",
        ("old-row-1", "70,000 Light-Years From Home", "tst", "1", "common", 1.00),
    )
    conn.commit()

    columns_before = {row[1] for row in conn.execute("PRAGMA table_info(cards)")}
    conn.close()
    assert "name_normalized" not in columns_before

    db.create_database(db_path)  # exactly what card_lookup.py's __init__ calls on every launch

    conn = sqlite3.connect(db_path)
    columns_after = {row[1] for row in conn.execute("PRAGMA table_info(cards)")}
    backfilled = conn.execute(
        "SELECT name_normalized FROM cards WHERE row_id = ?", ("old-row-1",)
    ).fetchone()[0]
    conn.close()

    assert "name_normalized" in columns_after
    assert backfilled == "70000lightyearsfromhome"

    rows, total = db.search_cards(db_path, search_text="70000 light years from home")
    assert total == 1


def test_create_database_migration_is_a_noop_on_an_already_current_database(tmp_path):
    """Running create_database() again (every app launch) against a
    database that already has name_normalized must not error or re-run
    the backfill."""
    db_path = tmp_path / "cards.sqlite"
    db.create_database(db_path)
    db.insert_cards(db_path, [make_card("1", "Lightning Bolt")])

    db.create_database(db_path)  # second call, same as a normal app relaunch

    rows, total = db.search_cards(db_path, search_text="lightning bolt")
    assert total == 1


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
