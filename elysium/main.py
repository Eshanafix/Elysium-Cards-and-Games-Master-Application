import logging
import os
import sys

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from elysium.local_card import paths
from elysium.logging_setup import configure_logging
from elysium.ui.error_handling import install_global_exception_handler
from elysium.ui.shell import MainWindow
from elysium.ui_settings import get_display_scale


def _apply_light_theme(app: QApplication) -> None:
    """Every screen in this app was built assuming a light background with
    dark text (e.g. dashboard.py's "Company Stats" title is styled color:
    #1a1a1a with no explicit background) -- fine on a light OS theme, but
    on a machine with Windows dark mode on, Qt's default palette goes dark
    and that same hardcoded-dark text becomes nearly invisible against it
    (reported: a streamer's dashboard showed a barely-visible "Company
    Stats" heading). Forcing Fusion + an explicit light QPalette here makes
    every screen render the same regardless of the OS theme, instead of
    every dark-text label needing its own explicit background as a patch.
    """
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#f0f0f0"))
    palette.setColor(QPalette.WindowText, QColor("#1a1a1a"))
    palette.setColor(QPalette.Base, QColor("#ffffff"))
    palette.setColor(QPalette.AlternateBase, QColor("#f5f5f5"))
    palette.setColor(QPalette.ToolTipBase, QColor("#ffffee"))
    palette.setColor(QPalette.ToolTipText, QColor("#1a1a1a"))
    palette.setColor(QPalette.Text, QColor("#1a1a1a"))
    palette.setColor(QPalette.Button, QColor("#f0f0f0"))
    palette.setColor(QPalette.ButtonText, QColor("#1a1a1a"))
    palette.setColor(QPalette.Highlight, QColor("#3daee9"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.PlaceholderText, QColor("#888888"))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#a0a0a0"))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#a0a0a0"))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#a0a0a0"))
    app.setPalette(palette)


def main():
    paths.ensure_app_dirs()
    log_path = configure_logging()
    logging.getLogger(__name__).info("Elysium Master Application starting. Log file: %s", log_path)

    # Must be set before QApplication() is constructed -- Qt's platform
    # plugin reads QT_SCALE_FACTOR exactly once, at that point, and layers
    # it on top of per-monitor DPI auto-scaling (elysium/ui_settings.py).
    os.environ["QT_SCALE_FACTOR"] = str(get_display_scale())

    app = QApplication(sys.argv)
    _apply_light_theme(app)
    install_global_exception_handler()

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
