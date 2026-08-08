"""
Global uncaught-exception handler (Phase 8 hardening: docs/
IMPLEMENTATION_PLAN.md LLD section 30 phase 8, "transaction failure
recovery"). PySide6/Qt does not safely propagate a Python exception raised
inside a slot back through the C++ event loop -- left completely unhandled,
it can silently no-op or destabilize the app, which is indistinguishable
from a crash to the user. This is a plausible root cause behind reports
like "the app closed randomly" that aren't explained by a specific bug
(distinct from the Qt use-after-free already fixed in ui/streams.py).

Every write path in this app goes through a MongoDB session.with_transaction()
(elysium/services/*_service.py), which already retries transient errors and
guarantees an all-or-nothing outcome on its own -- so a database failure
that reaches here always means nothing was left half-done. This handler's
job is only to make that failure visible instead of silent, and keep the
window alive instead of crashing.
"""

import logging
import sys

from PySide6.QtWidgets import QApplication, QMessageBox
from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)


def _friendly_message(exc_value: BaseException) -> str:
    if isinstance(exc_value, PyMongoError):
        return (
            "Lost connection to the database while completing that action.\n\n"
            "MongoDB transactions either fully complete or fully roll back, so nothing was "
            "left half-done. Check your connection and try again."
        )

    return (
        "Something went wrong completing that action.\n\n"
        "Nothing else in the app should be affected. The details have been written to the "
        "application log."
    )


def install_global_exception_handler() -> None:
    def handle(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logger.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))

        app = QApplication.instance()
        if app is not None:
            QMessageBox.critical(None, "Unexpected Error", _friendly_message(exc_value))

    sys.excepthook = handle
