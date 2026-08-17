"""
Regression test: the nav list used a hardcoded 160px max width, which
truncated longer labels ("Master Inventory" -> "Master Inv", "Shared
Sealed Prices" -> "Shared Se") on a laptop with a smaller screen or higher
effective UI scale than this was built/tested on. It's now sized to
whatever the widest item in the list actually needs.
"""

from PySide6.QtWidgets import QListWidget, QListWidgetItem

from elysium.ui import shell


def test_fit_nav_list_width_fits_the_widest_item(qtbot):
    nav_list = QListWidget()
    qtbot.addWidget(nav_list)
    nav_list.addItem(QListWidgetItem("Dashboard"))
    nav_list.addItem(QListWidgetItem("Shared Sealed Prices"))
    nav_list.addItem(QListWidgetItem("Logout"))

    shell._fit_nav_list_width(nav_list)

    metrics = nav_list.fontMetrics()
    widest = metrics.horizontalAdvance("Shared Sealed Prices")
    assert nav_list.width() == widest + 50


def test_fit_nav_list_width_grows_for_a_longer_item_than_the_old_160px_cap(qtbot):
    nav_list = QListWidget()
    qtbot.addWidget(nav_list)
    # This is exactly the kind of label that used to get truncated under
    # the old fixed 160px cap.
    nav_list.addItem(QListWidgetItem("Decommissioning"))

    shell._fit_nav_list_width(nav_list)

    assert nav_list.width() >= nav_list.fontMetrics().horizontalAdvance("Decommissioning")


def test_fit_nav_list_width_handles_empty_list(qtbot):
    nav_list = QListWidget()
    qtbot.addWidget(nav_list)

    shell._fit_nav_list_width(nav_list)  # must not raise

    assert nav_list.width() == 50


def test_guest_shell_nav_list_is_not_capped_at_160(qtbot, monkeypatch):
    monkeypatch.setattr(shell, "CardLookupTab", lambda: shell.QWidget())

    guest_shell = shell.GuestShell(on_login_requested=lambda: None)
    qtbot.addWidget(guest_shell)

    assert guest_shell.nav_list.maximumWidth() != 160
