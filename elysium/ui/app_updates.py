"""
Admin-only screen for publishing the mandatory-update gate that
elysium.ui.login checks on every login (elysium.services.update_service).
Publishing a version higher than a build's baked-in elysium.version.
APP_VERSION blocks that build from logging in until it's replaced.
"""

from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from elysium.models.users import User
from elysium.services import update_service
from elysium.version import APP_VERSION


class AppUpdatesScreen(QWidget):
    def __init__(self, user: User):
        super().__init__()

        self.user = user

        layout = QVBoxLayout()

        title = QLabel("App Updates")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")

        self.installed_version_label = QLabel(f"This machine's installed version: v{APP_VERSION}")

        self.current_required_label = QLabel()

        layout.addWidget(title)
        layout.addWidget(self.installed_version_label)
        layout.addWidget(self.current_required_label)

        explanation = QLabel(
            "Publishing a required version higher than a streamer's installed build blocks "
            "their login with a prompt to download the new installer -- there's no way past it "
            "until they install the update and reopen the app."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        layout.addWidget(QLabel("Required version (e.g. 1.1.0):"))
        self.version_input = QLineEdit()
        layout.addWidget(self.version_input)

        layout.addWidget(QLabel("Download URL (e.g. the GitHub release page or installer asset link):"))
        self.download_url_input = QLineEdit()
        layout.addWidget(self.download_url_input)

        layout.addWidget(QLabel("Release notes (optional, shown on the update prompt):"))
        self.release_notes_input = QTextEdit()
        self.release_notes_input.setMaximumHeight(100)
        layout.addWidget(self.release_notes_input)

        self.publish_button = QPushButton("Publish Required Version")
        self.publish_button.clicked.connect(self.publish)
        layout.addWidget(self.publish_button)

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        layout.addStretch()

        self.setLayout(layout)

        self.reload()

    def reload(self):
        config = update_service.get_update_config()
        self.current_required_label.setText(
            f"Currently published required version: v{config['required_version']}"
            + (f" -- {config['download_url']}" if config["download_url"] else "")
        )
        self.version_input.setText(config["required_version"])
        self.download_url_input.setText(config["download_url"])
        self.release_notes_input.setPlainText(config["release_notes"])

    def publish(self):
        self.message_label.setStyleSheet("color: #b00020;")

        version = self.version_input.text().strip()
        download_url = self.download_url_input.text().strip()
        release_notes = self.release_notes_input.toPlainText().strip()

        confirm = QMessageBox.question(
            self, "Publish Required Version",
            f"This immediately blocks any build below v{version} from logging in until it's "
            "updated. Continue?",
        )

        if confirm != QMessageBox.Yes:
            return

        try:
            update_service.publish_required_version(version, download_url, release_notes, self.user.id)
        except ValueError as e:
            self.message_label.setText(str(e))
            return

        self.message_label.setStyleSheet("color: #1a7f37;")
        self.message_label.setText("Required version published.")
        self.reload()
