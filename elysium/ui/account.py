"""
Account screen (LLD section 24: available to every logged-in role):
change your own password, and set this machine's display zoom.
"""

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from elysium.models.users import User
from elysium.services import auth_service
from elysium.ui.app_restart import restart_application
from elysium.ui_settings import DEFAULT_SCALE, SCALE_PRESETS, get_display_scale, set_display_scale


class AccountScreen(QWidget):
    def __init__(self, user: User):
        super().__init__()

        self.user = user

        layout = QVBoxLayout()

        title = QLabel(f"Account: {user.username}")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")

        self.current_password_input = QLineEdit()
        self.current_password_input.setPlaceholderText("Current password")
        self.current_password_input.setEchoMode(QLineEdit.Password)

        self.new_password_input = QLineEdit()
        self.new_password_input.setPlaceholderText("New password")
        self.new_password_input.setEchoMode(QLineEdit.Password)

        self.confirm_password_input = QLineEdit()
        self.confirm_password_input.setPlaceholderText("Confirm new password")
        self.confirm_password_input.setEchoMode(QLineEdit.Password)

        self.change_button = QPushButton("Change Password")
        self.change_button.clicked.connect(self.change_password)

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)

        display_title = QLabel("Display")
        display_title.setStyleSheet("font-size: 16px; font-weight: bold;")

        display_row = QHBoxLayout()
        display_row.addWidget(QLabel("Zoom (this computer only):"))

        self.zoom_combo = QComboBox()
        for preset in SCALE_PRESETS:
            self.zoom_combo.addItem(f"{int(preset * 100)}%", preset)
        current_scale = get_display_scale()
        idx = self.zoom_combo.findData(current_scale)
        self.zoom_combo.setCurrentIndex(idx if idx >= 0 else self.zoom_combo.findData(DEFAULT_SCALE))

        self.apply_zoom_button = QPushButton("Apply && Restart")
        self.apply_zoom_button.clicked.connect(self.apply_zoom)

        display_row.addWidget(self.zoom_combo)
        display_row.addWidget(self.apply_zoom_button)
        display_row.addStretch(1)

        layout.addWidget(title)
        layout.addWidget(self.current_password_input)
        layout.addWidget(self.new_password_input)
        layout.addWidget(self.confirm_password_input)
        layout.addWidget(self.change_button)
        layout.addWidget(self.message_label)
        layout.addSpacing(20)
        layout.addWidget(display_title)
        layout.addLayout(display_row)
        layout.addStretch()

        self.setLayout(layout)

    def apply_zoom(self):
        new_scale = self.zoom_combo.currentData()

        if new_scale == get_display_scale():
            return

        confirm = QMessageBox.question(
            self, "Restart Required",
            f"Set display zoom to {int(new_scale * 100)}% and restart the app now to apply it?",
        )

        if confirm != QMessageBox.Yes:
            return

        set_display_scale(new_scale)
        restart_application()

    def change_password(self):
        self.message_label.setStyleSheet("color: #ff6b6b;")

        current = self.current_password_input.text()
        new = self.new_password_input.text()
        confirm = self.confirm_password_input.text()

        if not current or not new:
            self.message_label.setText("Fill in all fields.")
            return

        if new != confirm:
            self.message_label.setText("New password and confirmation do not match.")
            return

        try:
            auth_service.change_own_password(self.user, current, new)
        except auth_service.InvalidCredentialsError as e:
            self.message_label.setText(str(e))
            return
        except Exception as e:
            self.message_label.setText(f"Password change failed: {e}")
            return

        self.current_password_input.clear()
        self.new_password_input.clear()
        self.confirm_password_input.clear()
        self.message_label.setStyleSheet("color: #4caf50;")
        self.message_label.setText("Password changed.")
