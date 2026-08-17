"""
QComboBox drop-in that ignores mouse wheel scrolling (docs feedback: an
unopened dropdown silently changes its selected value when the mouse
happens to be over it while the page is scrolled -- surprising and easy to
trigger by accident, e.g. scrolling past a booster-type combo box on a
smaller monitor).
"""

from PySide6.QtWidgets import QComboBox


class NoScrollComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()
