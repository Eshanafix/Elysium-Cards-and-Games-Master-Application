"""
Product model, matching elysium_master.products (docs/IMPLEMENTATION_PLAN.md
section 2.1). `booster_type` includes PLAY (added in Phase 3) alongside the
LLD's original DRAFT/SET/COLLECTOR -- see plan section 2.6 for why. CLASSIC
was added later for sets from before the 2020 Play/Draft/Set/Collector
split (e.g. Kaladesh) -- none of the other four types are historically
accurate for a set that only ever had one, undifferentiated "Booster Pack".
"""

import re
from dataclasses import dataclass
from datetime import date, datetime

BOOSTER_TYPE_DRAFT = "DRAFT"
BOOSTER_TYPE_SET = "SET"
BOOSTER_TYPE_COLLECTOR = "COLLECTOR"
BOOSTER_TYPE_PLAY = "PLAY"
BOOSTER_TYPE_CLASSIC = "CLASSIC"
# Jumpstart boosters are a genuinely distinct product line (pre-built
# half-decks, no rarity slots) sold alongside a set's regular boosters --
# not another qualifier on the same Play/Draft/Set/Collector spectrum, so it
# gets its own type rather than being folded into CLASSIC.
BOOSTER_TYPE_JUMPSTART = "JUMPSTART"
# Some Secret Lair drops (e.g. "Secret Lair x MSCHF: The Zeta Set") are
# genuinely randomized booster packs -- not the usual fixed, pre-known-
# contents Secret Lair bundle -- sold with NO booster box/display SKU at
# all on TCGCSV, just the one pack listing. Gets its own type rather than
# auto-deriving from the name (which would often wrongly collide with SET,
# DRAFT, etc. depending on the drop's own title) -- see
# tcgcsv_catalog_service's qualifier-word matching, which never guesses
# this type; it's always picked by hand in the product dialog. See also
# Product.box_tcgcsv_product_id -- this is the type that actually needs
# that field to be optional.
BOOSTER_TYPE_SECRET_LAIR = "SECRET_LAIR"

BOOSTER_TYPES = [
    BOOSTER_TYPE_DRAFT, BOOSTER_TYPE_SET, BOOSTER_TYPE_COLLECTOR, BOOSTER_TYPE_PLAY, BOOSTER_TYPE_CLASSIC,
    BOOSTER_TYPE_JUMPSTART, BOOSTER_TYPE_SECRET_LAIR,
]

# Display/sort priority for a Pack Type column (local feature request, no
# LLD section) -- Secret Lair and Collector are the highest-value, most
# frequently opened-on-stream types, so they sort first rather than
# alphabetically.
BOOSTER_TYPE_SORT_RANK = {
    BOOSTER_TYPE_SECRET_LAIR: 0,
    BOOSTER_TYPE_COLLECTOR: 1,
    BOOSTER_TYPE_PLAY: 2,
    BOOSTER_TYPE_DRAFT: 3,
    BOOSTER_TYPE_SET: 4,
    BOOSTER_TYPE_JUMPSTART: 5,
    BOOSTER_TYPE_CLASSIC: 6,
}


def normalize_product_name(name: str) -> str:
    """LLD 8.4 requires duplicate prevention on "normalized product name",
    not a literal string match -- collapses whitespace and case so "Foundations  Play Booster"
    and "foundations play booster" are recognized as the same name."""
    return re.sub(r"\s+", " ", name.strip().lower())


@dataclass
class Product:
    id: str  # product_id slug, e.g. "foundations-play-booster"
    name: str
    booster_type: str
    packs_per_box: int
    tcgcsv_category_id: str
    tcgcsv_group_id: str
    loose_pack_tcgcsv_product_id: str
    image_url: str
    # Optional (dataclass field-ordering is why this moved below the
    # non-default fields above rather than sitting next to
    # loose_pack_tcgcsv_product_id) -- almost every product has a real box/
    # display SKU on TCGCSV and this is always set for those, but a small
    # number of genuinely randomized-pack products (e.g. "Secret Lair x
    # MSCHF: The Zeta Set") have no box SKU at all. None here means exactly
    # that: no box exists, not "unknown" -- pricing already falls back to
    # loose-pack market price whenever box_price can't be resolved
    # (pricing_service._resolve_and_store_product_price), which is exactly
    # what an absent box id naturally produces. Every caller in this
    # codebase constructs Product with keyword arguments, so moving this
    # field doesn't change any call site.
    box_tcgcsv_product_id: str | None = None
    english_confirmed: bool = False
    language: str = "English"
    set_name: str | None = None
    set_code: str | None = None
    release_date: date | None = None
    is_active: bool = True
    created_at: datetime | None = None
    created_by: str | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None

    def to_document(self) -> dict:
        doc = {
            "_id": self.id,
            "name": self.name,
            "name_normalized": normalize_product_name(self.name),
            "set_name": self.set_name,
            "set_code": self.set_code,
            "booster_type": self.booster_type,
            "language": self.language,
            "english_confirmed": self.english_confirmed,
            "packs_per_box": self.packs_per_box,
            "tcgcsv_category_id": self.tcgcsv_category_id,
            "tcgcsv_group_id": self.tcgcsv_group_id,
            "loose_pack_tcgcsv_product_id": self.loose_pack_tcgcsv_product_id,
            "image_url": self.image_url,
            "release_date": self.release_date,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by,
        }

        # Sparse unique index on box_tcgcsv_product_id only skips documents
        # missing the field entirely -- a stored `null` still counts as a
        # value and would let at most one box-less product ever exist
        # (same reasoning as User.to_document()'s streamer_database_key/
        # streamer_database_name handling). Omit rather than null it out.
        if self.box_tcgcsv_product_id is not None:
            doc["box_tcgcsv_product_id"] = self.box_tcgcsv_product_id

        return doc

    @staticmethod
    def from_document(doc: dict) -> "Product":
        return Product(
            id=doc["_id"],
            name=doc["name"],
            set_name=doc.get("set_name"),
            set_code=doc.get("set_code"),
            booster_type=doc["booster_type"],
            language=doc.get("language", "English"),
            english_confirmed=doc.get("english_confirmed", False),
            packs_per_box=doc["packs_per_box"],
            tcgcsv_category_id=doc["tcgcsv_category_id"],
            tcgcsv_group_id=doc["tcgcsv_group_id"],
            loose_pack_tcgcsv_product_id=doc["loose_pack_tcgcsv_product_id"],
            box_tcgcsv_product_id=doc.get("box_tcgcsv_product_id"),
            image_url=doc["image_url"],
            release_date=doc.get("release_date"),
            is_active=doc.get("is_active", True),
            created_at=doc.get("created_at"),
            created_by=doc.get("created_by"),
            updated_at=doc.get("updated_at"),
            updated_by=doc.get("updated_by"),
        )
