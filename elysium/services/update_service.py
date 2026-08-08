"""
Mandatory update gate. Only 4 people run this app off shared MongoDB, so a
release is rolled out by an admin publishing a new required_version +
download_url here (via the admin App Updates screen) -- every login is then
blocked, with a prompt to download the new installer, until the local
build's baked-in elysium.version.APP_VERSION catches up. Nothing needs to
reset itself afterward: once someone installs the new build and reopens the
app, its (now-current) APP_VERSION satisfies the check on its own.
"""

from elysium.repositories import master_repository as repo
from elysium.services import audit_service
from elysium.version import APP_VERSION


def _parse_version(version: str) -> tuple[int, ...]:
    parts = []
    for piece in version.strip().split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def version_is_outdated(local_version: str, required_version: str) -> bool:
    return _parse_version(local_version) < _parse_version(required_version)


def get_update_config() -> dict:
    doc = repo.get_app_update_config()
    return {
        "required_version": doc.get("required_version", APP_VERSION) if doc else APP_VERSION,
        "download_url": doc.get("download_url", "") if doc else "",
        "release_notes": doc.get("release_notes", "") if doc else "",
    }


def is_update_required() -> bool:
    config = get_update_config()
    return version_is_outdated(APP_VERSION, config["required_version"])


def publish_required_version(version: str, download_url: str, release_notes: str, published_by: str) -> None:
    version = version.strip()
    download_url = download_url.strip()
    release_notes = release_notes.strip()

    if not version:
        raise ValueError("Version is required.")
    if not download_url:
        raise ValueError("Download URL is required.")

    fields = {
        "required_version": version,
        "download_url": download_url,
        "release_notes": release_notes,
    }
    repo.set_app_update_config(fields)

    audit_service.record_event(
        action_type="APP_UPDATE_PUBLISHED",
        performed_by=published_by,
        after_values=fields,
    )
