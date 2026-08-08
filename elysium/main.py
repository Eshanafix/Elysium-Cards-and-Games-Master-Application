import logging
import os
import sys

from PySide6.QtWidgets import QApplication

from elysium.local_card import paths
from elysium.logging_setup import configure_logging
from elysium.ui.error_handling import install_global_exception_handler
from elysium.ui.shell import MainWindow
from elysium.ui_settings import get_display_scale


def main():
    paths.ensure_app_dirs()
    log_path = configure_logging()
    logging.getLogger(__name__).info("Elysium Master Application starting. Log file: %s", log_path)

    # Must be set before QApplication() is constructed -- Qt's platform
    # plugin reads QT_SCALE_FACTOR exactly once, at that point, and layers
    # it on top of per-monitor DPI auto-scaling (elysium/ui_settings.py).
    os.environ["QT_SCALE_FACTOR"] = str(get_display_scale())

    app = QApplication(sys.argv)
    install_global_exception_handler()

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
