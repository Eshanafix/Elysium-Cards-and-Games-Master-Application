import logging
import os
import sys

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from elysium.local_card import paths
from elysium.logging_setup import configure_logging
from elysium.ui.error_handling import install_global_exception_handler
from elysium.ui.shell import MainWindow
from elysium.ui_settings import get_display_scale

# Comfortably larger than Qt's own Windows default (Segoe UI 9pt) without
# going through QT_SCALE_FACTOR -- a real crash (STATUS_STACK_BUFFER_OVERRUN,
# confirmed via crash-dump analysis deep inside Qt's Windows platform plugin,
# qwindows.dll) reproduced at this app's old default 150% QT_SCALE_FACTOR and
# stopped reproducing at 100%. QT_SCALE_FACTOR is a blunt device-pixel-ratio
# override applied before Qt's own native painting code even starts up;
# QFont point sizes go through Qt's ordinary, already-DPI-aware text layout
# instead, so this gets most of the same "everything reads bigger" result
# (font metrics drive a lot of this app's row heights/padding too) without
# touching that code path. ui_settings.DEFAULT_SCALE is now 1.0 for the same
# reason -- the zoom picker on the Account screen is still there for anyone
# who wants more than this.
BASE_FONT_POINT_SIZE = 12


def _apply_base_font(app: QApplication) -> None:
    font = app.font()
    font.setPointSize(BASE_FONT_POINT_SIZE)
    app.setFont(font)


def _apply_dark_theme(app: QApplication) -> None:
    """Forces a consistent dark palette regardless of the OS theme -- same
    reasoning as the light theme this replaced: most screens were built
    assuming *some* fixed background with a hardcoded, non-adaptive text
    color (e.g. dashboard.py's stat-section titles, or the red/green message
    labels used across nearly every screen), so an unmanaged palette (light
    OR dark, OS-controlled) risks the exact contrast bug that already
    shipped once (a streamer's dashboard had a barely-visible "Company
    Stats" heading under Windows dark mode). Switching this *back* to dark
    (per explicit request) meant first re-auditing every one of those
    hardcoded colors for readability against a dark background instead of a
    light one -- see dashboard.py's stat titles (color removed entirely, now
    inherits WindowText below) and the site-wide message-label red/green
    (brightened to #ff6b6b / #4caf50).
    """
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#353535"))
    palette.setColor(QPalette.WindowText, QColor("#e8e8e8"))
    palette.setColor(QPalette.Base, QColor("#232323"))
    palette.setColor(QPalette.AlternateBase, QColor("#2d2d2d"))
    palette.setColor(QPalette.ToolTipBase, QColor("#353535"))
    palette.setColor(QPalette.ToolTipText, QColor("#e8e8e8"))
    palette.setColor(QPalette.Text, QColor("#e8e8e8"))
    palette.setColor(QPalette.Button, QColor("#3a3a3a"))
    palette.setColor(QPalette.ButtonText, QColor("#e8e8e8"))
    palette.setColor(QPalette.Highlight, QColor("#3daee9"))
    palette.setColor(QPalette.HighlightedText, QColor("#0a0a0a"))
    palette.setColor(QPalette.PlaceholderText, QColor("#888888"))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#6e6e6e"))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#6e6e6e"))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#6e6e6e"))
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
    _apply_dark_theme(app)
    _apply_base_font(app)
    install_global_exception_handler()

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
