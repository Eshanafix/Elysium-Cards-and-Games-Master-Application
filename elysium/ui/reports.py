"""
Reports screen (LLD section 20; docs/IMPLEMENTATION_PLAN.md section 6.12).
Report picker + filters + preview table + background CSV export. Streamer
sees only their own-scoped reports (report_service enforces this itself,
not just this UI); admin sees everything, including admin-only datasets
that don't even appear in the picker for a non-admin.
"""

from datetime import datetime, time, timezone

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from elysium.exports.csv_exporter import CsvExportWorker
from elysium.exports.report_definitions import available_reports
from elysium.models.users import ROLE_ADMIN
from elysium.repositories import master_repository as repo
from elysium.services import report_service
from elysium.ui.table_scaling import make_columns_stretch
from elysium.ui.background import run_worker, safe_callback


def _qdate_to_start_of_day_utc(qdate: QDate) -> datetime:
    return datetime.combine(qdate.toPython(), time.min, tzinfo=timezone.utc)


def _qdate_to_end_of_day_utc(qdate: QDate) -> datetime:
    return datetime.combine(qdate.toPython(), time.max, tzinfo=timezone.utc)


class ReportsScreen(QWidget):
    def __init__(self, current_user):
        super().__init__()

        self.current_user = current_user
        self.definitions = []
        self.current_columns: list[str] = []
        self.current_rows: list[dict] = []
        self._export_worker = None

        layout = QVBoxLayout()

        title = QLabel("Reports")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")

        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("Report:"))
        self.report_combo = QComboBox()
        self.report_combo.currentIndexChanged.connect(self.on_report_changed)
        picker_row.addWidget(self.report_combo, stretch=1)

        filter_row = QHBoxLayout()

        self.streamer_label = QLabel("Streamer:")
        self.streamer_combo = QComboBox()
        self.streamer_combo.addItem("All", None)
        filter_row.addWidget(self.streamer_label)
        filter_row.addWidget(self.streamer_combo)

        self.product_label = QLabel("Product:")
        self.product_combo = QComboBox()
        self.product_combo.addItem("All", None)
        filter_row.addWidget(self.product_label)
        filter_row.addWidget(self.product_combo)

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
        self.run_button = QPushButton("Run Report")
        self.run_button.clicked.connect(self.run_report)
        self.export_button = QPushButton("Export CSV")
        self.export_button.clicked.connect(self.export_csv)
        button_row.addWidget(self.run_button)
        button_row.addWidget(self.export_button)
        button_row.addStretch(1)

        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        make_columns_stretch(self.table)

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addLayout(picker_row)
        layout.addLayout(filter_row)
        layout.addLayout(button_row)
        layout.addWidget(self.table)
        layout.addWidget(self.message_label)

        self.setLayout(layout)

        self.reload()

    def reload(self):
        self.definitions = available_reports(self.current_user)

        current_key = self.report_combo.currentData()
        self.report_combo.blockSignals(True)
        self.report_combo.clear()
        for d in self.definitions:
            self.report_combo.addItem(d.label, d.key)
        self.report_combo.blockSignals(False)

        if self.definitions:
            idx = self.report_combo.findData(current_key) if current_key else 0
            self.report_combo.setCurrentIndex(idx if idx >= 0 else 0)

        streamers = [u for u in repo.list_users() if u.streamer_database_name]
        self.streamer_combo.clear()
        self.streamer_combo.addItem("All", None)
        for u in streamers:
            self.streamer_combo.addItem(u.username, u.id)

        products = repo.list_products()
        self.product_combo.clear()
        self.product_combo.addItem("All", None)
        for p in sorted(products, key=lambda x: x.name):
            self.product_combo.addItem(p.name, p.id)

        self.on_report_changed()

    def _current_definition(self):
        key = self.report_combo.currentData()
        return next((d for d in self.definitions if d.key == key), None)

    def on_report_changed(self):
        definition = self._current_definition()

        if definition is None:
            return

        is_admin = ROLE_ADMIN in self.current_user.roles
        show_streamer_filter = definition.supports_streamer_filter and is_admin
        self.streamer_label.setVisible(show_streamer_filter)
        self.streamer_combo.setVisible(show_streamer_filter)

        self.product_label.setVisible(definition.supports_product_filter)
        self.product_combo.setVisible(definition.supports_product_filter)

        self.date_range_checkbox.setVisible(definition.supports_date_range)
        self.start_date_edit.setVisible(definition.supports_date_range)
        self.end_date_edit.setVisible(definition.supports_date_range)

    def on_date_range_toggled(self):
        enabled = self.date_range_checkbox.isChecked()
        self.start_date_edit.setEnabled(enabled)
        self.end_date_edit.setEnabled(enabled)

    def run_report(self):
        definition = self._current_definition()

        if definition is None:
            self.show_message("Select a report first.", error=True)
            return

        start_date = _qdate_to_start_of_day_utc(self.start_date_edit.date()) if self.date_range_checkbox.isChecked() else None
        end_date = _qdate_to_end_of_day_utc(self.end_date_edit.date()) if self.date_range_checkbox.isChecked() else None

        try:
            rows = definition.run(
                self.current_user,
                streamer_id=self.streamer_combo.currentData(),
                product_id=self.product_combo.currentData(),
                start_date=start_date,
                end_date=end_date,
            )
        except report_service.ReportPermissionError as e:
            self.show_message(str(e), error=True)
            return

        self.current_columns = definition.columns
        self.current_rows = rows

        self.table.setColumnCount(len(self.current_columns))
        self.table.setHorizontalHeaderLabels(self.current_columns)
        self.table.setRowCount(len(rows))

        for row_idx, row in enumerate(rows):
            for col_idx, column in enumerate(self.current_columns):
                value = row.get(column)
                self.table.setItem(row_idx, col_idx, QTableWidgetItem("" if value is None else str(value)))

        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()
        self.show_message(f"{len(rows)} row(s).", error=False)

    def export_csv(self):
        if not self.current_columns:
            self.show_message("Run a report first.", error=True)
            return

        definition = self._current_definition()
        default_name = f"{definition.key}.csv" if definition else "report.csv"

        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", default_name, "CSV Files (*.csv)")

        if not path:
            return

        self._export_worker = CsvExportWorker(self.current_columns, self.current_rows, path)
        self._export_worker.finished_success.connect(safe_callback(lambda p: self.show_message(f"Exported to {p}.", error=False)))
        self._export_worker.failed.connect(safe_callback(lambda err: self.show_message(f"Export failed: {err}", error=True)))
        run_worker(self._export_worker)

    def show_message(self, text: str, error: bool):
        self.message_label.setStyleSheet("color: #b00020;" if error else "color: #1a7f37;")
        self.message_label.setText(text)
