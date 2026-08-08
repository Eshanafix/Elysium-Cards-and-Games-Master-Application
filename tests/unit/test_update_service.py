"""
Regression tests for the mandatory update gate (elysium.services.
update_service): version comparison, reading the published config, and
publishing a new required version.
"""

from elysium.services import update_service
from elysium.version import APP_VERSION


def test_version_is_outdated_true_for_lower_version():
    assert update_service.version_is_outdated("1.0.0", "1.1.0") is True


def test_version_is_outdated_false_for_equal_version():
    assert update_service.version_is_outdated("1.1.0", "1.1.0") is False


def test_version_is_outdated_false_for_higher_version():
    assert update_service.version_is_outdated("1.2.0", "1.1.0") is False


def test_version_is_outdated_handles_multi_digit_segments():
    # A naive string compare would put "1.9.0" above "1.10.0" -- this must
    # compare numerically per segment instead.
    assert update_service.version_is_outdated("1.9.0", "1.10.0") is True
    assert update_service.version_is_outdated("1.10.0", "1.9.0") is False


def test_get_update_config_defaults_to_local_version_when_unset(monkeypatch):
    monkeypatch.setattr(update_service.repo, "get_app_update_config", lambda: None)

    config = update_service.get_update_config()

    assert config["required_version"] == APP_VERSION
    assert config["download_url"] == ""
    assert config["release_notes"] == ""


def test_is_update_required_false_when_local_version_current(monkeypatch):
    monkeypatch.setattr(
        update_service.repo, "get_app_update_config",
        lambda: {"required_version": APP_VERSION, "download_url": "https://example.com", "release_notes": ""},
    )

    assert update_service.is_update_required() is False


def test_is_update_required_true_when_published_version_is_higher(monkeypatch):
    monkeypatch.setattr(
        update_service.repo, "get_app_update_config",
        lambda: {"required_version": "999.0.0", "download_url": "https://example.com", "release_notes": ""},
    )

    assert update_service.is_update_required() is True


def test_publish_required_version_writes_config_and_records_audit(monkeypatch):
    written = {}
    audited = {}

    monkeypatch.setattr(update_service.repo, "set_app_update_config", lambda fields: written.update(fields))
    monkeypatch.setattr(
        update_service.audit_service, "record_event",
        lambda **kwargs: audited.update(kwargs) or "event-id",
    )

    update_service.publish_required_version("2.0.0", "https://example.com/setup.exe", "Fixed a crash.", "admin-1")

    assert written == {
        "required_version": "2.0.0",
        "download_url": "https://example.com/setup.exe",
        "release_notes": "Fixed a crash.",
    }
    assert audited["action_type"] == "APP_UPDATE_PUBLISHED"
    assert audited["performed_by"] == "admin-1"


def test_publish_required_version_rejects_blank_version():
    try:
        update_service.publish_required_version("  ", "https://example.com", "", "admin-1")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_publish_required_version_rejects_blank_download_url():
    try:
        update_service.publish_required_version("2.0.0", "  ", "", "admin-1")
        assert False, "expected ValueError"
    except ValueError:
        pass
