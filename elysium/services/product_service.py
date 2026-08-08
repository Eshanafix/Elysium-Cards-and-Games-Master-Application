"""
Product catalog CRUD (LLD section 8). Enforces the mandatory-field list
(8.2) and duplicate prevention (8.4) before anything is written.
"""

import re
from datetime import date, datetime, timezone

from pymongo.errors import DuplicateKeyError

from elysium.models.products import BOOSTER_TYPES, Product
from elysium.repositories import master_repository as repo
from elysium.services import audit_service

MAX_SLUG_DISAMBIGUATION_ATTEMPTS = 20


class ProductValidationError(Exception):
    pass


class DuplicateProductError(Exception):
    pass


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "product"


def _generate_unique_product_id(name: str) -> str:
    base_slug = _slugify(name)

    if not repo.product_id_exists(base_slug):
        return base_slug

    for suffix in range(2, MAX_SLUG_DISAMBIGUATION_ATTEMPTS + 1):
        candidate = f"{base_slug}-{suffix}"

        if not repo.product_id_exists(candidate):
            return candidate

    raise RuntimeError(f"Could not generate a unique product id for '{name}' after several attempts.")


def _validate_mandatory_fields(
    name: str,
    booster_type: str,
    packs_per_box: int,
    tcgcsv_category_id: str,
    tcgcsv_group_id: str,
    loose_pack_tcgcsv_product_id: str,
    box_tcgcsv_product_id: str,
    image_url: str,
    english_confirmed: bool,
) -> None:
    # LLD 8.2's six mandatory fields, plus the Phase 3 TCGCSV
    # category/group ids the group-batched refresh design requires.
    if not name or not name.strip():
        raise ProductValidationError("Product name is required.")

    if booster_type not in BOOSTER_TYPES:
        raise ProductValidationError(f"Booster type must be one of {BOOSTER_TYPES}.")

    if not loose_pack_tcgcsv_product_id or not loose_pack_tcgcsv_product_id.strip():
        raise ProductValidationError("Loose-pack TCGCSV product mapping is required.")

    if not box_tcgcsv_product_id or not box_tcgcsv_product_id.strip():
        raise ProductValidationError("Booster-box TCGCSV product mapping is required.")

    if not tcgcsv_category_id or not tcgcsv_group_id:
        raise ProductValidationError("TCGCSV category and group are required.")

    if not packs_per_box or packs_per_box < 1:
        raise ProductValidationError("Packs per box must be a positive integer.")

    if not image_url or not image_url.strip():
        raise ProductValidationError("Product image is required.")

    if not english_confirmed:
        raise ProductValidationError(
            "English-only confirmation is required (non-English sealed products are out of scope)."
        )


def _check_duplicates(
    name: str,
    booster_type: str,
    loose_pack_tcgcsv_product_id: str,
    box_tcgcsv_product_id: str,
) -> None:
    if repo.normalized_name_and_type_exists(name, booster_type):
        raise DuplicateProductError(f"A {booster_type} product named '{name}' already exists.")

    if repo.loose_tcgcsv_id_exists(loose_pack_tcgcsv_product_id):
        raise DuplicateProductError(
            f"Loose-pack TCGCSV product id '{loose_pack_tcgcsv_product_id}' is already mapped to another product."
        )

    if repo.box_tcgcsv_id_exists(box_tcgcsv_product_id):
        raise DuplicateProductError(
            f"Box TCGCSV product id '{box_tcgcsv_product_id}' is already mapped to another product."
        )


def create_product(
    name: str,
    booster_type: str,
    packs_per_box: int,
    tcgcsv_category_id: str,
    tcgcsv_group_id: str,
    loose_pack_tcgcsv_product_id: str,
    box_tcgcsv_product_id: str,
    image_url: str,
    english_confirmed: bool,
    created_by: str,
    set_name: str | None = None,
    set_code: str | None = None,
    release_date: date | None = None,
) -> Product:
    _validate_mandatory_fields(
        name, booster_type, packs_per_box, tcgcsv_category_id, tcgcsv_group_id,
        loose_pack_tcgcsv_product_id, box_tcgcsv_product_id, image_url, english_confirmed,
    )
    _check_duplicates(name, booster_type, loose_pack_tcgcsv_product_id, box_tcgcsv_product_id)

    now = datetime.now(timezone.utc)

    product = Product(
        id=_generate_unique_product_id(name),
        name=name.strip(),
        booster_type=booster_type,
        packs_per_box=packs_per_box,
        tcgcsv_category_id=tcgcsv_category_id,
        tcgcsv_group_id=tcgcsv_group_id,
        loose_pack_tcgcsv_product_id=loose_pack_tcgcsv_product_id,
        box_tcgcsv_product_id=box_tcgcsv_product_id,
        image_url=image_url.strip(),
        english_confirmed=english_confirmed,
        set_name=set_name,
        set_code=set_code,
        release_date=release_date,
        is_active=True,
        created_at=now,
        created_by=created_by,
        updated_at=now,
        updated_by=created_by,
    )

    try:
        repo.insert_product_with_zero_inventory(product)
    except DuplicateKeyError as e:
        raise DuplicateProductError(
            "This product conflicts with an existing one (duplicate id, TCGCSV mapping, or name+type)."
        ) from e

    audit_service.record_event(
        action_type="PRODUCT_CREATED",
        performed_by=created_by,
        product_id=product.id,
        after_values={"name": product.name, "booster_type": product.booster_type},
    )

    return product


def update_product(product_id: str, fields: dict, updated_by: str) -> None:
    fields = dict(fields)
    fields["updated_at"] = datetime.now(timezone.utc)
    fields["updated_by"] = updated_by

    try:
        repo.update_product_fields(product_id, fields)
    except DuplicateKeyError as e:
        raise DuplicateProductError(
            "This change conflicts with an existing product (duplicate TCGCSV mapping or name+type)."
        ) from e

    audit_service.record_event(
        action_type="PRODUCT_UPDATED",
        performed_by=updated_by,
        product_id=product_id,
        after_values=fields,
    )


def list_products() -> list[Product]:
    return repo.list_products()


def get_product(product_id: str) -> Product | None:
    return repo.find_product_by_id(product_id)
