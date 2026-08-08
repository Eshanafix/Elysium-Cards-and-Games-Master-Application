"""
Application-wide logging (LLD 5.2: "Log all important operations").

Writes to a rotating file under the same per-machine app-data directory as
the local card database, plus stderr when run from a terminal, so failures
like a background QThread's caught exception (which the UI only shows a
short message for) have a full traceback somewhere to look at.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from elysium.local_card.paths import get_app_data_dir

_configured = False


def configure_logging() -> Path:
    global _configured

    log_dir = get_app_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "app.log"

    if _configured:
        return log_path

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    _configured = True
    return log_path
