"""
Live integration tests for inventory_service against real Atlas, replicating
the LLD's exact acceptance-test scenarios (29.1-29.5) and the worked
example in LLD section 33, using disposable itest_* products/streamers
cleaned up afterward.
"""

import uuid
from decimal import Decimal

import pytest

from elysium.models.users import ROLE_STREAMER
from elysium.services import auth_service, inventory_service, product_service
from elysium.services.mongo_client import check_connection, get_master_db

pytestmark = pytest.mark.skipif(
    not check_connection().is_connected,
    reason="MongoDB is not reachable -- set MONGODB_URI in .env to run integration tests",
)


def unique(label: str) -> str:
    return f"itest_{label}_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def scenario():
    """Sets up one disposable product + two disposable streamers, tears
    everything down (including all audit_events/allocations they touched)
    afterward regardless of test outcome."""
    product = product_service.create_product(
        name=unique("Inventory Test Booster"), booster_type="PLAY", packs_per_box=36,
        tcgcsv_category_id="1", tcgcsv_group_id="23556",
        loose_pack_tcgcsv_product_id=unique("loose"), box_tcgcsv_product_id=unique("box"),
        image_url="https://example.com/x.jpg", english_confirmed=True,
        created_by="integration-test",
    )

    streamer_a = auth_service.create_user(
        unique("streamerA"), "Passw0rd!!", [ROLE_STREAMER], created_by="integration-test"
    )
    streamer_b = auth_service.create_user(
        unique("streamerB"), "Passw0rd!!", [ROLE_STREAMER], created_by="integration-test"
    )

    yield product, streamer_a, streamer_b

    master_db = get_master_db()
    for streamer in (streamer_a, streamer_b):
        master_db.streamer_allocations.delete_many({"streamer_id": streamer.id})
        master_db.audit_events.delete_many({
            "$or": [{"performed_by": streamer.id}, {"after_values.user_id": streamer.id}, {"streamer_id": streamer.id}]
        })
        master_db.users.delete_one({"_id": streamer.id})
        if streamer.streamer_database_name:
            master_db.client.drop_database(streamer.streamer_database_name)

    master_db.products.delete_one({"_id": product.id})
    master_db.inventory_current.delete_one({"_id": product.id})
    master_db.audit_events.delete_many({"product_id": product.id})
    master_db.audit_events.delete_many({"performed_by": "integration-test"})


def assert_master_invariant(product_id: str):
    """Master total = unassigned + sum of streamer allocations (LLD 10.2),
    checked directly against Atlas after each mutation."""
    master_db = get_master_db()
    inventory = master_db.inventory_current.find_one({"_id": product_id})
    allocations = list(master_db.streamer_allocations.find({"product_id": product_id}))

    total_allocated = sum(a["current_packs"] for a in allocations)
    assert inventory["total_packs"] == inventory["unassigned_packs"] + total_allocated, (
        f"invariant broken: total={inventory['total_packs']} "
        f"unassigned={inventory['unassigned_packs']} allocated_sum={total_allocated}"
    )
    return inventory, {a["streamer_id"]: a["current_packs"] for a in allocations}


def test_291_inventory_conversion_stores_no_box_quantity(scenario):
    product, _a, _b = scenario

    packs = inventory_service.box_to_packs(boxes=2, loose_packs=4, packs_per_box=36)
    assert packs == 76

    inventory_service.admin_add_inventory(product.id, packs, "integration-test")

    doc = get_master_db().inventory_current.find_one({"_id": product.id})
    assert "boxes" not in doc
    assert doc["total_packs"] == 76

    audit = get_master_db().audit_events.find_one({"action_type": "MASTER_INVENTORY_ADDED", "product_id": product.id})
    assert audit is not None
    assert "boxes" not in (audit.get("after_values") or {})
    assert audit["quantity_change"] == 76


def test_292_master_addition(scenario):
    product, _a, _b = scenario

    inventory_service.admin_add_inventory(product.id, 76, "integration-test")

    doc = get_master_db().inventory_current.find_one({"_id": product.id})
    assert doc["total_packs"] == 76
    assert doc["unassigned_packs"] == 76

    audit = get_master_db().audit_events.find_one({"action_type": "MASTER_INVENTORY_ADDED", "product_id": product.id})
    assert audit is not None


def test_293_294_295_full_lld_section_33_worked_example(scenario):
    """Replicates LLD section 33's exact worked example end-to-end against
    real Atlas: master=60, Streamer A claims 30, Streamer B over-claims 40
    (rejected, nothing changes), Streamer B claims 30, Streamer B returns 5."""
    product, streamer_a, streamer_b = scenario

    # Master total: 60, Unassigned: 60
    inventory_service.admin_add_inventory(product.id, 60, "integration-test")
    inv, _allocs = assert_master_invariant(product.id)
    assert inv["total_packs"] == 60 and inv["unassigned_packs"] == 60

    # Streamer A claims 30 -> Master total: 60, Unassigned: 30, A: 30
    inventory_service.streamer_claim(
        streamer_a.id, streamer_a.streamer_database_name, product.id, 30, requested_by=streamer_a.id
    )
    inv, allocs = assert_master_invariant(product.id)
    assert inv["total_packs"] == 60
    assert inv["unassigned_packs"] == 30
    assert allocs[streamer_a.id] == 30

    a_streamer_inv = get_master_db().client[streamer_a.streamer_database_name].inventory_current.find_one(
        {"_id": product.id}
    )
    assert a_streamer_inv["current_packs"] == 30

    claim_audit = get_master_db().audit_events.find_one({
        "action_type": "STREAMER_INVENTORY_CLAIMED", "streamer_id": streamer_a.id, "product_id": product.id,
    })
    assert claim_audit is not None and claim_audit["quantity_change"] == 30

    # Streamer B attempts to claim 40 -- only 30 unassigned remain. Must be
    # rejected with NO changes to any value (LLD 29.4).
    with pytest.raises(inventory_service.InsufficientInventoryError):
        inventory_service.streamer_claim(
            streamer_b.id, streamer_b.streamer_database_name, product.id, 40, requested_by=streamer_b.id
        )

    inv, allocs = assert_master_invariant(product.id)
    assert inv["total_packs"] == 60
    assert inv["unassigned_packs"] == 30
    assert streamer_b.id not in allocs or allocs[streamer_b.id] == 0

    b_streamer_inv = get_master_db().client[streamer_b.streamer_database_name].inventory_current.find_one(
        {"_id": product.id}
    )
    assert b_streamer_inv is None or b_streamer_inv["current_packs"] == 0

    no_claim_audit = get_master_db().audit_events.find_one({
        "action_type": "STREAMER_INVENTORY_CLAIMED", "streamer_id": streamer_b.id, "product_id": product.id,
    })
    assert no_claim_audit is None, "a rejected over-claim must not write a CLAIMED audit event"

    # Streamer B claims 30 (all remaining) -> Unassigned: 0, A: 30, B: 30
    inventory_service.streamer_claim(
        streamer_b.id, streamer_b.streamer_database_name, product.id, 30, requested_by=streamer_b.id
    )
    inv, allocs = assert_master_invariant(product.id)
    assert inv["total_packs"] == 60
    assert inv["unassigned_packs"] == 0
    assert allocs[streamer_a.id] == 30
    assert allocs[streamer_b.id] == 30

    # Streamer B returns 5 (LLD 29.5) -> Unassigned: 5, B: 25, total unchanged.
    inventory_service.streamer_return(
        streamer_b.id, streamer_b.streamer_database_name, product.id, 5,
        reason="test return", requested_by=streamer_b.id,
    )
    inv, allocs = assert_master_invariant(product.id)
    assert inv["total_packs"] == 60
    assert inv["unassigned_packs"] == 5
    assert allocs[streamer_b.id] == 25
    assert allocs[streamer_a.id] == 30

    return_audit = get_master_db().audit_events.find_one({
        "action_type": "STREAMER_INVENTORY_RETURNED", "streamer_id": streamer_b.id, "product_id": product.id,
    })
    assert return_audit is not None
    assert return_audit["reason"] == "test return"


def test_return_requires_reason(scenario):
    product, streamer_a, _b = scenario

    inventory_service.admin_add_inventory(product.id, 10, "integration-test")
    inventory_service.streamer_claim(
        streamer_a.id, streamer_a.streamer_database_name, product.id, 10, requested_by=streamer_a.id
    )

    with pytest.raises(inventory_service.InventoryValidationError):
        inventory_service.streamer_return(
            streamer_a.id, streamer_a.streamer_database_name, product.id, 5, reason="", requested_by=streamer_a.id
        )


def test_reduce_requires_reason(scenario):
    product, _a, _b = scenario
    inventory_service.admin_add_inventory(product.id, 10, "integration-test")

    with pytest.raises(inventory_service.InventoryValidationError):
        inventory_service.admin_reduce_inventory(product.id, 5, "", "integration-test")


def test_reduce_cannot_exceed_unassigned(scenario):
    product, streamer_a, _b = scenario

    inventory_service.admin_add_inventory(product.id, 10, "integration-test")
    inventory_service.streamer_claim(
        streamer_a.id, streamer_a.streamer_database_name, product.id, 10, requested_by=streamer_a.id
    )
    # All 10 packs are now assigned; 0 unassigned remain.

    with pytest.raises(inventory_service.InsufficientInventoryError):
        inventory_service.admin_reduce_inventory(product.id, 1, "test reason", "integration-test")

    inv, _allocs = assert_master_invariant(product.id)
    assert inv["total_packs"] == 10  # unchanged by the rejected reduction


def test_return_cannot_exceed_current_holdings(scenario):
    product, streamer_a, _b = scenario

    inventory_service.admin_add_inventory(product.id, 10, "integration-test")
    inventory_service.streamer_claim(
        streamer_a.id, streamer_a.streamer_database_name, product.id, 10, requested_by=streamer_a.id
    )

    with pytest.raises(inventory_service.InsufficientInventoryError):
        inventory_service.streamer_return(
            streamer_a.id, streamer_a.streamer_database_name, product.id, 11,
            reason="too many", requested_by=streamer_a.id,
        )


def test_master_inventory_view_shows_username_not_raw_streamer_id(scenario):
    """Regression test: the Master Inventory screen's allocation summary
    displayed a truncated streamer_id (e.g. "ff63f196:18") instead of the
    streamer's actual username -- get_master_inventory_view() must resolve
    and attach the real username for every allocation."""
    product, streamer_a, _b = scenario

    inventory_service.admin_add_inventory(product.id, 10, "integration-test")
    inventory_service.streamer_claim(
        streamer_a.id, streamer_a.streamer_database_name, product.id, 10, requested_by=streamer_a.id
    )

    view = inventory_service.get_master_inventory_view()
    row = next(r for r in view if r["product"].id == product.id)

    assert len(row["allocations"]) == 1
    allocation = row["allocations"][0]
    assert allocation["streamer_username"] == streamer_a.username
    assert allocation["streamer_username"] != streamer_a.id[:8]
