"""
Admin Discrepancies screen (LLD section 17.6.A; docs/IMPLEMENTATION_PLAN.md
sections 4.6, 6.15). Open/resolved inventory discrepancies opened by stream
corrections (or decommission approvals that leave a residual negative
balance) -- resolving one requires a note, permanently recorded on the
discrepancy document itself (it is not part of audit_events).
"""

from PySide6.QtWidgets import (
    QCheckBox,
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

from elysium.models.discrepancies import STATUS_OPEN
from elysium.repositories import master_repository as repo
from elysium.services import discrepancy_service
from elysium.ui.table_scaling import make_columns_stretch


class ResolveDiscrepancyDialog(QDialog):
    def __init__(self, streamer_username: str, product_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Resolve Discrepancy: {streamer_username} / {product_name}")

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Resolution note (required):"))

        self.note_input = QTextEdit()
        self.note_input.setMaximumHeight(80)
        layout.addWidget(self.note_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)


class DiscrepanciesScreen(QWidget):
    def __init__(self, current_user):
        super().__init__()

        self.current_user = current_user
        self.discrepancies = []

        layout = QVBoxLayout()

        title = QLabel("Inventory Discrepancies")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")

        button_row = QHBoxLayout()
        self.resolve_button = QPushButton("Resolve Selected")
        self.resolve_button.clicked.connect(self.resolve_selected)
        self.show_all_checkbox = QCheckBox("Show all (including resolved)")
        self.show_all_checkbox.stateChanged.connect(self.reload)

        button_row.addWidget(self.resolve_button)
        button_row.addWidget(self.show_all_checkbox)
        button_row.addStretch(1)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Streamer", "Product", "Type", "Quantity", "Source", "Status", "Resolution Note"]
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
        status = None if self.show_all_checkbox.isChecked() else STATUS_OPEN
        self.discrepancies = discrepancy_service.list_discrepancies(status=status)

        username_by_id = {user.id: user.username for user in repo.list_users()}
        products_by_id = {p.id: p for p in repo.list_products()}

        self.table.setRowCount(len(self.discrepancies))
        for row, d in enumerate(self.discrepancies):
            product = products_by_id.get(d.product_id)
            self.table.setItem(row, 0, QTableWidgetItem(username_by_id.get(d.streamer_id, d.streamer_id)))
            self.table.setItem(row, 1, QTableWidgetItem(product.name if product else d.product_id))
            self.table.setItem(row, 2, QTableWidgetItem(d.type))
            self.table.setItem(row, 3, QTableWidgetItem(str(d.quantity)))
            self.table.setItem(row, 4, QTableWidgetItem(d.source))
            self.table.setItem(row, 5, QTableWidgetItem(d.status))
            self.table.setItem(row, 6, QTableWidgetItem(d.resolution_note or ""))
            self.table.item(row, 0).setData(1000, d.id)

        self.table.resizeColumnsToContents()

    def selected_discrepancy(self):
        rows = self.table.selectionModel().selectedRows()

        if not rows:
            return None

        row = rows[0].row()
        discrepancy_id = self.table.item(row, 0).data(1000)
        return next((d for d in self.discrepancies if d.id == discrepancy_id), None)

    def resolve_selected(self):
        discrepancy = self.selected_discrepancy()

        if not discrepancy:
            self.show_message("Select a discrepancy first.", error=True)
            return

        if discrepancy.status != STATUS_OPEN:
            self.show_message("This discrepancy is already resolved.", error=True)
            return

        username_by_id = {user.id: user.username for user in repo.list_users()}
        products_by_id = {p.id: p for p in repo.list_products()}
        username = username_by_id.get(discrepancy.streamer_id, discrepancy.streamer_id)
        product = products_by_id.get(discrepancy.product_id)
        product_name = product.name if product else discrepancy.product_id

        dialog = ResolveDiscrepancyDialog(username, product_name, self)

        if dialog.exec() != QDialog.Accepted:
            return

        note = dialog.note_input.toPlainText().strip()

        try:
            discrepancy_service.resolve_discrepancy(discrepancy.id, resolved_by=self.current_user.id, resolution_note=note)
        except discrepancy_service.DiscrepancyValidationError as e:
            self.show_message(str(e), error=True)
            return

        self.show_message(f"Discrepancy for '{username}' / '{product_name}' resolved.", error=False)
        self.reload()

    def show_message(self, text: str, error: bool):
        self.message_label.setStyleSheet("color: #b00020;" if error else "color: #1a7f37;")
        self.message_label.setText(text)
