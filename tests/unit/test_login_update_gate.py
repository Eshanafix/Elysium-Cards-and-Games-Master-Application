"""
Regression tests: a mandatory update blocks login_succeeded from firing and
shows a MandatoryUpdateDialog instead, while a login on a current build
proceeds normally.
"""

from elysium.models.users import User
from elysium.services import auth_service
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
        lambda: {"required_version": "999.0.0", "download_url": "https://example.com/setup.exe", "release_notes": "Fixed a bug."},
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


def test_mandatory_update_dialog_download_button_disabled_without_url():
    dialog = login.MandatoryUpdateDialog("2.0.0", "", "")
    assert dialog.download_button.isEnabled() is False


def test_mandatory_update_dialog_download_button_enabled_with_url():
    dialog = login.MandatoryUpdateDialog("2.0.0", "https://example.com/setup.exe", "")
    assert dialog.download_button.isEnabled() is True
