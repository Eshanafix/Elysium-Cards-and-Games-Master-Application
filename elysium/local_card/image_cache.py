"""
Card image caching: reads (row_id, image_small) pairs out of the local
cards.sqlite and downloads any not already cached, on top of the shared
local_assets.image_cache_core downloader.

Different finishes of the same printing (nonfoil/foil/etched row_ids) very
often share one identical image_small URL. Downloading it once per row_id
would mean roughly a third of all requests are pure duplicates of an image
already fetched a moment earlier under a different local filename — wasted
bandwidth and, worse, wasted load against Scryfall's CDN that makes real
throttling/slowdowns more likely. So this fetches each distinct URL once
and locally copies the bytes to every row_id that shares it.
"""

import logging
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Callable

from elysium.local_assets.image_cache_core import (
    CacheResult,
    cached_image_path,
    download_missing_images,
)
from elysium.local_card.bulk_import import SCRYFALL_HEADERS

logger = logging.getLogger(__name__)


def get_cached_card_image_path(row_id: str, cache_dir: Path) -> Path | None:
    path = cached_image_path(row_id, cache_dir)
    return path if path.exists() else None


def download_missing_card_images(
    db_path: Path,
    cache_dir: Path,
    progress_callback: Callable[[int, int], None] | None = None,
) -> CacheResult:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT row_id, image_small FROM cards WHERE image_small IS NOT NULL")
    rows = cursor.fetchall()
    conn.close()

    row_ids_by_url: dict[str, list[str]] = defaultdict(list)

    for row_id, url in rows:
        row_ids_by_url[url].append(row_id)

    representative_items = [(row_ids[0], url) for url, row_ids in row_ids_by_url.items()]

    result = download_missing_images(
        items=representative_items,
        cache_dir=cache_dir,
        headers=SCRYFALL_HEADERS,
        on_progress=progress_callback,
    )

    copied = 0

    for row_ids in row_ids_by_url.values():
        if len(row_ids) < 2:
            continue

        representative_path = cached_image_path(row_ids[0], cache_dir)

        if not representative_path.exists():
            continue

        image_bytes = representative_path.read_bytes()

        for row_id in row_ids[1:]:
            target_path = cached_image_path(row_id, cache_dir)

            if not target_path.exists():
                target_path.write_bytes(image_bytes)
                copied += 1

    if copied:
        logger.info("Copied %s cached images locally instead of re-downloading duplicates", copied)

    return result
