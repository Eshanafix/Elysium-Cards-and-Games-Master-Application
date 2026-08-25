"""
Report queries (LLD section 20; docs/IMPLEMENTATION_PLAN.md section 6.12).
Every function returns a flat list[dict] -- CSV-ready rows, no nested
objects or raw Decimal/dataclass values -- and enforces LLD 20.1's
visibility rule itself (admin: all company data; streamer: their own data
only) rather than trusting the UI layer to filter correctly.

Scoped to the 14 datasets LLD section 20.5 explicitly names. The broader
"additional useful reports" list in section 20.4 (zero-stock products,
stale prices, inventory by booster type, etc.) are slices of these same
datasets -- the Reports screen's filters/sort on the preview table cover
them rather than each needing its own dedicated query function.
"""

from datetime import datetime, timezone
from decimal import Decimal

from elysium.models.users import ROLE_ADMIN, ROLE_STREAMER, User
from elysium.repositories import master_repository as repo
from elysium.repositories import price_repository as price_repo
from elysium.repositories import streamer_repository as streamer_repo
from elysium.services import audit_service, decommission_service, discrepancy_service, inventory_service


class ReportPermissionError(Exception):
    pass


def _require_admin(user: User) -> None:
    if ROLE_ADMIN not in user.roles:
        raise ReportPermissionError("This report is admin-only.")


def _streamer_scope(user: User, streamer_id: str | None) -> list[User]:
    """LLD 20.1: admins see all company data (optionally narrowed to one
    streamer via the filter); a streamer only ever sees their own data,
    regardless of what filter value is passed."""
    if ROLE_ADMIN in user.roles:
        streamers = [u for u in repo.list_users() if ROLE_STREAMER in u.roles and u.streamer_database_name]
        if streamer_id:
            streamers = [u for u in streamers if u.id == streamer_id]
        return streamers

    if ROLE_STREAMER in user.roles:
        return [user]

    return []


def _in_range(value, start_date, end_date) -> bool:
    if value is None:
        return start_date is None and end_date is None
    if start_date and value < start_date:
        return False
    if end_date and value > end_date:
        return False
    return True


def _money(value: Decimal | None):
    # Capped to 2 decimal places for display/export -- a raw Decimal
    # division (e.g. box price / packs per box, or a derived profit sum)
    # can carry many more digits than that, which read as noise in a report
    # table/CSV. Every other screen in the app already formats money this
    # way (f"${x:.2f}"); report_service just never matched it.
    return f"{value:.2f}" if value is not None else None


def _pack_summary(pack_lines: list[dict], products_by_id: dict) -> str:
    """One product per line ("Name x3") rather than comma-joined -- a break
    with several products comma-joined into one line ran wide enough to
    dominate the whole preview table/CSV row."""
    if not pack_lines:
        return ""

    return "\n".join(
        f"{products_by_id.get(line['product_id']).name if products_by_id.get(line['product_id']) else line['product_id']} x{line['quantity']}"
        for line in pack_lines
    )


# --- 1. master_inventory ---


def master_inventory_report(user: User) -> list[dict]:
    _require_admin(user)

    rows = []
    for row in inventory_service.get_master_inventory_view():
        product = row["product"]
        rows.append({
            "product_id": product.id,
            "product_name": product.name,
            "set_name": product.set_name,
            "booster_type": product.booster_type,
            "total_packs": row["total_packs"],
            "unassigned_packs": row["unassigned_packs"],
            "assigned_packs": row["assigned_packs"],
            "resolved_pack_price": _money(row["resolved_pack_price"]),
            "price_status": row["price_status"],
        })
    return rows


# --- 2. streamer_inventory ---


def streamer_inventory_report(user: User, streamer_id: str | None = None) -> list[dict]:
    rows = []
    for streamer in _streamer_scope(user, streamer_id):
        for row in inventory_service.get_streamer_inventory_view(streamer.streamer_database_name):
            product = row["product"]
            rows.append({
                "streamer_username": streamer.username,
                "product_id": product.id,
                "product_name": product.name,
                "current_packs": row["current_packs"],
                "resolved_pack_price": _money(row["resolved_pack_price"]),
                "price_status": row["price_status"],
            })
    return rows


# --- 3. streamer_allocations ---


def streamer_allocations_report(user: User, streamer_id: str | None = None) -> list[dict]:
    _require_admin(user)

    products_by_id = {p.id: p for p in repo.list_products()}
    username_by_id = {u.id: u.username for u in repo.list_users()}

    allocations = (
        repo.list_streamer_allocations_for_streamer(streamer_id) if streamer_id
        else repo.list_all_streamer_allocations()
    )

    rows = []
    for a in allocations:
        product = products_by_id.get(a["product_id"])
        rows.append({
            "streamer_username": username_by_id.get(a["streamer_id"], a["streamer_id"]),
            "product_id": a["product_id"],
            "product_name": product.name if product else a["product_id"],
            "current_packs": a["current_packs"],
        })
    return rows


# --- streams/breaks shared traversal ---


def _iter_streams_and_breaks(user: User, streamer_id: str | None, start_date, end_date):
    for streamer in _streamer_scope(user, streamer_id):
        for stream in streamer_repo.list_streams(streamer.streamer_database_name):
            if not _in_range(stream.start_time, start_date, end_date):
                continue

            breaks = streamer_repo.list_breaks_for_stream(streamer.streamer_database_name, stream.id, include_deleted=True)
            yield streamer, stream, breaks


# --- 4. streams ---


def streams_report(user: User, streamer_id: str | None = None, start_date=None, end_date=None) -> list[dict]:
    rows = []
    for streamer, stream, breaks in _iter_streams_and_breaks(user, streamer_id, start_date, end_date):
        rows.append({
            "stream_id": stream.id,
            "streamer_username": streamer.username,
            "date": stream.date,
            "start_time": stream.start_time,
            "end_time": stream.end_time,
            "status": stream.status,
            "number_of_breaks": len(breaks),
            "sum_of_break_gross": _money(stream.sum_of_break_gross),
            "final_stream_gross": _money(stream.final_stream_gross),
            "gross_difference": _money(stream.gross_difference),
            "stream_pack_market_value": _money(stream.stream_pack_market_value),
            "stream_profit": _money(stream.stream_profit),
            "stream_profit_margin": _money(stream.stream_profit_margin),
            "notes": stream.notes,
            "force_canceled": stream.force_canceled,
            "correction_count": len(stream.corrections),
        })
    return rows


# --- 5. breaks ---


def breaks_report(user: User, streamer_id: str | None = None, start_date=None, end_date=None) -> list[dict]:
    products_by_id = {p.id: p for p in repo.list_products()}

    rows = []
    for streamer, stream, breaks in _iter_streams_and_breaks(user, streamer_id, start_date, end_date):
        for b in breaks:
            rows.append({
                "streamer_username": streamer.username,
                "sequence_number": b.sequence_number,
                "name": b.name,
                "status": b.status,
                "packs_opened": _pack_summary(b.pack_lines, products_by_id),
                "start_time": b.start_time,
                "end_time": b.end_time,
                "total_pack_market_value": _money(b.total_pack_market_value),
                "break_gross": _money(b.break_gross),
                "break_profit": _money(b.break_profit),
                "break_profit_margin": _money(b.break_profit_margin),
                "notes": b.notes,
                "updated_at": b.updated_at,
                "break_id": b.id,
                "stream_id": stream.id,
            })
    return rows


# --- 6. break_products ---


def break_products_report(user: User, streamer_id: str | None = None, start_date=None, end_date=None) -> list[dict]:
    products_by_id = {p.id: p for p in repo.list_products()}

    rows = []
    for streamer, stream, breaks in _iter_streams_and_breaks(user, streamer_id, start_date, end_date):
        for b in breaks:
            for line in b.pack_lines:
                product = products_by_id.get(line["product_id"])
                rows.append({
                    "streamer_username": streamer.username,
                    "product_name": product.name if product else line["product_id"],
                    "quantity": line["quantity"],
                    "locked_unit_price": _money(line["locked_unit_price"]),
                    "price_source": line["price_source"],
                    "line_market_value": _money(line["line_market_value"]),
                    "product_id": line["product_id"],
                    "break_id": b.id,
                    "stream_id": stream.id,
                })
    return rows


# --- 7. stream_profit ---


def stream_profit_report(user: User, streamer_id: str | None = None, start_date=None, end_date=None) -> list[dict]:
    return [
        {
            "stream_id": row["stream_id"],
            "streamer_username": row["streamer_username"],
            "date": row["date"],
            "final_stream_gross": row["final_stream_gross"],
            "stream_pack_market_value": row["stream_pack_market_value"],
            "stream_profit": row["stream_profit"],
            "stream_profit_margin": row["stream_profit_margin"],
        }
        for row in streams_report(user, streamer_id, start_date, end_date)
    ]


# --- 8. break_profit ---


def break_profit_report(user: User, streamer_id: str | None = None, start_date=None, end_date=None) -> list[dict]:
    return [
        {
            "break_id": row["break_id"],
            "stream_id": row["stream_id"],
            "streamer_username": row["streamer_username"],
            "sequence_number": row["sequence_number"],
            "break_gross": row["break_gross"],
            "total_pack_market_value": row["total_pack_market_value"],
            "break_profit": row["break_profit"],
            "break_profit_margin": row["break_profit_margin"],
        }
        for row in breaks_report(user, streamer_id, start_date, end_date)
    ]


# --- 9. price_current ---


def price_current_report(user: User) -> list[dict]:
    products_by_id = {p.id: p for p in repo.list_products()}
    prices = price_repo.list_all_current_prices()

    rows = []
    for product_id, price in prices.items():
        product = products_by_id.get(product_id)
        rows.append({
            "product_id": product_id,
            "product_name": product.name if product else product_id,
            "resolved_pack_price": _money(price.resolved_pack_price),
            "resolved_price_source": price.resolved_price_source,
            "price_status": price.price_status,
            "raw_loose_pack_market_price": _money(price.raw_loose_pack_market_price),
            "raw_box_market_price": _money(price.raw_box_market_price),
            "last_successful_refresh_at": price.last_successful_refresh_at,
        })
    return rows


# --- 10. price_history ---


def _decimal128_to_str(value) -> str | None:
    return str(value.to_decimal()) if value is not None else None


def price_history_report(user: User, product_id: str | None = None) -> list[dict]:
    products_by_id = {p.id: p for p in repo.list_products()}

    rows = []
    for doc in price_repo.list_price_history(product_id=product_id):
        product = products_by_id.get(doc["product_id"])
        rows.append({
            "product_id": doc["product_id"],
            "product_name": product.name if product else doc["product_id"],
            "previous_price": _decimal128_to_str(doc.get("previous_price")),
            "new_price": _decimal128_to_str(doc.get("new_price")),
            "previous_source": doc.get("previous_source"),
            "new_source": doc.get("new_source"),
            "initiated_by": doc.get("initiated_by"),
            "manual_entry_by": doc.get("manual_entry_by"),
            "timestamp": doc.get("timestamp"),
            "tcgcsv_status": doc.get("tcgcsv_status"),
        })
    return rows


# --- 11. inventory_audit ---

_INVENTORY_ACTION_TYPES = (
    "MASTER_INVENTORY_ADDED", "MASTER_INVENTORY_REMOVED",
    "STREAMER_INVENTORY_CLAIMED", "STREAMER_INVENTORY_RETURNED",
    "STREAM_COMPLETED", "STREAM_BREAK_CORRECTED", "DECOMMISSION_APPROVED",
)


def inventory_audit_report(user: User, streamer_id: str | None = None, start_date=None, end_date=None) -> list[dict]:
    _require_admin(user)

    username_by_id = {u.id: u.username for u in repo.list_users()}
    rows = []
    for action_type in _INVENTORY_ACTION_TYPES:
        for doc in audit_service.list_events(
            action_type=action_type, streamer_id=streamer_id, start_date=start_date, end_date=end_date
        ):
            rows.append({
                "event_id": doc.get("event_id"),
                "action_type": doc.get("action_type"),
                "performed_by": username_by_id.get(doc.get("performed_by"), doc.get("performed_by")),
                "role": doc.get("role"),
                "timestamp": doc.get("timestamp"),
                "product_id": doc.get("product_id"),
                "streamer_username": username_by_id.get(doc.get("streamer_id"), doc.get("streamer_id")),
                "quantity_change": doc.get("quantity_change"),
                "reason": doc.get("reason"),
                "status": doc.get("status"),
            })
    rows.sort(key=lambda r: r["timestamp"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return rows


# --- 12. inventory_discrepancies ---


def inventory_discrepancies_report(user: User, streamer_id: str | None = None) -> list[dict]:
    username_by_id = {u.id: u.username for u in repo.list_users()}
    products_by_id = {p.id: p for p in repo.list_products()}

    if ROLE_ADMIN in user.roles:
        discrepancies = discrepancy_service.list_discrepancies_for_streamer(streamer_id) if streamer_id else discrepancy_service.list_discrepancies()
    elif ROLE_STREAMER in user.roles:
        discrepancies = discrepancy_service.list_discrepancies_for_streamer(user.id)
    else:
        discrepancies = []

    rows = []
    for d in discrepancies:
        product = products_by_id.get(d.product_id)
        rows.append({
            "discrepancy_id": d.id,
            "streamer_username": username_by_id.get(d.streamer_id, d.streamer_id),
            "product_name": product.name if product else d.product_id,
            "type": d.type,
            "quantity": d.quantity,
            "source": d.source,
            "status": d.status,
            "created_at": d.created_at,
            "resolved_at": d.resolved_at,
            "resolution_note": d.resolution_note,
        })
    return rows


# --- 13. users ---


def users_report(user: User) -> list[dict]:
    _require_admin(user)

    return [
        {
            "user_id": u.id,
            "username": u.username,
            "roles": ", ".join(u.roles),
            "is_active": u.is_active,
            "decommission_status": u.decommission_status,
            "created_at": u.created_at,
            "disabled_at": u.disabled_at,
        }
        for u in repo.list_users()
    ]


# --- 14. decommission_requests ---


def decommission_requests_report(user: User) -> list[dict]:
    _require_admin(user)

    username_by_id = {u.id: u.username for u in repo.list_users()}

    return [
        {
            "request_id": r.id,
            "streamer_username": username_by_id.get(r.streamer_id, r.streamer_id),
            "status": r.status,
            "initiated_by": username_by_id.get(r.initiated_by, r.initiated_by),
            "initiated_at": r.initiated_at,
            "approved_by": username_by_id.get(r.approved_by, r.approved_by) if r.approved_by else None,
            "approved_at": r.approved_at,
            "notes": r.notes,
        }
        for r in decommission_service.list_all()
    ]
