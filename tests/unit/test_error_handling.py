import sys

from pymongo.errors import PyMongoError

from elysium.ui import error_handling


def test_friendly_message_distinguishes_pymongo_errors():
    db_message = error_handling._friendly_message(PyMongoError("connection reset"))
    generic_message = error_handling._friendly_message(ValueError("bad input"))

    assert "database" in db_message.lower()
    assert "database" not in generic_message.lower()


def test_install_global_exception_handler_sets_excepthook(monkeypatch):
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)

    error_handling.install_global_exception_handler()

    assert sys.excepthook is not sys.__excepthook__


def test_handler_reraises_keyboard_interrupt_via_default_hook(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: calls.append(a))

    error_handling.install_global_exception_handler()

    try:
        raise KeyboardInterrupt()
    except KeyboardInterrupt:
        sys.excepthook(*sys.exc_info())

    assert len(calls) == 1
