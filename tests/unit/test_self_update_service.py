"""
Regression tests for the in-app self-updater (docs feedback: manually
finding the installer in Downloads, clicking through it, and relaunching
the app by hand was the single biggest point of friction in keeping this
app current). download_installer() never hands launch_silent_install an
unverified or partial file -- every failure path (network error, checksum
mismatch) cleans up whatever was written to disk.
"""

import hashlib

import pytest
import requests

from elysium.services import self_update_service


class FakeResponse:
    """Stands in for requests.Response -- just enough of the context-
    manager + streaming-iteration protocol download_installer() uses."""

    def __init__(self, content: bytes, raise_error: Exception | None = None):
        self.content = content
        self.headers = {"content-length": str(len(content))}
        self._raise_error = raise_error

    def raise_for_status(self):
        if self._raise_error:
            raise self._raise_error

    def iter_content(self, chunk_size):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


FAKE_INSTALLER_BYTES = b"fake installer contents, not a real exe" * 100


def make_fake_get(content=FAKE_INSTALLER_BYTES, raise_error=None, network_error=None):
    def fake_get(url, stream=True, timeout=None):
        if network_error:
            raise network_error
        return FakeResponse(content, raise_error=raise_error)
    return fake_get


def test_download_installer_writes_file_and_reports_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(self_update_service.paths, "get_updates_dir", lambda: tmp_path)
    monkeypatch.setattr(self_update_service.requests, "get", make_fake_get())

    progress_calls = []
    path = self_update_service.download_installer(
        "https://example.com/setup.exe", "2.0.0",
        progress_callback=lambda downloaded, total: progress_calls.append((downloaded, total)),
    )

    assert path.exists()
    assert path.read_bytes() == FAKE_INSTALLER_BYTES
    assert path.name == "ElysiumMasterApplication-Setup-v2.0.0.exe"
    assert progress_calls  # at least one progress update happened
    assert progress_calls[-1] == (len(FAKE_INSTALLER_BYTES), len(FAKE_INSTALLER_BYTES))


def test_download_installer_accepts_a_matching_checksum(tmp_path, monkeypatch):
    monkeypatch.setattr(self_update_service.paths, "get_updates_dir", lambda: tmp_path)
    monkeypatch.setattr(self_update_service.requests, "get", make_fake_get())

    real_sha256 = hashlib.sha256(FAKE_INSTALLER_BYTES).hexdigest()

    path = self_update_service.download_installer(
        "https://example.com/setup.exe", "2.0.0", expected_sha256=real_sha256,
    )

    assert path.exists()


def test_download_installer_is_case_insensitive_on_checksum(tmp_path, monkeypatch):
    monkeypatch.setattr(self_update_service.paths, "get_updates_dir", lambda: tmp_path)
    monkeypatch.setattr(self_update_service.requests, "get", make_fake_get())

    real_sha256 = hashlib.sha256(FAKE_INSTALLER_BYTES).hexdigest()

    path = self_update_service.download_installer(
        "https://example.com/setup.exe", "2.0.0", expected_sha256=real_sha256.upper(),
    )

    assert path.exists()


def test_download_installer_rejects_checksum_mismatch_and_deletes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(self_update_service.paths, "get_updates_dir", lambda: tmp_path)
    monkeypatch.setattr(self_update_service.requests, "get", make_fake_get())

    with pytest.raises(self_update_service.SelfUpdateError):
        self_update_service.download_installer(
            "https://example.com/setup.exe", "2.0.0", expected_sha256="0" * 64,
        )

    assert list(tmp_path.iterdir()) == []  # the bad download must not be left behind


def test_download_installer_skips_checksum_check_when_none_given(tmp_path, monkeypatch):
    monkeypatch.setattr(self_update_service.paths, "get_updates_dir", lambda: tmp_path)
    monkeypatch.setattr(self_update_service.requests, "get", make_fake_get())

    path = self_update_service.download_installer("https://example.com/setup.exe", "2.0.0", expected_sha256=None)

    assert path.exists()


def test_download_installer_cleans_up_on_network_error(tmp_path, monkeypatch):
    monkeypatch.setattr(self_update_service.paths, "get_updates_dir", lambda: tmp_path)
    monkeypatch.setattr(
        self_update_service.requests, "get",
        make_fake_get(network_error=requests.ConnectionError("no network")),
    )

    with pytest.raises(self_update_service.SelfUpdateError):
        self_update_service.download_installer("https://example.com/setup.exe", "2.0.0")

    assert list(tmp_path.iterdir()) == []


def test_download_installer_cleans_up_on_http_error_status(tmp_path, monkeypatch):
    monkeypatch.setattr(self_update_service.paths, "get_updates_dir", lambda: tmp_path)
    monkeypatch.setattr(
        self_update_service.requests, "get",
        make_fake_get(raise_error=requests.HTTPError("404 not found")),
    )

    with pytest.raises(self_update_service.SelfUpdateError):
        self_update_service.download_installer("https://example.com/setup.exe", "2.0.0")

    assert list(tmp_path.iterdir()) == []


# --- launch_silent_install ---


def test_launch_silent_install_passes_the_correct_unattended_flags(monkeypatch):
    calls = []
    monkeypatch.setattr(
        self_update_service.QProcess, "startDetached",
        staticmethod(lambda program, args: calls.append((program, args)) or True),
    )

    self_update_service.launch_silent_install("C:\\fake\\setup.exe")

    assert len(calls) == 1
    program, args = calls[0]
    assert program == "C:\\fake\\setup.exe"
    for flag in ("/VERYSILENT", "/SUPPRESSMSGBOX", "/NORESTART", "/SP-", "/CLOSEAPPLICATIONS"):
        assert flag in args
    assert "/RESTARTAPPLICATIONS" not in args  # unreliable live -- see module docstring


def test_launch_silent_install_raises_when_process_fails_to_start(monkeypatch):
    monkeypatch.setattr(self_update_service.QProcess, "startDetached", staticmethod(lambda program, args: False))

    with pytest.raises(self_update_service.SelfUpdateError):
        self_update_service.launch_silent_install("C:\\fake\\setup.exe")
