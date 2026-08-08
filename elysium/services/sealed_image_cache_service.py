"""
Local per-machine cache for product.image_url (docs/IMPLEMENTATION_PLAN.md
section 2.5). The shared `products` collection only ever stores a URL,
never a local path -- each computer downloads and caches its own copy on
top of the same generic downloader the card-image cache uses.
"""

from pathlib import Path

from elysium.local_assets.image_cache_core import cached_image_path, download_missing_images
from elysium.local_card.paths import get_sealed_image_cache_dir

HEADERS = {"User-Agent": "ElysiumMasterApplication/1.0 (local desktop app)"}


def get_cached_product_image_path(product_id: str) -> Path | None:
    path = cached_image_path(product_id, get_sealed_image_cache_dir())
    return path if path.exists() else None


def ensure_product_image_cached(product_id: str, image_url: str) -> Path | None:
    """Downloads the image if not already cached; returns the local path,
    or None if the download failed (never raises -- a missing product
    image thumbnail is not fatal to anything using it)."""
    cache_dir = get_sealed_image_cache_dir()
    existing = get_cached_product_image_path(product_id)

    if existing:
        return existing

    result = download_missing_images(items=[(product_id, image_url)], cache_dir=cache_dir, headers=HEADERS)

    if result.downloaded:
        return get_cached_product_image_path(product_id)

    return None
