import os

from dotenv import load_dotenv

load_dotenv()

APP_NAME = "Elysium Master Application"

MONGODB_CONNECT_TIMEOUT_MS = 4000

STALE_CARD_DATA_HOURS = 24


def resolve_mongodb_uri() -> str:
    """
    Keyring (Windows Credential Manager) first, since that's where a real
    installed build caches its baked-in connection (LLD 13.3) — falls back
    to the MONGODB_URI env var for local development via .env. Resolved
    on every call rather than cached at import time, so tests can
    monkeypatch the environment and a Retry-Connection click can pick up a
    freshly-stored keyring value without restarting the app.
    """
    from elysium.security.credential_store import get_stored_mongodb_uri

    stored = get_stored_mongodb_uri()

    if stored:
        return stored.strip()

    return os.environ.get("MONGODB_URI", "").strip()
