from PySide6.QtCore import QRect
from PySide6.QtWidgets import QDialog

from elysium.ui.dialog_sizing import clamp_to_screen


class FakeScreen:
    def __init__(self, available: QRect):
        self._available = available

    def availableGeometry(self):
        return self._available


def test_clamp_shrinks_when_requested_size_exceeds_available_screen(qtbot):
    dialog = QDialog()
    qtbot.addWidget(dialog)
    dialog.screen = lambda: FakeScreen(QRect(0, 0, 1000, 600))

    clamp_to_screen(dialog, width=460, height=900, margin=80)

    assert dialog.height() <= 900
    assert dialog.height() == 520  # 600 - 80 margin
    assert dialog.width() == 460  # fits as requested


def test_clamp_leaves_size_unchanged_when_it_already_fits(qtbot):
    dialog = QDialog()
    qtbot.addWidget(dialog)
    dialog.screen = lambda: FakeScreen(QRect(0, 0, 2000, 2000))

    clamp_to_screen(dialog, width=460, height=700, margin=80)

    assert dialog.width() == 460
    assert dialog.height() == 700


def test_clamp_never_goes_below_minimum_floor(qtbot):
    dialog = QDialog()
    qtbot.addWidget(dialog)
    dialog.screen = lambda: FakeScreen(QRect(0, 0, 100, 100))

    clamp_to_screen(dialog, width=460, height=700, margin=80)

    assert dialog.width() >= 200
    assert dialog.height() >= 200
