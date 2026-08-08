"""
Regression test for the card-tile pixmap cache (elysium/ui/card_lookup.py)
-- decoding+scaling an image from disk measured ~7-8ms/card, the single
biggest contributor to Card Lookup feeling laggy while typing, since up to
PAGE_SIZE tiles get rebuilt on every debounced keystroke.
"""

from elysium.ui import card_lookup


def test_get_scaled_card_pixmap_returns_none_when_no_cached_image(monkeypatch):
    monkeypatch.setattr(card_lookup, "get_cached_card_image_path", lambda row_id, cache_dir: None)
    card_lookup._pixmap_cache.clear()

    result = card_lookup._get_scaled_card_pixmap("row-1", 146, 204)

    assert result is None


def test_get_scaled_card_pixmap_caches_by_row_id_and_size(monkeypatch, tmp_path, qtbot):
    from PySide6.QtGui import QPixmap

    fake_image = tmp_path / "fake.png"
    QPixmap(10, 10).save(str(fake_image))

    calls = []

    def fake_path_lookup(row_id, cache_dir):
        calls.append(row_id)
        return fake_image

    monkeypatch.setattr(card_lookup, "get_cached_card_image_path", fake_path_lookup)
    card_lookup._pixmap_cache.clear()

    first = card_lookup._get_scaled_card_pixmap("row-1", 146, 204)
    second = card_lookup._get_scaled_card_pixmap("row-1", 146, 204)

    assert first is not None
    assert first is second  # same cached object, not re-decoded
    assert calls == ["row-1"]  # disk lookup only happened once


def test_get_scaled_card_pixmap_different_sizes_are_separate_cache_entries(monkeypatch, tmp_path, qtbot):
    from PySide6.QtGui import QPixmap

    fake_image = tmp_path / "fake.png"
    QPixmap(10, 10).save(str(fake_image))

    monkeypatch.setattr(card_lookup, "get_cached_card_image_path", lambda row_id, cache_dir: fake_image)
    card_lookup._pixmap_cache.clear()

    small = card_lookup._get_scaled_card_pixmap("row-1", 100, 140)
    large = card_lookup._get_scaled_card_pixmap("row-1", 200, 280)

    assert small is not large


def test_pixmap_cache_clears_once_it_hits_the_cap(monkeypatch, tmp_path, qtbot):
    from PySide6.QtGui import QPixmap

    fake_image = tmp_path / "fake.png"
    QPixmap(10, 10).save(str(fake_image))

    monkeypatch.setattr(card_lookup, "get_cached_card_image_path", lambda row_id, cache_dir: fake_image)
    monkeypatch.setattr(card_lookup, "_PIXMAP_CACHE_MAX", 3)
    card_lookup._pixmap_cache.clear()

    for i in range(3):
        card_lookup._get_scaled_card_pixmap(f"row-{i}", 100, 140)

    assert len(card_lookup._pixmap_cache) == 3

    card_lookup._get_scaled_card_pixmap("row-overflow", 100, 140)

    # Capped: the cache was cleared before inserting the entry that would
    # have exceeded the cap, so it holds only the newest entry now.
    assert len(card_lookup._pixmap_cache) == 1
