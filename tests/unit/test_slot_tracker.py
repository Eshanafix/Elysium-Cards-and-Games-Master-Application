from decimal import Decimal

from elysium.ui.slot_tracker import MAX_SLOTS, SlotValueTracker


def test_enter_pressed_fills_next_open_slot_in_order(qtbot):
    tracker = SlotValueTracker()
    qtbot.addWidget(tracker)

    tracker.value_input.setText("10")
    tracker.on_enter_pressed()
    tracker.value_input.setText("15.50")
    tracker.on_enter_pressed()

    assert tracker.values == {1: Decimal("10"), 2: Decimal("15.50")}
    assert tracker.value_input.text() == ""  # cleared after each entry


def test_total_label_reflects_running_sum(qtbot):
    tracker = SlotValueTracker()
    qtbot.addWidget(tracker)

    tracker.value_input.setText("10")
    tracker.on_enter_pressed()
    tracker.value_input.setText("5")
    tracker.on_enter_pressed()

    assert "$15.00" in tracker.total_label.text()
    assert "2/8" in tracker.total_label.text()


def test_ignores_empty_and_invalid_input(qtbot):
    tracker = SlotValueTracker()
    qtbot.addWidget(tracker)

    tracker.value_input.setText("")
    tracker.on_enter_pressed()
    tracker.value_input.setText("not a number")
    tracker.on_enter_pressed()

    assert tracker.values == {}


def test_stops_after_all_slots_filled(qtbot):
    tracker = SlotValueTracker()
    qtbot.addWidget(tracker)

    for i in range(MAX_SLOTS):
        tracker.value_input.setText("1")
        tracker.on_enter_pressed()

    assert len(tracker.values) == MAX_SLOTS

    tracker.value_input.setText("99")
    tracker.on_enter_pressed()  # should be a no-op, all slots full

    assert len(tracker.values) == MAX_SLOTS
    assert Decimal("99") not in tracker.values.values()


def test_reset_clears_values_and_input(qtbot):
    tracker = SlotValueTracker()
    qtbot.addWidget(tracker)

    tracker.value_input.setText("10")
    tracker.on_enter_pressed()

    tracker.reset()

    assert tracker.values == {}
    assert tracker.value_input.text() == ""


def test_compare_value_shows_covered_when_slots_meet_or_exceed_pack_value(qtbot):
    tracker = SlotValueTracker()
    qtbot.addWidget(tracker)

    tracker.set_compare_value(Decimal("20.00"))
    tracker.value_input.setText("25")
    tracker.on_enter_pressed()

    assert "covered" in tracker.compare_label.text().lower()
    assert "5.00" in tracker.compare_label.text()


def test_compare_value_shows_under_when_slots_below_pack_value(qtbot):
    tracker = SlotValueTracker()
    qtbot.addWidget(tracker)

    tracker.set_compare_value(Decimal("20.00"))
    tracker.value_input.setText("5")
    tracker.on_enter_pressed()

    assert "under" in tracker.compare_label.text().lower()
    assert "15.00" in tracker.compare_label.text()


def test_no_compare_label_before_any_slot_filled(qtbot):
    tracker = SlotValueTracker()
    qtbot.addWidget(tracker)

    tracker.set_compare_value(Decimal("20.00"))

    assert tracker.compare_label.text() == ""


def test_open_edit_dialog_applies_edited_values(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    tracker = SlotValueTracker()
    qtbot.addWidget(tracker)

    tracker.value_input.setText("10")
    tracker.on_enter_pressed()

    class FakeDialog:
        def __init__(self, values, parent=None):
            pass

        def exec(self):
            return QDialog.Accepted

        def values(self):
            return {1: Decimal("50"), 3: Decimal("7")}

    monkeypatch.setattr("elysium.ui.slot_tracker.SlotEditDialog", FakeDialog)

    tracker.open_edit_dialog()

    assert tracker.values == {1: Decimal("50"), 3: Decimal("7")}
