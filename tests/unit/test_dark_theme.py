"""
Regression test for the app's forced dark palette (elysium.main._apply_dark_theme).
Backgrounds must stay dark and text light regardless of the OS theme -- this
is the same "force a known palette instead of trusting the OS" fix as the
light theme it replaced, just inverted, and it depends on every hardcoded
per-widget text color in the app actually being safe against a dark
background (see dashboard.py's stat-section titles and the site-wide
message-label colors) rather than assuming a light one like before.
"""

from PySide6.QtGui import QColor, QPalette

from elysium.main import _apply_dark_theme


def test_apply_dark_theme_sets_light_text_on_dark_backgrounds(qapp):
    _apply_dark_theme(qapp)

    palette = qapp.palette()

    # Backgrounds must stay dark regardless of the OS theme...
    for role in (QPalette.Window, QPalette.Base, QPalette.Button):
        color = palette.color(role)
        assert color.lightness() < 80, f"{role} was not dark: {color.name()}"

    # ...and text must stay light enough to read against them.
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        color = palette.color(role)
        assert color.lightness() > 180, f"{role} was not light: {color.name()}"


def test_apply_dark_theme_sets_fusion_style(qapp):
    _apply_dark_theme(qapp)

    assert qapp.style().objectName().lower() == "fusion"


def test_apply_dark_theme_highlight_has_readable_contrast(qapp):
    _apply_dark_theme(qapp)

    palette = qapp.palette()
    highlight = palette.color(QPalette.Highlight)
    highlighted_text = palette.color(QPalette.HighlightedText)

    # A mid-bright accent color needs dark text on top of it, not more light
    # text -- otherwise the selected/highlighted state is the one place in
    # a "fixed dark theme" that quietly becomes hard to read.
    assert abs(highlight.lightness() - highlighted_text.lightness()) > 80
