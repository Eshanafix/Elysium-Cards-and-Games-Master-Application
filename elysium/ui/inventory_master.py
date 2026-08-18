"""
Admin Master Inventory screen (LLD section 10, 24.3).
"""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from elysium.models.users import ROLE_ADMIN
from elysium.services import inventory_service
from elysium.ui.numeric_inputs import SelectAllSpinBox
from elysium.ui.numeric_table_item import NumericTableWidgetItem
from elysium.ui.table_scaling import make_columns_stretch


class AddInventoryDialog(QDialog):
    def __init__(self, product_name: str, packs_per_box: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Add Inventory: {product_name}")
        self.packs_per_box = packs_per_box

        layout = QVBoxLayout()

        self.boxes_input = SelectAllSpinBox()
        self.boxes_input.setRange(0, 9999)
        self.boxes_input.valueChanged.connect(self.update_converted_label)

        self.loose_packs_input = SelectAllSpinBox()
        self.loose_packs_input.setRange(0, 9999)
        self.loose_packs_input.valueChanged.connect(self.update_converted_label)

        self.converted_label = QLabel()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(QLabel(f"Packs per box: {packs_per_box}"))
        layout.addWidget(QLabel("Boxes:"))
        layout.addWidget(self.boxes_input)
        layout.addWidget(QLabel("Additional loose packs:"))
        layout.addWidget(self.loose_packs_input)
        layout.addWidget(self.converted_label)
        layout.addWidget(buttons)

        self.setLayout(layout)
        self.update_converted_label()

    def update_converted_label(self):
        packs = inventory_service.box_to_packs(
            self.boxes_input.value(), self.loose_packs_input.value(), self.packs_per_box
        )
        self.converted_label.setText(f"Will add: {packs} packs")

    def converted_packs(self) -> int:
        return inventory_service.box_to_packs(
            self.boxes_input.value(), self.loose_packs_input.value(), self.packs_per_box
        )


class ReduceInventoryDialog(QDialog):
    def __init__(self, product_name: str, unassigned_packs: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Reduce Inventory: {product_name}")

        layout = QVBoxLayout()

        self.packs_input = SelectAllSpinBox()
        self.packs_input.setRange(1, max(1, unassigned_packs))

        self.reason_input = QTextEdit()
        self.reason_input.setPlaceholderText("Reason (required)")
        self.reason_input.setMaximumHeight(80)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(QLabel(f"Currently unassigned: {unassigned_packs}"))
        layout.addWidget(QLabel("Packs to remove:"))
        layout.addWidget(self.packs_input)
        layout.addWidget(QLabel("Reason:"))
        layout.addWidget(self.reason_input)
        layout.addWidget(buttons)

        self.setLayout(layout)


class MasterInventoryScreen(QWidget):
    def __init__(self, current_user):
        super().__init__()

        self.current_user = current_user
        self._rows = []

        layout = QVBoxLayout()

        title = QLabel("Master Inventory")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")

        button_row = QHBoxLayout()
        self.add_button = QPushButton("Add Inventory")
        self.add_button.clicked.connect(self.add_inventory)
        self.reduce_button = QPushButton("Reduce Inventory")
        self.reduce_button.clicked.connect(self.reduce_inventory)

        # LLD hard rule: only an admin ever changes the master total.
        # Streamers can now browse this screen but never these actions.
        is_admin = ROLE_ADMIN in current_user.roles
        self.add_button.setVisible(is_admin)
        self.reduce_button.setVisible(is_admin)

        button_row.addWidget(self.add_button)
        button_row.addWidget(self.reduce_button)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Product", "Total", "Unassigned", "Assigned", "Price", "Market Value", "Allocations"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        make_columns_stretch(self.table)

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addLayout(button_row)
        layout.addWidget(self.table)
        layout.addWidget(self.message_label)

        self.setLayout(layout)

        self.reload()

    def reload(self):
        self._rows = inventory_service.get_master_inventory_view()
        # Sorting reorders the table's visual rows without touching
        # self._rows -- selected_row() looks the selection up by product id
        # (stored on the row's own item) instead of a positional index into
        # this list, so it still resolves to the right row after a sort.
        self._rows_by_id = {row["product"].id: row for row in self._rows}

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._rows))

        for row_index, row in enumerate(self._rows):
            product = row["product"]
            price = row["resolved_pack_price"]
            market_value = (price * row["total_packs"]) if price is not None else None

            allocation_summary = ", ".join(
                f"{a['streamer_username']}:{a['current_packs']}"
                for a in row["allocations"] if a["current_packs"] != 0
            )

            name_item = QTableWidgetItem(product.name)
            name_item.setData(1000, product.id)
            self.table.setItem(row_index, 0, name_item)
            self.table.setItem(row_index, 1, NumericTableWidgetItem(str(row["total_packs"]), row["total_packs"]))
            self.table.setItem(row_index, 2, NumericTableWidgetItem(str(row["unassigned_packs"]), row["unassigned_packs"]))
            self.table.setItem(row_index, 3, NumericTableWidgetItem(str(row["assigned_packs"]), row["assigned_packs"]))
            self.table.setItem(row_index, 4, NumericTableWidgetItem(
                f"${price:.2f}" if price is not None else row["price_status"], price,
            ))
            self.table.setItem(row_index, 5, NumericTableWidgetItem(
                f"${market_value:.2f}" if market_value is not None else "", market_value,
            ))
            self.table.setItem(row_index, 6, QTableWidgetItem(allocation_summary))

        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)

    def selected_row(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows()

        if not rows:
            return None

        product_id = self.table.item(rows[0].row(), 0).data(1000)
        return self._rows_by_id.get(product_id)

    def add_inventory(self):
        if ROLE_ADMIN not in self.current_user.roles:
            return

        row = self.selected_row()

        if not row:
            self.show_message("Select a product first.", error=True)
            return

        product = row["product"]
        dialog = AddInventoryDialog(product.name, product.packs_per_box, self)

        if dialog.exec() != QDialog.Accepted:
            return

        packs = dialog.converted_packs()

        if packs <= 0:
            self.show_message("Enter at least one box or loose pack.", error=True)
            return

        try:
            inventory_service.admin_add_inventory(product.id, packs, self.current_user.id)
        except inventory_service.InventoryValidationError as e:
            self.show_message(str(e), error=True)
            return

        self.show_message(f"Added {packs} packs to '{product.name}'.", error=False)
        self.reload()

    def reduce_inventory(self):
        if ROLE_ADMIN not in self.current_user.roles:
            return

        row = self.selected_row()

        if not row:
            self.show_message("Select a product first.", error=True)
            return

        product = row["product"]
        dialog = ReduceInventoryDialog(product.name, row["unassigned_packs"], self)

        if dialog.exec() != QDialog.Accepted:
            return

        packs = dialog.packs_input.value()
        reason = dialog.reason_input.toPlainText().strip()

        try:
            inventory_service.admin_reduce_inventory(product.id, packs, reason, self.current_user.id)
        except (inventory_service.InventoryValidationError, inventory_service.InsufficientInventoryError) as e:
            self.show_message(str(e), error=True)
            return

        self.show_message(f"Removed {packs} packs from '{product.name}'.", error=False)
        self.reload()

    def show_message(self, text: str, error: bool):
        self.message_label.setStyleSheet("color: #ff6b6b;" if error else "color: #4caf50;")
        self.message_label.setText(text)
