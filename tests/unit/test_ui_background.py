"""
Regression tests for the QThread-lifetime crash fix (elysium/ui/
background.py). Root cause: a QThread garbage collected while its OS
thread is still running is undefined behavior in Qt and crashed the app
(confirmed access violation inside Qt6Core.dll) -- these lock in the fix.
"""

import time

import pytest
from PySide6.QtCore import QThread

from elysium.ui import background


class _TinyWorker(QThread):
    def run(self):
        time.sleep(0.05)


def test_run_worker_keeps_reference_until_finished(qtbot):
    worker = _TinyWorker()
    background.run_worker(worker)

    assert worker in background._active_workers

    with qtbot.waitSignal(worker.finished, timeout=2000):
        pass

    assert worker not in background._active_workers


def test_safe_callback_swallows_deleted_widget_runtime_error():
    def boom():
        raise RuntimeError("Internal C++ object already deleted")

    wrapped = background.safe_callback(boom)
    wrapped()  # must not raise


def test_safe_callback_passes_through_args():
    calls = []
    wrapped = background.safe_callback(lambda *a, **k: calls.append((a, k)))

    wrapped(1, 2, x=3)

    assert calls == [((1, 2), {"x": 3})]


def test_safe_callback_does_not_swallow_other_exceptions():
    def boom():
        raise ValueError("a real bug, not a deleted-widget race")

    wrapped = background.safe_callback(boom)

    with pytest.raises(ValueError):
        wrapped()
