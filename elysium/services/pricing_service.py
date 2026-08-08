"""
Shared sealed-product pricing (LLD section 9; docs/IMPLEMENTATION_PLAN.md
sections 2.6/4.3). TCGCSV refresh is batched per (category, group) instead
of per product, and price-record selection/ambiguity handling matches the
live-verified TCGCSV shape (see plan section 2.6's Phase 3 addendum).
"""

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

import requests

from elysium.models.prices import (
    SOURCE_DERIVED_FROM_BOX_MARKET,
    SOURCE_LOOSE_PACK_MARKET,
    SOURCE_MANUAL,
    SOURCE_PREVIOUS_VALUE,
    STATUS_AMBIGUOUS,
    STATUS_MANUAL,
    STATUS_OK,
    STATUS_UNRESOLVED,
    CurrentPrice,
    ManualPriceMetadata,
)
from elysium.models.products import Product
from elysium.repositories import price_repository as price_repo
from elysium.services import audit_service, lock_service, product_service

logger = logging.getLogger(__name__)

TCGCSV_BASE_URL = "https://tcgcsv.com/tcgplayer"
TCGCSV_TIMEOUT_SECONDS = 30
TCGCSV_HEADERS = {"User-Agent": "ElysiumMasterApplication/1.0 (local desktop app)"}

# Priority order for selecting one price row when a productId has more than
# one. Verified live (2026-08-07): sealed booster/box products only ever
# return a single "Normal" row; "Foil" only appears for individual cards.
PREFERRED_SUBTYPE_PRIORITY = ["normal"]


class PriceEntryError(Exception):
    pass


def fetch_group_prices(category_id: str, group_id: str) -> list[dict]:
    url = f"{TCGCSV_BASE_URL}/{category_id}/{group_id}/prices"
    response = requests.get(url, headers=TCGCSV_HEADERS, timeout=TCGCSV_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json().get("results", [])


def _extract_market_price(row: dict) -> Decimal | None:
    market = row.get("marketPrice")
    return Decimal(str(market)) if market is not None else None


def group_rows_by_product_id(rows: list[dict]) -> dict[str, list[dict]]:
    """
    TCGCSV returns productId as a JSON number, but loose_pack_tcgcsv_
    product_id/box_tcgcsv_product_id are stored as strings throughout the
    schema -- key by str(productId) so lookups against those fields
    actually match. (A prior version of this function kept the raw int
    key, which made every lookup silently miss and every product resolve
    as UNRESOLVED regardless of real data availability.)
    """
    grouped: dict[str, list[dict]] = defaultdict(list)

    for row in rows:
        product_id = row.get("productId")

        if product_id is not None:
            grouped[str(product_id)].append(row)

    return grouped


def resolve_single_mapping(rows: list[dict]) -> tuple[Decimal | None, bool]:
    """
    Returns (price, is_ambiguous) for one TCGCSV productId's price rows.
    Never guesses: multiple rows with no single preferred match come back
    as (None, True) rather than silently picking one (plan section 2.6).
    """
    if not rows:
        return None, False

    if len(rows) == 1:
        return _extract_market_price(rows[0]), False

    for preferred in PREFERRED_SUBTYPE_PRIORITY:
        matches = [r for r in rows if str(r.get("subTypeName", "")).strip().lower() == preferred]

        if len(matches) == 1:
            return _extract_market_price(matches[0]), False

    return None, True


def _record_price_history(
    product_id: str,
    previous_price,
    new_price,
    previous_source,
    new_source,
    initiated_by: str,
    session_id: str,
    tcgcsv_status: str,
    manual_entry_by: str | None = None,
) -> None:
    price_repo.insert_price_history(
        product_id=product_id,
        previous_price=previous_price,
        new_price=new_price,
        previous_source=previous_source,
        new_source=new_source,
        initiated_by=initiated_by,
        refresh_session_id=session_id,
        tcgcsv_status=tcgcsv_status,
        manual_entry_by=manual_entry_by,
    )


def _resolve_and_store_product_price(
    product: Product,
    rows_by_product_id: dict,
    session_id: str,
    started_by: str,
) -> None:
    loose_rows = rows_by_product_id.get(product.loose_pack_tcgcsv_product_id, [])
    box_rows = rows_by_product_id.get(product.box_tcgcsv_product_id, [])

    loose_price, loose_ambiguous = resolve_single_mapping(loose_rows)
    box_price, box_ambiguous = resolve_single_mapping(box_rows)

    existing = price_repo.find_current_price(product.id)
    now = datetime.now(timezone.utc)

    price_repo.increment_refresh_session_counters(session_id, products_checked=1)

    if loose_price is not None:
        resolved_price, source, status = loose_price, SOURCE_LOOSE_PACK_MARKET, STATUS_OK
    elif box_price is not None:
        resolved_price = box_price / product.packs_per_box
        source, status = SOURCE_DERIVED_FROM_BOX_MARKET, STATUS_OK
    elif loose_ambiguous or box_ambiguous:
        resolved_price, source, status = None, None, STATUS_AMBIGUOUS
    else:
        resolved_price, source, status = None, None, STATUS_UNRESOLVED

    # A manual price stays in effect until a later refresh finds a genuinely
    # valid automatic price (LLD 9.5) -- an UNRESOLVED/AMBIGUOUS outcome
    # must not clobber an existing manual price.
    if status != STATUS_OK and existing and existing.price_status == STATUS_MANUAL:
        price_repo.upsert_current_price(CurrentPrice(
            product_id=product.id,
            tcgcsv_category_id=product.tcgcsv_category_id,
            tcgcsv_group_id=product.tcgcsv_group_id,
            loose_pack_tcgcsv_product_id=product.loose_pack_tcgcsv_product_id,
            box_tcgcsv_product_id=product.box_tcgcsv_product_id,
            packs_per_box=product.packs_per_box,
            raw_loose_pack_market_price=loose_price,
            raw_box_market_price=box_price,
            resolved_pack_price=existing.resolved_pack_price,
            resolved_price_source=existing.resolved_price_source,
            price_status=STATUS_MANUAL,
            last_successful_refresh_at=existing.last_successful_refresh_at,
            last_attempted_refresh_at=now,
            last_modified_by=existing.last_modified_by,
            previous_resolved_price=existing.previous_resolved_price,
            manual_price_metadata=existing.manual_price_metadata,
            version=existing.version + 1,
            updated_at=now,
        ))

        if status == STATUS_AMBIGUOUS:
            price_repo.increment_refresh_session_counters(session_id, ambiguous_products=1)

        return

    previous_resolved_price = None
    if existing:
        previous_resolved_price = existing.resolved_pack_price or existing.previous_resolved_price

    price_repo.upsert_current_price(CurrentPrice(
        product_id=product.id,
        tcgcsv_category_id=product.tcgcsv_category_id,
        tcgcsv_group_id=product.tcgcsv_group_id,
        loose_pack_tcgcsv_product_id=product.loose_pack_tcgcsv_product_id,
        box_tcgcsv_product_id=product.box_tcgcsv_product_id,
        packs_per_box=product.packs_per_box,
        raw_loose_pack_market_price=loose_price,
        raw_box_market_price=box_price,
        resolved_pack_price=resolved_price,
        resolved_price_source=source,
        price_status=status,
        last_successful_refresh_at=now if status == STATUS_OK else (existing.last_successful_refresh_at if existing else None),
        last_attempted_refresh_at=now,
        last_modified_by=started_by if status == STATUS_OK else (existing.last_modified_by if existing else None),
        previous_resolved_price=previous_resolved_price,
        manual_price_metadata=None,
        version=(existing.version + 1) if existing else 0,
        updated_at=now,
    ))

    if status == STATUS_OK:
        old_price = existing.resolved_pack_price if existing else None

        if old_price == resolved_price:
            price_repo.increment_refresh_session_counters(session_id, prices_unchanged=1)
        else:
            price_repo.increment_refresh_session_counters(session_id, prices_updated=1)

        if source == SOURCE_LOOSE_PACK_MARKET:
            price_repo.increment_refresh_session_counters(session_id, loose_pack_prices_used=1)
        else:
            price_repo.increment_refresh_session_counters(session_id, box_derived_prices_used=1)

        _record_price_history(
            product.id, old_price, resolved_price,
            existing.resolved_price_source if existing else None, source,
            started_by, session_id, "OK",
        )
    elif status == STATUS_AMBIGUOUS:
        price_repo.increment_refresh_session_counters(session_id, ambiguous_products=1)
        price_repo.push_refresh_session_failure(
            session_id, "failed_products",
            {"product_id": product.id, "error": "AMBIGUOUS_PRICE_RECORD: multiple candidate price rows"},
        )


def refresh_prices(started_by: str) -> str:
    """
    Full refresh: acquire the lock, group every catalog product (including
    zero-stock, LLD 9.6 step 3) by TCGCSV group, fetch each unique group's
    price dataset once, resolve and store every product's price. Always
    releases the lock, even on failure.
    """
    session_id = lock_service.acquire_price_refresh_lock(started_by)
    price_repo.create_refresh_session(session_id, started_by)

    audit_service.record_event(
        action_type="PRICE_REFRESH_STARTED", performed_by=started_by, related_transaction_id=session_id,
    )

    try:
        products = product_service.list_products()

        groups: dict[tuple[str, str], list[Product]] = defaultdict(list)
        for product in products:
            groups[(product.tcgcsv_category_id, product.tcgcsv_group_id)].append(product)

        price_repo.update_refresh_session(session_id, {"unique_groups_requested": len(groups)})

        for (category_id, group_id), group_products in groups.items():
            try:
                rows = fetch_group_prices(category_id, group_id)
            except Exception as e:
                logger.exception("TCGCSV group fetch failed for group %s", group_id)
                price_repo.push_refresh_session_failure(
                    session_id, "failed_groups", {"tcgcsv_group_id": group_id, "error": str(e)},
                )
                continue

            rows_by_product_id = group_rows_by_product_id(rows)

            for product in group_products:
                _resolve_and_store_product_price(product, rows_by_product_id, session_id, started_by)

        price_repo.update_refresh_session(session_id, {
            "status": "COMPLETED",
            "completed_at": datetime.now(timezone.utc),
        })

        audit_service.record_event(
            action_type="PRICE_REFRESH_COMPLETED", performed_by=started_by, related_transaction_id=session_id,
        )

    except Exception as e:
        logger.exception("Price refresh failed")
        price_repo.update_refresh_session(session_id, {
            "status": "FAILED",
            "completed_at": datetime.now(timezone.utc),
            "error_summary": str(e),
        })
        audit_service.record_event(
            action_type="PRICE_REFRESH_FAILED", performed_by=started_by,
            related_transaction_id=session_id, status="FAILURE", reason=str(e),
        )
        raise

    finally:
        lock_service.release_price_refresh_lock()

    return session_id


def enter_manual_price(product_id: str, price: Decimal, entered_by: str, note: str | None = None) -> None:
    existing = price_repo.find_current_price(product_id)
    now = datetime.now(timezone.utc)
    correlation_id = str(uuid.uuid4())

    old_price = existing.resolved_pack_price if existing else None
    old_source = existing.resolved_price_source if existing else None

    price_repo.upsert_current_price(CurrentPrice(
        product_id=product_id,
        tcgcsv_category_id=existing.tcgcsv_category_id if existing else None,
        tcgcsv_group_id=existing.tcgcsv_group_id if existing else None,
        loose_pack_tcgcsv_product_id=existing.loose_pack_tcgcsv_product_id if existing else None,
        box_tcgcsv_product_id=existing.box_tcgcsv_product_id if existing else None,
        packs_per_box=existing.packs_per_box if existing else None,
        raw_loose_pack_market_price=existing.raw_loose_pack_market_price if existing else None,
        raw_box_market_price=existing.raw_box_market_price if existing else None,
        resolved_pack_price=price,
        resolved_price_source=SOURCE_MANUAL,
        price_status=STATUS_MANUAL,
        last_successful_refresh_at=existing.last_successful_refresh_at if existing else None,
        last_attempted_refresh_at=existing.last_attempted_refresh_at if existing else None,
        last_modified_by=entered_by,
        previous_resolved_price=old_price,
        manual_price_metadata=ManualPriceMetadata(entered_by=entered_by, entered_at=now, note=note),
        version=(existing.version + 1) if existing else 0,
        updated_at=now,
    ))

    _record_price_history(
        product_id, old_price, price, old_source, SOURCE_MANUAL,
        entered_by, correlation_id, "MANUAL", manual_entry_by=entered_by,
    )

    audit_service.record_event(
        action_type="MANUAL_PRICE_ENTERED", performed_by=entered_by, product_id=product_id,
        amount_change=price, reason=note, related_transaction_id=correlation_id,
    )


def accept_previous_price(product_id: str, accepted_by: str) -> None:
    existing = price_repo.find_current_price(product_id)

    if existing is None or existing.previous_resolved_price is None:
        raise PriceEntryError(f"No previous price is available for '{product_id}'.")

    now = datetime.now(timezone.utc)
    correlation_id = str(uuid.uuid4())
    accepted_price = existing.previous_resolved_price

    price_repo.upsert_current_price(CurrentPrice(
        product_id=product_id,
        tcgcsv_category_id=existing.tcgcsv_category_id,
        tcgcsv_group_id=existing.tcgcsv_group_id,
        loose_pack_tcgcsv_product_id=existing.loose_pack_tcgcsv_product_id,
        box_tcgcsv_product_id=existing.box_tcgcsv_product_id,
        packs_per_box=existing.packs_per_box,
        raw_loose_pack_market_price=existing.raw_loose_pack_market_price,
        raw_box_market_price=existing.raw_box_market_price,
        resolved_pack_price=accepted_price,
        resolved_price_source=SOURCE_PREVIOUS_VALUE,
        price_status=STATUS_OK,
        last_successful_refresh_at=existing.last_successful_refresh_at,
        last_attempted_refresh_at=existing.last_attempted_refresh_at,
        last_modified_by=accepted_by,
        previous_resolved_price=existing.previous_resolved_price,
        manual_price_metadata=None,
        version=existing.version + 1,
        updated_at=now,
    ))

    _record_price_history(
        product_id, None, accepted_price, existing.resolved_price_source, SOURCE_PREVIOUS_VALUE,
        accepted_by, correlation_id, "PREVIOUS_VALUE_ACCEPTED",
    )

    audit_service.record_event(
        action_type="PREVIOUS_PRICE_ACCEPTED", performed_by=accepted_by, product_id=product_id,
        amount_change=accepted_price, related_transaction_id=correlation_id,
    )
