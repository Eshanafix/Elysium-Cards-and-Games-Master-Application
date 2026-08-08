"""
Admin Correct Stream screen (LLD section 17.6; docs/IMPLEMENTATION_PLAN.md
section 6.13). Read-only browse of a streamer's completed streams and their
breaks, with entry points into correction_service's break/gross correction
flows -- required reason, before/after is shown via the reload after a
correction lands, and the shortage-choice (A/B/C/D) dialog appears only
when a pack-line increase actually needs one.
"""

from decimal import Decimal, InvalidOperation

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from elysium.models.streams import STATUS_COMPLETED
from elysium.models.users import ROLE_STREAMER
from elysium.repositories import master_repository as repo
from elysium.repositories import streamer_repository as streamer_repo
from elysium.services import correction_service
from elysium.ui.dialog_sizing import clamp_to_screen
from elysium.ui.numeric_inputs import SelectAllDoubleSpinBox, SelectAllSpinBox


class ShortageChoiceDialog(QDialog):
    """LLD 17.6.A's four-way shortage choice, shown only when a correction
    increases pack usage beyond the streamer's current ledger balance."""

    def __init__(self, shortage_summary: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Shortage Choice Required")

        layout = QVBoxLayout()

        label = QLabel(
            "This correction increases pack usage beyond what the streamer's ledger "
            f"currently shows as available:\n\n{shortage_summary}\n\nHow should the "
            "shortfall be handled?"
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        self.choice_a = QRadioButton("A -- Allow negative inventory (ledger may go negative; discrepancy opened)")
        self.choice_c = QRadioButton("C -- Deduct available, record discrepancy (ledger clamped at 0)")
        self.choice_b = QRadioButton("B -- Block this correction (add/return inventory first)")
        self.choice_a.setChecked(True)

        layout.addWidget(self.choice_a)
        layout.addWidget(self.choice_c)
        layout.addWidget(self.choice_b)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def selected_choice(self) -> str:
        if self.choice_a.isChecked():
            return correction_service.CHOICE_A_NEGATIVE
        if self.choice_c.isChecked():
            return correction_service.CHOICE_C_PARTIAL
        return correction_service.CHOICE_B_BLOCKED


class CorrectBreakDialog(QDialog):
    def __init__(self, break_obj, stream, products_by_id: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Correct Break #{break_obj.sequence_number}")
        clamp_to_screen(self, 600, 500)

        self.break_obj = break_obj
        self.stream = stream
        self.products_by_id = products_by_id
        self._row_product_ids: list[str] = []

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Pack lines (edit quantity; 0 removes the line):"))

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Product", "Original Qty", "New Qty", "Historical Price"])
        for line in break_obj.pack_lines:
            self._add_row(line["product_id"], line["quantity"], price_editable=False)
        layout.addWidget(self.table)

        add_row_layout = QHBoxLayout()
        self.add_product_combo = QComboBox()
        existing_ids = {line["product_id"] for line in break_obj.pack_lines}
        for product in sorted(products_by_id.values(), key=lambda p: p.name):
            if product.id not in existing_ids:
                self.add_product_combo.addItem(product.name, product.id)
        self.add_row_button = QPushButton("Add Product Line")
        self.add_row_button.clicked.connect(self.on_add_row)
        add_row_layout.addWidget(self.add_product_combo, stretch=1)
        add_row_layout.addWidget(self.add_row_button)
        layout.addLayout(add_row_layout)

        gross_layout = QHBoxLayout()
        gross_layout.addWidget(QLabel("New Break Gross (optional, blank = unchanged):"))
        self.gross_input = QLineEdit()
        if break_obj.break_gross is not None:
            self.gross_input.setPlaceholderText(str(break_obj.break_gross))
        gross_layout.addWidget(self.gross_input)
        layout.addLayout(gross_layout)

        layout.addWidget(QLabel("Reason (required):"))
        self.reason_input = QTextEdit()
        self.reason_input.setMaximumHeight(70)
        layout.addWidget(self.reason_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def _add_row(self, product_id: str, original_qty: int, price_editable: bool):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._row_product_ids.append(product_id)

        product = self.products_by_id.get(product_id)
        self.table.setItem(row, 0, QTableWidgetItem(product.name if product else product_id))
        self.table.setItem(row, 1, QTableWidgetItem(str(original_qty)))

        spin = SelectAllSpinBox()
        spin.setRange(0, 100000)
        spin.setValue(original_qty)
        self.table.setCellWidget(row, 2, spin)

        price_field = QLineEdit()
        price_field.setEnabled(price_editable)
        if not price_editable:
            price_field.setPlaceholderText("uses locked/snapshot price")
        self.table.setCellWidget(row, 3, price_field)

        self.table.resizeColumnsToContents()

    def on_add_row(self):
        product_id = self.add_product_combo.currentData()

        if product_id is None or product_id in self._row_product_ids:
            return

        has_snapshot_price = self.stream.price_for_product(product_id) is not None
        self._add_row(product_id, 0, price_editable=not has_snapshot_price)
        idx = self.add_product_combo.findData(product_id)
        if idx >= 0:
            self.add_product_combo.removeItem(idx)

    def pack_line_changes(self) -> dict[str, int]:
        changes = {}
        for row, product_id in enumerate(self._row_product_ids):
            new_qty = self.table.cellWidget(row, 2).value()
            changes[product_id] = new_qty
        return changes

    def historical_prices(self) -> dict[str, Decimal]:
        prices = {}
        for row, product_id in enumerate(self._row_product_ids):
            field = self.table.cellWidget(row, 3)
            text = field.text().strip()
            if field.isEnabled() and text:
                try:
                    prices[product_id] = Decimal(text)
                except InvalidOperation:
                    pass
        return prices

    def new_break_gross(self) -> Decimal | None:
        text = self.gross_input.text().strip()
        if not text:
            return None
        return Decimal(text)

    def reason(self) -> str:
        return self.reason_input.toPlainText().strip()


class CorrectFinalGrossDialog(QDialog):
    def __init__(self, stream, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Correct Final Stream Gross")

        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"Current final stream gross: {stream.final_stream_gross}"))

        self.gross_input = SelectAllDoubleSpinBox()
        self.gross_input.setRange(0, 10_000_000)
        self.gross_input.setDecimals(2)
        self.gross_input.setValue(float(stream.final_stream_gross or 0))
        layout.addWidget(self.gross_input)

        layout.addWidget(QLabel("Reason (required):"))
        self.reason_input = QTextEdit()
        self.reason_input.setMaximumHeight(70)
        layout.addWidget(self.reason_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def new_gross(self) -> Decimal:
        return Decimal(str(self.gross_input.value()))

    def reason(self) -> str:
        return self.reason_input.toPlainText().strip()


class StreamCorrectionsScreen(QWidget):
    def __init__(self, current_user):
        super().__init__()

        self.current_user = current_user
        self.streamers = []
        self.streams = []
        self.breaks = []
        self.selected_stream = None

        layout = QVBoxLayout()

        title = QLabel("Correct Stream")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")

        streamer_row = QHBoxLayout()
        streamer_row.addWidget(QLabel("Streamer:"))
        self.streamer_combo = QComboBox()
        self.streamer_combo.currentIndexChanged.connect(self.on_streamer_changed)
        streamer_row.addWidget(self.streamer_combo, stretch=1)

        layout.addWidget(title)
        layout.addLayout(streamer_row)

        layout.addWidget(QLabel("Completed streams:"))
        self.streams_table = QTableWidget(0, 4)
        self.streams_table.setHorizontalHeaderLabels(["Date", "Final Gross", "Stream Profit", "Corrections"])
        self.streams_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.streams_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.streams_table.itemSelectionChanged.connect(self.on_stream_selected)
        layout.addWidget(self.streams_table)

        stream_button_row = QHBoxLayout()
        self.correct_gross_button = QPushButton("Correct Final Gross")
        self.correct_gross_button.clicked.connect(self.on_correct_gross)
        stream_button_row.addWidget(self.correct_gross_button)
        stream_button_row.addStretch(1)
        layout.addLayout(stream_button_row)

        layout.addWidget(QLabel("Breaks:"))
        self.breaks_table = QTableWidget(0, 4)
        self.breaks_table.setHorizontalHeaderLabels(["#", "Name", "Status", "Break Gross"])
        self.breaks_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.breaks_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.breaks_table)

        break_button_row = QHBoxLayout()
        self.correct_break_button = QPushButton("Correct Selected Break")
        self.correct_break_button.clicked.connect(self.on_correct_break)
        break_button_row.addWidget(self.correct_break_button)
        break_button_row.addStretch(1)
        layout.addLayout(break_button_row)

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        self.setLayout(layout)

        self.reload()

    def reload(self):
        self.streamers = [u for u in repo.list_users() if ROLE_STREAMER in u.roles and u.streamer_database_name]

        current_id = self.streamer_combo.currentData()
        self.streamer_combo.blockSignals(True)
        self.streamer_combo.clear()
        for user in self.streamers:
            self.streamer_combo.addItem(user.username, user.id)
        self.streamer_combo.blockSignals(False)

        if self.streamers:
            idx = self.streamer_combo.findData(current_id) if current_id else 0
            self.streamer_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.load_streams()

    def _selected_streamer(self):
        user_id = self.streamer_combo.currentData()
        return next((u for u in self.streamers if u.id == user_id), None)

    def on_streamer_changed(self):
        self.load_streams()

    def load_streams(self):
        streamer = self._selected_streamer()
        self.streams = []
        self.streams_table.setRowCount(0)
        self.breaks_table.setRowCount(0)
        self.selected_stream = None

        if streamer is None:
            return

        self.streams = streamer_repo.list_streams(streamer.streamer_database_name, status=STATUS_COMPLETED)

        self.streams_table.setRowCount(len(self.streams))
        for row, stream in enumerate(self.streams):
            self.streams_table.setItem(row, 0, QTableWidgetItem(stream.date or ""))
            self.streams_table.setItem(row, 1, QTableWidgetItem(str(stream.final_stream_gross)))
            self.streams_table.setItem(row, 2, QTableWidgetItem(str(stream.stream_profit)))
            self.streams_table.setItem(row, 3, QTableWidgetItem(str(len(stream.corrections))))
            self.streams_table.item(row, 0).setData(1000, stream.id)

        self.streams_table.resizeColumnsToContents()

    def on_stream_selected(self):
        rows = self.streams_table.selectionModel().selectedRows()
        self.breaks_table.setRowCount(0)
        self.breaks = []
        self.selected_stream = None

        if not rows:
            return

        stream_id = self.streams_table.item(rows[0].row(), 0).data(1000)
        self.selected_stream = next((s for s in self.streams if s.id == stream_id), None)

        if self.selected_stream is None:
            return

        streamer = self._selected_streamer()
        self.breaks = streamer_repo.list_breaks_for_stream(
            streamer.streamer_database_name, self.selected_stream.id, include_deleted=True
        )

        self.breaks_table.setRowCount(len(self.breaks))
        for row, b in enumerate(self.breaks):
            self.breaks_table.setItem(row, 0, QTableWidgetItem(str(b.sequence_number)))
            self.breaks_table.setItem(row, 1, QTableWidgetItem(b.name or ""))
            self.breaks_table.setItem(row, 2, QTableWidgetItem(b.status))
            self.breaks_table.setItem(row, 3, QTableWidgetItem(str(b.break_gross)))
            self.breaks_table.item(row, 0).setData(1000, b.id)

        self.breaks_table.resizeColumnsToContents()

    def _selected_break(self):
        rows = self.breaks_table.selectionModel().selectedRows()

        if not rows:
            return None

        break_id = self.breaks_table.item(rows[0].row(), 0).data(1000)
        return next((b for b in self.breaks if b.id == break_id), None)

    def on_correct_gross(self):
        if self.selected_stream is None:
            self.show_message("Select a completed stream first.", error=True)
            return

        dialog = CorrectFinalGrossDialog(self.selected_stream, self)

        if dialog.exec() != QDialog.Accepted:
            return

        reason = dialog.reason()

        if not reason:
            self.show_message("A reason is required.", error=True)
            return

        streamer = self._selected_streamer()

        try:
            correction_service.correct_final_stream_gross(
                self.selected_stream.id, streamer.id, streamer.streamer_database_name,
                admin_id=self.current_user.id, reason=reason, new_final_stream_gross=dialog.new_gross(),
            )
        except correction_service.CorrectionValidationError as e:
            self.show_message(str(e), error=True)
            return

        self.show_message("Final stream gross corrected.", error=False)
        self.load_streams()

    def on_correct_break(self):
        break_obj = self._selected_break()

        if break_obj is None or self.selected_stream is None:
            self.show_message("Select a break first.", error=True)
            return

        products_by_id = {p.id: p for p in repo.list_products()}
        dialog = CorrectBreakDialog(break_obj, self.selected_stream, products_by_id, self)

        if dialog.exec() != QDialog.Accepted:
            return

        reason = dialog.reason()

        if not reason:
            self.show_message("A reason is required.", error=True)
            return

        raw_changes = dialog.pack_line_changes()
        original_qty_by_product = {line["product_id"]: line["quantity"] for line in break_obj.pack_lines}
        pack_line_changes = {
            pid: qty for pid, qty in raw_changes.items() if qty != original_qty_by_product.get(pid, 0)
        }

        streamer = self._selected_streamer()

        self._submit_correction(streamer, break_obj, pack_line_changes, dialog.new_break_gross(), dialog.historical_prices(), reason, shortage_choice=None)

    def _submit_correction(self, streamer, break_obj, pack_line_changes, new_break_gross, historical_prices, reason, shortage_choice):
        try:
            correction_service.correct_break(
                self.selected_stream.id, streamer.id, streamer.streamer_database_name, break_obj.id,
                admin_id=self.current_user.id, reason=reason,
                pack_line_changes=pack_line_changes or None, new_break_gross=new_break_gross,
                historical_prices=historical_prices, shortage_choice=shortage_choice,
            )
        except correction_service.CorrectionBlockedError as e:
            self.show_message(str(e), error=True)
            return
        except correction_service.CorrectionValidationError as e:
            if "shortage choice" in str(e).lower():
                shortage_dialog = ShortageChoiceDialog(str(e), self)

                if shortage_dialog.exec() != QDialog.Accepted:
                    return

                self._submit_correction(
                    streamer, break_obj, pack_line_changes, new_break_gross, historical_prices, reason,
                    shortage_choice=shortage_dialog.selected_choice(),
                )
                return

            self.show_message(str(e), error=True)
            return

        self.show_message("Break corrected.", error=False)
        self.load_streams()

    def show_message(self, text: str, error: bool):
        self.message_label.setStyleSheet("color: #b00020;" if error else "color: #1a7f37;")
        self.message_label.setText(text)
