"""
Local card SQLite schema, ingestion, and search.

Adapted from the original Elysium Card LookUp reference project's db.py.
Two behavioral changes from the original, both required by
docs/IMPLEMENTATION_PLAN.md section 8:

- Every path is parameterized (callers pass a Path, usually from
  local_card.paths) instead of a hardcoded "cards.sqlite" relative to the
  current working directory.
- Rebuilding the database no longer deletes the working file up front.
  rebuild_database_safely() builds a temporary database and swaps it into
  place with os.replace() only after a fully successful import, so a failed
  refresh (network error, malformed bulk file, etc.) never destroys the
  previously-working database (LLD 26.3, 27.2).
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

LAST_SUCCESSFUL_REFRESH_KEY = "last_successful_refresh_at"


def safe_float(value):
    return float(value) if value not in (None, "") else None


def join_list(value):
    if isinstance(value, list):
        return ", ".join(str(x) for x in value)
    return ""


def clean_label(value):
    return str(value).replace("_", " ").replace("-", " ").title()


def build_printing_details(card):
    labels = []

    for effect in card.get("frame_effects", []) or []:
        labels.append(clean_label(effect))

    for promo_type in card.get("promo_types", []) or []:
        labels.append(clean_label(promo_type))

    if card.get("full_art"):
        labels.append("Full Art")

    if card.get("textless"):
        labels.append("Textless")

    if card.get("variation"):
        labels.append("Variation")

    if card.get("promo"):
        labels.append("Promo")

    if not labels:
        labels.append("Regular")

    seen = set()
    final = []

    for label in labels:
        if label not in seen:
            seen.add(label)
            final.append(label)

    return " / ".join(final)


def create_database(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cards (
        row_id TEXT PRIMARY KEY,

        scryfall_id TEXT,
        oracle_id TEXT,

        name TEXT,
        printed_name TEXT,

        set_code TEXT,
        set_name TEXT,
        collector_number TEXT,
        rarity TEXT,
        lang TEXT,
        released_at TEXT,

        printing_details TEXT,
        finish TEXT,
        price REAL,

        frame TEXT,
        border_color TEXT,
        security_stamp TEXT,

        promo INTEGER,
        full_art INTEGER,
        textless INTEGER,
        booster INTEGER,
        story_spotlight INTEGER,
        variation INTEGER,
        variation_of TEXT,
        oversized INTEGER,

        mana_cost TEXT,
        cmc REAL,
        type_line TEXT,
        oracle_text TEXT,
        power TEXT,
        toughness TEXT,
        colors_text TEXT,
        color_identity_text TEXT,

        image_small TEXT,
        image_normal TEXT,
        image_large TEXT,
        image_png TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS local_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    # Search filters on `name` with a leading wildcard (LIKE '%text%'), which
    # can't seek a plain index -- but SQLite can still satisfy the COUNT(*)
    # this runs on every keystroke with a full scan of this narrow covering
    # index instead of the wide `cards` table (37 columns, incl. large text
    # fields), which measured ~90ms per keystroke against a 145k-row table
    # without it, ~10ms with it.
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name)")

    # search_cards()'s actual row-fetch query (not just the count) also
    # sorts by price and limits to a page -- with only idx_cards_name,
    # SQLite still had to read every matching row's full data to sort by
    # price before applying LIMIT (measured ~90-100ms for ~1600 matches).
    # This covering index (includes price and row_id) lets the sort+limit
    # step scan only the narrow index instead, dropping to ~20-25ms;
    # search_cards() then does a second targeted fetch for just the winning
    # row_ids to pull the remaining display columns.
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cards_name_price_id ON cards(name, price, row_id)")

    conn.commit()
    conn.close()


def set_meta(db_path: Path, key: str, value: str) -> None:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        "INSERT OR REPLACE INTO local_meta (key, value) VALUES (?, ?)",
        (key, value),
    )

    conn.commit()
    conn.close()


def get_meta(db_path: Path, key: str) -> str | None:
    if not db_path.exists():
        return None

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT value FROM local_meta WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        # local_meta table predates this app version, or DB is mid-setup.
        return None
    finally:
        conn.close()


def get_last_successful_refresh_at(db_path: Path) -> datetime | None:
    raw = get_meta(db_path, LAST_SUCCESSFUL_REFRESH_KEY)

    if not raw:
        return None

    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def is_stale(last_refresh_at: datetime | None, hours: int) -> bool:
    """
    False for "never refreshed" — that's a distinct empty-state, not a
    staleness warning (LLD 21.5 is specifically about a refresh that
    happened but is now old).
    """
    if last_refresh_at is None:
        return False

    return datetime.now(timezone.utc) - last_refresh_at > timedelta(hours=hours)


def _insert_one_version(cursor, card, finish, price, image_uris, printing_details):
    row_id = f"{card.get('id')}::{finish.lower()}"

    cursor.execute("""
    INSERT OR REPLACE INTO cards (
        row_id,

        scryfall_id,
        oracle_id,

        name,
        printed_name,

        set_code,
        set_name,
        collector_number,
        rarity,
        lang,
        released_at,

        printing_details,
        finish,
        price,

        frame,
        border_color,
        security_stamp,

        promo,
        full_art,
        textless,
        booster,
        story_spotlight,
        variation,
        variation_of,
        oversized,

        mana_cost,
        cmc,
        type_line,
        oracle_text,
        power,
        toughness,
        colors_text,
        color_identity_text,

        image_small,
        image_normal,
        image_large,
        image_png
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        row_id,

        card.get("id"),
        card.get("oracle_id"),

        card.get("name"),
        card.get("printed_name"),

        card.get("set"),
        card.get("set_name"),
        card.get("collector_number"),
        card.get("rarity"),
        card.get("lang"),
        card.get("released_at"),

        printing_details,
        finish,
        price,

        card.get("frame"),
        card.get("border_color"),
        card.get("security_stamp"),

        int(card.get("promo", False)),
        int(card.get("full_art", False)),
        int(card.get("textless", False)),
        int(card.get("booster", False)),
        int(card.get("story_spotlight", False)),
        int(card.get("variation", False)),
        card.get("variation_of"),
        int(card.get("oversized", False)),

        card.get("mana_cost"),
        safe_float(card.get("cmc")),
        card.get("type_line"),
        card.get("oracle_text"),
        card.get("power"),
        card.get("toughness"),
        join_list(card.get("colors")),
        join_list(card.get("color_identity")),

        image_uris.get("small"),
        image_uris.get("normal"),
        image_uris.get("large"),
        image_uris.get("png"),
    ))


def insert_cards(
    db_path: Path,
    cards: list,
    progress_callback: Callable[[int, int], None] | None = None,
) -> None:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    total = len(cards)

    for index, card in enumerate(cards, start=1):
        if progress_callback and (index % 500 == 0 or index == total):
            progress_callback(index, total)

        try:
            prices = card.get("prices", {}) or {}
            image_uris = card.get("image_uris", {}) or {}

            if not image_uris and card.get("card_faces"):
                image_uris = (card["card_faces"][0].get("image_uris", {}) or {})

            printing_details = build_printing_details(card)

            versions = [
                ("Nonfoil", safe_float(prices.get("usd"))),
                ("Foil", safe_float(prices.get("usd_foil"))),
                ("Etched", safe_float(prices.get("usd_etched"))),
            ]

            for finish, price in versions:
                if price is not None:
                    _insert_one_version(cursor, card, finish, price, image_uris, printing_details)

        except Exception as e:
            print("Error inserting card:", card.get("name"), e)

    conn.commit()
    conn.close()


def rebuild_database_safely(
    real_db_path: Path,
    cards: list,
    progress_callback: Callable[[int, int], None] | None = None,
) -> None:
    """
    Builds a fresh database at a temporary path and atomically swaps it into
    place with os.replace() only once the import fully succeeds. If
    anything raises, the temp file is removed and real_db_path is left
    completely untouched (LLD 26.3).
    """
    temp_db_path = real_db_path.with_name(real_db_path.stem + ".rebuilding.sqlite")

    if temp_db_path.exists():
        temp_db_path.unlink()

    try:
        create_database(temp_db_path)
        insert_cards(temp_db_path, cards, progress_callback=progress_callback)

        now_iso = datetime.now(timezone.utc).isoformat()
        set_meta(temp_db_path, LAST_SUCCESSFUL_REFRESH_KEY, now_iso)

        temp_db_path.replace(real_db_path)

    except Exception:
        if temp_db_path.exists():
            temp_db_path.unlink()
        raise


def get_set_options(db_path: Path) -> list[tuple[str, str, int]]:
    if not db_path.exists():
        return []

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT set_code, set_name, COUNT(*) as row_count
    FROM cards
    GROUP BY set_code, set_name
    ORDER BY set_name ASC
    """)

    rows = cursor.fetchall()
    conn.close()

    return rows


def search_cards(
    db_path: Path,
    search_text: str = "",
    set_codes: set[str] | None = None,
    collector_numbers: set[str] | None = None,
    limit: int | None = None,
) -> tuple[list[tuple], int]:
    """
    Returns (rows, total_matches). rows are capped at `limit` (None = no cap);
    total_matches reflects the full filtered count for "Showing X of Y" and
    "Load More" UI.
    """
    if not db_path.exists():
        return [], 0

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    conditions = ["name LIKE ?"]
    params: list = [f"%{search_text}%"]

    if set_codes:
        placeholders = ",".join("?" for _ in set_codes)
        conditions.append(f"set_code IN ({placeholders})")
        params.extend(list(set_codes))

    if collector_numbers:
        placeholders = ",".join("?" for _ in collector_numbers)
        conditions.append(f"collector_number IN ({placeholders})")
        params.extend(list(collector_numbers))

    where_clause = " AND ".join(conditions)

    cursor.execute(f"SELECT COUNT(*) FROM cards WHERE {where_clause}", params)
    total_matches = cursor.fetchone()[0]

    # Two-step fetch: first sort+limit against the narrow (name, price,
    # row_id) covering index rather than a single query that sorts the full
    # matching set by price against the wide `cards` table -- the latter
    # measured ~90-100ms for ~1600 matches on a 145k-row table (SQLite has
    # to read every matching row's full data before it can apply LIMIT to
    # an ORDER BY it can't satisfy from an index); this version measured
    # ~20-25ms for the same search.
    id_query = f"SELECT row_id FROM cards WHERE {where_clause} ORDER BY price DESC"
    id_params = list(params)

    if limit is not None:
        id_query += " LIMIT ?"
        id_params.append(limit)

    cursor.execute(id_query, id_params)
    winning_ids = [row[0] for row in cursor.fetchall()]

    if not winning_ids:
        conn.close()
        return [], total_matches

    id_placeholders = ",".join("?" for _ in winning_ids)
    cursor.execute(f"""
        SELECT row_id, name, set_code, collector_number, rarity,
               printing_details, finish, price, full_art, image_small
        FROM cards
        WHERE row_id IN ({id_placeholders})
        ORDER BY price DESC
    """, winning_ids)
    rows = cursor.fetchall()

    conn.close()

    return rows, total_matches
