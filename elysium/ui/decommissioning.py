"""
Admin Decommissioning screen (LLD section 18.1; docs/IMPLEMENTATION_PLAN.md
sections 4.3, 4.8, 6.14). Pending requests show the streamer's allocation
snapshot from initiation time; Approve re-validates against live inventory
inside decommission_service's transaction and only then disables login.
"""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from elysium.models.decommission import STATUS_PENDING
from elysium.repositories import master_repository as repo
from elysium.services import decommission_service
from elysium.ui.table_scaling import make_columns_stretch, resize_columns_to_contents


class DecommissionDetailDialog(QDialog):
    def __init__(self, request, streamer_username: str, products_by_id: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Decommission: {streamer_username}")

        layout = QVBoxLayout()
        layout.addWidget(QLabel(
            f"Streamer: {streamer_username}\n"
            f"Initiated by: {request.initiated_by}\nInitiated at: {request.initiated_at}\n\n"
            "Snapshot at initiation (approval re-validates against live inventory):"
        ))

        table = QTableWidget(len(request.snapshot_of_allocations_at_initiation), 2)
        table.setHorizontalHeaderLabels(["Product", "Current Packs"])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        make_columns_stretch(table)

        for row, entry in enumerate(request.snapshot_of_allocations_at_initiation):
            product = products_by_id.get(entry["product_id"])
            name = product.name if product else entry["product_id"]
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, QTableWidgetItem(str(entry["current_packs"])))

        resize_columns_to_contents(table)
        layout.addWidget(table)

        note = QLabel(
            "Only positive balances are swept back to master unassigned stock. Any residual "
            "negative (ledger-shortage) balance is left open in Discrepancies for manual "
            "resolution -- it is never silently erased by decommissioning."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Approve")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)


class CancelDecommissionDialog(QDialog):
    def __init__(self, streamer_username: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Cancel Decommission: {streamer_username}")

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Optional note:"))

        self.notes_input = QTextEdit()
        self.notes_input.setMaximumHeight(80)
        layout.addWidget(self.notes_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)


class DecommissioningScreen(QWidget):
    def __init__(self, current_user):
        super().__init__()

        self.current_user = current_user
        self.requests = []
        self._columns_sized = False

        layout = QVBoxLayout()

        title = QLabel("Decommissioning")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")

        button_row = QHBoxLayout()
        self.approve_button = QPushButton("Approve Selected")
        self.approve_button.clicked.connect(self.approve_selected)
        self.cancel_button = QPushButton("Cancel Selected")
        self.cancel_button.clicked.connect(self.cancel_selected)
        self.show_all_checkbox = QCheckBox("Show all (including approved/canceled)")
        self.show_all_checkbox.stateChanged.connect(self.reload)

        button_row.addWidget(self.approve_button)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.show_all_checkbox)
        button_row.addStretch(1)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Streamer", "Status", "Initiated By", "Initiated At", "Notes"])
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
        if self.show_all_checkbox.isChecked():
            self.requests = decommission_service.list_all()
        else:
            self.requests = decommission_service.list_pending()

        username_by_id = {user.id: user.username for user in repo.list_users()}

        self.table.setRowCount(len(self.requests))
        for row, request in enumerate(self.requests):
            self.table.setItem(row, 0, QTableWidgetItem(username_by_id.get(request.streamer_id, request.streamer_id)))
            self.table.setItem(row, 1, QTableWidgetItem(request.status))
            self.table.setItem(row, 2, QTableWidgetItem(username_by_id.get(request.initiated_by, request.initiated_by)))
            self.table.setItem(row, 3, QTableWidgetItem(str(request.initiated_at)))
            self.table.setItem(row, 4, QTableWidgetItem(request.notes or ""))
            self.table.item(row, 0).setData(1000, request.id)

        # Only auto-size once -- the "Show all" checkbox calls reload()
        # again, and resizing on every call would keep undoing a
        # manually-widened column.
        if not self._columns_sized:
            resize_columns_to_contents(self.table)
            self._columns_sized = True

    def selected_request(self):
        rows = self.table.selectionModel().selectedRows()

        if not rows:
            return None

        row = rows[0].row()
        request_id = self.table.item(row, 0).data(1000)
        return next((r for r in self.requests if r.id == request_id), None)

    def approve_selected(self):
        request = self.selected_request()

        if not request:
            self.show_message("Select a pending decommission request first.", error=True)
            return

        if request.status != STATUS_PENDING:
            self.show_message("Only a pending request can be approved.", error=True)
            return

        username_by_id = {user.id: user.username for user in repo.list_users()}
        products_by_id = {p.id: p for p in repo.list_products()}
        username = username_by_id.get(request.streamer_id, request.streamer_id)

        dialog = DecommissionDetailDialog(request, username, products_by_id, self)

        if dialog.exec() != QDialog.Accepted:
            return

        try:
            decommission_service.approve(request.id, approved_by=self.current_user.id)
        except decommission_service.DecommissionValidationError as e:
            self.show_message(str(e), error=True)
            return
        except decommission_service.ActiveStreamLockError as e:
            self.show_message(str(e), error=True)
            return

        self.show_message(f"Decommission approved for '{username}'; login disabled.", error=False)
        self.reload()

    def cancel_selected(self):
        request = self.selected_request()

        if not request:
            self.show_message("Select a pending decommission request first.", error=True)
            return

        if request.status != STATUS_PENDING:
            self.show_message("Only a pending request can be canceled.", error=True)
            return

        username_by_id = {user.id: user.username for user in repo.list_users()}
        username = username_by_id.get(request.streamer_id, request.streamer_id)

        confirm = QMessageBox.question(self, "Cancel Decommission", f"Cancel the decommission request for '{username}'?")

        if confirm != QMessageBox.Yes:
            return

        dialog = CancelDecommissionDialog(username, self)

        if dialog.exec() != QDialog.Accepted:
            return

        try:
            decommission_service.cancel(
                request.id, canceled_by=self.current_user.id, notes=dialog.notes_input.toPlainText().strip() or None
            )
        except decommission_service.DecommissionValidationError as e:
            self.show_message(str(e), error=True)
            return

        self.show_message(f"Decommission request for '{username}' canceled.", error=False)
        self.reload()

    def show_message(self, text: str, error: bool):
        self.message_label.setStyleSheet("color: #ff6b6b;" if error else "color: #4caf50;")
        self.message_label.setText(text)
