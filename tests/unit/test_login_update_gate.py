"""
Regression tests: a mandatory update blocks login_succeeded from firing and
shows a MandatoryUpdateDialog instead, while a login on a current build
proceeds normally. Also covers the in-app self-update flow (docs feedback:
manually downloading from a browser, clicking through SmartScreen, and
relaunching by hand was the single biggest point of friction in this app)
-- "Update Now" downloads and launches the installer itself; "Download
Manually Instead" is the old browser-opening behavior, kept as a fallback.
"""

from PySide6.QtCore import QThread, Signal

from elysium.models.users import User
from elysium.services import auth_service, self_update_service
from elysium.ui import login


def make_screen(qtbot, monkeypatch, update_required: bool):
    monkeypatch.setattr(login.mongo_client, "reset_client", lambda: None)
    monkeypatch.setattr(
        login.mongo_client, "check_connection",
        lambda: type("S", (), {"is_connected": True, "detail": "ok"})(),
    )

    user = User(id="u1", username="alice", password_hash="x", roles=["streamer"])
    monkeypatch.setattr(login.auth_service, "login", lambda username, password: user)
    monkeypatch.setattr(login.update_service, "is_update_required", lambda: update_required)
    monkeypatch.setattr(
        login.update_service, "get_update_config",
        lambda: {
            "required_version": "999.0.0", "download_url": "https://example.com/setup.exe",
            "release_notes": "Fixed a bug.", "sha256": "abc123",
        },
    )
    monkeypatch.setattr(login.MandatoryUpdateDialog, "exec", lambda self: login.QDialog.Accepted)

    screen = login.LoginScreen()
    qtbot.addWidget(screen)
    screen.username_input.setText("alice")
    screen.password_input.setText("hunter2")
    return screen, user


def test_login_blocked_when_update_required(qtbot, monkeypatch):
    screen, user = make_screen(qtbot, monkeypatch, update_required=True)

    received = []
    screen.login_succeeded.connect(lambda u: received.append(u))

    screen.attempt_login()

    assert received == []


def test_login_succeeds_when_no_update_required(qtbot, monkeypatch):
    screen, user = make_screen(qtbot, monkeypatch, update_required=False)

    received = []
    screen.login_succeeded.connect(lambda u: received.append(u))

    screen.attempt_login()

    assert received == [user]


def test_mandatory_update_dialog_buttons_disabled_without_url():
    dialog = login.MandatoryUpdateDialog("2.0.0", "", "")
    assert dialog.download_button.isEnabled() is False
    assert dialog.update_now_button.isEnabled() is False


def test_mandatory_update_dialog_buttons_enabled_with_url():
    dialog = login.MandatoryUpdateDialog("2.0.0", "https://example.com/setup.exe", "")
    assert dialog.download_button.isEnabled() is True
    assert dialog.update_now_button.isEnabled() is True


def test_mandatory_update_dialog_accepts_sha256_as_keyword():
    """Regression: sha256 was inserted as a new parameter ahead of parent
    -- the real caller (LoginScreen.attempt_login) must pass both as
    keywords, never positionally, or a QWidget parent would silently land
    in the sha256 slot instead."""
    dialog = login.MandatoryUpdateDialog(
        "2.0.0", "https://example.com/setup.exe", "", sha256="deadbeef", parent=None,
    )
    assert dialog.sha256 == "deadbeef"


# --- Self-update flow ---


class DummySelfUpdateWorker(QThread):
    """Stands in for the real SelfUpdateWorker -- a no-op run() means
    nothing actually downloads over the network; tests drive the
    finished_success/failed callbacks directly instead."""

    progress = Signal(int)
    finished_success = Signal(str)
    failed = Signal(str)

    def __init__(self, download_url, version, expected_sha256):
        super().__init__()

    def run(self):
        pass


def make_dialog(qtbot, monkeypatch, download_url="https://example.com/setup.exe"):
    monkeypatch.setattr(login, "SelfUpdateWorker", DummySelfUpdateWorker)
    dialog = login.MandatoryUpdateDialog("2.0.0", download_url, "Fixed a bug.", sha256="abc123")
    qtbot.addWidget(dialog)
    return dialog


def test_start_self_update_disables_buttons_and_shows_progress(qtbot, monkeypatch):
    dialog = make_dialog(qtbot, monkeypatch)

    dialog.start_self_update()

    assert dialog.update_now_button.isEnabled() is False
    assert dialog.download_button.isEnabled() is False
    assert dialog.close_button.isEnabled() is False
    assert dialog.progress_bar.isVisibleTo(dialog) is True


def test_on_download_finished_launches_installer_and_quits_app(qtbot, monkeypatch):
    dialog = make_dialog(qtbot, monkeypatch)

    launched = []
    monkeypatch.setattr(self_update_service, "launch_silent_install", lambda path: launched.append(path))

    quit_called = []
    monkeypatch.setattr(login.QApplication, "quit", staticmethod(lambda: quit_called.append(True)))

    dialog.on_download_finished("C:\\fake\\ElysiumMasterApplication-Setup-v2.0.0.exe")

    assert launched == ["C:\\fake\\ElysiumMasterApplication-Setup-v2.0.0.exe"]
    assert quit_called == [True]


def test_on_download_finished_surfaces_install_launch_failure(qtbot, monkeypatch):
    """If launching the installer itself fails, the app must NOT quit --
    that would leave the user with no running app and no update applied."""
    dialog = make_dialog(qtbot, monkeypatch)

    def boom(path):
        raise self_update_service.SelfUpdateError("could not launch")

    monkeypatch.setattr(self_update_service, "launch_silent_install", boom)

    quit_called = []
    monkeypatch.setattr(login.QApplication, "quit", staticmethod(lambda: quit_called.append(True)))

    dialog.on_download_finished("C:\\fake\\setup.exe")

    assert quit_called == []
    assert "could not launch" in dialog.status_label.text()
    assert dialog.update_now_button.isEnabled() is True  # re-enabled so they can retry


def test_on_download_failed_re_enables_buttons_and_shows_error(qtbot, monkeypatch):
    dialog = make_dialog(qtbot, monkeypatch)
    dialog.start_self_update()  # disables everything first, same as a real attempt would

    dialog.on_download_failed("network error")

    assert dialog.update_now_button.isEnabled() is True
    assert dialog.download_button.isEnabled() is True
    assert dialog.close_button.isEnabled() is True
    assert dialog.progress_bar.isVisibleTo(dialog) is False
    assert "network error" in dialog.status_label.text()
    assert "manually" in dialog.status_label.text().lower()
