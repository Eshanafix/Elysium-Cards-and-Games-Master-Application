"""
LLD section 29 acceptance criteria that are pure logic -- no MongoDB
required. Live/DB-dependent criteria are in test_29_live_scope.py.
"""

import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from elysium.local_card.db import is_stale
from elysium.services import inventory_service, stream_service
from elysium.ui.shell import GuestShell
from elysium.services.mongo_client import check_connection


def test_29_1_inventory_conversion():
    """2 boxes + 4 loose packs at 36 packs/box = 76 packs; no box quantity
    is ever accepted by the actual inventory-writing function."""
    assert inventory_service.box_to_packs(boxes=2, loose_packs=4, packs_per_box=36) == 76

    add_params = inspect.signature(inventory_service.admin_add_inventory).parameters
    assert "boxes" not in add_params
    assert set(add_params) == {"product_id", "packs", "admin_id"}


def test_29_12_final_stream_calculation():
    """Break gross total = $500, final stream gross = $480, pack market
    value = $300 -> gross difference = -$20, stream profit = $180."""
    break_gross_total = Decimal("500")
    final_stream_gross = Decimal("480")
    pack_market_value = Decimal("300")

    gross_difference = final_stream_gross - break_gross_total
    stream_profit = stream_service.compute_stream_profit(final_stream_gross, pack_market_value)

    assert gross_difference == Decimal("-20")
    assert stream_profit == Decimal("180")


def test_29_18_card_data_stale_banner():
    """More than 24 hours since last local refresh triggers the stale
    banner; a fresh refresh, or having never refreshed at all, does not."""
    assert is_stale(datetime.now(timezone.utc) - timedelta(hours=25), hours=24) is True
    assert is_stale(datetime.now(timezone.utc) - timedelta(hours=1), hours=24) is False
    assert is_stale(None, hours=24) is False  # never-refreshed is a distinct empty state


def test_29_19_offline_mode_guest_shell_only_exposes_card_lookup(qtbot):
    """Guest access (no login) must only ever offer Card Lookup + Login --
    no shared/company screen is reachable without an account, so there is
    nothing that could attempt a shared write while offline."""
    shell = GuestShell(on_login_requested=lambda: None)
    qtbot.addWidget(shell)

    labels = [shell.nav_list.item(i).text() for i in range(shell.nav_list.count())]

    assert labels == ["Card Lookup", "Login"]


def test_29_19_offline_mode_connection_check_never_raises():
    """check_connection() must degrade gracefully (used to drive the guest
    fallback), never raise, even when MongoDB is genuinely unreachable."""
    status = check_connection()
    assert isinstance(status.is_connected, bool)
