"""
Scryfall bulk-data discovery and download.

Adapted from the reference project's bulk_import.py: same discovery/download
logic, now parameterized on paths (local_card.paths) instead of CWD-relative
constants, and sharing the User-Agent header convention Scryfall asks API
clients to send.

Scryfall's bulk-data API changed since the reference project was written:
each bulk-data object no longer has a `download_uri` pointing at one big
JSON array. It now has `jsonl_download_uri`, a gzip-compressed file of
newline-delimited JSON (one card object per line). load_bulk_cards()
decompresses and parses that format; everything downstream (insert_cards)
still just sees a plain list of card dicts, so no other code needed to
change.
"""

import gzip
import json
from pathlib import Path
from typing import Callable

import requests

BULK_INFO_URL = "https://api.scryfall.com/bulk-data"
CHUNK_SIZE = 8192

SCRYFALL_HEADERS = {
    "User-Agent": "ElysiumMasterApplication/1.0 (local desktop app)",
    "Accept": "application/json;q=0.9,*/*;q=0.8",
}


def get_default_cards_download_url() -> str:
    response = requests.get(BULK_INFO_URL, headers=SCRYFALL_HEADERS, timeout=30)
    response.raise_for_status()

    data = response.json()

    for item in data["data"]:
        if item["type"] == "default_cards":
            return item["jsonl_download_uri"]

    raise RuntimeError("Could not find default_cards bulk data.")


def download_default_cards(
    bulk_file_path: Path,
    progress_callback: Callable[[int, int], None] | None = None,
) -> None:
    """Downloads the default_cards bulk file to bulk_file_path. Streams to
    disk so large files don't need to fit in memory twice."""
    bulk_file_path.parent.mkdir(parents=True, exist_ok=True)

    download_url = get_default_cards_download_url()

    with requests.get(download_url, headers=SCRYFALL_HEADERS, stream=True, timeout=120) as response:
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0

        with open(bulk_file_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    file.write(chunk)
                    downloaded += len(chunk)

                    if progress_callback and total_size:
                        progress_callback(downloaded, total_size)


def load_bulk_cards(bulk_file_path: Path) -> list:
    cards = []

    with gzip.open(bulk_file_path, "rt", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if line:
                cards.append(json.loads(line))

    return cards
