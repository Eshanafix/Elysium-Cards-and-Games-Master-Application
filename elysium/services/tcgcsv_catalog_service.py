"""
TCGCSV set/product lookup for the simplified product-creation flow
(docs/IMPLEMENTATION_PLAN.md Phase 3 UX revision). Admins search sets by
name instead of typing raw TCGCSV category/group/product ids; booster
type, box product, image, and packs-per-box are derived automatically
where the live data allows it, and are always left editable since none of
this is guaranteed to be perfectly reliable across every set/era.
"""

import logging
import re
from dataclasses import dataclass

import requests

from elysium.models.products import (
    BOOSTER_TYPE_CLASSIC,
    BOOSTER_TYPE_COLLECTOR,
    BOOSTER_TYPE_DRAFT,
    BOOSTER_TYPE_JUMPSTART,
    BOOSTER_TYPE_PLAY,
    BOOSTER_TYPE_SET,
)
from elysium.repositories import price_repository as price_repo

logger = logging.getLogger(__name__)

TCGCSV_BASE_URL = "https://tcgcsv.com/tcgplayer"
TCGCSV_TIMEOUT_SECONDS = 30
TCGCSV_HEADERS = {"User-Agent": "ElysiumMasterApplication/1.0 (local desktop app)"}

MAGIC_CATEGORY_ID = "1"

# Verified live against tcgcsv.com (2026-08-07): box products are named
# inconsistently across set eras -- "X Booster Display" for recent sets
# (e.g. Foundations), "X Booster Box" for older ones (e.g. Dominaria
# United). Both are treated as equivalent. "...Display Case" / "...Box
# Case" / "...Display Master Case" variants (bulk case quantities, not a
# single box) are deliberately excluded by anchoring the match at the end
# of the product name.
#
# Verified live again (2026-08-08): the Play/Draft/Set/Collector qualifier
# only exists from ~2020 onward. Pre-2020 sets (e.g. "Kaladesh - Booster
# Pack", "Ravnica Allegiance - Booster Box") have no qualifier word at all
# -- requiring one meant these products matched neither pattern, so
# classify_sealed_candidates() came back completely empty for any set from
# before the split, and they were impossible to add via the search flow.
# A bare "- Booster Pack/Box" (dash directly before "Booster", nothing else
# in between) is now also accepted and treated as CLASSIC -- none of
# Play/Draft/Set/Collector are historically accurate for a set that only
# ever had one, undifferentiated booster. This is deliberately NOT the same
# as making the qualifier word merely optional -- an unrecognized word (e.g.
# "Theme", "Prerelease") still doesn't match at all, so those stay excluded.
# Also matches the "Collectors" (plural) variant used in some older sets,
# e.g. "Ravnica Allegiance - Collectors Booster Pack".
#
# Verified live again (2026-08-16): "Jumpstart" and "Beyond" are two more
# real qualifier words TCGPlayer uses for genuinely sellable single-SKU
# products -- "Avatar: The Last Airbender - Jumpstart Booster Pack" and
# "Universes Beyond: Assassin's Creed - Beyond Booster Pack" are both real,
# purchasable products that streamers want to open on stream, not a
# different product line to filter out the way Jumpstart boosters riding
# alongside an otherwise-normal Play/Draft/Set/Collector set are (that's
# still true for e.g. Dominaria United's Jumpstart boosters -- Jumpstart
# itself just isn't inherently "not a real product" the way this comment
# previously implied). "Beyond" sets have no Play/Draft/Set split of their
# own (like a CLASSIC-era set), so it maps to CLASSIC rather than getting
# its own type; Jumpstart boosters are a genuinely distinct product
# (pre-built half-decks, no rarity slots) and get their own type.
_BOOSTER_TYPE_BY_WORD = {
    "play": BOOSTER_TYPE_PLAY,
    "draft": BOOSTER_TYPE_DRAFT,
    "set": BOOSTER_TYPE_SET,
    "collector": BOOSTER_TYPE_COLLECTOR,
    "collectors": BOOSTER_TYPE_COLLECTOR,
    "jumpstart": BOOSTER_TYPE_JUMPSTART,
    "beyond": BOOSTER_TYPE_CLASSIC,
}

# Some products (Mystery Booster's retail/convention-exclusive listings) add
# a bracketed and/or parenthesized annotation after "Booster Pack/Box", e.g.
# "Mystery Booster - Booster Pack [Retail Exclusive]" or "Mystery Booster -
# Booster Box [Convention Edition] (2019)" -- both real, single-SKU sealed
# products, so the end-of-name anchor now tolerates one of each, in order,
# after the core "Booster Pack/Box/Display" match. This does NOT reopen the
# door to "Theme"/"Prerelease" variants (e.g. "Ravnica Allegiance - Theme
# Booster Pack [Azorius]") -- those still fail to match at all, since
# "Theme"/"Prerelease" aren't in the qualifier-word alternation above and
# aren't a bare dash either.
#
# Pre-2020 sets with real Collector Boosters (e.g. Throne of Eldraine) name
# the box "<Set> - Collector Booster Pack Display [N Packs]" -- an extra
# "Pack" between "Booster" and "Display" that the box pattern didn't
# originally allow for. Missing that meant the real Collector box never
# matched either pattern and silently never appeared as a candidate at all
# (confirmed live: this is exactly how Throne of Eldraine Collector
# Booster ended up mapped to the *regular* Booster Box instead -- the
# actual Collector box wasn't in the dropdown to pick from).
_LOOSE_PATTERN = re.compile(
    r"(?:\b(Play|Draft|Set|Collectors?|Jumpstart|Beyond)\s+Booster\s+Pack|-\s*Booster\s+Pack)"
    r"(?:\s*\[[^\]]+\])?(?:\s*\([^)]+\))?$",
    re.IGNORECASE,
)
_BOX_PATTERN = re.compile(
    r"(?:\b(Play|Draft|Set|Collectors?|Jumpstart|Beyond)\s+Booster\s+(?:Pack\s+)?(?:Box|Display)"
    r"|-\s*Booster\s+(?:Pack\s+)?(?:Box|Display))(?:\s*\[[^\]]+\])?(?:\s*\([^)]+\))?$",
    re.IGNORECASE,
)

# TCGCSV/TCGPlayer don't expose a structured "packs per box" field -- it's
# real-world box-contents knowledge, not pricing data. These are sane
# fallback defaults when the description text can't be parsed; always
# editable, never silently trusted.
DEFAULT_PACKS_PER_BOX = {
    BOOSTER_TYPE_PLAY: 36,
    BOOSTER_TYPE_DRAFT: 36,
    BOOSTER_TYPE_SET: 30,
    BOOSTER_TYPE_COLLECTOR: 12,
    BOOSTER_TYPE_CLASSIC: 36,
    BOOSTER_TYPE_JUMPSTART: 18,
}

# Verified live against tcgcsv.com (2026-08-07): a box's description text
# routinely contains MULTIPLE "contains: N" phrases -- e.g. Foundations'
# real text says "...each Play Booster Pack contains: 14 Magic: The
# Gathering cards" (cards per pack) well before "...Play Booster Box
# contains:<br>• 36 Magic..." (the actual packs-per-box count). A pattern
# that isn't anchored to "Booster Box/Display contains" grabs the first
# (wrong) match. The gap between "contains:" and the digits also isn't
# pure whitespace in practice -- it can include literal "<br>" markup and
# bullet characters -- so it's matched with [^\d]{0,20} rather than \s*.
_PACKS_PER_BOX_TEXT_PATTERN = re.compile(
    r"Booster\s+(?:Box|Display)\s+contains:?[^\d]{0,20}(\d{1,3})\b", re.IGNORECASE
)


@dataclass
class SealedCandidate:
    product_id: str
    name: str
    image_url: str | None
    booster_type: str | None


def refresh_groups_cache(started_by: str, category_id: str = MAGIC_CATEGORY_ID) -> int:
    """Fetches every group (set) for a category and upserts them into the
    shared cache. Cheap -- one HTTP request, a few hundred rows -- and
    pure reference data with no business-state coupling, so no lock is
    needed (unlike the sealed-price refresh)."""
    url = f"{TCGCSV_BASE_URL}/{category_id}/groups"
    response = requests.get(url, headers=TCGCSV_HEADERS, timeout=TCGCSV_TIMEOUT_SECONDS)
    response.raise_for_status()

    groups = response.json().get("results", [])

    docs = [
        {
            "_id": f"{category_id}:{group['groupId']}",
            "group_id": str(group["groupId"]),
            "category_id": category_id,
            "name": group.get("name", ""),
            "abbreviation": group.get("abbreviation"),
            "is_supplemental": group.get("isSupplemental", False),
            "published_on": group.get("publishedOn"),
        }
        for group in groups
        if group.get("groupId") is not None
    ]

    price_repo.upsert_tcgcsv_groups(docs)
    logger.info("Refreshed %s TCGCSV groups for category %s (by %s)", len(docs), category_id, started_by)
    return len(docs)


def search_groups(query: str, category_id: str = MAGIC_CATEGORY_ID, limit: int = 20) -> list[dict]:
    query = query.strip()

    if not query:
        return []

    return price_repo.search_tcgcsv_groups(query, category_id, limit)


def groups_cache_count(category_id: str = MAGIC_CATEGORY_ID) -> int:
    return price_repo.tcgcsv_groups_count(category_id)


def fetch_group_products(category_id: str, group_id: str) -> list[dict]:
    url = f"{TCGCSV_BASE_URL}/{category_id}/{group_id}/products"
    response = requests.get(url, headers=TCGCSV_HEADERS, timeout=TCGCSV_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json().get("results", [])


def derive_booster_type_from_name(name: str) -> str | None:
    match = _LOOSE_PATTERN.search(name) or _BOX_PATTERN.search(name)

    if not match:
        return None

    qualifier = match.group(1)

    if qualifier is None:
        # Pre-2020 sets have no Play/Draft/Set/Collector split -- a plain
        # "<Set> - Booster Pack/Box" doesn't fit any of those four types.
        return BOOSTER_TYPE_CLASSIC

    return _BOOSTER_TYPE_BY_WORD.get(qualifier.lower())


def classify_sealed_candidates(products: list[dict]) -> tuple[list[SealedCandidate], list[SealedCandidate]]:
    """
    Returns (loose_candidates, box_candidates) filtered from a raw TCGCSV
    /products response. Never guesses which one is "the" product for a
    booster type -- callers present the (usually short, 1-4 item)
    candidate list for the admin to pick from rather than auto-selecting.
    """
    loose, box = [], []

    for product in products:
        name = product.get("name", "")
        product_id = product.get("productId")

        if product_id is None:
            continue

        if _LOOSE_PATTERN.search(name):
            loose.append(SealedCandidate(
                product_id=str(product_id), name=name,
                image_url=product.get("imageUrl"),
                booster_type=derive_booster_type_from_name(name),
            ))
        elif _BOX_PATTERN.search(name):
            box.append(SealedCandidate(
                product_id=str(product_id), name=name,
                image_url=product.get("imageUrl"),
                booster_type=derive_booster_type_from_name(name),
            ))

    return loose, box


def parse_packs_per_box(product: dict) -> int | None:
    """
    Best-effort extraction from the box product's description text.
    Returns None if no confident match is found -- callers should fall
    back to default_packs_per_box() and always let the admin override
    whatever value is shown.

    Takes the LAST anchored match, not the first. Confirmed live (Aetherdrift
    productId 604250): the description can contain more than one "Booster
    Box/Display contains" sentence -- an early one about a box-topper card
    ("...Play Booster Display contains a 2-card First-Place Box Topper")
    followed by the real summary sentence near the end ("Aetherdrift - Play
    Booster Box contains:<br>. 30 ... Play Booster Packs"). Taking the first
    match silently returned 2 instead of 30 for this product's description.
    """
    for entry in product.get("extendedData", []) or []:
        if entry.get("name") != "OracleText":
            continue

        matches = list(_PACKS_PER_BOX_TEXT_PATTERN.finditer(entry.get("value", "")))

        if matches:
            return int(matches[-1].group(1))

    return None


def default_packs_per_box(booster_type: str) -> int:
    return DEFAULT_PACKS_PER_BOX.get(booster_type, 36)


def suggest_product_name(set_name: str, booster_type: str) -> str:
    if booster_type == BOOSTER_TYPE_CLASSIC:
        # No qualifier word for the pre-2020 unified booster -- matches how
        # these are actually named, e.g. "Kaladesh - Booster Pack", not
        # "Kaladesh Classic Booster".
        return f"{set_name} Booster"

    type_word = {
        BOOSTER_TYPE_PLAY: "Play",
        BOOSTER_TYPE_DRAFT: "Draft",
        BOOSTER_TYPE_SET: "Set",
        BOOSTER_TYPE_COLLECTOR: "Collector",
    }.get(booster_type, booster_type.title())

    return f"{set_name} {type_word} Booster"
