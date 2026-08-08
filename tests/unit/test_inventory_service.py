import pytest

from elysium.services.inventory_service import (
    InventoryValidationError,
    _require_positive_quantity,
    box_to_packs,
)


def test_box_to_packs_example_from_lld():
    # LLD 4.1 worked example: 36 packs/box, 8 boxes + 4 loose packs = 292.
    assert box_to_packs(boxes=8, loose_packs=4, packs_per_box=36) == 292


def test_box_to_packs_zero_boxes_is_just_loose_packs():
    assert box_to_packs(boxes=0, loose_packs=5, packs_per_box=36) == 5


def test_box_to_packs_zero_everything_is_zero():
    assert box_to_packs(boxes=0, loose_packs=0, packs_per_box=36) == 0


def test_box_to_packs_rejects_negative_boxes():
    with pytest.raises(InventoryValidationError):
        box_to_packs(boxes=-1, loose_packs=0, packs_per_box=36)


def test_box_to_packs_rejects_negative_loose_packs():
    with pytest.raises(InventoryValidationError):
        box_to_packs(boxes=0, loose_packs=-1, packs_per_box=36)


def test_box_to_packs_rejects_zero_packs_per_box():
    with pytest.raises(InventoryValidationError):
        box_to_packs(boxes=1, loose_packs=0, packs_per_box=0)


def test_require_positive_quantity_accepts_positive():
    _require_positive_quantity(1)  # should not raise


def test_require_positive_quantity_rejects_zero():
    with pytest.raises(InventoryValidationError):
        _require_positive_quantity(0)


def test_require_positive_quantity_rejects_negative():
    with pytest.raises(InventoryValidationError):
        _require_positive_quantity(-5)
