"""
Regression tests for the admin App Updates screen: it loads the currently
published config, and Publish calls update_service.publish_required_version
with the entered fields after the confirmation prompt is accepted.
"""

from PySide6.QtWidgets import QMessageBox

from elysium.models.users import User
from elysium.ui import app_updates


def make_screen(qtbot, monkeypatch, config=None):
    monkeypatch.setattr(
        app_updates.update_service, "get_update_config",
        lambda: config or {"required_version": "1.0.0", "download_url": "", "release_notes": ""},
    )

    admin = User(id="a1", username="admin", password_hash="x", roles=["admin"])
    screen = app_updates.AppUpdatesScreen(admin)
    qtbot.addWidget(screen)
    return screen, admin


def test_loads_currently_published_config(qtbot, monkeypatch):
    screen, _ = make_screen(qtbot, monkeypatch, config={
        "required_version": "1.2.0", "download_url": "https://example.com/setup.exe", "release_notes": "Notes.",
    })

    assert screen.version_input.text() == "1.2.0"
    assert screen.download_url_input.text() == "https://example.com/setup.exe"
    assert screen.release_notes_input.toPlainText() == "Notes."


def test_publish_calls_service_after_confirmation(qtbot, monkeypatch):
    screen, admin = make_screen(qtbot, monkeypatch)

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    calls = {}
    monkeypatch.setattr(
        app_updates.update_service, "publish_required_version",
        lambda version, download_url, release_notes, published_by: calls.update(
            version=version, download_url=download_url, release_notes=release_notes, published_by=published_by,
        ),
    )

    screen.version_input.setText("2.0.0")
    screen.download_url_input.setText("https://example.com/v2.exe")
    screen.release_notes_input.setPlainText("Fixed a bug.")
    screen.publish()

    assert calls == {
        "version": "2.0.0", "download_url": "https://example.com/v2.exe",
        "release_notes": "Fixed a bug.", "published_by": admin.id,
    }
    assert "published" in screen.message_label.text().lower()


def test_publish_does_nothing_when_confirmation_declined(qtbot, monkeypatch):
    screen, _ = make_screen(qtbot, monkeypatch)

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)

    called = []
    monkeypatch.setattr(
        app_updates.update_service, "publish_required_version",
        lambda *a, **k: called.append(True),
    )

    screen.version_input.setText("2.0.0")
    screen.publish()

    assert called == []


def test_publish_shows_validation_error(qtbot, monkeypatch):
    screen, _ = make_screen(qtbot, monkeypatch)

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(
        app_updates.update_service, "publish_required_version",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("Download URL is required.")),
    )

    screen.version_input.setText("2.0.0")
    screen.publish()

    assert screen.message_label.text() == "Download URL is required."
