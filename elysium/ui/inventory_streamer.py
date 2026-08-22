"""
Streamer "My Inventory" screen (LLD section 11, 24.2) and the admin
read-only "Streamer Inventory" view of any streamer's holdings (LLD 7.1,
24.3).
"""

from PySide6.QtWidgets import (
    QComboBox,
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

from elysium.models.users import ROLE_STREAMER
from elysium.repositories import master_repository as repo
from elysium.services import inventory_service, product_service
from elysium.ui.numeric_inputs import SelectAllSpinBox
from elysium.ui.numeric_table_item import NumericTableWidgetItem
from elysium.ui.product_search import ProductSearchDialog
from elysium.ui.table_scaling import make_columns_stretch, resize_columns_to_contents


class ClaimInventoryDialog(QDialog):
    """Quantity entry for a claim, once a product has already been chosen via
    ProductSearchDialog -- kept as a separate step (rather than a product
    combo box inside this same dialog) so picking the product is a focused
    search instead of scanning a 90+ item dropdown that used to take up the
    whole screen."""

    def __init__(self, product, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Claim Received Inventory: {product.name}")
        self.product = product

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

        layout.addWidget(QLabel(f"Packs per box: {product.packs_per_box}"))
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
            self.boxes_input.value(), self.loose_packs_input.value(), self.product.packs_per_box
        )
        self.converted_label.setText(f"Will claim: {packs} packs")

    def converted_packs(self) -> int:
        return inventory_service.box_to_packs(
            self.boxes_input.value(), self.loose_packs_input.value(), self.product.packs_per_box
        )


class ReturnInventoryDialog(QDialog):
    def __init__(self, product_name: str, current_packs: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Return Inventory: {product_name}")

        layout = QVBoxLayout()

        self.packs_input = SelectAllSpinBox()
        self.packs_input.setRange(1, max(1, current_packs))

        self.reason_input = QTextEdit()
        self.reason_input.setPlaceholderText("Reason (required)")
        self.reason_input.setMaximumHeight(80)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(QLabel(f"Currently held: {current_packs}"))
        layout.addWidget(QLabel("Packs to return:"))
        layout.addWidget(self.packs_input)
        layout.addWidget(QLabel("Reason:"))
        layout.addWidget(self.reason_input)
        layout.addWidget(buttons)

        self.setLayout(layout)


class MyInventoryScreen(QWidget):
    def __init__(self, current_user):
        super().__init__()

        self.current_user = current_user
        self._rows = []
        self._columns_sized = False

        layout = QVBoxLayout()

        title = QLabel("My Inventory")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")

        button_row = QHBoxLayout()
        self.claim_button = QPushButton("Claim Received Inventory")
        self.claim_button.clicked.connect(self.claim_inventory)
        self.return_button = QPushButton("Return Inventory")
        self.return_button.clicked.connect(self.return_inventory)

        button_row.addWidget(self.claim_button)
        button_row.addWidget(self.return_button)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Product", "Current Packs", "Price", "Market Value"])
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
        self._rows = inventory_service.get_streamer_inventory_view(self.current_user.streamer_database_name)
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
            market_value = (price * row["current_packs"]) if price is not None else None

            name_item = QTableWidgetItem(product.name)
            name_item.setData(1000, product.id)
            self.table.setItem(row_index, 0, name_item)
            self.table.setItem(row_index, 1, NumericTableWidgetItem(str(row["current_packs"]), row["current_packs"]))
            self.table.setItem(row_index, 2, NumericTableWidgetItem(
                f"${price:.2f}" if price is not None else row["price_status"], price,
            ))
            self.table.setItem(row_index, 3, NumericTableWidgetItem(
                f"${market_value:.2f}" if market_value is not None else "", market_value,
            ))

        # Only auto-size once -- claiming/returning inventory calls reload()
        # again right after, and resizeColumnsToContents() on every call
        # would silently undo a column width the user had just dragged wider.
        if not self._columns_sized:
            resize_columns_to_contents(self.table)
            self._columns_sized = True
        self.table.setSortingEnabled(True)

    def selected_row(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows()

        if not rows:
            return None

        product_id = self.table.item(rows[0].row(), 0).data(1000)
        return self._rows_by_id.get(product_id)

    def claim_inventory(self):
        products = [p for p in product_service.list_products() if p.is_active]
        picker = ProductSearchDialog(products, self, title="Claim Received Inventory: Select Product")

        if picker.exec() != QDialog.Accepted:
            return

        product = picker.selected_product()

        if not product:
            return

        dialog = ClaimInventoryDialog(product, self)

        if dialog.exec() != QDialog.Accepted:
            return

        packs = dialog.converted_packs()

        if packs <= 0:
            self.show_message("Enter at least one box or loose pack.", error=True)
            return

        try:
            inventory_service.streamer_claim(
                self.current_user.id, self.current_user.streamer_database_name, product.id, packs,
                requested_by=self.current_user.id,
            )
        except (inventory_service.InventoryValidationError,
                inventory_service.InsufficientInventoryError,
                inventory_service.StreamerLockedError) as e:
            self.show_message(str(e), error=True)
            return

        self.show_message(f"Claimed {packs} packs of '{product.name}'.", error=False)
        self.reload()

    def return_inventory(self):
        row = self.selected_row()

        if not row:
            self.show_message("Select a product first.", error=True)
            return

        product = row["product"]
        dialog = ReturnInventoryDialog(product.name, row["current_packs"], self)

        if dialog.exec() != QDialog.Accepted:
            return

        packs = dialog.packs_input.value()
        reason = dialog.reason_input.toPlainText().strip()

        try:
            inventory_service.streamer_return(
                self.current_user.id, self.current_user.streamer_database_name, product.id, packs, reason,
                requested_by=self.current_user.id,
            )
        except (inventory_service.InventoryValidationError,
                inventory_service.InsufficientInventoryError,
                inventory_service.StreamerLockedError) as e:
            self.show_message(str(e), error=True)
            return

        self.show_message(f"Returned {packs} packs of '{product.name}'.", error=False)
        self.reload()

    def show_message(self, text: str, error: bool):
        self.message_label.setStyleSheet("color: #ff6b6b;" if error else "color: #4caf50;")
        self.message_label.setText(text)


class StreamerInventoryAdminScreen(QWidget):
    """Admin read-only view of any streamer's current inventory (LLD 7.1)."""

    def __init__(self, current_user):
        super().__init__()

        self.current_user = current_user
        self._rows = []
        self._columns_sized = False
        self._streamers = [u for u in repo.list_users() if ROLE_STREAMER in u.roles]

        layout = QVBoxLayout()

        title = QLabel("Streamer Inventory")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")

        self.streamer_combo = QComboBox()
        for user in self._streamers:
            self.streamer_combo.addItem(user.username, user)
        self.streamer_combo.currentIndexChanged.connect(self.reload)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Product", "Current Packs", "Price"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        make_columns_stretch(self.table)

        layout.addWidget(title)
        layout.addWidget(QLabel("Streamer:"))
        layout.addWidget(self.streamer_combo)
        layout.addWidget(self.table)

        self.setLayout(layout)

        self.reload()

    def reload(self):
        streamer = self.streamer_combo.currentData()

        if not streamer or not streamer.streamer_database_name:
            self.table.setRowCount(0)
            return

        self._rows = inventory_service.get_streamer_inventory_view(streamer.streamer_database_name)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._rows))

        for row_index, row in enumerate(self._rows):
            product = row["product"]
            price = row["resolved_pack_price"]

            self.table.setItem(row_index, 0, QTableWidgetItem(product.name))
            self.table.setItem(row_index, 1, NumericTableWidgetItem(str(row["current_packs"]), row["current_packs"]))
            self.table.setItem(row_index, 2, NumericTableWidgetItem(
                f"${price:.2f}" if price is not None else row["price_status"], price,
            ))

        # Only auto-size once -- the streamer dropdown calls reload() every
        # time it's changed, and resizeColumnsToContents() on every call
        # would silently undo a column width the user had just dragged wider
        # (e.g. "why do I have to keep resizing the Product column").
        if not self._columns_sized:
            resize_columns_to_contents(self.table)
            self._columns_sized = True
        self.table.setSortingEnabled(True)
