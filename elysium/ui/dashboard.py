"""
Dashboard (LLD section 24.4). Shows the indicators that are actually real
right now (connection, current user/role, global lock state) -- the rest
of the required indicator list (pending decommissions, discrepancies,
etc.) gets added here as each phase that produces that data is built,
rather than showing placeholder/fake values now.
"""

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from elysium.models.users import ROLE_ADMIN, ROLE_STREAMER, User
from elysium.services import dashboard_service, factory_reset_service, lock_service, mongo_client, stream_service

FACTORY_RESET_CONFIRMATION_PHRASE = "WIPE ALL DATA"


def _format_margin(margin) -> str:
    return f"{margin * 100:.1f}%" if margin is not None else "N/A"


def _format_money(amount) -> str:
    return f"${amount:.2f}" if amount is not None else "N/A"


class StatTile(QFrame):
    """A small "cool widget" stat card -- title + big value."""

    def __init__(self, title: str, value: str):
        super().__init__()

        self.setStyleSheet("""
            QFrame { background-color: #f5f5f5; border: 1px solid #cccccc; border-radius: 8px; padding: 10px; }
            QLabel { background-color: transparent; border: none; color: #1a1a1a; }
        """)

        layout = QVBoxLayout()

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 12px; font-weight: 600; color: #555555;")

        self.value_label = QLabel(value)
        self.value_label.setStyleSheet("font-size: 22px; font-weight: bold; color: #1a1a1a;")

        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        self.setLayout(layout)

    def set_value(self, value: str):
        self.value_label.setText(value)


class ForceCancelDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Force Cancel Active Stream")

        layout = QVBoxLayout()

        self.reason_input = QTextEdit()
        self.reason_input.setPlaceholderText("Reason (required)")
        self.reason_input.setMaximumHeight(80)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(QLabel(
            "This releases the global stream lock and marks the active stream canceled. "
            "No inventory is deducted. Use only when the original streamer cannot return (LLD 16.4)."
        ))
        layout.addWidget(QLabel("Reason:"))
        layout.addWidget(self.reason_input)
        layout.addWidget(buttons)

        self.setLayout(layout)


class RecoverRefreshLockDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recover Price Refresh Lock")

        layout = QVBoxLayout()

        self.reason_input = QTextEdit()
        self.reason_input.setPlaceholderText("Reason (required)")
        self.reason_input.setMaximumHeight(80)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(QLabel(
            "This clears only the stuck price-refresh sub-state (plan section 4.4) -- it never "
            "touches an active stream lock. Use only when a refresh session is clearly dead "
            "(app crashed/killed mid-refresh, no progress for a long time)."
        ))
        layout.addWidget(QLabel("Reason:"))
        layout.addWidget(self.reason_input)
        layout.addWidget(buttons)

        self.setLayout(layout)


class FactoryResetPhraseDialog(QDialog):
    """Third and final confirmation -- typing the exact phrase is a much
    stronger guard against an accidental click than a third Yes/No box
    would be (muscle memory clicks through those easily)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Final Confirmation: Factory Reset")

        layout = QVBoxLayout()
        layout.addWidget(QLabel(
            "This is the last confirmation. Factory reset cannot be undone.\n\n"
            f'Type "{FACTORY_RESET_CONFIRMATION_PHRASE}" exactly to enable the reset button.'
        ))

        self.phrase_input = QLineEdit()
        layout.addWidget(self.phrase_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.Ok)
        self.ok_button.setEnabled(False)
        self.ok_button.setText("Wipe Everything")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.phrase_input.textChanged.connect(self._on_text_changed)

        layout.addWidget(buttons)
        self.setLayout(layout)

    def _on_text_changed(self, text: str):
        self.ok_button.setEnabled(text.strip() == FACTORY_RESET_CONFIRMATION_PHRASE)


class DashboardScreen(QWidget):
    def __init__(self, user: User, on_logout=None):
        super().__init__()

        self.user = user
        self.on_logout = on_logout

        layout = QVBoxLayout()

        title = QLabel(f"Welcome, {user.username}")
        title.setStyleSheet("font-size: 22px; font-weight: bold;")

        self.role_label = QLabel(f"Role: {', '.join(user.roles) or '(none)'}")
        self.connection_label = QLabel()
        self.lock_label = QLabel()

        self.force_cancel_button = QPushButton("Force Cancel Active Stream")
        self.force_cancel_button.clicked.connect(self.force_cancel)
        self.force_cancel_button.setVisible(False)

        self.recover_refresh_lock_button = QPushButton("Recover Price Refresh Lock")
        self.recover_refresh_lock_button.clicked.connect(self.recover_refresh_lock)
        self.recover_refresh_lock_button.setVisible(False)

        # --- Company-wide stats (admin) ---
        self.admin_stats_title = QLabel("Company Stats")
        self.admin_stats_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #1a1a1a; margin-top: 16px; margin-bottom: 4px;")

        self.total_packs_tile = StatTile("Total Packs", "—")
        self.total_value_tile = StatTile("Total Pack Value", "—")
        self.overall_margin_tile = StatTile("Overall Profit Margin", "—")

        admin_stats_row = QHBoxLayout()
        admin_stats_row.addWidget(self.total_packs_tile)
        admin_stats_row.addWidget(self.total_value_tile)
        admin_stats_row.addWidget(self.overall_margin_tile)
        self.admin_stats_container = QWidget()
        self.admin_stats_container.setLayout(admin_stats_row)

        # --- Personal stats (streamer) ---
        self.streamer_stats_title = QLabel("Your Stats")
        self.streamer_stats_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #1a1a1a; margin-top: 16px; margin-bottom: 4px;")

        # All-time by default; the checkbox opts into truncating by a
        # specific date range instead (start/end dates default to the
        # last month purely as a sane starting point once enabled).
        self.date_filter_checkbox = QCheckBox("Filter by date range (unchecked = all time)")
        self.date_filter_checkbox.stateChanged.connect(self._on_date_filter_toggled)

        self.date_from_input = QDateEdit(QDate.currentDate().addMonths(-1))
        self.date_from_input.setCalendarPopup(True)
        self.date_from_input.setEnabled(False)

        self.date_to_input = QDateEdit(QDate.currentDate())
        self.date_to_input.setCalendarPopup(True)
        self.date_to_input.setEnabled(False)

        self.apply_date_filter_button = QPushButton("Apply")
        self.apply_date_filter_button.clicked.connect(self._refresh_stats)
        self.apply_date_filter_button.setEnabled(False)

        date_filter_row = QHBoxLayout()
        date_filter_row.addWidget(self.date_filter_checkbox)
        date_filter_row.addWidget(QLabel("From:"))
        date_filter_row.addWidget(self.date_from_input)
        date_filter_row.addWidget(QLabel("To:"))
        date_filter_row.addWidget(self.date_to_input)
        date_filter_row.addWidget(self.apply_date_filter_button)
        date_filter_row.addStretch(1)
        self.date_filter_container = QWidget()
        self.date_filter_container.setLayout(date_filter_row)

        self.stream_count_tile = StatTile("Streams", "—")
        self.avg_stream_gross_tile = StatTile("Avg Stream Gross", "—")
        self.avg_stream_profit_tile = StatTile("Avg Stream Profit", "—")
        self.streamer_profit_margin_tile = StatTile("Profit Margin", "—")

        self.break_count_tile = StatTile("Breaks", "—")
        self.avg_break_gross_tile = StatTile("Avg Break Gross", "—")
        self.avg_break_profit_tile = StatTile("Avg Break Profit", "—")

        streamer_stats_row1 = QHBoxLayout()
        streamer_stats_row1.addWidget(self.stream_count_tile)
        streamer_stats_row1.addWidget(self.avg_stream_gross_tile)
        streamer_stats_row1.addWidget(self.avg_stream_profit_tile)
        streamer_stats_row1.addWidget(self.streamer_profit_margin_tile)

        streamer_stats_row2 = QHBoxLayout()
        streamer_stats_row2.addWidget(self.break_count_tile)
        streamer_stats_row2.addWidget(self.avg_break_gross_tile)
        streamer_stats_row2.addWidget(self.avg_break_profit_tile)

        streamer_stats_layout = QVBoxLayout()
        streamer_stats_layout.addLayout(streamer_stats_row1)
        streamer_stats_layout.addLayout(streamer_stats_row2)
        self.streamer_stats_container = QWidget()
        self.streamer_stats_container.setLayout(streamer_stats_layout)

        self.danger_zone_label = QLabel("Danger Zone")
        self.danger_zone_label.setStyleSheet("font-weight: bold; color: #b00020; margin-top: 12px;")

        self.factory_reset_button = QPushButton("Factory Reset (Wipe All Data)")
        self.factory_reset_button.setStyleSheet(
            "QPushButton { background-color: #b00020; color: white; font-weight: bold; padding: 6px; }"
        )
        self.factory_reset_button.clicked.connect(self.factory_reset)

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(self.role_label)
        layout.addWidget(self.connection_label)
        layout.addWidget(self.lock_label)

        if ROLE_ADMIN in user.roles:
            layout.addWidget(self.force_cancel_button)
            layout.addWidget(self.recover_refresh_lock_button)
            layout.addWidget(self.admin_stats_title)
            layout.addWidget(self.admin_stats_container)

        if ROLE_STREAMER in user.roles:
            layout.addWidget(self.streamer_stats_title)
            layout.addWidget(self.date_filter_container)
            layout.addWidget(self.streamer_stats_container)

        # Factory Reset is deliberately the very last thing on the screen,
        # below every stat widget -- a destructive admin action shouldn't
        # sit near the top where it competes for attention with routine
        # status/stats.
        if ROLE_ADMIN in user.roles:
            layout.addWidget(self.danger_zone_label)
            layout.addWidget(self.factory_reset_button)

        layout.addWidget(self.message_label)
        layout.addStretch()

        self.setLayout(layout)

        self.refresh()

    def refresh(self):
        status = mongo_client.check_connection()

        if status.is_connected:
            self.connection_label.setText("MongoDB: connected")
            self.connection_label.setStyleSheet("color: #1a7f37;")
            self._refresh_lock_status()
            self._refresh_stats()
        else:
            self.connection_label.setText(f"MongoDB: unavailable ({status.detail})")
            self.connection_label.setStyleSheet("color: #b00020;")
            self.lock_label.setText("")
            self.force_cancel_button.setVisible(False)
            self.recover_refresh_lock_button.setVisible(False)

    def _refresh_stats(self):
        if ROLE_ADMIN in self.user.roles:
            summary = dashboard_service.get_admin_summary()
            self.total_packs_tile.set_value(str(summary["total_packs"]))
            self.total_value_tile.set_value(f"${summary['total_value']:.2f}")
            self.overall_margin_tile.set_value(_format_margin(summary["overall_profit_margin"]))

        if ROLE_STREAMER in self.user.roles and self.user.streamer_database_name:
            start_date, end_date = self._current_date_range()
            stats = dashboard_service.get_streamer_stats(self.user.streamer_database_name, start_date, end_date)
            self.stream_count_tile.set_value(str(stats["stream_count"]))
            self.avg_stream_gross_tile.set_value(_format_money(stats["avg_stream_gross"]))
            self.avg_stream_profit_tile.set_value(_format_money(stats["avg_stream_profit"]))
            self.streamer_profit_margin_tile.set_value(_format_margin(stats["profit_margin"]))
            self.break_count_tile.set_value(str(stats["break_count"]))
            self.avg_break_gross_tile.set_value(_format_money(stats["avg_break_gross"]))
            self.avg_break_profit_tile.set_value(_format_money(stats["avg_break_profit"]))

    def _current_date_range(self):
        if not self.date_filter_checkbox.isChecked():
            return None, None
        return self.date_from_input.date().toPython(), self.date_to_input.date().toPython()

    def _on_date_filter_toggled(self, _state):
        enabled = self.date_filter_checkbox.isChecked()
        self.date_from_input.setEnabled(enabled)
        self.date_to_input.setEnabled(enabled)
        self.apply_date_filter_button.setEnabled(enabled)
        self._refresh_stats()

    def _refresh_lock_status(self):
        try:
            lock = lock_service.get_lock_state()
        except RuntimeError:
            self.lock_label.setText("")
            return

        if lock.get("stream_active"):
            self.lock_label.setText(
                f"Active stream: streamer {lock.get('streamer_id')}, started {lock.get('stream_started_at')}. "
                "Shared sealed prices cannot be refreshed."
            )
            self.force_cancel_button.setVisible(ROLE_ADMIN in self.user.roles)
            self.recover_refresh_lock_button.setVisible(False)
        elif lock.get("price_refresh_active"):
            self.lock_label.setText(
                f"A shared price refresh is in progress (started by {lock.get('refresh_started_by')} "
                f"at {lock.get('refresh_started_at')})."
            )
            self.force_cancel_button.setVisible(False)
            self.recover_refresh_lock_button.setVisible(ROLE_ADMIN in self.user.roles)
        else:
            self.lock_label.setText("No active stream. Shared sealed prices can be refreshed.")
            self.force_cancel_button.setVisible(False)
            self.recover_refresh_lock_button.setVisible(False)

    def force_cancel(self):
        dialog = ForceCancelDialog(self)

        if dialog.exec() != QDialog.Accepted:
            return

        reason = dialog.reason_input.toPlainText().strip()

        if not reason:
            QMessageBox.warning(self, "Reason required", "A reason is required to force-cancel a stream.")
            return

        try:
            stream_service.force_cancel_stream(self.user.id, reason)
        except stream_service.StreamValidationError as e:
            self.message_label.setStyleSheet("color: #b00020;")
            self.message_label.setText(str(e))
            return

        self.message_label.setStyleSheet("color: #1a7f37;")
        self.message_label.setText("Active stream force-canceled.")
        self.refresh()

    def recover_refresh_lock(self):
        dialog = RecoverRefreshLockDialog(self)

        if dialog.exec() != QDialog.Accepted:
            return

        reason = dialog.reason_input.toPlainText().strip()

        if not reason:
            QMessageBox.warning(self, "Reason required", "A reason is required to recover the price refresh lock.")
            return

        lock_service.recover_stuck_price_refresh_lock(self.user.id, reason)

        self.message_label.setStyleSheet("color: #1a7f37;")
        self.message_label.setText("Price refresh lock recovered.")
        self.refresh()

    def factory_reset(self):
        first = QMessageBox.warning(
            self, "Factory Reset -- Are You Sure? (1/3)",
            "This permanently deletes ALL data: every user account (including admins), every "
            "product, all inventory, every stream and break, all audit history, discrepancies, "
            "decommission requests, all shared prices, and every streamer's own database.\n\n"
            "This cannot be undone.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )

        if first != QMessageBox.Yes:
            return

        second = QMessageBox.warning(
            self, "Factory Reset -- Are You Sure? (2/3)",
            "Really sure? Your own account will be deleted along with everyone else's -- you "
            "will be logged out immediately once this completes, and will need to run "
            "create_admin.py again to log back in, exactly like a brand new install.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )

        if second != QMessageBox.Yes:
            return

        phrase_dialog = FactoryResetPhraseDialog(self)

        if phrase_dialog.exec() != QDialog.Accepted:
            return

        try:
            summary = factory_reset_service.wipe_all_data(confirmed_by=self.user.id)
        except Exception as e:
            QMessageBox.critical(self, "Factory Reset Failed", f"An error occurred: {e}")
            return

        QMessageBox.information(
            self, "Factory Reset Complete",
            f"All data wiped. {len(summary['dropped_databases'])} streamer database(s) dropped.\n\n"
            "You will now be logged out. Run create_admin.py to create the first admin again.",
        )

        if self.on_logout:
            self.on_logout()
