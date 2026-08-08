"""
Keeps a QThread worker alive until it actually finishes, independent of
whatever happens to the screen that started it.

Root-cause note: Qt has undefined behavior (Qt's own docs: usually a hard
crash) if a QThread object is garbage collected while its underlying OS
thread is still running. Every screen in this app that fires off a
background worker (CSV export, price refresh) previously stored the only
reference to it as a plain instance attribute (`self._worker = Worker(...)`)
-- if that *screen* gets torn down while the worker is still mid-run (e.g.
switching accounts recreates the whole AppShell, deleting the old screen),
Python's refcounting can collect the worker with it, mid-thread. This was
the actual cause of an access-violation crash inside Qt6Core.dll (confirmed
via Windows Error Reporting) while a streamer was on the Reports screen --
almost certainly a CSV export thread outliving the screen that launched it.

Registering a worker here keeps a strong reference in a place that never
gets torn down by screen navigation, until the worker's own `finished`
signal (QThread's built-in one, always emitted when run() returns) confirms
it's safe to let go.
"""

_active_workers = set()


def run_worker(worker) -> None:
    _active_workers.add(worker)
    worker.finished.connect(lambda: _active_workers.discard(worker))
    worker.start()


def safe_callback(fn):
    """Wraps a worker-result callback (e.g. a lambda touching `self.
    show_message(...)`) so that the now-harmless race of "the screen that
    launched this worker was navigated away from before it finished" fails
    silently instead of surfacing as an "Unexpected Error" dialog -- the
    C++ side of a deleted PySide widget raises RuntimeError on access,
    which is expected here, not a bug, once run_worker() above has already
    ensured the *thread itself* was never the thing torn down early."""
    def wrapped(*args, **kwargs):
        try:
            fn(*args, **kwargs)
        except RuntimeError:
            pass
    return wrapped
