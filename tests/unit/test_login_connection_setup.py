"""
Regression tests for the first-run "Configure Database Connection" flow
(elysium.ui.login.DatabaseConnectionDialog): a packaged install has no
.env and nothing in Credential Manager yet, so this is the only way to get
a MongoDB URI onto a fresh machine.
"""

from elysium.ui import login


def connected():
    return type("S", (), {"is_connected": True, "detail": "Connected."})()


def unavailable(detail="Server selection timeout"):
    return type("S", (), {"is_connected": False, "detail": detail})()


def test_test_and_save_rejects_blank_uri(qtbot):
    dialog = login.DatabaseConnectionDialog()
    qtbot.addWidget(dialog)
    dialog.uri_input.setText("   ")

    dialog.test_and_save()

    assert "Enter a connection string" in dialog.status_label.text()


def test_test_and_save_shows_error_and_does_not_store_on_failed_connection(qtbot, monkeypatch):
    dialog = login.DatabaseConnectionDialog()
    qtbot.addWidget(dialog)
    dialog.uri_input.setText("mongodb+srv://bad")

    monkeypatch.setattr(login.mongo_client, "test_connection_string", lambda uri: unavailable("timed out"))
    stored = []
    monkeypatch.setattr(login.credential_store, "set_stored_mongodb_uri", lambda uri: stored.append(uri))

    dialog.test_and_save()

    assert "Could not connect" in dialog.status_label.text()
    assert stored == []


def test_test_and_save_stores_and_accepts_on_success(qtbot, monkeypatch):
    dialog = login.DatabaseConnectionDialog()
    qtbot.addWidget(dialog)
    dialog.uri_input.setText("mongodb+srv://user:pass@cluster.mongodb.net/")

    monkeypatch.setattr(login.mongo_client, "test_connection_string", lambda uri: connected())
    stored = []
    monkeypatch.setattr(login.credential_store, "set_stored_mongodb_uri", lambda uri: stored.append(uri))
    monkeypatch.setattr(login.DatabaseConnectionDialog, "accept", lambda self: setattr(self, "_accepted", True))

    dialog.test_and_save()

    assert stored == ["mongodb+srv://user:pass@cluster.mongodb.net/"]
    assert dialog._accepted is True


def test_configure_connection_button_refreshes_status_on_accept(qtbot, monkeypatch):
    monkeypatch.setattr(login.mongo_client, "reset_client", lambda: None)
    monkeypatch.setattr(login.mongo_client, "check_connection", connected)
    monkeypatch.setattr(login.DatabaseConnectionDialog, "exec", lambda self: login.QDialog.Accepted)

    screen = login.LoginScreen()
    qtbot.addWidget(screen)

    screen.configure_connection()

    assert screen.connection_status_label.text() == "MongoDB: connected"


def test_configure_connection_button_does_nothing_on_cancel(qtbot, monkeypatch):
    monkeypatch.setattr(login.mongo_client, "reset_client", lambda: None)
    monkeypatch.setattr(login.mongo_client, "check_connection", lambda: unavailable())
    monkeypatch.setattr(login.DatabaseConnectionDialog, "exec", lambda self: login.QDialog.Rejected)

    screen = login.LoginScreen()
    qtbot.addWidget(screen)

    reset_calls = []
    monkeypatch.setattr(login.mongo_client, "reset_client", lambda: reset_calls.append(True))

    screen.configure_connection()

    assert reset_calls == []
