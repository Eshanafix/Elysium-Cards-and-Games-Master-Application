"""
Offscreen smoke test for the Phase 1 golden path: app opens to Login,
Continue as Guest reaches Card Lookup, and an empty/never-refreshed local
database shows the expected empty-state message (LLD 21.5's stale banner
covers ">24h old"; "never refreshed" is the related empty state Card
Lookup must also handle gracefully).

Runs with QT_QPA_PLATFORM=offscreen (set in conftest.py) so it works in a
headless environment without a real display.
"""

from PySide6.QtCore import Qt

from elysium.ui.card_lookup import NEVER_REFRESHED_MESSAGE
from elysium.ui.shell import GuestShell, MainWindow


def test_app_opens_to_login_screen(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.stacked.currentWidget() is window.login_screen


def test_continue_as_guest_reaches_card_lookup(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    qtbot.mouseClick(window.login_screen.guest_button, Qt.LeftButton)

    assert window.stacked.currentWidget() is window.guest_shell
    assert window.guest_shell.content.currentWidget() is window.guest_shell.card_lookup_tab


def test_guest_nav_login_item_returns_to_login_screen(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    window.show_guest_shell()
    window.guest_shell.nav_list.setCurrentRow(1)  # "Login"

    assert window.stacked.currentWidget() is window.login_screen


def test_card_lookup_shows_never_refreshed_message_on_fresh_install(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    shell = GuestShell(on_login_requested=lambda: None)
    qtbot.addWidget(shell)
    shell.show()
    qtbot.waitExposed(shell)

    assert shell.card_lookup_tab.stale_banner_container.isVisible()
    assert shell.card_lookup_tab.stale_banner.text() == NEVER_REFRESHED_MESSAGE
    assert shell.card_lookup_tab.status_label.text() == "Showing 0 of 0 matches"
