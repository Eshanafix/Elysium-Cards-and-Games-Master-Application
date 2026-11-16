"""
Login screen (LLD section 6). Shown first whenever the application opens.
"""

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from elysium.config import APP_NAME
from elysium.security import credential_store
from elysium.services import auth_service, mongo_client, self_update_service, update_service
from elysium.ui.background import run_worker, safe_callback
from elysium.version import APP_VERSION


class DatabaseConnectionDialog(QDialog):
    """A packaged installer build ships with no .env and nothing pre-seeded
    in Windows Credential Manager, so the very first launch on a new
    machine has no MongoDB URI at all (config.resolve_mongodb_uri() falls
    through to ""). This is the one-time setup flow that fills that in --
    validated against a throwaway client before it's saved, then cached in
    Credential Manager so it's never asked for again on this machine."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Database Connection")

        layout = QVBoxLayout()

        message = QLabel(
            "Paste the MongoDB Atlas connection string for this app. It's stored securely "
            "in Windows Credential Manager on this machine only, and won't be asked for again."
        )
        message.setWordWrap(True)
        layout.addWidget(message)

        self.uri_input = QLineEdit()
        self.uri_input.setPlaceholderText("mongodb+srv://user:password@cluster.mongodb.net/?retryWrites=true&w=majority")
        layout.addWidget(self.uri_input)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.test_and_save_button = QPushButton("Test && Save")
        self.test_and_save_button.clicked.connect(self.test_and_save)
        layout.addWidget(self.test_and_save_button)

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        layout.addWidget(cancel_button)

        self.setLayout(layout)

    def test_and_save(self):
        uri = self.uri_input.text().strip()

        if not uri:
            self.status_label.setStyleSheet("color: #ff6b6b;")
            self.status_label.setText("Enter a connection string.")
            return

        self.status_label.setStyleSheet("color: #aaaaaa;")
        self.status_label.setText("Testing connection...")
        self.test_and_save_button.setEnabled(False)
        self.repaint()

        status = mongo_client.test_connection_string(uri)
        self.test_and_save_button.setEnabled(True)

        if not status.is_connected:
            self.status_label.setStyleSheet("color: #ff6b6b;")
            self.status_label.setText(f"Could not connect: {status.detail}")
            return

        credential_store.set_stored_mongodb_uri(uri)
        self.accept()


class SelfUpdateWorker(QThread):
    """Downloads the installer only -- launching it and quitting the app
    happen back on the main thread (MandatoryUpdateDialog.on_download_
    finished) rather than here, since starting a detached process and
    then tearing down the whole QApplication is the kind of thing that
    should happen from the thread Qt already considers "the" main one,
    not a worker."""

    progress = Signal(int)
    finished_success = Signal(str)  # installer_path
    failed = Signal(str)

    def __init__(self, download_url: str, version: str, expected_sha256: str):
        super().__init__()
        self.download_url = download_url
        self.version = version
        self.expected_sha256 = expected_sha256

    def run(self):
        try:
            def on_progress(downloaded, total):
                self.progress.emit(int(downloaded / total * 100))

            installer_path = self_update_service.download_installer(
                self.download_url, self.version, self.expected_sha256 or None, progress_callback=on_progress,
            )
            self.finished_success.emit(str(installer_path))
        except self_update_service.SelfUpdateError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(f"Unexpected error: {e}")


class MandatoryUpdateDialog(QDialog):
    """No "continue anyway" option by design -- update_service.
    is_update_required() gates the login itself, so the only way past this
    dialog is to actually install the new build and relaunch.

    "Update Now" downloads the installer itself and runs it fully silently
    (self_update_service) -- no Downloads folder, no manual double-click,
    no relaunching the app by hand. "Download Manually" (the old behavior:
    open the release page in a browser) stays as a fallback in case the
    in-app path fails for some reason (no network from Python specifically,
    antivirus interference, etc.)."""

    def __init__(self, required_version: str, download_url: str, release_notes: str, sha256: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update Required")
        self.required_version = required_version
        self.download_url = download_url
        self.sha256 = sha256
        self._worker = None

        layout = QVBoxLayout()

        message = QLabel(
            f"A required update (v{required_version}) is available. You must install it "
            f"before you can log in. You're currently on v{APP_VERSION}."
        )
        message.setWordWrap(True)
        layout.addWidget(message)

        if release_notes:
            notes = QLabel(release_notes)
            notes.setWordWrap(True)
            notes.setStyleSheet("color: #aaaaaa;")
            layout.addWidget(notes)

        self.update_now_button = QPushButton("Update Now")
        self.update_now_button.setEnabled(bool(download_url))
        self.update_now_button.clicked.connect(self.start_self_update)
        layout.addWidget(self.update_now_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.download_button = QPushButton("Download Manually Instead")
        self.download_button.setEnabled(bool(download_url))
        self.download_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(download_url)))
        layout.addWidget(self.download_button)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        layout.addWidget(self.close_button)

        self.setLayout(layout)

    def start_self_update(self):
        self.update_now_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_label.setStyleSheet("")
        self.status_label.setText("Downloading update...")

        self._worker = SelfUpdateWorker(self.download_url, self.required_version, self.sha256)
        self._worker.progress.connect(safe_callback(self.progress_bar.setValue))
        self._worker.finished_success.connect(safe_callback(self.on_download_finished))
        self._worker.failed.connect(safe_callback(self.on_download_failed))
        run_worker(self._worker)

    def on_download_finished(self, installer_path: str):
        self.status_label.setText("Installing update...")

        try:
            self_update_service.launch_silent_install(installer_path)
        except self_update_service.SelfUpdateError as e:
            self.on_download_failed(str(e))
            return

        # The installer's own CloseApplications=yes will also close this
        # process if it's still running by the time it gets there, but
        # quitting cleanly ourselves right away is the more graceful path
        # -- same shape as elysium/ui/app_restart.py's display-scale restart.
        QApplication.quit()

    def on_download_failed(self, error: str):
        self.update_now_button.setEnabled(True)
        self.download_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setStyleSheet("color: #ff6b6b;")
        self.status_label.setText(f"Update failed: {error} You can still download and run it manually below.")


class LoginScreen(QWidget):
    guest_requested = Signal()
    login_succeeded = Signal(object)  # elysium.models.users.User

    def __init__(self):
        super().__init__()

        layout = QVBoxLayout()

        self.title = QLabel(APP_NAME)
        self.title.setStyleSheet("font-size: 24px; font-weight: bold;")

        self.version_label = QLabel(f"v{APP_VERSION}")
        self.version_label.setStyleSheet("color: #999999; font-size: 11px;")

        self.connection_status_label = QLabel()

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.returnPressed.connect(self.attempt_login)

        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self.attempt_login)

        self.retry_connection_button = QPushButton("Retry Connection")
        self.retry_connection_button.clicked.connect(self.refresh_connection_status)

        self.configure_connection_button = QPushButton("Configure Database Connection")
        self.configure_connection_button.clicked.connect(self.configure_connection)

        self.guest_button = QPushButton("Continue as Guest")
        self.guest_button.clicked.connect(self.guest_requested.emit)

        self.login_error_label = QLabel()
        self.login_error_label.setWordWrap(True)
        self.login_error_label.setStyleSheet("color: #ff6b6b;")

        layout.addWidget(self.title)
        layout.addWidget(self.version_label)
        layout.addWidget(self.connection_status_label)
        layout.addWidget(self.username_input)
        layout.addWidget(self.password_input)
        layout.addWidget(self.login_button)
        layout.addWidget(self.login_error_label)
        layout.addWidget(self.retry_connection_button)
        layout.addWidget(self.configure_connection_button)
        layout.addWidget(self.guest_button)
        layout.addStretch()

        self.setLayout(layout)

        self.refresh_connection_status()

    def refresh_connection_status(self):
        mongo_client.reset_client()
        status = mongo_client.check_connection()

        if status.is_connected:
            self.connection_status_label.setText("MongoDB: connected")
            self.connection_status_label.setStyleSheet("color: #4caf50;")
        else:
            self.connection_status_label.setText(f"MongoDB: unavailable ({status.detail})")
            self.connection_status_label.setStyleSheet("color: #ff6b6b;")

    def configure_connection(self):
        dialog = DatabaseConnectionDialog(self)

        if dialog.exec() == QDialog.Accepted:
            mongo_client.reset_client()
            self.refresh_connection_status()

    def attempt_login(self):
        self.login_error_label.setText("")

        username = self.username_input.text().strip()
        password = self.password_input.text()

        if not username or not password:
            self.login_error_label.setText("Enter a username and password.")
            return

        status = mongo_client.check_connection()

        if not status.is_connected:
            self.login_error_label.setText(
                "Cannot log in: the shared database is unavailable "
                f"({status.detail}). You can continue as a guest, or press Retry Connection."
            )
            return

        try:
            user = auth_service.login(username, password)
        except auth_service.InvalidCredentialsError:
            self.login_error_label.setText("Incorrect username or password.")
            return
        except auth_service.AccountDisabledError:
            self.login_error_label.setText("This account has been disabled. Contact an admin.")
            return
        except Exception as e:
            self.login_error_label.setText(f"Login failed: {e}")
            return

        self.password_input.clear()

        if update_service.is_update_required():
            config = update_service.get_update_config()
            dialog = MandatoryUpdateDialog(
                config["required_version"], config["download_url"], config["release_notes"],
                sha256=config["sha256"], parent=self,
            )
            dialog.exec()
            return

        self.login_succeeded.emit(user)
