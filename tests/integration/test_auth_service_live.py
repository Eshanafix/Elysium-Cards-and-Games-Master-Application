"""
Live integration tests for auth_service against the real Atlas cluster,
using disposable itest_* accounts that are fully cleaned up afterward --
never touches your real admin account. Skips if Mongo isn't reachable.
"""

import uuid

import pytest

from elysium.models.users import ROLE_ADMIN, ROLE_STREAMER
from elysium.repositories import master_repository as repo
from elysium.services import auth_service
from elysium.services.mongo_client import check_connection, get_client, get_master_db

pytestmark = pytest.mark.skipif(
    not check_connection().is_connected,
    reason="MongoDB is not reachable -- set MONGODB_URI in .env to run integration tests",
)


@pytest.fixture
def created_users():
    """Yields a list the test appends User objects to; tears down every
    created user's document, any audit_events it generated, and drops any
    streamer database it provisioned, after the test finishes."""
    users = []
    yield users

    master_db = get_master_db()
    client = get_client()

    for user in users:
        master_db.users.delete_one({"_id": user.id})
        master_db.streamer_allocations.delete_many({"streamer_id": user.id})
        master_db.audit_events.delete_many({
            "$or": [{"performed_by": user.id}, {"after_values.user_id": user.id}]
        })

        if user.streamer_database_name:
            client.drop_database(user.streamer_database_name)

    master_db.audit_events.delete_many({"performed_by": "integration-test"})


def unique_username(label: str) -> str:
    return f"itest_{label}_{uuid.uuid4().hex[:8]}"


def test_create_streamer_user_provisions_database(created_users):
    username = unique_username("streamer")

    user = auth_service.create_user(username, "TestPassw0rd!", [ROLE_STREAMER], created_by="integration-test")
    created_users.append(user)

    assert user.streamer_database_key is not None
    assert user.streamer_database_name == f"elysium_s_{user.streamer_database_key}"

    db_names = get_client().list_database_names()
    assert user.streamer_database_name in db_names

    streamer_db = get_client()[user.streamer_database_name]
    collection_names = set(streamer_db.list_collection_names())
    assert {"inventory_current", "streams", "breaks", "streamer_history"}.issubset(collection_names)


def test_login_round_trip(created_users):
    username = unique_username("login")
    user = auth_service.create_user(username, "CorrectHorse1!", [ROLE_ADMIN], created_by="integration-test")
    created_users.append(user)

    logged_in = auth_service.login(username, "CorrectHorse1!")
    assert logged_in.id == user.id

    with pytest.raises(auth_service.InvalidCredentialsError):
        auth_service.login(username, "wrong-password")

    with pytest.raises(auth_service.InvalidCredentialsError):
        auth_service.login("no-such-user-" + uuid.uuid4().hex[:8], "whatever")


def test_disabled_account_cannot_login(created_users):
    username = unique_username("disable")
    user = auth_service.create_user(username, "Passw0rd!!", [ROLE_ADMIN], created_by="integration-test")
    created_users.append(user)

    outcome = auth_service.disable_account(user.id, requested_by="integration-test")
    assert outcome == auth_service.DisableOutcome.DISABLED

    with pytest.raises(auth_service.AccountDisabledError):
        auth_service.login(username, "Passw0rd!!")


def test_disable_account_requires_decommission_when_streamer_has_inventory(created_users):
    username = unique_username("hasinv")
    user = auth_service.create_user(username, "Passw0rd!!", [ROLE_STREAMER], created_by="integration-test")
    created_users.append(user)

    get_master_db().streamer_allocations.insert_one({
        "streamer_id": user.id,
        "product_id": "integration-test-product",
        "current_packs": 5,
        "version": 0,
        "updated_at": None,
    })

    outcome = auth_service.disable_account(user.id, requested_by="integration-test")
    assert outcome == auth_service.DisableOutcome.REQUIRES_DECOMMISSION

    still_active = repo.find_user_by_id(user.id)
    assert still_active.is_active is True


def test_reset_password_sets_exact_new_password(created_users):
    username = unique_username("reset")
    user = auth_service.create_user(username, "OldPassword1!", [ROLE_ADMIN], created_by="integration-test")
    created_users.append(user)

    auth_service.reset_password(user.id, "NewPassword2!", reset_by="integration-test")

    logged_in = auth_service.login(username, "NewPassword2!")
    assert logged_in.id == user.id

    with pytest.raises(auth_service.InvalidCredentialsError):
        auth_service.login(username, "OldPassword1!")


def test_change_own_password_requires_correct_current_password(created_users):
    username = unique_username("selfchange")
    user = auth_service.create_user(username, "Correct1!", [ROLE_ADMIN], created_by="integration-test")
    created_users.append(user)

    with pytest.raises(auth_service.InvalidCredentialsError):
        auth_service.change_own_password(user, "wrong-current", "NewOne1!")

    auth_service.change_own_password(user, "Correct1!", "NewOne1!")

    logged_in = auth_service.login(username, "NewOne1!")
    assert logged_in.id == user.id


def test_create_user_writes_user_created_audit_event(created_users):
    username = unique_username("audit")
    user = auth_service.create_user(username, "Passw0rd!!", [ROLE_ADMIN], created_by="integration-test")
    created_users.append(user)

    event = get_master_db().audit_events.find_one({
        "action_type": "USER_CREATED",
        "after_values.user_id": user.id,
    })

    assert event is not None
    assert event["performed_by"] == "integration-test"
    assert event["after_values"]["username"] == username
    assert event["status"] == "SUCCESS"


def test_reset_password_writes_audit_event(created_users):
    username = unique_username("auditreset")
    user = auth_service.create_user(username, "Passw0rd!!", [ROLE_ADMIN], created_by="integration-test")
    created_users.append(user)

    auth_service.reset_password(user.id, "NewOne1!", reset_by="integration-test")

    event = get_master_db().audit_events.find_one({
        "action_type": "PASSWORD_RESET",
        "after_values.user_id": user.id,
    })
    assert event is not None


def test_multiple_non_streamer_accounts_can_coexist(created_users):
    """Regression test for the sparse-index-vs-explicit-null bug: creating
    a second (and third) admin-only account must not collide on
    streamer_database_key, since none of them should have that field at
    all now."""
    first = auth_service.create_user(
        unique_username("multiadmin1"), "Passw0rd!!", [ROLE_ADMIN], created_by="integration-test"
    )
    created_users.append(first)

    second = auth_service.create_user(
        unique_username("multiadmin2"), "Passw0rd!!", [ROLE_ADMIN], created_by="integration-test"
    )
    created_users.append(second)

    third = auth_service.create_user(
        unique_username("multiadmin3"), "Passw0rd!!", [ROLE_ADMIN], created_by="integration-test"
    )
    created_users.append(third)

    assert len({first.id, second.id, third.id}) == 3


def test_disable_account_writes_audit_event(created_users):
    username = unique_username("auditdisable")
    user = auth_service.create_user(username, "Passw0rd!!", [ROLE_ADMIN], created_by="integration-test")
    created_users.append(user)

    auth_service.disable_account(user.id, requested_by="integration-test")

    event = get_master_db().audit_events.find_one({
        "action_type": "ACCOUNT_DISABLED",
        "after_values.user_id": user.id,
    })
    assert event is not None


def test_duplicate_username_is_rejected(created_users):
    username = unique_username("dup")
    user = auth_service.create_user(username, "Passw0rd!!", [ROLE_ADMIN], created_by="integration-test")
    created_users.append(user)

    with pytest.raises(auth_service.UsernameTakenError):
        auth_service.create_user(username, "AnotherPass1!", [ROLE_ADMIN], created_by="integration-test")
