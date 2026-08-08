"""
MongoDB Atlas connectivity, per LLD 6.3 / 27.2: the app must work whether or
not Atlas is reachable, guest Card Lookup must never depend on it, and the
user must be able to retry the connection.
"""

import threading
from dataclasses import dataclass

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError

from elysium import config

MASTER_DB_NAME = "elysium_master"
PRICES_DB_NAME = "elysium_prices"

_client: MongoClient | None = None
_client_lock = threading.Lock()


@dataclass
class ConnectionStatus:
    is_connected: bool
    detail: str


def get_client() -> MongoClient:
    global _client

    with _client_lock:
        if _client is None:
            _client = MongoClient(
                config.resolve_mongodb_uri(),
                serverSelectionTimeoutMS=config.MONGODB_CONNECT_TIMEOUT_MS,
            )
        return _client


def get_master_db() -> Database:
    return get_client()[MASTER_DB_NAME]


def get_prices_db() -> Database:
    return get_client()[PRICES_DB_NAME]


def get_streamer_db(streamer_database_name: str) -> Database:
    return get_client()[streamer_database_name]


def check_connection() -> ConnectionStatus:
    if not config.resolve_mongodb_uri():
        return ConnectionStatus(False, "No MongoDB connection is configured on this install yet.")

    try:
        get_client().admin.command("ping")
        return ConnectionStatus(True, "Connected.")
    except PyMongoError as e:
        return ConnectionStatus(False, str(e))


def test_connection_string(uri: str) -> ConnectionStatus:
    """Validates a candidate URI on a throwaway client, without touching the
    shared client -- used by the Login screen's connection setup dialog to
    verify a URI before it's saved to Credential Manager."""
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=config.MONGODB_CONNECT_TIMEOUT_MS)
        client.admin.command("ping")
        client.close()
        return ConnectionStatus(True, "Connected.")
    except PyMongoError as e:
        return ConnectionStatus(False, str(e))


def reset_client() -> None:
    """Forces the next check_connection()/get_client() call to reconnect
    from scratch — used by the Login screen's Retry Connection action."""
    global _client

    with _client_lock:
        if _client is not None:
            _client.close()
        _client = None
