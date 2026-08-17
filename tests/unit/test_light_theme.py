"""
Regression test: every screen in this app assumes a light background with
dark, often-hardcoded text colors (e.g. dashboard.py's "Company Stats"
title is styled color: #1a1a1a with no explicit background) -- on a
machine with the OS in dark mode, Qt's default palette went dark and that
text became nearly invisible. _apply_light_theme() forces a consistent
light palette regardless of the OS theme.
"""

from PySide6.QtGui import QColor, QPalette

from elysium.main import _apply_light_theme


def test_apply_light_theme_sets_dark_text_on_light_backgrounds(qapp):
    _apply_light_theme(qapp)

    palette = qapp.palette()

    # Backgrounds must stay light regardless of the OS theme...
    for role in (QPalette.Window, QPalette.Base, QPalette.Button):
        color = palette.color(role)
        assert color.lightness() > 200, f"{role} was not light: {color.name()}"

    # ...and text must stay dark enough to read against them.
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        color = palette.color(role)
        assert color.lightness() < 60, f"{role} was not dark: {color.name()}"


def test_apply_light_theme_sets_fusion_style(qapp):
    _apply_light_theme(qapp)

    assert qapp.style().objectName().lower() == "fusion"
