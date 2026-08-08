"""
Clamps a dialog's initial size to the actual usable screen area (excluding
the taskbar/dock) -- a hardcoded `self.resize(w, h)` can otherwise produce
a window taller than the visible screen, with its buttons (and, on some
window managers, its resize handle) rendered off-screen and unreachable.
This got much easier to trigger once the default UI zoom went to 150%
(elysium/ui_settings.py), since every dialog's hardcoded pixel size scales
up right along with everything else.
"""

from PySide6.QtWidgets import QApplication


def clamp_to_screen(dialog, width: int, height: int, margin: int = 80) -> None:
    screen = dialog.screen() or QApplication.primaryScreen()

    if screen is None:
        dialog.resize(width, height)
        return

    available = screen.availableGeometry()  # excludes the taskbar/dock

    clamped_width = max(200, min(width, available.width() - margin))
    clamped_height = max(200, min(height, available.height() - margin))

    dialog.resize(clamped_width, clamped_height)
