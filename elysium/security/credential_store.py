"""
Stores the MongoDB connection string using the Windows Credential Manager
(via the `keyring` package), per LLD 5.2. This is where a packaged,
installer-distributed build (docs/IMPLEMENTATION_PLAN.md section 13) caches
the connection it's baked in with on first launch, so it's never re-entered
or displayed again.

For local development right now, MONGODB_URI in .env is the simpler path
(config.resolve_mongodb_uri() checks keyring first, then falls back to the
env var) — nothing here requires keyring to actually hold a value yet.
"""

import keyring
from keyring.errors import KeyringError

_SERVICE_NAME = "ElysiumMasterApplication"
_USERNAME = "mongodb_uri"


def get_stored_mongodb_uri() -> str | None:
    try:
        return keyring.get_password(_SERVICE_NAME, _USERNAME)
    except KeyringError:
        return None


def set_stored_mongodb_uri(uri: str) -> None:
    keyring.set_password(_SERVICE_NAME, _USERNAME, uri)


def clear_stored_mongodb_uri() -> None:
    try:
        keyring.delete_password(_SERVICE_NAME, _USERNAME)
    except KeyringError:
        pass
