"""
Admin-only "Ask Elysium" data assistant. Lets an admin ask a natural-language
business question (e.g. "do I make more profit on breaks with 3 or 4 packs")
and get an answer computed from this app's own data, via Claude tool use.

Architecture mirrors the rest of this app rather than introducing a parallel
pattern: Claude is only ever given a small, fixed set of read-only Python
functions (this file's @beta_tool-decorated functions below), each of which
just calls existing repository/service code -- the same functions the
Reports screen already uses. There is no raw/arbitrary MongoDB query tool
and no write tool, ever; Claude cannot see or touch anything this file
doesn't explicitly expose.

The Anthropic API key is configured once by an admin (via the Ask Elysium
screen's inline setup) and stored in elysium_master.app_config -- the same
collection the mandatory-update gate already uses (master_repository's
AI_ASSISTANT_CONFIG_ID, mirroring APP_UPDATE_CONFIG_ID). Every other admin's
installed app then picks the key up automatically the next time they open
the screen, with no per-machine setup step. This extends the same trust
model already accepted for the shared MongoDB connection string: anyone
with direct Atlas access already has full plaintext access to this
business's data, so a shared API key stored alongside it isn't a new
category of exposure for this 4-person team.

Note for whoever reads this next: a query's question text (and the data the
tools return) leaves the app and goes to Anthropic's API as part of the
request -- unlike the rest of this app, which only ever talks to MongoDB
Atlas.
"""

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import anthropic
from anthropic import beta_tool
from bson import Decimal128

from elysium.models.prices import from_decimal128
from elysium.models.users import ROLE_STREAMER
from elysium.repositories import master_repository as repo
from elysium.repositories import price_repository as price_repo
from elysium.repositories import streamer_repository as streamer_repo
from elysium.services import audit_service, dashboard_service

MODEL = "claude-sonnet-5"
# A question that makes the model reason over many rows of tool data (e.g.
# summing/comparing value across dozens of products) can burn through its
# entire token budget on internal reasoning alone before writing a single
# word of the actual answer -- confirmed live: a "where's the value
# concentrated" question over one streamer's ~70-product allocation used
# the full old budget (4096) purely on thinking tokens and got cut off with
# stop_reason=max_tokens and zero text, which is what ask() below reports
# back as "The assistant didn't return a text answer." 16000 leaves
# headroom for both the reasoning and the reply on realistic questions.
MAX_TOKENS = 16000

SYSTEM_PROMPT = (
    "You are Ask Elysium, a data assistant built into the Elysium Cards and Games "
    "Master Application, answering questions for a company admin about their own "
    "trading-card breaking/streaming business. Always use the provided tools to pull "
    "real data before answering a question about business performance -- never guess "
    "or estimate numbers. If a tool returns no data for what was asked, say so plainly "
    "instead of making something up. Keep answers concise and lead with the concrete "
    "number(s) the admin asked for. Money values are US dollars."
)


class AiAssistantError(Exception):
    pass


class AiAssistantNotConfiguredError(AiAssistantError):
    pass


def _jsonable(value):
    if isinstance(value, Decimal128):
        value = value.to_decimal()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _to_tool_result(value) -> str:
    return json.dumps(_jsonable(value))


def _parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _date_range_start(value: str) -> datetime | None:
    d = _parse_date(value)
    return datetime(d.year, d.month, d.day) if d else None


def _date_range_end(value: str) -> datetime | None:
    d = _parse_date(value)
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999999) if d else None


def _streamer_users() -> list:
    return [u for u in repo.list_users() if ROLE_STREAMER in u.roles and u.streamer_database_name]


def _find_product_by_name(name: str):
    """Case-insensitive product lookup by exact name, falling back to a
    substring match -- lets Claude pass whatever name form the admin typed
    rather than requiring the exact stored name. Returns (product, None) on
    a single match, or (None, candidate_names) when the name is ambiguous or
    unmatched, so the calling tool can report that back instead of guessing."""
    name_lower = name.strip().lower()
    products = repo.list_products()

    exact = [p for p in products if p.name.lower() == name_lower]
    if exact:
        return exact[0], None

    matches = [p for p in products if name_lower in p.name.lower()]
    if len(matches) == 1:
        return matches[0], None

    return None, [p.name for p in matches]


# --- Tools exposed to Claude (read-only, parameterized, purpose-built --
# never raw/arbitrary queries) ---


@beta_tool
def list_streamers() -> str:
    """List every streamer's username. Call this first if you need to ask about
    a specific streamer by name, so you use the exact username on file rather than
    guessing one.
    """
    return _to_tool_result([u.username for u in _streamer_users()])


@beta_tool
def get_company_summary() -> str:
    """Get company-wide totals: current total packs in inventory, current total
    inventory value, and all-time gross/profit/profit margin across every
    streamer's completed streams combined.
    """
    return _to_tool_result(dashboard_service.get_admin_summary())


@beta_tool
def get_streamer_performance(streamer_username: str, start_date: str = "", end_date: str = "") -> str:
    """Get one streamer's own stream/break performance: completed stream count,
    average stream gross/profit, break count, average break gross/profit, and
    overall profit margin.

    Args:
        streamer_username: Exact username, e.g. from list_streamers.
        start_date: Optional inclusive start date as YYYY-MM-DD. Omit for all-time.
        end_date: Optional inclusive end date as YYYY-MM-DD. Omit for all-time.
    """
    user = repo.find_user_by_username(streamer_username.strip())

    if user is None or ROLE_STREAMER not in user.roles or not user.streamer_database_name:
        return _to_tool_result({"error": f"No streamer found with username '{streamer_username}'."})

    stats = dashboard_service.get_streamer_stats(
        user.streamer_database_name, _parse_date(start_date), _parse_date(end_date),
    )
    return _to_tool_result(stats)


@beta_tool
def get_break_profit_by_pack_count(streamer_username: str = "") -> str:
    """Get average break gross/profit grouped by how many packs were in the
    break (e.g. to compare 3-pack breaks vs. 4-pack breaks). Only includes
    breaks that have actually ended (in-progress breaks have no gross/profit
    yet). Covers every streamer combined by default.

    Args:
        streamer_username: Optional exact username to scope to one streamer
            instead of the whole company. Omit for a company-wide view.
    """
    streamer_username = streamer_username.strip()

    if streamer_username:
        user = repo.find_user_by_username(streamer_username)
        if user is None or ROLE_STREAMER not in user.roles or not user.streamer_database_name:
            return _to_tool_result({"error": f"No streamer found with username '{streamer_username}'."})
        database_names = [user.streamer_database_name]
    else:
        database_names = [u.streamer_database_name for u in _streamer_users()]

    grouped: dict[int, list] = {}
    for database_name in database_names:
        for b in streamer_repo.list_all_breaks_for_streamer(database_name):
            if b.break_gross is None:
                continue
            pack_count = sum(line["quantity"] for line in b.pack_lines)
            grouped.setdefault(pack_count, []).append(b)

    results = []
    for pack_count, breaks in sorted(grouped.items()):
        grosses = [b.break_gross for b in breaks]
        profits = [b.break_profit for b in breaks if b.break_profit is not None]
        results.append({
            "pack_count": pack_count,
            "break_count": len(breaks),
            "avg_break_gross": (sum(grosses, Decimal("0")) / len(grosses)) if grosses else None,
            "avg_break_profit": (sum(profits, Decimal("0")) / len(profits)) if profits else None,
        })

    return _to_tool_result(results)


@beta_tool
def list_users() -> str:
    """List every user account with their roles (admin and/or streamer) and
    whether the account is active. Call this for "who are our users" or "which
    accounts are admins" questions. To get just streamer usernames before
    calling a streamer-scoped tool, list_streamers is more direct.
    """
    return _to_tool_result([
        {"username": u.username, "roles": u.roles, "is_active": u.is_active} for u in repo.list_users()
    ])


@beta_tool
def get_master_inventory_summary() -> str:
    """Get current master inventory: for every product, its name, total packs
    held company-wide, unassigned (not yet given to a streamer) packs, and its
    current resolved market price per pack.
    """
    inventory = repo.list_inventory_current()
    prices = price_repo.list_all_current_prices()
    products = {p.id: p for p in repo.list_products()}

    results = []
    for product_id, doc in inventory.items():
        product = products.get(product_id)
        price = prices.get(product_id)
        results.append({
            "product_name": product.name if product else product_id,
            "total_packs": doc.get("total_packs", 0),
            "unassigned_packs": doc.get("unassigned_packs", 0),
            "resolved_pack_price": price.resolved_pack_price if price else None,
        })

    return _to_tool_result(results)


@beta_tool
def get_price_history(product_name: str, days: int = 7) -> str:
    """Call this when asked how a specific product's price has changed recently,
    or whether it went up or down -- returns every recorded price change for
    that one product, each with when it happened, the previous price, the new
    price, and where the new price came from (TCGCSV loose-pack market price,
    derived from box price, or a manual entry). For a company-wide "how have
    prices changed" question covering every product, use
    get_recent_price_changes instead.

    Args:
        product_name: Product name, or a distinctive substring of it (e.g.
            "Foundations Play Booster"). Case-insensitive.
        days: How many days back to look. Defaults to 7.
    """
    product, ambiguous_matches = _find_product_by_name(product_name)

    if product is None:
        if ambiguous_matches:
            return _to_tool_result({
                "error": f"'{product_name}' matches more than one product.",
                "matching_names": ambiguous_matches,
            })
        return _to_tool_result({"error": f"No product found matching '{product_name}'."})

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    changes = []

    for entry in price_repo.list_price_history(product.id, limit=500):
        timestamp = entry.get("timestamp")
        if timestamp is None or timestamp < cutoff:
            break  # newest-first order -- everything after this is even older
        changes.append({
            "timestamp": timestamp,
            "previous_price": from_decimal128(entry.get("previous_price")),
            "new_price": from_decimal128(entry.get("new_price")),
            "source": entry.get("new_source"),
        })

    return _to_tool_result({"product_name": product.name, "days": days, "changes": changes})


@beta_tool
def get_recent_price_changes(days: int = 7) -> str:
    """Call this for a general "how have prices changed recently" question
    covering every product at once, not just one. Returns every recorded price
    change across all products in the given window, each with the product
    name, when it happened, the previous price, the new price, and where the
    new price came from. For one specific product, use get_price_history
    instead.

    Args:
        days: How many days back to look. Defaults to 7.
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    products = {p.id: p for p in repo.list_products()}
    changes = []

    for entry in price_repo.list_price_history(limit=2000):
        timestamp = entry.get("timestamp")
        if timestamp is None or timestamp < cutoff:
            break  # newest-first order -- everything after this is even older
        product = products.get(entry.get("product_id"))
        changes.append({
            "product_name": product.name if product else entry.get("product_id"),
            "timestamp": timestamp,
            "previous_price": from_decimal128(entry.get("previous_price")),
            "new_price": from_decimal128(entry.get("new_price")),
            "source": entry.get("new_source"),
        })

    return _to_tool_result({"days": days, "changes": changes})


@beta_tool
def get_product_catalog(active_only: bool = True) -> str:
    """Get the full product catalog: every product's name, booster type, packs
    per box, set name, and set code. Call this for "what products do we sell"
    or "what set is X from" questions. For current stock levels and prices,
    use get_master_inventory_summary instead.

    Args:
        active_only: If True (default), excludes discontinued/inactive products.
    """
    results = []
    for p in repo.list_products():
        if active_only and not p.is_active:
            continue
        results.append({
            "name": p.name,
            "booster_type": p.booster_type,
            "packs_per_box": p.packs_per_box,
            "set_name": p.set_name,
            "set_code": p.set_code,
            "is_active": p.is_active,
        })

    return _to_tool_result(results)


@beta_tool
def get_streamer_allocations(streamer_username: str = "") -> str:
    """Get how many packs each streamer currently holds (or owes, if negative)
    of each product -- their live personal allocation, separate from
    company-wide master inventory. Call this for "how many packs does X have
    right now" or "who's holding what" questions. Zero-balance rows are
    omitted.

    Args:
        streamer_username: Optional exact username to scope to one streamer.
            Omit to list every streamer's allocations.
    """
    streamer_username = streamer_username.strip()

    if streamer_username:
        user = repo.find_user_by_username(streamer_username)
        if user is None or ROLE_STREAMER not in user.roles:
            return _to_tool_result({"error": f"No streamer found with username '{streamer_username}'."})
        allocations = repo.list_streamer_allocations_for_streamer(user.id)
    else:
        allocations = repo.list_all_streamer_allocations()

    users_by_id = {u.id: u.username for u in repo.list_users()}
    products_by_id = {p.id: p.name for p in repo.list_products()}

    results = []
    for a in allocations:
        if a.get("current_packs", 0) == 0:
            continue
        results.append({
            "streamer_username": users_by_id.get(a.get("streamer_id"), a.get("streamer_id")),
            "product_name": products_by_id.get(a.get("product_id"), a.get("product_id")),
            "current_packs": a.get("current_packs", 0),
        })

    return _to_tool_result(results)


@beta_tool
def list_streams(streamer_username: str, status: str = "", start_date: str = "", end_date: str = "", limit: int = 50) -> str:
    """List one streamer's individual streams with their date, status, gross,
    profit, and margin -- e.g. for "what was my best stream" or "list my
    streams from last month" questions. For aggregated averages instead of a
    list, use get_streamer_performance.

    Args:
        streamer_username: Exact username, e.g. from list_streamers.
        status: Optional exact status to filter to: "ACTIVE", "COMPLETED", or
            "CANCELED". Omit to include every status.
        start_date: Optional inclusive start date as YYYY-MM-DD, compared
            against each stream's start time.
        end_date: Optional inclusive end date as YYYY-MM-DD.
        limit: Maximum number of streams to return, newest first. Defaults to 50.
    """
    user = repo.find_user_by_username(streamer_username.strip())

    if user is None or ROLE_STREAMER not in user.roles or not user.streamer_database_name:
        return _to_tool_result({"error": f"No streamer found with username '{streamer_username}'."})

    streams = streamer_repo.list_streams(user.streamer_database_name, status=status.strip() or None)

    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start is not None:
        streams = [s for s in streams if s.start_time and s.start_time.date() >= start]
    if end is not None:
        streams = [s for s in streams if s.start_time and s.start_time.date() <= end]

    results = []
    for s in streams[:limit]:
        results.append({
            "date": s.start_time.date() if s.start_time else None,
            "status": s.status,
            "final_stream_gross": s.final_stream_gross,
            "stream_profit": s.stream_profit,
            "stream_profit_margin": s.stream_profit_margin,
            "notes": s.notes,
        })

    return _to_tool_result(results)


@beta_tool
def get_discrepancies(status: str = "OPEN", streamer_username: str = "") -> str:
    """Get inventory discrepancies -- cases where a stream correction let a
    streamer's ledger go negative, or a shortage couldn't be fully deducted.
    Call this for "are there any open discrepancies" or "what discrepancies
    has X had" questions.

    Args:
        status: "OPEN", "RESOLVED", or "" for both. Defaults to "OPEN".
        streamer_username: Optional exact username to scope to one streamer.
            Omit for every streamer.
    """
    status_filter = status.strip().upper() or None
    streamer_username = streamer_username.strip()

    if streamer_username:
        user = repo.find_user_by_username(streamer_username)
        if user is None:
            return _to_tool_result({"error": f"No streamer found with username '{streamer_username}'."})
        discrepancies = repo.list_discrepancies_for_streamer(user.id, status=status_filter)
    else:
        discrepancies = repo.list_discrepancies(status=status_filter)

    users_by_id = {u.id: u.username for u in repo.list_users()}
    products_by_id = {p.id: p.name for p in repo.list_products()}

    results = []
    for d in discrepancies:
        results.append({
            "streamer_username": users_by_id.get(d.streamer_id, d.streamer_id),
            "product_name": products_by_id.get(d.product_id, d.product_id),
            "type": d.type,
            "quantity": d.quantity,
            "source": d.source,
            "status": d.status,
            "created_at": d.created_at,
            "resolution_note": d.resolution_note,
        })

    return _to_tool_result(results)


@beta_tool
def get_decommission_requests(status: str = "") -> str:
    """Get streamer account decommission requests -- the two-step
    initiate-then-approve process used to close out a streamer's account and
    sweep their remaining packs back to unassigned inventory. Call this for
    "which accounts are being decommissioned" or "is X's decommission
    approved yet" questions.

    Args:
        status: Optional exact status to filter to: "PENDING", "APPROVED", or
            "CANCELED". Omit for every status.
    """
    requests = repo.list_decommission_requests(status=status.strip().upper() or None)
    users_by_id = {u.id: u.username for u in repo.list_users()}

    results = []
    for r in requests:
        results.append({
            "streamer_username": users_by_id.get(r.streamer_id, r.streamer_id),
            "status": r.status,
            "initiated_at": r.initiated_at,
            "approved_at": r.approved_at,
            "canceled_at": r.canceled_at,
            "notes": r.notes,
        })

    return _to_tool_result(results)


@beta_tool
def get_audit_history(
    action_type: str = "",
    streamer_username: str = "",
    product_name: str = "",
    start_date: str = "",
    end_date: str = "",
    limit: int = 50,
) -> str:
    """Get the audit trail of admin/system actions -- inventory added or
    reduced, prices manually overridden, streams corrected, discrepancies
    resolved, accounts disabled, etc. Call this for "who did what and when"
    questions.

    Args:
        action_type: Optional exact action type to filter to, e.g.
            "MASTER_INVENTORY_ADDED", "STREAMER_INVENTORY_CLAIMED",
            "PRICE_MANUAL_ENTRY". Omit to include every type.
        streamer_username: Optional exact username to scope to one streamer's events.
        product_name: Optional product name (or a distinctive substring) to scope
            to one product's events.
        start_date: Optional inclusive start date as YYYY-MM-DD.
        end_date: Optional inclusive end date as YYYY-MM-DD.
        limit: Maximum number of events to return, newest first. Defaults to 50.
    """
    streamer_id = None
    if streamer_username.strip():
        user = repo.find_user_by_username(streamer_username.strip())
        if user is None:
            return _to_tool_result({"error": f"No user found with username '{streamer_username}'."})
        streamer_id = user.id

    product_id = None
    if product_name.strip():
        product, ambiguous_matches = _find_product_by_name(product_name)
        if product is None:
            return _to_tool_result({
                "error": f"No product found matching '{product_name}'.",
                "matching_names": ambiguous_matches or [],
            })
        product_id = product.id

    events = audit_service.list_events(
        action_type=action_type.strip() or None,
        streamer_id=streamer_id,
        product_id=product_id,
        start_date=_date_range_start(start_date),
        end_date=_date_range_end(end_date),
        limit=limit,
    )

    users_by_id = {u.id: u.username for u in repo.list_users()}
    products_by_id = {p.id: p.name for p in repo.list_products()}

    results = []
    for e in events:
        results.append({
            "action_type": e.get("action_type"),
            "performed_by": users_by_id.get(e.get("performed_by"), e.get("performed_by")),
            "timestamp": e.get("timestamp"),
            "streamer": users_by_id.get(e.get("streamer_id")) if e.get("streamer_id") else None,
            "product": products_by_id.get(e.get("product_id")) if e.get("product_id") else None,
            "quantity_change": e.get("quantity_change"),
            "amount_change": e.get("amount_change"),
            "reason": e.get("reason"),
            "status": e.get("status"),
        })

    return _to_tool_result(results)


_TOOLS = [
    list_streamers,
    list_users,
    get_company_summary,
    get_streamer_performance,
    get_break_profit_by_pack_count,
    get_master_inventory_summary,
    get_price_history,
    get_recent_price_changes,
    get_product_catalog,
    get_streamer_allocations,
    list_streams,
    get_discrepancies,
    get_decommission_requests,
    get_audit_history,
]


# --- Configuration (shared key, stored in elysium_master.app_config) ---


def is_configured() -> bool:
    config = repo.get_ai_assistant_config()
    return bool(config and config.get("api_key"))


def test_api_key(api_key: str) -> tuple[bool, str]:
    """Validates a candidate key on a throwaway client before it's saved --
    mirrors mongo_client.test_connection_string's role for the DB URI."""
    try:
        client = anthropic.Anthropic(api_key=api_key)
        client.models.list()
        return True, "Connected."
    except Exception as e:
        return False, str(e)


def configure_api_key(api_key: str, configured_by: str) -> None:
    api_key = api_key.strip()

    if not api_key:
        raise ValueError("API key is required.")

    ok, detail = test_api_key(api_key)
    if not ok:
        raise ValueError(f"Couldn't validate this API key: {detail}")

    repo.set_ai_assistant_config({
        "api_key": api_key,
        "configured_by": configured_by,
        "configured_at": datetime.now(timezone.utc),
    })

    audit_service.record_event(action_type="AI_ASSISTANT_KEY_CONFIGURED", performed_by=configured_by)


# --- Asking a question ---


def ask(question: str, asked_by: str) -> str:
    question = question.strip()

    if not question:
        raise ValueError("Enter a question first.")

    config = repo.get_ai_assistant_config()
    api_key = config.get("api_key") if config else None

    if not api_key:
        raise AiAssistantNotConfiguredError("The AI assistant hasn't been set up on this account yet.")

    client = anthropic.Anthropic(api_key=api_key)

    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=_TOOLS,
        messages=[{"role": "user", "content": question}],
    )

    final_message = None
    for message in runner:
        final_message = message

    if final_message is None:
        raise AiAssistantError("The assistant didn't return a response.")

    answer = "\n".join(block.text for block in final_message.content if block.type == "text").strip()

    audit_service.record_event(
        action_type="AI_ASSISTANT_QUERY", performed_by=asked_by, after_values={"question": question},
    )

    return answer or "The assistant didn't return a text answer."
