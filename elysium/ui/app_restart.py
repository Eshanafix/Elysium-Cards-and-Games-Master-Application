"""
Relaunches the app in a new process and quits the current one -- used after
a UI display-scale change, since Qt only reads QT_SCALE_FACTOR once at
QApplication startup (elysium/ui_settings.py).
"""

import sys

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication


def restart_application() -> None:
    if getattr(sys, "frozen", False):
        # PyInstaller-frozen build: sys.executable IS the app itself, with
        # no script path argument to re-pass.
        QProcess.startDetached(sys.executable, [])
    else:
        QProcess.startDetached(sys.executable, sys.argv)

    QApplication.quit()
