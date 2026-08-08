import os
from pathlib import Path

APP_DIR_NAME = "ElysiumMasterApp"


def get_app_data_dir() -> Path:
    """
    Resolves the per-machine local storage root.

    Card data (SQLite DB, Scryfall bulk-data download, cached images) is
    independent on every computer per LLD 5.4/21.2, and must live under a
    stable location that works regardless of the app's launch/install
    directory (LLD 26.3-derived requirement, see docs/IMPLEMENTATION_PLAN.md
    section 8/10#4) — not relative to the current working directory as the
    original reference implementation did.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")

    if local_app_data:
        base = Path(local_app_data)
    else:
        # Non-Windows dev fallback; production target is Windows only (LLD 5.1).
        base = Path.home() / ".local" / "share"

    return base / APP_DIR_NAME


def get_db_path() -> Path:
    return get_app_data_dir() / "cards.sqlite"


def get_cache_dir() -> Path:
    return get_app_data_dir() / "cache"


def get_sealed_image_cache_dir() -> Path:
    return get_app_data_dir() / "sealed_product_images"


def get_data_dir() -> Path:
    return get_app_data_dir() / "data"


def get_bulk_file_path() -> Path:
    return get_data_dir() / "default_cards.jsonl.gz"


def get_setup_flag_path() -> Path:
    return get_data_dir() / "setup_complete.txt"


def ensure_app_dirs() -> None:
    get_app_data_dir().mkdir(parents=True, exist_ok=True)
    get_cache_dir().mkdir(parents=True, exist_ok=True)
    get_sealed_image_cache_dir().mkdir(parents=True, exist_ok=True)
    get_data_dir().mkdir(parents=True, exist_ok=True)
