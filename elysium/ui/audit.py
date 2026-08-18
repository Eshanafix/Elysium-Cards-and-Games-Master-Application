"""
Admin Audit History screen (LLD section 6.16; docs/IMPLEMENTATION_PLAN.md
section 4.5). Filterable/sortable browse over audit_events, CSV export
(audit-only, admin-only per LLD 20.5), and an inline Edit Reason action
that only appears when audit_service.editable_reason_target() recognizes
the selected row as having one -- the underlying audit_events document is
never touched by this screen, only whatever live record actually holds the
editable reason (plan section 4.5).
"""

from datetime import datetime, time, timezone

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from elysium.exports.csv_exporter import CsvExportWorker
from elysium.repositories import master_repository as repo
from elysium.services import audit_service
from elysium.ui.background import run_worker, safe_callback
from elysium.ui.table_scaling import make_columns_stretch, resize_columns_to_contents

_ACTION_TYPES = [
    "MASTER_INVENTORY_ADDED", "MASTER_INVENTORY_REMOVED",
    "STREAMER_INVENTORY_CLAIMED", "STREAMER_INVENTORY_RETURNED",
    "STREAM_STARTED", "BREAK_CREATED", "BREAK_ENDED", "BREAK_EDITED", "BREAK_DELETED",
    "STREAM_COMPLETED", "STREAM_CANCELED", "STREAM_FORCE_CANCELED",
    "STREAM_BREAK_CORRECTED", "STREAM_GROSS_CORRECTED",
    "INVENTORY_DISCREPANCY_CREATED", "INVENTORY_DISCREPANCY_RESOLVED",
    "PRICE_REFRESH_STARTED", "PRICE_REFRESH_COMPLETED", "PRICE_REFRESH_FAILED",
    "MANUAL_PRICE_ENTERED", "PREVIOUS_PRICE_ACCEPTED",
    "USER_CREATED", "PASSWORD_RESET",
    "DECOMMISSION_INITIATED", "DECOMMISSION_APPROVED", "DECOMMISSION_CANCELED",
    "ACCOUNT_DISABLED", "REASON_EDITED",
]

_COLUMNS = [
    "timestamp", "action_type", "performed_by", "role", "product_id", "streamer_id",
    "stream_id", "break_id", "quantity_change", "amount_change", "reason", "status",
]


class EditReasonDialog(QDialog):
    def __init__(self, current_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Reason")

        layout = QVBoxLayout()
        layout.addWidget(QLabel("New reason text (the previous text is preserved, never erased):"))

        self.text_input = QTextEdit()
        self.text_input.setPlainText(current_text or "")
        layout.addWidget(self.text_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def new_text(self) -> str:
        return self.text_input.toPlainText().strip()


class AuditHistoryScreen(QWidget):
    def __init__(self, current_user):
        super().__init__()

        self.current_user = current_user
        self.events: list[dict] = []
        self._columns_sized = False

        layout = QVBoxLayout()

        title = QLabel("Audit History")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Action:"))
        self.action_combo = QComboBox()
        self.action_combo.addItem("All", None)
        for action_type in _ACTION_TYPES:
            self.action_combo.addItem(action_type, action_type)
        filter_row.addWidget(self.action_combo)

        filter_row.addWidget(QLabel("Streamer:"))
        self.streamer_combo = QComboBox()
        self.streamer_combo.addItem("All", None)
        filter_row.addWidget(self.streamer_combo)

        self.date_range_checkbox = QCheckBox("Filter by date range")
        self.date_range_checkbox.stateChanged.connect(self.on_date_range_toggled)
        filter_row.addWidget(self.date_range_checkbox)

        self.start_date_edit = QDateEdit(calendarPopup=True)
        self.start_date_edit.setDate(QDate.currentDate().addMonths(-1))
        self.start_date_edit.setEnabled(False)
        filter_row.addWidget(self.start_date_edit)

        filter_row.addWidget(QLabel("to"))

        self.end_date_edit = QDateEdit(calendarPopup=True)
        self.end_date_edit.setDate(QDate.currentDate())
        self.end_date_edit.setEnabled(False)
        filter_row.addWidget(self.end_date_edit)

        filter_row.addStretch(1)

        button_row = QHBoxLayout()
        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self.reload)
        self.edit_reason_button = QPushButton("Edit Reason")
        self.edit_reason_button.clicked.connect(self.edit_selected_reason)
        self.export_button = QPushButton("Export CSV")
        self.export_button.clicked.connect(self.export_csv)
        button_row.addWidget(self.run_button)
        button_row.addWidget(self.edit_reason_button)
        button_row.addWidget(self.export_button)
        button_row.addStretch(1)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        make_columns_stretch(self.table)

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addLayout(filter_row)
        layout.addLayout(button_row)
        layout.addWidget(self.table)
        layout.addWidget(self.message_label)

        self.setLayout(layout)

        self._export_worker = None
        self.reload_streamers()
        self.reload()

    def reload_streamers(self):
        current = self.streamer_combo.currentData()
        self.streamer_combo.clear()
        self.streamer_combo.addItem("All", None)
        for u in repo.list_users():
            if u.streamer_database_name:
                self.streamer_combo.addItem(u.username, u.id)
        idx = self.streamer_combo.findData(current)
        if idx >= 0:
            self.streamer_combo.setCurrentIndex(idx)

    def on_date_range_toggled(self):
        enabled = self.date_range_checkbox.isChecked()
        self.start_date_edit.setEnabled(enabled)
        self.end_date_edit.setEnabled(enabled)

    def reload(self):
        start_date = None
        end_date = None
        if self.date_range_checkbox.isChecked():
            start_date = datetime.combine(self.start_date_edit.date().toPython(), time.min, tzinfo=timezone.utc)
            end_date = datetime.combine(self.end_date_edit.date().toPython(), time.max, tzinfo=timezone.utc)

        self.events = audit_service.list_events(
            action_type=self.action_combo.currentData(),
            streamer_id=self.streamer_combo.currentData(),
            start_date=start_date,
            end_date=end_date,
        )

        username_by_id = {u.id: u.username for u in repo.list_users()}

        self.table.setRowCount(len(self.events))
        for row, event in enumerate(self.events):
            for col, column in enumerate(_COLUMNS):
                value = event.get(column)
                if column in ("performed_by", "streamer_id") and value:
                    value = username_by_id.get(value, value)
                if hasattr(value, "to_decimal"):
                    value = value.to_decimal()
                self.table.setItem(row, col, QTableWidgetItem("" if value is None else str(value)))

        # Only auto-size once -- Run/filter changes call reload() repeatedly,
        # and resizing on every call would keep undoing a manually-widened column.
        if not self._columns_sized:
            resize_columns_to_contents(self.table)
            self._columns_sized = True
        self.show_message(f"{len(self.events)} event(s).", error=False)

    def selected_event(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows()

        if not rows:
            return None

        return self.events[rows[0].row()]

    def edit_selected_reason(self):
        event = self.selected_event()

        if event is None:
            self.show_message("Select an event first.", error=True)
            return

        target = audit_service.editable_reason_target(event)

        if target is None:
            self.show_message("This event's reason is not editable.", error=True)
            return

        dialog = EditReasonDialog(event.get("reason") or "", self)

        if dialog.exec() != QDialog.Accepted:
            return

        new_text = dialog.new_text()

        if not new_text:
            self.show_message("Reason text cannot be empty.", error=True)
            return

        streamer_database_name = None
        streamer_id = target.get("streamer_id")
        if streamer_id:
            streamer = repo.find_user_by_id(streamer_id)
            streamer_database_name = streamer.streamer_database_name if streamer else None

        try:
            audit_service.edit_reason(
                target["related_record_type"], target["related_record_id"], new_text,
                edited_by=self.current_user.id,
                streamer_database_name=streamer_database_name,
                stream_id=target.get("stream_id"),
            )
        except (audit_service.ReasonEditPermissionError, audit_service.ReasonEditValidationError) as e:
            self.show_message(str(e), error=True)
            return

        self.show_message("Reason updated.", error=False)
        self.reload()

    def export_csv(self):
        if not self.events:
            self.show_message("Nothing to export -- run a query first.", error=True)
            return

        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "audit_history.csv", "CSV Files (*.csv)")

        if not path:
            return

        rows = []
        for event in self.events:
            row = {}
            for column in _COLUMNS:
                value = event.get(column)
                row[column] = str(value.to_decimal()) if hasattr(value, "to_decimal") else value
            rows.append(row)

        self._export_worker = CsvExportWorker(_COLUMNS, rows, path)
        self._export_worker.finished_success.connect(safe_callback(lambda p: self.show_message(f"Exported to {p}.", error=False)))
        self._export_worker.failed.connect(safe_callback(lambda err: self.show_message(f"Export failed: {err}", error=True)))
        run_worker(self._export_worker)

    def show_message(self, text: str, error: bool):
        self.message_label.setStyleSheet("color: #ff6b6b;" if error else "color: #4caf50;")
        self.message_label.setText(text)
