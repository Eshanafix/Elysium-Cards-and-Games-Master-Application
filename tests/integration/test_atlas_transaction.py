"""
Resolves docs/IMPLEMENTATION_PLAN.md section 10 item 6 -- the single
highest-risk open item in the whole plan: does the actual provisioned
Atlas cluster support multi-document ACID transactions spanning more than
one database in the same client session? Every claim/return/stream-start/
stream-complete transaction design in the plan depends on this being true.

Skips (rather than fails) when Mongo isn't reachable, so this suite doesn't
break for a contributor without Atlas credentials configured.
"""

import uuid

import pytest
from pymongo.errors import PyMongoError

from elysium.services.mongo_client import check_connection, get_client, get_master_db, get_streamer_db

TEST_STREAMER_DB_NAME = "elysium_s_integration_test"

pytestmark = pytest.mark.skipif(
    not check_connection().is_connected,
    reason="MongoDB is not reachable -- set MONGODB_URI in .env to run integration tests",
)


@pytest.fixture
def cleanup_test_docs():
    inserted_ids = []
    yield inserted_ids

    master_db = get_master_db()
    for doc_id in inserted_ids:
        master_db.integration_test_scratch.delete_one({"_id": doc_id})

    # Mongo auto-creates elysium_s_integration_test on first write to it;
    # drop the whole database rather than leaving an empty shell behind
    # for every test run.
    get_client().drop_database(TEST_STREAMER_DB_NAME)


def test_cross_database_transaction_commits(cleanup_test_docs):
    """A single transaction writes to elysium_master AND a separate
    streamer-style database, commits, and both writes must be visible
    afterward -- proving real distributed multi-document ACID transactions
    work on this cluster."""
    doc_id = str(uuid.uuid4())
    cleanup_test_docs.append(doc_id)

    client = get_client()
    master_db = get_master_db()
    streamer_db = get_streamer_db(TEST_STREAMER_DB_NAME)

    with client.start_session() as session:
        with session.start_transaction():
            master_db.integration_test_scratch.insert_one(
                {"_id": doc_id, "marker": "master"}, session=session
            )
            streamer_db.integration_test_scratch.insert_one(
                {"_id": doc_id, "marker": "streamer"}, session=session
            )

    master_doc = master_db.integration_test_scratch.find_one({"_id": doc_id})
    streamer_doc = streamer_db.integration_test_scratch.find_one({"_id": doc_id})

    assert master_doc is not None and master_doc["marker"] == "master"
    assert streamer_doc is not None and streamer_doc["marker"] == "streamer"


def test_cross_database_transaction_aborts_on_error(cleanup_test_docs):
    """If the second write in a cross-database transaction fails, the first
    write must NOT be left behind -- proving atomicity, not just that two
    writes can happen to succeed together."""
    doc_id = str(uuid.uuid4())
    cleanup_test_docs.append(doc_id)

    client = get_client()
    master_db = get_master_db()
    streamer_db = get_streamer_db(TEST_STREAMER_DB_NAME)

    class DeliberateFailure(Exception):
        pass

    with pytest.raises(DeliberateFailure):
        with client.start_session() as session:
            with session.start_transaction():
                master_db.integration_test_scratch.insert_one(
                    {"_id": doc_id, "marker": "master"}, session=session
                )
                raise DeliberateFailure("simulated failure before the second write")

    master_doc = master_db.integration_test_scratch.find_one({"_id": doc_id})
    streamer_doc = streamer_db.integration_test_scratch.find_one({"_id": doc_id})

    assert master_doc is None, "aborted transaction must not leave a partial write behind"
    assert streamer_doc is None


def test_with_transaction_helper_retries_and_commits(cleanup_test_docs):
    """pymongo's recommended with_transaction() retry helper (what the real
    services will use, per plan section 4.1) works end-to-end too, not just
    manual start_transaction()."""
    doc_id = str(uuid.uuid4())
    cleanup_test_docs.append(doc_id)

    client = get_client()
    master_db = get_master_db()
    streamer_db = get_streamer_db(TEST_STREAMER_DB_NAME)

    def callback(session):
        master_db.integration_test_scratch.insert_one(
            {"_id": doc_id, "marker": "master"}, session=session
        )
        streamer_db.integration_test_scratch.insert_one(
            {"_id": doc_id, "marker": "streamer"}, session=session
        )

    with client.start_session() as session:
        session.with_transaction(callback)

    assert master_db.integration_test_scratch.find_one({"_id": doc_id}) is not None
    assert streamer_db.integration_test_scratch.find_one({"_id": doc_id}) is not None
