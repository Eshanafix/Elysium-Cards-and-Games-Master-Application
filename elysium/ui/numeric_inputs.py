"""
QSpinBox/QDoubleSpinBox select-all-on-focus (docs feedback: "when entering
a value for something, ie boxes, money, it starts at 0 for some reason, so
if I want to enter 5 I need to delete the 0 or it becomes 05"). Qt's
default spin box behavior places the cursor without selecting the existing
text on focus, so a typed digit is inserted next to whatever value was
already there instead of replacing it -- these two drop-in subclasses fix
that everywhere a number is entered (boxes, packs, money amounts).
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox


class SelectAllSpinBox(QSpinBox):
    def focusInEvent(self, event):
        super().focusInEvent(event)
        # Deferred: selecting immediately gets clobbered by the click that
        # caused the focus-in event itself.
        QTimer.singleShot(0, self.selectAll)


class SelectAllDoubleSpinBox(QDoubleSpinBox):
    def focusInEvent(self, event):
        super().focusInEvent(event)
        QTimer.singleShot(0, self.selectAll)
