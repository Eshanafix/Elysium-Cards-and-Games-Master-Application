"""
Magic Card Lookup tab (LLD section 21).

Ported from the reference Elysium Card LookUp project's app.py. Available to
guests and logged-in users alike, with no MongoDB dependency at all — every
search happens against the local cards.sqlite (LLD 21.1/21.2).

Changes from the reference implementation:
- Paths come from local_card.paths (%LOCALAPPDATA%) instead of CWD-relative
  constants, so the tab works correctly once packaged/installed (LLD 26.3-
  derived requirement).
- A separate first-run "setup" window is gone; an empty/never-refreshed
  database is just another state this widget renders inline.
- Added the persistent stale-data banner required by LLD 21.5 (>24h since
  last successful local refresh), backed by local_card.db's local_meta
  table via ScryfallRefreshWorker's safe-swap rebuild.
"""

import shutil

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from elysium.config import STALE_CARD_DATA_HOURS
from elysium.local_card import db, paths
from elysium.local_card.image_cache import get_cached_card_image_path
from elysium.services.scryfall_service import ScryfallRefreshWorker
from elysium.ui.background import run_worker, safe_callback
from elysium.ui.dialog_sizing import clamp_to_screen
from elysium.ui.grid_stretch import apply_trailing_stretch

YELLOW_THRESHOLD = 2.00
GREEN_THRESHOLD = 5.00
PAGE_SIZE = 50

STALE_DATA_MESSAGE = (
    f"Card data was last refreshed more than {STALE_CARD_DATA_HOURS} hours ago. "
    f"Prices may be outdated."
)
NEVER_REFRESHED_MESSAGE = (
    "No local card data yet. Click Refresh Card Data to download the current Magic card database."
)


class SetFilterDialog(QDialog):
    def __init__(self, parent, selected_set_codes, selected_card_codes, zoom):
        super().__init__(parent)

        self.setWindowTitle("Choose Sets")
        clamp_to_screen(self, 650, 700)

        self.selected_set_codes = set(selected_set_codes)
        self.result_set_codes = set(selected_set_codes)
        self.selected_card_codes = set(selected_card_codes)
        self.result_card_codes = set(selected_card_codes)
        self.zoom = zoom

        layout = QVBoxLayout()

        self.title = QLabel("Filters")

        self.tabs = QTabWidget()

        self.set_tab = QWidget()
        set_tab_layout = QVBoxLayout()

        self.enabled_sets_label = QLabel("Currently Selected:\nAll Sets")
        self.enabled_sets_label.setWordWrap(True)
        self.enabled_sets_label.setMinimumHeight(80)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search sets...")

        self.set_list = QListWidget()
        self.set_list.setSelectionMode(QAbstractItemView.MultiSelection)

        set_button_row = QHBoxLayout()
        self.apply_button = QPushButton("Apply Sets")
        self.clear_button = QPushButton("Clear Sets")
        self.close_button = QPushButton("Close")

        set_button_row.addWidget(self.apply_button)
        set_button_row.addWidget(self.clear_button)
        set_button_row.addWidget(self.close_button)

        set_tab_layout.addWidget(self.enabled_sets_label)
        set_tab_layout.addWidget(self.search)
        set_tab_layout.addWidget(self.set_list)
        set_tab_layout.addLayout(set_button_row)

        self.set_tab.setLayout(set_tab_layout)

        self.code_tab = QWidget()
        code_tab_layout = QVBoxLayout()

        self.enabled_codes_label = QLabel("Collector # Filter:\nNone")
        self.enabled_codes_label.setWordWrap(True)
        self.enabled_codes_label.setMinimumHeight(60)

        self.code_input = QTextEdit()
        self.code_input.setPlaceholderText(
            "Enter collector numbers, separated by commas or new lines.\nExample:\n123\n124\n390"
        )

        code_button_row = QHBoxLayout()
        self.apply_codes_button = QPushButton("Apply Card Codes")
        self.clear_codes_button = QPushButton("Clear Card Codes")

        code_button_row.addWidget(self.apply_codes_button)
        code_button_row.addWidget(self.clear_codes_button)

        code_tab_layout.addWidget(self.enabled_codes_label)
        code_tab_layout.addWidget(self.code_input)
        code_tab_layout.addLayout(code_button_row)

        self.code_tab.setLayout(code_tab_layout)

        self.settings_tab = QWidget()
        settings_layout = QVBoxLayout()

        self.settings_warning = QLabel(
            "Total Reset will delete the local card database, image cache, and\n"
            "downloaded bulk data on this computer. Other computers are unaffected.\n\n"
            "You'll need to press Refresh Card Data again afterward."
        )
        self.settings_warning.setWordWrap(True)

        self.reset_button = QPushButton("Total Reset Local Card Data")
        self.confirm_reset_button = QPushButton("Are You Sure? Confirm Reset")
        self.confirm_reset_button.setVisible(False)

        settings_layout.addWidget(self.settings_warning)
        settings_layout.addWidget(self.reset_button)
        settings_layout.addWidget(self.confirm_reset_button)
        settings_layout.addStretch()

        self.settings_tab.setLayout(settings_layout)

        self.tabs.addTab(self.set_tab, "Sets")
        self.tabs.addTab(self.code_tab, "Card Codes")
        self.tabs.addTab(self.settings_tab, "Settings")

        layout.addWidget(self.title)
        layout.addWidget(self.tabs)

        self.setLayout(layout)

        self.search.textChanged.connect(self.filter_set_list)

        self.apply_button.clicked.connect(self.apply_filter)
        self.clear_button.clicked.connect(self.clear_filter)
        self.close_button.clicked.connect(self.reject)

        self.apply_codes_button.clicked.connect(self.apply_card_code_filter)
        self.clear_codes_button.clicked.connect(self.clear_card_code_filter)
        self.reset_button.clicked.connect(self.show_reset_confirmation)
        self.confirm_reset_button.clicked.connect(self.total_reset_application)

        self.apply_style()
        self.load_set_options()
        self.load_card_codes()

    def apply_style(self):
        self.setStyleSheet(f"""
            QDialog {{ background-color: white; }}
            QLabel {{ color: white; }}
            QLineEdit {{
                font-size: {int(16 * self.zoom)}px;
                padding: {int(8 * self.zoom)}px;
                color: black;
                background-color: white;
                border: 1px solid gray;
                border-radius: {int(6 * self.zoom)}px;
            }}
            QListWidget {{
                font-size: {int(14 * self.zoom)}px;
                color: black;
                background-color: white;
                border: 1px solid gray;
            }}
            QListWidget::item:selected {{
                background-color: #87CEFA;
                color: black;
            }}
            QPushButton {{
                font-size: {int(14 * self.zoom)}px;
                padding: {int(8 * self.zoom)}px;
                color: black;
                background-color: #eeeeee;
                border: 1px solid gray;
                border-radius: {int(6 * self.zoom)}px;
            }}
        """)

        self.title.setStyleSheet(f"font-size: {int(22 * self.zoom)}px; font-weight: bold; color: white;")

        label_style = f"""
            font-size: {int(13 * self.zoom)}px;
            color: black;
            background-color: #f0f0f0;
            border: 1px solid gray;
            border-radius: {int(5 * self.zoom)}px;
            padding: {int(8 * self.zoom)}px;
            min-height: {int(80 * self.zoom)}px;
        """
        self.enabled_sets_label.setStyleSheet(label_style)
        self.enabled_codes_label.setStyleSheet(label_style)

        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: 1px solid gray; background-color: white; }}
            QTabBar::tab {{
                font-size: {int(14 * self.zoom)}px;
                padding: {int(8 * self.zoom)}px;
                color: black;
                background-color: #dddddd;
            }}
            QTabBar::tab:selected {{ background-color: #ffffff; font-weight: bold; }}
        """)

        self.code_input.setStyleSheet(f"""
            font-size: {int(14 * self.zoom)}px;
            color: black;
            background-color: white;
            border: 1px solid gray;
        """)

        self.settings_warning.setStyleSheet(f"""
            font-size: {int(14 * self.zoom)}px;
            color: black;
            background-color: #fff3cd;
            border: 1px solid #cc9900;
            border-radius: {int(6 * self.zoom)}px;
            padding: {int(10 * self.zoom)}px;
        """)

        self.reset_button.setStyleSheet(f"""
            QPushButton {{
                font-size: {int(14 * self.zoom)}px;
                padding: {int(10 * self.zoom)}px;
                color: white;
                background-color: #b00020;
                border: 1px solid #700000;
                border-radius: {int(6 * self.zoom)}px;
                font-weight: bold;
            }}
        """)

        self.confirm_reset_button.setStyleSheet(f"""
            QPushButton {{
                font-size: {int(14 * self.zoom)}px;
                padding: {int(10 * self.zoom)}px;
                color: white;
                background-color: #ff0000;
                border: 2px solid #700000;
                border-radius: {int(6 * self.zoom)}px;
                font-weight: bold;
            }}
        """)

    def load_set_options(self):
        self.set_list.clear()

        for set_code, set_name, row_count in db.get_set_options(paths.get_db_path()):
            label = f"{set_name} ({set_code.upper()}) — {row_count} versions"

            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, set_code)
            self.set_list.addItem(item)

            if set_code in self.selected_set_codes:
                item.setSelected(True)

        self.update_enabled_sets_label()

    def load_card_codes(self):
        if self.selected_card_codes:
            self.code_input.setPlainText("\n".join(sorted(self.selected_card_codes)))

        self.update_enabled_codes_label()

    def parse_card_codes(self):
        raw_text = self.code_input.toPlainText()
        parts = raw_text.replace(",", "\n").replace(";", "\n").splitlines()
        return {part.strip() for part in parts if part.strip()}

    def update_enabled_codes_label(self):
        if not self.result_card_codes:
            self.enabled_codes_label.setText("Collector # Filter:\nNone")
            return

        text = ", ".join(sorted(self.result_card_codes))
        self.enabled_codes_label.setText(f"Collector # Filter:\n{text}")

    def apply_card_code_filter(self):
        self.result_card_codes = self.parse_card_codes()
        self.update_enabled_codes_label()

        if self.parent():
            self.parent().selected_card_codes = self.result_card_codes
            self.parent().current_limit = PAGE_SIZE
            self.parent().load_cards()
            self.parent().update_filter_status()

    def clear_card_code_filter(self):
        self.result_card_codes = set()
        self.code_input.clear()
        self.update_enabled_codes_label()

        if self.parent():
            self.parent().selected_card_codes = set()
            self.parent().current_limit = PAGE_SIZE
            self.parent().load_cards()
            self.parent().update_filter_status()

    def show_reset_confirmation(self):
        self.confirm_reset_button.setVisible(True)
        self.reset_button.setText("Reset requested...")

    def total_reset_application(self):
        try:
            if self.parent():
                self.parent().selected_set_codes = set()
                self.parent().selected_card_codes = set()
                self.parent().cards = []
                self.parent().clear_grid()

            db_path = paths.get_db_path()
            if db_path.exists():
                db_path.unlink()

            for directory in (paths.get_cache_dir(), paths.get_data_dir()):
                if directory.exists():
                    shutil.rmtree(directory)

            self.confirm_reset_button.setVisible(False)
            self.reset_button.setText("Reset Complete")

            if self.parent():
                self.parent().status_label.setText(
                    "Local card data reset. Click Refresh Card Data to download it again."
                )
                self.parent().update_stale_banner()
                self.parent().update_filter_status()

            self.close()

        except Exception as e:
            if self.parent():
                self.parent().status_label.setText(f"Reset failed: {e}")

    def filter_set_list(self):
        search_text = self.search.text().lower().strip()

        for i in range(self.set_list.count()):
            item = self.set_list.item(i)
            item.setHidden(search_text not in item.text().lower())

    def get_selected_set_codes(self):
        return {item.data(Qt.UserRole) for item in self.set_list.selectedItems()}

    def update_enabled_sets_label(self):
        selected_items = self.set_list.selectedItems()

        if not selected_items:
            self.enabled_sets_label.setText("Currently Selected:\nAll Sets")
            return

        names = [item.text().split(" — ")[0] for item in selected_items]
        self.enabled_sets_label.setText(f"Currently Selected:\n{', '.join(names)}")

    def apply_filter(self):
        self.result_set_codes = self.get_selected_set_codes()
        self.update_enabled_sets_label()

        if self.parent():
            self.parent().selected_set_codes = self.result_set_codes
            self.parent().current_limit = PAGE_SIZE
            self.parent().load_cards()
            self.parent().update_filter_status()

    def clear_filter(self):
        self.result_set_codes = set()
        self.set_list.clearSelection()
        self.update_enabled_sets_label()

        if self.parent():
            self.parent().selected_set_codes = set()
            self.parent().current_limit = PAGE_SIZE
            self.parent().load_cards()
            self.parent().update_filter_status()


# Decoding + scaling a card image from disk measured ~7-8ms/card -- with up
# to PAGE_SIZE tiles rebuilt on every debounced keystroke (search results
# usually overlap heavily between "light" and "lightning"), that's the
# single biggest contributor to the reported typing lag. Caching the scaled
# QPixmap by (row_id, size) means a card seen in an earlier search reuses
# the already-decoded pixmap instead of hitting disk again. Capped so a
# long session searching through many different cards doesn't grow this
# unboundedly; simplest safe eviction is just clearing it outright once full,
# no LRU bookkeeping needed for a cache that's cheap to refill.
_PIXMAP_CACHE_MAX = 800
_pixmap_cache: dict[tuple[str, int, int], QPixmap] = {}


def _get_scaled_card_pixmap(row_id: str, width: int, height: int) -> QPixmap | None:
    key = (row_id, width, height)
    cached = _pixmap_cache.get(key)

    if cached is not None:
        return cached

    image_path = get_cached_card_image_path(row_id, paths.get_cache_dir())

    if not image_path:
        return None

    pixmap = QPixmap(str(image_path)).scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    if len(_pixmap_cache) >= _PIXMAP_CACHE_MAX:
        _pixmap_cache.clear()

    _pixmap_cache[key] = pixmap
    return pixmap


class CardTile(QFrame):
    def __init__(self, card, zoom):
        super().__init__()

        (
            row_id, name, set_code, collector_number, rarity,
            printing_details, finish, price, full_art, image_url,
        ) = card

        card_width = int(220 * zoom)
        image_width = int(146 * zoom)
        image_height = int(204 * zoom)

        self.setFixedWidth(card_width)

        if price is not None and price >= GREEN_THRESHOLD:
            background = "#90EE90"
        elif price is not None and price >= YELLOW_THRESHOLD:
            background = "#FFF59D"
        else:
            background = "#FFFFFF"

        self.setStyleSheet(f"""
            QFrame {{
                background-color: {background};
                border: 1px solid #999999;
                border-radius: {int(8 * zoom)}px;
                padding: {int(8 * zoom)}px;
            }}
            QLabel {{ color: black; background-color: transparent; border: none; }}
        """)

        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignTop)
        layout.setSpacing(int(5 * zoom))

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignCenter)

        pixmap = _get_scaled_card_pixmap(row_id, image_width, image_height)

        if pixmap is not None:
            image_label.setPixmap(pixmap)
        else:
            image_label.setText("No Image")

        name_label = QLabel(name)
        name_label.setWordWrap(True)
        name_label.setStyleSheet(f"font-weight: bold; font-size: {int(13 * zoom)}px;")

        details_label = QLabel(printing_details or "Regular")
        details_label.setWordWrap(True)
        details_label.setStyleSheet(f"font-size: {int(11 * zoom)}px;")

        finish_label = QLabel(f"{finish} • {set_code.upper()} #{collector_number}")
        finish_label.setWordWrap(True)
        finish_label.setStyleSheet(f"font-size: {int(11 * zoom)}px;")

        rarity_label = QLabel(rarity.title() if rarity else "")
        rarity_label.setStyleSheet(f"font-size: {int(11 * zoom)}px;")

        price_label = QLabel(f"${price:.2f}" if price is not None else "No price")
        price_label.setStyleSheet(f"font-weight: bold; font-size: {int(14 * zoom)}px;")

        layout.addWidget(image_label)
        layout.addWidget(name_label)
        layout.addWidget(details_label)
        layout.addWidget(finish_label)
        layout.addWidget(rarity_label)
        layout.addWidget(price_label)

        self.setLayout(layout)


class CardLookupTab(QWidget):
    def __init__(self):
        super().__init__()

        self.zoom = 1.0
        self.cards = []
        self.refresh_worker = None
        self._grid_stretch_state: dict = {}
        self.selected_set_codes = set()
        self.selected_card_codes = set()
        self.current_limit = PAGE_SIZE
        self.total_matches = 0

        main_layout = QVBoxLayout()

        self.title = QLabel("Magic Card Lookup")

        self.stale_banner = QLabel()
        self.stale_banner.setWordWrap(True)
        self.stale_banner.setVisible(False)
        self.stale_refresh_button = QPushButton("Refresh Card Data")
        self.stale_refresh_button.clicked.connect(self.refresh_card_data)

        stale_row = QHBoxLayout()
        stale_row.addWidget(self.stale_banner, stretch=1)
        stale_row.addWidget(self.stale_refresh_button)
        self.stale_banner_container = QWidget()
        self.stale_banner_container.setLayout(stale_row)
        self.stale_banner_container.setVisible(False)

        top_row = QHBoxLayout()

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search card name...")

        self.filter_button = QPushButton("Apply Filter")
        self.filter_button.clicked.connect(self.open_filter_dialog)

        self.clear_filters_button = QPushButton("Clear Filters")
        self.clear_filters_button.clicked.connect(self.clear_all_filters)
        self.clear_filters_button.setVisible(False)

        self.refresh_button = QPushButton("Refresh Card Data")
        self.refresh_button.clicked.connect(self.refresh_card_data)

        top_row.addWidget(self.search_bar)
        top_row.addWidget(self.filter_button)
        top_row.addWidget(self.clear_filters_button)
        top_row.addWidget(self.refresh_button)

        self.status_label = QLabel("Ready")
        self.filter_status_label = QLabel("Enabled Sets: All Sets")

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)

        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.load_cards)
        self.search_bar.textChanged.connect(self.schedule_search)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)

        self.grid_container = QWidget()
        self.grid_layout = QGridLayout()
        self.grid_container.setLayout(self.grid_layout)
        self.scroll_area.setWidget(self.grid_container)

        self.load_more_button = QPushButton("Load More")
        self.load_more_button.clicked.connect(self.load_more_cards)

        main_layout.addWidget(self.title)
        main_layout.addWidget(self.stale_banner_container)
        main_layout.addLayout(top_row)
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(self.filter_status_label)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.scroll_area)
        main_layout.addWidget(self.load_more_button)

        self.setLayout(main_layout)

        QShortcut(QKeySequence("Ctrl++"), self, activated=self.zoom_in)
        QShortcut(QKeySequence("Ctrl+="), self, activated=self.zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self, activated=self.zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self, activated=self.reset_zoom)

        paths.ensure_app_dirs()
        # Idempotent (CREATE TABLE/INDEX IF NOT EXISTS) -- backfills the
        # name-search index onto a database created before it existed,
        # without requiring a full Refresh Card Data cycle first.
        if paths.get_db_path().exists():
            db.create_database(paths.get_db_path())

        # Re-check staleness periodically so the banner appears without
        # requiring the user to restart the app mid-session.
        self.stale_check_timer = QTimer()
        self.stale_check_timer.timeout.connect(self.update_stale_banner)
        self.stale_check_timer.start(5 * 60 * 1000)

        self.apply_zoom()
        self.update_filter_status()
        self.update_stale_banner()
        self.load_cards()

    def open_filter_dialog(self):
        if hasattr(self, "filter_dialog"):
            self.filter_dialog.show()
            self.filter_dialog.raise_()
            self.filter_dialog.activateWindow()
            return

        self.filter_dialog = SetFilterDialog(
            parent=self,
            selected_set_codes=self.selected_set_codes,
            selected_card_codes=self.selected_card_codes,
            zoom=self.zoom,
        )
        self.filter_dialog.show()

    def clear_all_filters(self):
        self.selected_set_codes = set()
        self.selected_card_codes = set()
        self.current_limit = PAGE_SIZE

        if hasattr(self, "filter_dialog"):
            self.filter_dialog.result_set_codes = set()
            self.filter_dialog.result_card_codes = set()
            self.filter_dialog.set_list.clearSelection()
            self.filter_dialog.code_input.clear()
            self.filter_dialog.update_enabled_sets_label()
            self.filter_dialog.update_enabled_codes_label()

        self.update_filter_status()
        self.load_cards()

    def update_filter_status(self):
        if not self.selected_set_codes:
            sets_text = "All Sets"
        else:
            names = [
                f"{set_name} ({set_code.upper()})"
                for set_code, set_name, _ in db.get_set_options(paths.get_db_path())
                if set_code in self.selected_set_codes
            ]

            if len(names) <= 3:
                sets_text = ", ".join(names)
            else:
                sets_text = ", ".join(names[:3]) + f" + {len(names) - 3} more"

        parts = [f"Enabled Sets: {sets_text}"]

        if self.selected_card_codes:
            codes = sorted(self.selected_card_codes)
            codes_text = ", ".join(codes) if len(codes) <= 5 else ", ".join(codes[:5]) + f" + {len(codes) - 5} more"
            parts.append(f"Card Codes: {codes_text}")

        self.filter_status_label.setText(" | ".join(parts))
        self.clear_filters_button.setVisible(bool(self.selected_set_codes or self.selected_card_codes))

    def update_stale_banner(self):
        last_refresh = db.get_last_successful_refresh_at(paths.get_db_path())

        if last_refresh is None:
            self.stale_banner.setText(NEVER_REFRESHED_MESSAGE)
            self.stale_banner_container.setVisible(True)
            return

        if db.is_stale(last_refresh, STALE_CARD_DATA_HOURS):
            self.stale_banner.setText(STALE_DATA_MESSAGE)
            self.stale_banner_container.setVisible(True)
        else:
            self.stale_banner_container.setVisible(False)

    def refresh_card_data(self):
        self.refresh_button.setEnabled(False)
        self.stale_refresh_button.setEnabled(False)

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("Starting refresh...")

        self.refresh_worker = ScryfallRefreshWorker()
        self.refresh_worker.progress.connect(safe_callback(self.progress_bar.setValue))
        self.refresh_worker.status.connect(safe_callback(self.status_label.setText))
        self.refresh_worker.finished_success.connect(safe_callback(self.refresh_finished))
        self.refresh_worker.failed.connect(safe_callback(self.refresh_failed))
        run_worker(self.refresh_worker)

    def refresh_finished(self):
        self.refresh_button.setEnabled(True)
        self.stale_refresh_button.setEnabled(True)

        self.progress_bar.setValue(100)
        self.status_label.setText("Card data and image refresh complete.")

        QTimer.singleShot(1500, self.hide_progress_bar)

        self.update_stale_banner()
        self.update_filter_status()
        self.load_cards()

    def refresh_failed(self, error):
        self.refresh_button.setEnabled(True)
        self.stale_refresh_button.setEnabled(True)
        self.status_label.setText(f"Refresh failed: {error}")

    def hide_progress_bar(self):
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)

    def apply_zoom(self):
        self.title.setStyleSheet(f"font-size: {int(26 * self.zoom)}px; font-weight: bold; color: white;")

        self.search_bar.setStyleSheet(f"""
            QLineEdit {{
                font-size: {int(18 * self.zoom)}px;
                padding: {int(8 * self.zoom)}px;
                color: black;
                background-color: white;
                border: 1px solid gray;
                border-radius: {int(6 * self.zoom)}px;
            }}
        """)

        button_style = f"""
            QPushButton {{
                font-size: {int(14 * self.zoom)}px;
                padding: {int(8 * self.zoom)}px;
                color: black;
                background-color: #eeeeee;
                border: 1px solid gray;
                border-radius: {int(6 * self.zoom)}px;
            }}
        """
        self.filter_button.setStyleSheet(button_style)
        self.refresh_button.setStyleSheet(button_style)
        self.stale_refresh_button.setStyleSheet(button_style)

        self.status_label.setStyleSheet(f"font-size: {int(13 * self.zoom)}px; color: white;")

        self.stale_banner.setStyleSheet(f"""
            font-size: {int(13 * self.zoom)}px;
            color: black;
            background-color: #fff3cd;
            border: 1px solid #cc9900;
            border-radius: {int(5 * self.zoom)}px;
            padding: {int(8 * self.zoom)}px;
        """)

        self.filter_status_label.setStyleSheet(f"""
            font-size: {int(13 * self.zoom)}px;
            color: black;
            background-color: #f0f0f0;
            border: 1px solid gray;
            border-radius: {int(5 * self.zoom)}px;
            padding: {int(6 * self.zoom)}px;
        """)

        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                font-size: {int(12 * self.zoom)}px;
                color: black;
                border: 1px solid gray;
                border-radius: {int(4 * self.zoom)}px;
                text-align: center;
                height: {int(18 * self.zoom)}px;
            }}
        """)

        self.grid_layout.setSpacing(int(12 * self.zoom))

    def zoom_in(self):
        self.zoom = min(2.5, round(self.zoom + 0.1, 2))
        self.apply_zoom()
        self.rebuild_grid()

    def zoom_out(self):
        self.zoom = max(0.6, round(self.zoom - 0.1, 2))
        self.apply_zoom()
        self.rebuild_grid()

    def reset_zoom(self):
        self.zoom = 1.0
        self.apply_zoom()
        self.rebuild_grid()

    def schedule_search(self):
        self.current_limit = PAGE_SIZE
        self.search_timer.start(150)

    def clear_grid(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def load_cards(self):
        self.cards, self.total_matches = db.search_cards(
            paths.get_db_path(),
            search_text=self.search_bar.text(),
            set_codes=self.selected_set_codes,
            collector_numbers=self.selected_card_codes,
            limit=self.current_limit,
        )
        self.rebuild_grid()

        shown = len(self.cards)
        self.status_label.setText(f"Showing {shown} of {self.total_matches} matches")
        self.load_more_button.setVisible(shown < self.total_matches)

    def load_more_cards(self):
        self.current_limit += PAGE_SIZE
        self.load_cards()

    def rebuild_grid(self):
        self.clear_grid()

        card_width = int(220 * self.zoom)
        spacing = int(30 * self.zoom)

        available_width = self.scroll_area.viewport().width()
        columns = max(1, available_width // (card_width + spacing))

        row = -1
        for index, card in enumerate(self.cards):
            tile = CardTile(card, self.zoom)
            row = index // columns
            col = index % columns
            self.grid_layout.addWidget(tile, row, col)

        apply_trailing_stretch(self.grid_layout, self._grid_stretch_state, row + 1, columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)

        if hasattr(self, "cards"):
            self.rebuild_grid()
