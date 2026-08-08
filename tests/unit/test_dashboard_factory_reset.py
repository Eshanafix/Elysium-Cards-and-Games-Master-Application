"""
Regression tests for the admin Factory Reset button (docs feedback: "add 3
are you sure warnings as I don't want this pressed on accident"). These
exercise the confirmation gate and phrase-dialog logic without ever
touching Mongo -- wipe_all_data() itself is covered by
test_factory_reset_service.py.
"""

from PySide6.QtWidgets import QMessageBox

from elysium.models.users import ROLE_ADMIN, User
from elysium.ui import dashboard


def make_admin_screen(qtbot, monkeypatch):
    monkeypatch.setattr(dashboard.mongo_client, "check_connection", lambda: type(
        "S", (), {"is_connected": False, "detail": "n/a"}
    )())
    user = User(id="admin-1", username="admin", password_hash="x", roles=[ROLE_ADMIN])
    logged_out = {"called": False}
    screen = dashboard.DashboardScreen(user, on_logout=lambda: logged_out.__setitem__("called", True))
    qtbot.addWidget(screen)
    return screen, logged_out


def test_factory_reset_phrase_dialog_requires_exact_phrase(qtbot):
    dialog = dashboard.FactoryResetPhraseDialog()
    qtbot.addWidget(dialog)

    assert not dialog.ok_button.isEnabled()

    dialog.phrase_input.setText("wipe all data")  # wrong case
    assert not dialog.ok_button.isEnabled()

    dialog.phrase_input.setText("WIPE ALL DATA")
    assert dialog.ok_button.isEnabled()

    dialog.phrase_input.setText("WIPE ALL DATA ")  # trailing space, stripped
    assert dialog.ok_button.isEnabled()


def test_factory_reset_aborts_if_first_warning_declined(qtbot, monkeypatch):
    screen, logged_out = make_admin_screen(qtbot, monkeypatch)

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.No)
    called = {}
    monkeypatch.setattr(dashboard.factory_reset_service, "wipe_all_data", lambda **k: called.setdefault("ran", True))

    screen.factory_reset()

    assert "ran" not in called
    assert logged_out["called"] is False


def test_factory_reset_aborts_if_phrase_dialog_canceled(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    screen, logged_out = make_admin_screen(qtbot, monkeypatch)

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(dashboard.FactoryResetPhraseDialog, "exec", lambda self: QDialog.Rejected)
    called = {}
    monkeypatch.setattr(dashboard.factory_reset_service, "wipe_all_data", lambda **k: called.setdefault("ran", True))

    screen.factory_reset()

    assert "ran" not in called
    assert logged_out["called"] is False


def test_factory_reset_runs_and_logs_out_when_all_three_confirmed(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    screen, logged_out = make_admin_screen(qtbot, monkeypatch)

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(dashboard.FactoryResetPhraseDialog, "exec", lambda self: QDialog.Accepted)

    captured = {}
    monkeypatch.setattr(
        dashboard.factory_reset_service, "wipe_all_data",
        lambda confirmed_by: (captured.setdefault("confirmed_by", confirmed_by), {"deleted_counts": {}, "dropped_databases": ["elysium_s_abc"]})[1],
    )

    screen.factory_reset()

    assert captured["confirmed_by"] == "admin-1"
    assert logged_out["called"] is True


def test_factory_reset_shows_error_and_does_not_log_out_on_failure(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    screen, logged_out = make_admin_screen(qtbot, monkeypatch)

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(dashboard.FactoryResetPhraseDialog, "exec", lambda self: QDialog.Accepted)

    def boom(confirmed_by):
        raise RuntimeError("connection lost")

    monkeypatch.setattr(dashboard.factory_reset_service, "wipe_all_data", boom)

    screen.factory_reset()

    assert logged_out["called"] is False


def test_factory_reset_button_only_visible_for_admin(qtbot, monkeypatch):
    monkeypatch.setattr(dashboard.mongo_client, "check_connection", lambda: type(
        "S", (), {"is_connected": False, "detail": "n/a"}
    )())
    streamer = User(id="s1", username="streamer1", password_hash="x", roles=["streamer"])
    screen = dashboard.DashboardScreen(streamer)
    qtbot.addWidget(screen)

    assert screen.factory_reset_button.parent() is None
