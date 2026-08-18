"""
Admin Users screen (LLD section 7.1, 24.3): create accounts, reset
passwords, disable accounts. Disabling a streamer with assigned inventory
correctly redirects instead of disabling (plan section 4.8) -- the
Decommissioning workflow itself is Phase 6, so today that just means the
admin sees a clear message instead of the account silently staying enabled
or being disabled incorrectly.
"""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from elysium.models.users import ROLE_ADMIN, ROLE_STREAMER
from elysium.repositories import master_repository as repo
from elysium.services import auth_service, decommission_service
from elysium.ui.table_scaling import make_columns_stretch, resize_columns_to_contents


class CreateUserDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create User")

        layout = QVBoxLayout()

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)

        self.admin_checkbox = QCheckBox("Admin")
        self.streamer_checkbox = QCheckBox("Streamer")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(QLabel("New account details:"))
        layout.addWidget(self.username_input)
        layout.addWidget(self.password_input)
        layout.addWidget(self.admin_checkbox)
        layout.addWidget(self.streamer_checkbox)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def selected_roles(self) -> list[str]:
        roles = []

        if self.admin_checkbox.isChecked():
            roles.append(ROLE_ADMIN)

        if self.streamer_checkbox.isChecked():
            roles.append(ROLE_STREAMER)

        return roles


class ResetPasswordDialog(QDialog):
    def __init__(self, username: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Reset Password: {username}")

        layout = QVBoxLayout()

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("New password")
        self.password_input.setEchoMode(QLineEdit.Password)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(QLabel(f"New password for {username}:"))
        layout.addWidget(self.password_input)
        layout.addWidget(buttons)

        self.setLayout(layout)


class UsersScreen(QWidget):
    def __init__(self, current_user):
        super().__init__()

        self.current_user = current_user
        self._columns_sized = False

        layout = QVBoxLayout()

        title = QLabel("Users")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")

        button_row = QHBoxLayout()
        self.create_button = QPushButton("Create User")
        self.create_button.clicked.connect(self.open_create_dialog)
        self.reset_password_button = QPushButton("Reset Password")
        self.reset_password_button.clicked.connect(self.reset_selected_password)
        self.disable_button = QPushButton("Disable Account")
        self.disable_button.clicked.connect(self.disable_selected_account)

        button_row.addWidget(self.create_button)
        button_row.addWidget(self.reset_password_button)
        button_row.addWidget(self.disable_button)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Username", "Roles", "Active", "Decommission Status"])
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

        self.reload_users()

    def reload_users(self):
        users = repo.list_users()

        self.table.setRowCount(len(users))

        for row, user in enumerate(users):
            self.table.setItem(row, 0, QTableWidgetItem(user.username))
            self.table.setItem(row, 1, QTableWidgetItem(", ".join(user.roles)))
            self.table.setItem(row, 2, QTableWidgetItem("Yes" if user.is_active else "No"))
            self.table.setItem(row, 3, QTableWidgetItem(user.decommission_status or ""))
            self.table.item(row, 0).setData(1000, user.id)

        # Only auto-size once -- creating/disabling/resetting a user calls
        # reload_users() again, and resizing on every call would keep
        # undoing a manually-widened column.
        if not self._columns_sized:
            resize_columns_to_contents(self.table)
            self._columns_sized = True

    def selected_user(self):
        rows = self.table.selectionModel().selectedRows()

        if not rows:
            return None

        row = rows[0].row()
        user_id = self.table.item(row, 0).data(1000)
        username = self.table.item(row, 0).text()
        return user_id, username

    def open_create_dialog(self):
        dialog = CreateUserDialog(self)

        if dialog.exec() != QDialog.Accepted:
            return

        username = dialog.username_input.text().strip()
        password = dialog.password_input.text()
        roles = dialog.selected_roles()

        if not username or not password:
            self.show_message("Username and password are required.", error=True)
            return

        if not roles:
            self.show_message("Select at least one role.", error=True)
            return

        try:
            auth_service.create_user(username, password, roles, created_by=self.current_user.id)
        except auth_service.UsernameTakenError as e:
            self.show_message(str(e), error=True)
            return
        except Exception as e:
            self.show_message(f"Could not create user: {e}", error=True)
            return

        self.show_message(f"User '{username}' created.", error=False)
        self.reload_users()

    def reset_selected_password(self):
        selected = self.selected_user()

        if not selected:
            self.show_message("Select a user first.", error=True)
            return

        user_id, username = selected
        dialog = ResetPasswordDialog(username, self)

        if dialog.exec() != QDialog.Accepted:
            return

        new_password = dialog.password_input.text()

        if not new_password:
            self.show_message("Enter a new password.", error=True)
            return

        auth_service.reset_password(user_id, new_password, reset_by=self.current_user.id)
        self.show_message(f"Password reset for '{username}'.", error=False)

    def disable_selected_account(self):
        selected = self.selected_user()

        if not selected:
            self.show_message("Select a user first.", error=True)
            return

        user_id, username = selected

        confirm = QMessageBox.question(
            self, "Disable Account", f"Disable '{username}'?",
        )

        if confirm != QMessageBox.Yes:
            return

        try:
            outcome = auth_service.disable_account(user_id, requested_by=self.current_user.id)
        except auth_service.ActiveStreamLockError as e:
            self.show_message(str(e), error=True)
            return
        except Exception as e:
            self.show_message(f"Could not disable account: {e}", error=True)
            return

        if outcome == auth_service.DisableOutcome.REQUIRES_DECOMMISSION:
            self._redirect_to_decommissioning(user_id, username)
            return

        self.show_message(f"'{username}' disabled.", error=False)
        self.reload_users()

    def _redirect_to_decommissioning(self, user_id: str, username: str):
        redirect = QMessageBox.question(
            self, "Decommissioning Required",
            f"'{username}' holds assigned inventory and cannot be disabled directly.\n\n"
            "Disabling this account requires Decommissioning: a pending request will be "
            "created with a snapshot of their current allocation, for an admin to review "
            "and approve on the Decommissioning screen. Login is only disabled once that "
            "approval completes.\n\n"
            "Initiate decommissioning now?",
        )

        if redirect != QMessageBox.Yes:
            return

        try:
            decommission_service.initiate(user_id, initiated_by=self.current_user.id)
        except decommission_service.DecommissionValidationError as e:
            self.show_message(str(e), error=True)
            return
        except decommission_service.ActiveStreamLockError as e:
            self.show_message(str(e), error=True)
            return

        self.show_message(
            f"Decommissioning initiated for '{username}' -- review and approve it on the "
            "Decommissioning screen to finish disabling the account.",
            error=False,
        )
        self.reload_users()

    def show_message(self, text: str, error: bool):
        self.message_label.setStyleSheet("color: #ff6b6b;" if error else "color: #4caf50;")
        self.message_label.setText(text)
