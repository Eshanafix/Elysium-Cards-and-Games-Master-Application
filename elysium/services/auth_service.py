"""
Login and account management (LLD sections 6, 7, 19; docs/IMPLEMENTATION_
PLAN.md section 4.8 for the disable-account/decommission interaction).
"""

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from pymongo.errors import DuplicateKeyError

from elysium.bootstrap.provision_streamer_db import provision_streamer_database, streamer_database_name
from elysium.models.users import ROLE_ADMIN, ROLE_STREAMER, User
from elysium.repositories import master_repository as repo
from elysium.security.password_hashing import hash_password, verify_password
from elysium.services import audit_service
from elysium.services.mongo_client import get_master_db

logger = logging.getLogger(__name__)

MAX_STREAMER_KEY_ATTEMPTS = 5


class InvalidCredentialsError(Exception):
    pass


class AccountDisabledError(Exception):
    pass


class UsernameTakenError(Exception):
    pass


class ActiveStreamLockError(Exception):
    """Raised when an action targets a streamer who currently owns the
    active global stream lock (LLD 18.2, plan section 4.8)."""
    pass


class DisableOutcome(Enum):
    DISABLED = "DISABLED"
    REQUIRES_DECOMMISSION = "REQUIRES_DECOMMISSION"


def login(username: str, password: str) -> User:
    user = repo.find_user_by_username(username)

    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("Incorrect username or password.")

    if not user.is_active:
        raise AccountDisabledError("This account has been disabled.")

    logger.info("User '%s' logged in", username)
    return user


def _generate_unique_streamer_database_key() -> str:
    for _ in range(MAX_STREAMER_KEY_ATTEMPTS):
        candidate = secrets.token_hex(6)  # 12 hex chars, independent of username

        if not repo.get_master_db_users_streamer_key_exists(candidate):
            return candidate

    raise RuntimeError("Could not generate a unique streamer database key after several attempts.")


def create_user(username: str, password: str, roles: list[str], created_by: str) -> User:
    if repo.username_exists(username):
        raise UsernameTakenError(f"Username '{username}' is already taken.")

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    streamer_database_key = None
    db_name = None

    if ROLE_STREAMER in roles:
        streamer_database_key = _generate_unique_streamer_database_key()

        try:
            db_name = provision_streamer_database(streamer_database_key)
        except DuplicateKeyError:
            # Extremely unlikely given the pre-check above, but the unique
            # index is the real source of truth -- surface it rather than
            # silently proceeding with a possibly-shared database.
            raise RuntimeError("Streamer database key collision during provisioning; try again.")

    user = User(
        id=user_id,
        username=username,
        password_hash=hash_password(password),
        roles=list(roles),
        streamer_database_key=streamer_database_key,
        streamer_database_name=db_name,
        is_active=True,
        created_at=now,
        created_by=created_by,
        updated_at=now,
    )

    try:
        repo.insert_user(user)
    except DuplicateKeyError as e:
        raise UsernameTakenError(f"Username '{username}' is already taken.") from e

    audit_service.record_event(
        action_type="USER_CREATED",
        performed_by=created_by,
        after_values={"user_id": user_id, "username": username, "roles": roles},
    )

    logger.info("User '%s' created with roles %s by '%s'", username, roles, created_by)
    return user


def change_own_password(user: User, current_password: str, new_password: str) -> None:
    if not verify_password(current_password, user.password_hash):
        raise InvalidCredentialsError("Current password is incorrect.")

    reset_password(user.id, new_password, reset_by=user.id)


def reset_password(user_id: str, new_password: str, reset_by: str) -> None:
    now = datetime.now(timezone.utc)

    repo.update_user_fields(user_id, {
        "password_hash": hash_password(new_password),
        "password_reset_at": now,
        "updated_at": now,
    })

    audit_service.record_event(
        action_type="PASSWORD_RESET",
        performed_by=reset_by,
        after_values={"user_id": user_id},
    )

    logger.info("Password for user '%s' reset by '%s'", user_id, reset_by)


def _active_stream_owned_by(user_id: str) -> bool:
    lock = get_master_db().global_operations.find_one({"_id": "GLOBAL_OPERATIONS"})
    return bool(lock and lock.get("stream_active") and lock.get("streamer_id") == user_id)


def disable_account(user_id: str, requested_by: str) -> DisableOutcome:
    """
    Direct disabling only for non-streamers or streamers with zero net
    inventory; otherwise the caller must route through Decommissioning
    (plan section 4.8). Decommissioning itself is Phase 6 -- this just
    reports which path applies without silently disabling someone it
    shouldn't.
    """
    user = repo.find_user_by_id(user_id)

    if user is None:
        raise ValueError(f"No such user: {user_id}")

    if _active_stream_owned_by(user_id):
        raise ActiveStreamLockError(
            "This streamer currently owns the active stream. "
            "Complete or cancel it before disabling this account."
        )

    if ROLE_STREAMER in user.roles and repo.streamer_has_nonzero_allocation(user_id):
        return DisableOutcome.REQUIRES_DECOMMISSION

    repo.update_user_fields(user_id, {
        "is_active": False,
        "disabled_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })

    audit_service.record_event(
        action_type="ACCOUNT_DISABLED",
        performed_by=requested_by,
        streamer_id=user_id if ROLE_STREAMER in user.roles else None,
        after_values={"user_id": user_id},
    )

    logger.info("User '%s' disabled by '%s'", user_id, requested_by)
    return DisableOutcome.DISABLED
