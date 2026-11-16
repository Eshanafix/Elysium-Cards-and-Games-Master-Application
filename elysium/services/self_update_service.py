"""
In-app self-update (docs feedback: manually finding the installer in
Downloads, clicking through it, then relaunching the app by hand was the
single biggest point of friction in keeping this app current -- it also
left a pile of numbered duplicate downloads behind every time). The app
downloads the new installer itself and launches it fully silently, then
quits itself (elysium/ui/login.py's MandatoryUpdateDialog.
on_download_finished) -- no UAC prompt, since this is already a per-user
install (PrivilegesRequired=lowest).

Quitting ourselves, rather than leaning on Inno Setup's Restart Manager
integration (CloseApplications/RestartApplications) to close this app for
us, was a deliberate choice after testing both live: Restart Manager's
"ask this Qt app to close" request was unreliable on real hardware --
sometimes closed it within ~10s, sometimes never closed it at all even
after 90+s, with no code difference between runs. installer.iss still
sets CloseApplications=yes as a backstop for the plain manual-install
case, but the self-update path here doesn't depend on it. The relaunch
afterward comes from installer.iss's own [Run] postinstall entry (which
fires on every install, silent or not), not from RestartApplications.

Deliberately only ever triggered from the login screen's mandatory-update
gate (elysium/ui/login.py), never as a background check while the app is
already in use -- an update landing mid-stream would be exactly the kind
of risk this app's lock system (lock_service) exists to prevent elsewhere.
"""

import hashlib
import logging
from pathlib import Path
from typing import Callable

import requests
from PySide6.QtCore import QProcess

from elysium.local_card import paths

logger = logging.getLogger(__name__)

DOWNLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MB
DOWNLOAD_TIMEOUT_SECONDS = 120

# Standard Inno Setup unattended-install switches: no wizard UI at all
# (/SP- matters here even under /VERYSILENT -- without it the installer
# silently blocks forever on an invisible "continue?" prompt, confirmed
# live), no "are you sure" message boxes, and don't prompt for a reboot.
# /CLOSEAPPLICATIONS is kept as a backstop in case this process is still
# running by the time the installer reaches the file-copy step, but the
# normal path is that MandatoryUpdateDialog.on_download_finished already
# quit this app before the installer gets that far -- see this module's
# docstring for why /RESTARTAPPLICATIONS isn't used here.
_SILENT_INSTALL_ARGS = [
    "/VERYSILENT", "/SUPPRESSMSGBOX", "/NORESTART", "/SP-", "/CLOSEAPPLICATIONS",
]


class SelfUpdateError(Exception):
    pass


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(DOWNLOAD_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_installer(
    download_url: str,
    version: str,
    expected_sha256: str | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Path:
    """
    Downloads the installer to %LOCALAPPDATA%\\ElysiumMasterApp\\updates\\,
    named by version so a retry never collides with (or silently reuses) a
    stale partial file from an earlier failed attempt. Verifies the result
    against expected_sha256 when one is given -- raises SelfUpdateError
    rather than ever handing an unverified binary to launch_silent_install.
    """
    updates_dir = paths.get_updates_dir()
    updates_dir.mkdir(parents=True, exist_ok=True)
    installer_path = updates_dir / f"ElysiumMasterApplication-Setup-v{version}.exe"

    try:
        with requests.get(download_url, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            response.raise_for_status()
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0

            with open(installer_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                    if chunk:
                        file.write(chunk)
                        downloaded += len(chunk)

                        if progress_callback and total_size:
                            progress_callback(downloaded, total_size)
    except requests.RequestException as e:
        installer_path.unlink(missing_ok=True)
        raise SelfUpdateError(f"Could not download the update: {e}") from e

    if expected_sha256:
        actual = _sha256_of_file(installer_path)

        if actual.lower() != expected_sha256.strip().lower():
            installer_path.unlink(missing_ok=True)
            raise SelfUpdateError(
                "The downloaded update failed integrity verification (checksum mismatch) -- "
                "not installing a file that doesn't match what was published."
            )

    return installer_path


def launch_silent_install(installer_path: Path | str) -> None:
    """
    Starts the installer, fully silent and detached from this process.
    Does NOT quit the app itself -- that's the caller's job, immediately
    after this returns (same QProcess.startDetached-then-quit shape as
    elysium/ui/app_restart.py's display-scale restart). Whether this
    process quits itself or Restart Manager closes it is harmless either
    way; Restart Manager's own file-lock detection handles the case where
    it's still shutting down when the installer starts checking.
    """
    if not QProcess.startDetached(str(installer_path), _SILENT_INSTALL_ARGS):
        raise SelfUpdateError("Could not launch the installer process.")

    logger.info("Launched silent self-update installer: %s", installer_path)
