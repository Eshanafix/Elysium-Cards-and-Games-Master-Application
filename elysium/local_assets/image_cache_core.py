"""
Generic "download a URL and cache it locally under a key" helper.

Shared by the card-image cache (elysium.local_card.image_cache, keyed by
Scryfall row_id) and the sealed-product image cache (services.sealed_image_
cache_service, keyed by product_id) — see docs/IMPLEMENTATION_PLAN.md
section 2.5/8. Both just need "key + URL -> local jpg", concurrently, with
failures isolated per-item so one bad URL never aborts the batch.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable, NamedTuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT_SECONDS = 15
# Lowered from 12: observed evidence (many connections stuck in SynSent,
# throughput collapsing under concurrent load) points at something on the
# local network path — router NAT table, antivirus/firewall connection
# inspection, etc. — struggling with a high rate of simultaneous new
# outbound connections. A smaller pool is gentler on that regardless of
# the exact cause.
DEFAULT_MAX_WORKERS = 6


def _build_session(max_workers: int) -> requests.Session:
    """
    A plain requests.get() per call opens a brand-new TCP+TLS connection
    every time — across tens of thousands of image requests that can
    exhaust locally available ephemeral ports (Windows holds each closed
    connection in TIME_WAIT for ~120s), which shows up as throughput
    quietly collapsing over the course of a run rather than staying
    roughly constant or failing outright. A shared Session with a
    connection-pooling HTTPAdapter reuses keep-alive connections across
    requests on the same thread instead of opening a fresh one each time.
    """
    session = requests.Session()

    retry = Retry(
        total=2,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )

    adapter = HTTPAdapter(pool_connections=max_workers, pool_maxsize=max_workers, max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


def safe_filename(key: str) -> str:
    return key.replace(":", "_").replace("/", "_")


def cached_image_path(key: str, cache_dir: Path, extension: str = "jpg") -> Path:
    return cache_dir / f"{safe_filename(key)}.{extension}"


class CacheResult(NamedTuple):
    downloaded: int
    cached: int
    missing_url: int
    failed: int


def download_missing_images(
    items: Iterable[tuple[str, str | None]],
    cache_dir: Path,
    headers: dict | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    on_progress: Callable[[int, int], None] | None = None,
) -> CacheResult:
    """
    items: iterable of (key, url) pairs. Skips any key whose cached file
    already exists. Downloads the rest concurrently.

    on_progress(completed_count, total_count) is called after each item
    finishes (success or failure), so callers can drive a progress bar.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)

    to_fetch = []
    missing_url = 0

    for key, url in items:
        if not url:
            missing_url += 1
            continue

        path = cached_image_path(key, cache_dir)

        if not path.exists():
            to_fetch.append((key, url, path))

    if not to_fetch:
        return CacheResult(downloaded=0, cached=0, missing_url=missing_url, failed=0)

    session = _build_session(max_workers)

    def fetch_one(item):
        key, url, path = item

        try:
            response = session.get(url, headers=headers, timeout=DEFAULT_TIMEOUT_SECONDS)
            response.raise_for_status()

            path.write_bytes(response.content)
            return True

        except Exception:
            return False

    downloaded = 0
    failed = 0
    completed = 0
    total = len(to_fetch)

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(fetch_one, item) for item in to_fetch]

            for future in as_completed(futures):
                success = future.result()
                completed += 1

                if success:
                    downloaded += 1
                else:
                    failed += 1

                if on_progress:
                    on_progress(completed, total)
    finally:
        session.close()

    return CacheResult(downloaded=downloaded, cached=0, missing_url=missing_url, failed=failed)
