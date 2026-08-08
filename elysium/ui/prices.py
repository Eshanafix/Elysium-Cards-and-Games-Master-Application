"""
Shared Sealed Prices screen (LLD section 9, 24; docs/IMPLEMENTATION_PLAN.md
section 6.9). Available to streamers and admins alike.
"""

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from elysium.models.prices import STATUS_AMBIGUOUS, STATUS_UNRESOLVED
from elysium.repositories import price_repository as price_repo
from elysium.services import product_service, pricing_service
from elysium.ui.background import run_worker, safe_callback


class PriceRefreshWorker(QThread):
    finished_success = Signal(str)  # refresh_session_id
    failed = Signal(str)

    def __init__(self, started_by: str):
        super().__init__()
        self.started_by = started_by

    def run(self):
        try:
            session_id = pricing_service.refresh_prices(self.started_by)
            self.finished_success.emit(session_id)
        except Exception as e:
            self.failed.emit(str(e))


class ManualPriceDialog(QDialog):
    def __init__(self, product_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Enter Manual Price: {product_name}")

        layout = QVBoxLayout()

        self.price_input = QLineEdit()
        self.price_input.setPlaceholderText("Price per pack, e.g. 4.25")

        self.note_input = QTextEdit()
        self.note_input.setPlaceholderText("Note (optional)")
        self.note_input.setMaximumHeight(80)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(QLabel("Price per pack (USD):"))
        layout.addWidget(self.price_input)
        layout.addWidget(QLabel("Note:"))
        layout.addWidget(self.note_input)
        layout.addWidget(buttons)

        self.setLayout(layout)


class PricesScreen(QWidget):
    def __init__(self, current_user):
        super().__init__()

        self.current_user = current_user
        self.refresh_worker = None

        layout = QVBoxLayout()

        title = QLabel("Shared Sealed Prices")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")

        button_row = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh Sealed Prices")
        self.refresh_button.clicked.connect(self.start_refresh)
        self.use_previous_button = QPushButton("Use Previous Price")
        self.use_previous_button.clicked.connect(self.use_previous_price)
        self.enter_manual_button = QPushButton("Enter Manual Price")
        self.enter_manual_button.clicked.connect(self.enter_manual_price)

        button_row.addWidget(self.refresh_button)
        button_row.addWidget(self.use_previous_button)
        button_row.addWidget(self.enter_manual_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate -- refresh duration isn't predictable
        self.progress_bar.setVisible(False)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Product", "Raw Loose", "Raw Box", "Resolved Price", "Source", "Status", "Last Refresh"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addLayout(button_row)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table)
        layout.addWidget(self.message_label)

        self.setLayout(layout)

        self.reload_prices()

    def reload_prices(self):
        products = {p.id: p for p in product_service.list_products()}
        prices = price_repo.list_all_current_prices()

        self._rows = []
        for product_id, product in products.items():
            self._rows.append((product, prices.get(product_id)))

        self.table.setRowCount(len(self._rows))

        for row, (product, price) in enumerate(self._rows):
            self.table.setItem(row, 0, QTableWidgetItem(product.name))
            self.table.setItem(row, 1, QTableWidgetItem(self._fmt(price.raw_loose_pack_market_price if price else None)))
            self.table.setItem(row, 2, QTableWidgetItem(self._fmt(price.raw_box_market_price if price else None)))
            self.table.setItem(row, 3, QTableWidgetItem(self._fmt(price.resolved_pack_price if price else None)))
            self.table.setItem(row, 4, QTableWidgetItem(price.resolved_price_source if price else ""))
            self.table.setItem(row, 5, QTableWidgetItem(price.price_status if price else "UNRESOLVED"))
            self.table.setItem(row, 6, QTableWidgetItem(str(price.last_successful_refresh_at) if price and price.last_successful_refresh_at else ""))

        self.table.resizeColumnsToContents()

    @staticmethod
    def _fmt(value) -> str:
        return f"${value:.2f}" if value is not None else ""

    def selected_row(self):
        rows = self.table.selectionModel().selectedRows()

        if not rows:
            return None

        return self._rows[rows[0].row()]

    def start_refresh(self):
        self.refresh_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.summary_label.setText("Refreshing...")

        self.refresh_worker = PriceRefreshWorker(self.current_user.id)
        self.refresh_worker.finished_success.connect(safe_callback(self.on_refresh_finished))
        self.refresh_worker.failed.connect(safe_callback(self.on_refresh_failed))
        run_worker(self.refresh_worker)

    def on_refresh_finished(self, session_id: str):
        self.refresh_button.setEnabled(True)
        self.progress_bar.setVisible(False)

        session = price_repo.find_refresh_session(session_id)

        if session:
            self.summary_label.setText(
                f"Groups requested: {session.get('unique_groups_requested', 0)} | "
                f"Products checked: {session.get('products_checked', 0)} | "
                f"Updated: {session.get('prices_updated', 0)} | "
                f"Unchanged: {session.get('prices_unchanged', 0)} | "
                f"Loose used: {session.get('loose_pack_prices_used', 0)} | "
                f"Box-derived used: {session.get('box_derived_prices_used', 0)} | "
                f"Ambiguous: {session.get('ambiguous_products', 0)} | "
                f"Failed groups: {len(session.get('failed_groups', []))} | "
                f"Started: {session.get('started_at')} | Completed: {session.get('completed_at')}"
            )

        self.reload_prices()

    def on_refresh_failed(self, error: str):
        self.refresh_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.summary_label.setText(f"Refresh failed: {error}")

    def use_previous_price(self):
        selected = self.selected_row()

        if not selected:
            self.show_message("Select a product first.", error=True)
            return

        product, price = selected

        if not price or price.price_status not in (STATUS_UNRESOLVED, STATUS_AMBIGUOUS):
            self.show_message("This product doesn't need resolution.", error=True)
            return

        try:
            pricing_service.accept_previous_price(product.id, self.current_user.id)
        except pricing_service.PriceEntryError as e:
            self.show_message(str(e), error=True)
            return

        self.show_message(f"Previous price accepted for '{product.name}'.", error=False)
        self.reload_prices()

    def enter_manual_price(self):
        selected = self.selected_row()

        if not selected:
            self.show_message("Select a product first.", error=True)
            return

        product, _price = selected
        dialog = ManualPriceDialog(product.name, self)

        if dialog.exec() != QDialog.Accepted:
            return

        try:
            price_value = Decimal(dialog.price_input.text().strip())
        except InvalidOperation:
            self.show_message("Enter a valid price.", error=True)
            return

        pricing_service.enter_manual_price(
            product.id, price_value, self.current_user.id,
            note=dialog.note_input.toPlainText().strip() or None,
        )

        self.show_message(f"Manual price set for '{product.name}'.", error=False)
        self.reload_prices()

    def show_message(self, text: str, error: bool):
        self.message_label.setStyleSheet("color: #b00020;" if error else "color: #1a7f37;")
        self.message_label.setText(text)
