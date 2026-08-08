"""
Per-break "slot value" bookkeeping aid (streamer request; not part of the
LLD data model, purely a local/ephemeral UI scratchpad -- nothing here is
persisted or synced to Mongo). Some streamers split a break into up to 8
paid slots and want a running total as they go, to compare against the
break's locked pack market value while the break is still open ("are we
already past pack value by slot 4/8? maybe add a pack to balance it out").

Always visible, no button needed to reveal it: type an amount, press
Enter, it fills the next open slot automatically. Entirely optional -- a
streamer who never touches it just sees an empty box.
"""

from decimal import Decimal, InvalidOperation

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

MAX_SLOTS = 8


class SlotEditDialog(QDialog):
    """The "little dropdown" the streamer can open to fix a mistake --
    every slot shown at once, each independently editable."""

    def __init__(self, values: dict[int, Decimal], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Slot Values")

        layout = QVBoxLayout()
        self.inputs: dict[int, QLineEdit] = {}

        grid = QGridLayout()
        for slot in range(1, MAX_SLOTS + 1):
            grid.addWidget(QLabel(f"Slot {slot}:"), slot - 1, 0)
            field = QLineEdit()
            if slot in values:
                field.setText(f"{values[slot]:.2f}")
            grid.addWidget(field, slot - 1, 1)
            self.inputs[slot] = field
        layout.addLayout(grid)

        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #b00020;")
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)
        self._parsed_values: dict[int, Decimal] = {}

    def _try_accept(self):
        result: dict[int, Decimal] = {}

        for slot, field in self.inputs.items():
            text = field.text().strip()

            if not text:
                continue

            try:
                result[slot] = Decimal(text)
            except InvalidOperation:
                self.error_label.setText(f"Slot {slot} has an invalid amount: '{text}'")
                return

        self._parsed_values = result
        self.accept()

    def values(self) -> dict[int, Decimal]:
        return self._parsed_values


class SlotValueTracker(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("QFrame { border: 1px solid #999999; border-radius: 6px; }")

        self.values: dict[int, Decimal] = {}
        self.compare_to: Decimal | None = None

        layout = QVBoxLayout()

        title = QLabel("Slot Tracker (optional)")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        self.next_slot_label = QLabel()
        self.next_slot_label.setWordWrap(True)
        layout.addWidget(self.next_slot_label)

        self.value_input = QLineEdit()
        self.value_input.setPlaceholderText("Amount, then press Enter")
        self.value_input.returnPressed.connect(self.on_enter_pressed)
        layout.addWidget(self.value_input)

        self.total_label = QLabel()
        self.total_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.total_label.setWordWrap(True)
        layout.addWidget(self.total_label)

        self.compare_label = QLabel()
        self.compare_label.setWordWrap(True)
        layout.addWidget(self.compare_label)

        button_row = QHBoxLayout()
        self.edit_button = QPushButton("Edit Slots")
        self.edit_button.clicked.connect(self.open_edit_dialog)
        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.reset)
        button_row.addWidget(self.edit_button)
        button_row.addWidget(self.reset_button)
        layout.addLayout(button_row)

        self.setLayout(layout)

        self._refresh_labels()

    def set_compare_value(self, value: Decimal | None) -> None:
        """The current break's locked pack market value, so the tracker
        can flag "already past pack value" once enough slots are filled."""
        self.compare_to = value
        self._refresh_labels()

    def set_input_enabled(self, enabled: bool) -> None:
        self.value_input.setEnabled(enabled and self._next_open_slot() is not None)
        self.edit_button.setEnabled(enabled)

    def reset(self) -> None:
        self.values = {}
        self.value_input.clear()
        self._refresh_labels()

    def _next_open_slot(self) -> int | None:
        for slot in range(1, MAX_SLOTS + 1):
            if slot not in self.values:
                return slot
        return None

    def on_enter_pressed(self):
        text = self.value_input.text().strip()

        if not text:
            return

        slot = self._next_open_slot()

        if slot is None:
            self.value_input.clear()
            return

        try:
            amount = Decimal(text)
        except InvalidOperation:
            return

        self.values[slot] = amount
        self.value_input.clear()
        self._refresh_labels()

    def open_edit_dialog(self):
        dialog = SlotEditDialog(self.values, self)

        if dialog.exec() != QDialog.Accepted:
            return

        self.values = dialog.values()
        self._refresh_labels()

    def _refresh_labels(self):
        filled = len(self.values)
        next_slot = self._next_open_slot()

        if next_slot is None:
            self.next_slot_label.setText(f"All {MAX_SLOTS} slots filled -- use Edit Slots to change one.")
            self.value_input.setEnabled(False)
        else:
            self.next_slot_label.setText(f"Next entry fills slot {next_slot}/{MAX_SLOTS}")

        total = sum(self.values.values(), Decimal("0"))
        self.total_label.setText(f"Slots total: ${total:.2f} ({filled}/{MAX_SLOTS} filled)")

        if self.compare_to is not None and filled > 0:
            diff = total - self.compare_to
            if diff >= 0:
                self.compare_label.setStyleSheet("color: #1a7f37;")
                self.compare_label.setText(f"${diff:.2f} over pack value (${self.compare_to:.2f}) -- covered.")
            else:
                self.compare_label.setStyleSheet("color: #b00020;")
                self.compare_label.setText(f"${-diff:.2f} under pack value (${self.compare_to:.2f}) so far.")
        else:
            self.compare_label.setStyleSheet("")
            self.compare_label.setText("")
