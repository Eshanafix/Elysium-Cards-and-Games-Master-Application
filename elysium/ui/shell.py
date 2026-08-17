"""
Main application window (LLD section 24).
"""

from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from elysium.config import APP_NAME
from elysium.models.users import ROLE_ADMIN, ROLE_STREAMER
from elysium.ui.account import AccountScreen
from elysium.ui.app_updates import AppUpdatesScreen
from elysium.ui.audit import AuditHistoryScreen
from elysium.ui.card_lookup import CardLookupTab
from elysium.ui.corrections import StreamCorrectionsScreen
from elysium.ui.dashboard import DashboardScreen
from elysium.ui.decommissioning import DecommissioningScreen
from elysium.ui.dialog_sizing import clamp_to_screen
from elysium.ui.discrepancies import DiscrepanciesScreen
from elysium.ui.inventory_master import MasterInventoryScreen
from elysium.ui.inventory_streamer import MyInventoryScreen, StreamerInventoryAdminScreen
from elysium.ui.login import LoginScreen
from elysium.ui.prices import PricesScreen
from elysium.ui.products import ProductsScreen
from elysium.ui.reports import ReportsScreen
from elysium.ui.streams import StreamResumePromptDialog, StreamsScreen
from elysium.ui.users import UsersScreen
from elysium.repositories import streamer_repository as streamer_repo
from elysium.services import lock_service, stream_service

NAV_CARD_LOOKUP = "Card Lookup"
NAV_LOGIN = "Login"
NAV_DASHBOARD = "Dashboard"
NAV_MASTER_INVENTORY = "Master Inventory"
NAV_MY_INVENTORY = "My Inventory"
NAV_STREAMER_INVENTORY = "Streamer Inventory"
NAV_STREAMS = "Streams"
NAV_CORRECTIONS = "Correct Stream"
NAV_DECOMMISSIONING = "Decommissioning"
NAV_DISCREPANCIES = "Discrepancies"
NAV_PRODUCTS = "Product Catalog"
NAV_PRICES = "Shared Sealed Prices"
NAV_REPORTS = "Reports"
NAV_AUDIT_HISTORY = "Audit History"
NAV_ACCOUNT = "Account"
NAV_USERS = "Users"
NAV_APP_UPDATES = "App Updates"
NAV_LOGOUT = "Logout"


def _fit_nav_list_width(nav_list: QListWidget) -> None:
    """A hardcoded 160px assumed a particular font/DPI -- fine on the
    monitor this was built on, but at a different effective UI scale (a
    smaller laptop screen, different OS-level display scaling, etc.) the
    longer labels ("Master Inventory", "Shared Sealed Prices") don't fit
    and get truncated mid-word instead. Size to whatever's actually needed
    for the widest item currently in the list, at the list's real font."""
    metrics = nav_list.fontMetrics()
    widest = max((metrics.horizontalAdvance(nav_list.item(i).text()) for i in range(nav_list.count())), default=0)
    nav_list.setFixedWidth(widest + 50)


class GuestShell(QWidget):
    def __init__(self, on_login_requested):
        super().__init__()

        self.on_login_requested = on_login_requested

        layout = QHBoxLayout()

        self.nav_list = QListWidget()
        self.nav_list.addItem(QListWidgetItem(NAV_CARD_LOOKUP))
        self.nav_list.addItem(QListWidgetItem(NAV_LOGIN))
        _fit_nav_list_width(self.nav_list)
        self.nav_list.currentTextChanged.connect(self.on_nav_changed)

        self.content = QStackedWidget()
        self.card_lookup_tab = CardLookupTab()
        self.content.addWidget(self.card_lookup_tab)

        layout.addWidget(self.nav_list)
        layout.addWidget(self.content, stretch=1)

        self.setLayout(layout)

        self.nav_list.setCurrentRow(0)

    def on_nav_changed(self, label: str):
        if label == NAV_LOGIN:
            self.on_login_requested()
        else:
            self.content.setCurrentWidget(self.card_lookup_tab)


class AppShell(QWidget):
    """Nav + content for a logged-in user, scoped to whatever that user's
    roles actually grant screens for right now."""

    def __init__(self, user, on_logout):
        super().__init__()

        self.user = user
        self.on_logout = on_logout

        layout = QHBoxLayout()

        self.nav_list = QListWidget()

        # Dashboard always first, then ordered by actual usage frequency.
        # Streamers now get read-only Master Inventory visibility too (LLD
        # "only admin changes master total" still holds -- the screen
        # itself hides the Add/Reduce actions for a non-admin viewer).
        nav_items = [NAV_DASHBOARD, NAV_MASTER_INVENTORY]

        if ROLE_ADMIN in user.roles:
            nav_items.append(NAV_STREAMER_INVENTORY)
            nav_items.append(NAV_PRODUCTS)

        if ROLE_STREAMER in user.roles:
            nav_items.append(NAV_MY_INVENTORY)

        nav_items.append(NAV_PRICES)
        nav_items.append(NAV_CARD_LOOKUP)

        if ROLE_ADMIN in user.roles:
            nav_items.append(NAV_AUDIT_HISTORY)

        if ROLE_STREAMER in user.roles:
            nav_items.append(NAV_STREAMS)

        if ROLE_ADMIN in user.roles:
            nav_items.append(NAV_CORRECTIONS)
            nav_items.append(NAV_DECOMMISSIONING)
            nav_items.append(NAV_DISCREPANCIES)

        nav_items.append(NAV_REPORTS)

        if ROLE_ADMIN in user.roles:
            nav_items.append(NAV_USERS)
            nav_items.append(NAV_APP_UPDATES)

        nav_items.append(NAV_ACCOUNT)
        nav_items.append(NAV_LOGOUT)

        for label in nav_items:
            self.nav_list.addItem(QListWidgetItem(label))

        _fit_nav_list_width(self.nav_list)
        self.nav_list.currentTextChanged.connect(self.on_nav_changed)

        self.content = QStackedWidget()

        self.dashboard_screen = DashboardScreen(user, on_logout=on_logout)
        self.prices_screen = PricesScreen(user)
        self.card_lookup_tab = CardLookupTab()
        self.account_screen = AccountScreen(user)
        self.reports_screen = ReportsScreen(user)

        self.content.addWidget(self.dashboard_screen)
        self.content.addWidget(self.prices_screen)
        self.content.addWidget(self.card_lookup_tab)
        self.content.addWidget(self.account_screen)
        self.content.addWidget(self.reports_screen)

        self.users_screen = None
        self.app_updates_screen = None
        self.products_screen = None
        self.streamer_inventory_admin_screen = None
        self.my_inventory_screen = None
        self.corrections_screen = None
        self.decommissioning_screen = None
        self.discrepancies_screen = None
        self.audit_history_screen = None

        # Read-only for a streamer viewer -- MasterInventoryScreen itself
        # hides the Add/Reduce actions unless the user is an admin.
        self.master_inventory_screen = MasterInventoryScreen(user)
        self.content.addWidget(self.master_inventory_screen)

        if ROLE_ADMIN in user.roles:
            self.users_screen = UsersScreen(user)
            self.content.addWidget(self.users_screen)

            self.app_updates_screen = AppUpdatesScreen(user)
            self.content.addWidget(self.app_updates_screen)

            self.products_screen = ProductsScreen(user)
            self.content.addWidget(self.products_screen)

            self.streamer_inventory_admin_screen = StreamerInventoryAdminScreen(user)
            self.content.addWidget(self.streamer_inventory_admin_screen)

            self.corrections_screen = StreamCorrectionsScreen(user)
            self.content.addWidget(self.corrections_screen)

            self.decommissioning_screen = DecommissioningScreen(user)
            self.content.addWidget(self.decommissioning_screen)

            self.discrepancies_screen = DiscrepanciesScreen(user)
            self.content.addWidget(self.discrepancies_screen)

            self.audit_history_screen = AuditHistoryScreen(user)
            self.content.addWidget(self.audit_history_screen)

        self.streams_screen = None

        if ROLE_STREAMER in user.roles:
            self.my_inventory_screen = MyInventoryScreen(user)
            self.content.addWidget(self.my_inventory_screen)

            self.streams_screen = StreamsScreen(user)
            self.content.addWidget(self.streams_screen)

        layout.addWidget(self.nav_list)
        layout.addWidget(self.content, stretch=1)

        self.setLayout(layout)

        self.nav_list.setCurrentRow(0)

    def on_nav_changed(self, label: str):
        if label == NAV_LOGOUT:
            self.on_logout()
        elif label == NAV_DASHBOARD:
            self.dashboard_screen.refresh()
            self.content.setCurrentWidget(self.dashboard_screen)
        elif label == NAV_MASTER_INVENTORY and self.master_inventory_screen is not None:
            self.master_inventory_screen.reload()
            self.content.setCurrentWidget(self.master_inventory_screen)
        elif label == NAV_STREAMER_INVENTORY and self.streamer_inventory_admin_screen is not None:
            self.streamer_inventory_admin_screen.reload()
            self.content.setCurrentWidget(self.streamer_inventory_admin_screen)
        elif label == NAV_MY_INVENTORY and self.my_inventory_screen is not None:
            self.my_inventory_screen.reload()
            self.content.setCurrentWidget(self.my_inventory_screen)
        elif label == NAV_STREAMS and self.streams_screen is not None:
            self.streams_screen.reload()
            self.content.setCurrentWidget(self.streams_screen)
        elif label == NAV_CORRECTIONS and self.corrections_screen is not None:
            self.corrections_screen.reload()
            self.content.setCurrentWidget(self.corrections_screen)
        elif label == NAV_DECOMMISSIONING and self.decommissioning_screen is not None:
            self.decommissioning_screen.reload()
            self.content.setCurrentWidget(self.decommissioning_screen)
        elif label == NAV_DISCREPANCIES and self.discrepancies_screen is not None:
            self.discrepancies_screen.reload()
            self.content.setCurrentWidget(self.discrepancies_screen)
        elif label == NAV_REPORTS:
            self.reports_screen.reload()
            self.content.setCurrentWidget(self.reports_screen)
        elif label == NAV_AUDIT_HISTORY and self.audit_history_screen is not None:
            self.audit_history_screen.reload_streamers()
            self.audit_history_screen.reload()
            self.content.setCurrentWidget(self.audit_history_screen)
        elif label == NAV_PRODUCTS and self.products_screen is not None:
            self.products_screen.reload_products()
            self.content.setCurrentWidget(self.products_screen)
        elif label == NAV_PRICES:
            self.prices_screen.reload_prices()
            self.content.setCurrentWidget(self.prices_screen)
        elif label == NAV_CARD_LOOKUP:
            self.content.setCurrentWidget(self.card_lookup_tab)
        elif label == NAV_ACCOUNT:
            self.content.setCurrentWidget(self.account_screen)
        elif label == NAV_USERS and self.users_screen is not None:
            self.users_screen.reload_users()
            self.content.setCurrentWidget(self.users_screen)
        elif label == NAV_APP_UPDATES and self.app_updates_screen is not None:
            self.app_updates_screen.reload()
            self.content.setCurrentWidget(self.app_updates_screen)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(APP_NAME)
        clamp_to_screen(self, 1500, 850, margin=40)
        self._center_on_screen()

        self.stacked = QStackedWidget()

        self.login_screen = LoginScreen()
        self.login_screen.guest_requested.connect(self.show_guest_shell)
        self.login_screen.login_succeeded.connect(self.show_app_shell)

        self.guest_shell = GuestShell(on_login_requested=self.show_login)

        self.app_shell = None

        self.stacked.addWidget(self.login_screen)
        self.stacked.addWidget(self.guest_shell)

        self.setCentralWidget(self.stacked)

        self.show_login()

    def _center_on_screen(self):
        """Some window managers place a new top-level window at a screen
        corner by default rather than centering it, which combined with a
        1500x850 window can leave part of it off-screen -- requiring a
        manual drag/resize just to reach the controls."""
        screen = self.screen() or QApplication.primaryScreen()

        if screen is None:
            return

        available = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def show_login(self):
        if self.app_shell is not None:
            self.stacked.removeWidget(self.app_shell)
            self.app_shell.deleteLater()
            self.app_shell = None

        self.login_screen.refresh_connection_status()
        self.stacked.setCurrentWidget(self.login_screen)

    def show_guest_shell(self):
        self.guest_shell.nav_list.setCurrentRow(0)
        self.stacked.setCurrentWidget(self.guest_shell)

    def show_app_shell(self, user):
        if self.app_shell is not None:
            self.stacked.removeWidget(self.app_shell)
            self.app_shell.deleteLater()

        if ROLE_STREAMER in user.roles and user.streamer_database_name:
            self._offer_stream_resume(user)

        self.app_shell = AppShell(user, on_logout=self.show_login)
        self.stacked.addWidget(self.app_shell)
        self.stacked.setCurrentWidget(self.app_shell)

    def _offer_stream_resume(self, user):
        """LLD 16.1: prompt before the normal dashboard appears, not
        something the streamer has to go looking for."""
        stream = stream_service.resume_check(user.streamer_database_name)

        if stream is None:
            return

        breaks = streamer_repo.list_breaks_for_stream(user.streamer_database_name, stream.id)
        dialog = StreamResumePromptDialog(stream, breaks, self)
        dialog.exec()

        if dialog.result_action == "cancel":
            stream_service.cancel_stream(
                stream.id, user.id, user.streamer_database_name, canceled_by=user.id
            )
