"""
Streams screen (LLD sections 13-16, 24.2): Start Stream, the active break
workspace (visual product tiles for pack selection, LLD 14.2/14.3), and
the End Stream review/settlement flow.
"""

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from elysium.models.breaks import STATUS_ACTIVE as BREAK_STATUS_ACTIVE
from elysium.models.breaks import STATUS_DELETED, STATUS_ENDED_EDITABLE
from elysium.repositories import streamer_repository as streamer_repo
from elysium.services import (
    break_service,
    inventory_service,
    lock_service,
    product_service,
    sealed_image_cache_service,
    stream_service,
)
from elysium.ui.background import run_worker, safe_callback
from elysium.ui.dialog_sizing import clamp_to_screen
from elysium.ui.grid_stretch import apply_trailing_stretch
from elysium.ui.prices import PriceRefreshWorker
from elysium.ui.slot_tracker import SlotValueTracker

BREAK_STATUS_LABELS = {
    BREAK_STATUS_ACTIVE: "In Progress",
    STATUS_ENDED_EDITABLE: "Ended",
    STATUS_DELETED: "Deleted",
}


def _pack_summary(break_obj, product_names: dict) -> str:
    """LLD asks streamers to be able to see what was opened in each break
    at a glance -- not just the gross/profit totals. One product per line
    (not comma-joined) so a break with several products stacks readably
    within the cell instead of running wide; pairs with
    resizeRowsToContents() on the table so every line is actually visible."""
    if not break_obj.pack_lines:
        return "(no packs selected)"

    return "\n".join(
        f"{product_names.get(line['product_id'], line['product_id'])} x{line['quantity']}"
        for line in break_obj.pack_lines
    )


class StreamResumePromptDialog(QDialog):
    """LLD 16.1: shown right after login, before the normal dashboard, if
    this streamer has an unfinished stream left over from a crash/close."""

    def __init__(self, stream, breaks, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Unfinished Stream Found")
        self.setModal(True)
        self.result_action = None

        ended = [b for b in breaks if b.status == STATUS_ENDED_EDITABLE]
        active = [b for b in breaks if b.status == BREAK_STATUS_ACTIVE]
        total_selected = sum(sum(line["quantity"] for line in b.pack_lines) for b in breaks)
        provisional_gross = sum((b.break_gross or Decimal("0")) for b in ended)

        layout = QVBoxLayout()

        layout.addWidget(QLabel("An unfinished stream was found."))
        layout.addWidget(QLabel(f"Stream: {stream.date} — started {stream.start_time}"))
        layout.addWidget(QLabel(f"Ended breaks: {len(ended)}"))
        layout.addWidget(QLabel(f"Active break in progress: {'Yes' if active else 'No'}"))
        layout.addWidget(QLabel(f"Total packs selected: {total_selected}"))
        layout.addWidget(QLabel(f"Provisional gross so far: ${provisional_gross:.2f}"))

        button_row = QHBoxLayout()
        resume_button = QPushButton("Resume Stream")
        resume_button.clicked.connect(self._resume)
        cancel_button = QPushButton("Cancel Stream")
        cancel_button.clicked.connect(self._cancel)
        button_row.addWidget(resume_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

        self.setLayout(layout)

    def _resume(self):
        self.result_action = "resume"
        self.accept()

    def _cancel(self):
        self.result_action = "cancel"
        self.accept()


class EndBreakDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("End Break")

        layout = QVBoxLayout()

        self.gross_input = QLineEdit()
        self.gross_input.setPlaceholderText("Break gross, e.g. 30.00")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(QLabel("Break gross:"))
        layout.addWidget(self.gross_input)
        layout.addWidget(buttons)

        self.setLayout(layout)


class EditBreakGrossDialog(QDialog):
    def __init__(self, current_gross, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Break Gross")

        layout = QVBoxLayout()

        self.gross_input = QLineEdit(f"{current_gross:.2f}" if current_gross is not None else "")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(QLabel("New break gross:"))
        layout.addWidget(self.gross_input)
        layout.addWidget(buttons)

        self.setLayout(layout)


class EndStreamDialog(QDialog):
    def __init__(self, stream, streamer_database_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("End Stream")
        clamp_to_screen(self, 700, 500)

        self.stream = stream
        self.streamer_database_name = streamer_database_name
        self.product_names = {entry["product_id"]: entry["product_name_at_snapshot"] for entry in stream.price_snapshot}

        layout = QVBoxLayout()

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)

        self.breaks_table = QTableWidget(0, 6)
        self.breaks_table.setHorizontalHeaderLabels(["#", "Name", "Packs Opened", "Gross", "Market Value", "Profit"])
        self.breaks_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.breaks_table.setEditTriggers(QTableWidget.NoEditTriggers)

        button_row = QHBoxLayout()
        self.edit_gross_button = QPushButton("Edit Selected Break Gross")
        self.edit_gross_button.clicked.connect(self.edit_selected_break_gross)
        self.delete_button = QPushButton("Delete Selected Break")
        self.delete_button.clicked.connect(self.delete_selected_break)
        button_row.addWidget(self.edit_gross_button)
        button_row.addWidget(self.delete_button)

        self.final_gross_input = QLineEdit()
        self.final_gross_input.setPlaceholderText("Final Whatnot stream gross")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Confirm Final Submission")
        buttons.accepted.connect(self.confirm_submission)
        buttons.rejected.connect(self.reject)

        layout.addWidget(self.summary_label)
        layout.addWidget(self.breaks_table)
        layout.addLayout(button_row)
        layout.addWidget(QLabel("Final Whatnot stream gross:"))
        layout.addWidget(self.final_gross_input)
        layout.addWidget(buttons)

        self.setLayout(layout)

        self.reload()

    def reload(self):
        self.breaks = streamer_repo.list_breaks_for_stream(self.streamer_database_name, self.stream.id)
        aggregates = stream_service.aggregate_breaks_for_settlement(self.breaks)

        self.breaks_table.setRowCount(len(self.breaks))
        for row, b in enumerate(self.breaks):
            self.breaks_table.setItem(row, 0, QTableWidgetItem(str(b.sequence_number)))
            self.breaks_table.setItem(row, 1, QTableWidgetItem(b.name or ""))
            self.breaks_table.setItem(row, 2, QTableWidgetItem(_pack_summary(b, self.product_names)))
            self.breaks_table.setItem(row, 3, QTableWidgetItem(f"${b.break_gross:.2f}" if b.break_gross is not None else ""))
            self.breaks_table.setItem(row, 4, QTableWidgetItem(f"${b.total_pack_market_value:.2f}"))
            self.breaks_table.setItem(row, 5, QTableWidgetItem(f"${b.break_profit:.2f}" if b.break_profit is not None else ""))

        self.breaks_table.resizeColumnsToContents()
        self.breaks_table.resizeRowsToContents()

        self.summary_label.setText(
            f"Breaks: {len(self.breaks)} | Sum of break gross: ${aggregates['sum_of_break_gross']:.2f} | "
            f"Stream pack market value: ${aggregates['stream_pack_market_value']:.2f}"
        )

    def selected_break(self):
        rows = self.breaks_table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.breaks[rows[0].row()]

    def edit_selected_break_gross(self):
        b = self.selected_break()
        if not b:
            return

        dialog = EditBreakGrossDialog(b.break_gross, self)
        if dialog.exec() != QDialog.Accepted:
            return

        try:
            new_gross = Decimal(dialog.gross_input.text().strip())
        except InvalidOperation:
            QMessageBox.warning(self, "Invalid", "Enter a valid amount.")
            return

        try:
            break_service.edit_break_gross(self.streamer_database_name, b, new_gross, edited_by=self.stream.streamer_id)
        except break_service.BreakValidationError as e:
            QMessageBox.warning(self, "Cannot edit", str(e))
            return

        self.reload()

    def delete_selected_break(self):
        b = self.selected_break()
        if not b:
            return

        if QMessageBox.question(self, "Delete Break", f"Delete break #{b.sequence_number}?") != QMessageBox.Yes:
            return

        break_service.delete_break(self.streamer_database_name, b, deleted_by=self.stream.streamer_id)
        self.reload()

    def confirm_submission(self):
        try:
            final_gross = Decimal(self.final_gross_input.text().strip())
        except InvalidOperation:
            QMessageBox.warning(self, "Invalid", "Enter the final stream gross.")
            return

        try:
            stream_service.end_stream(
                self.stream.id, self.stream.streamer_id, self.streamer_database_name, final_gross,
                requested_by=self.stream.streamer_id,
            )
        except (stream_service.StreamValidationError, stream_service.StreamAuthorizationError) as e:
            QMessageBox.critical(self, "Cannot complete stream", str(e))
            return

        self.accept()


TILE_WIDTH = 120  # 25% smaller than the original 160px -- more packs visible at once
TILE_IMAGE_WIDTH = 105
TILE_IMAGE_HEIGHT = 146
GRID_SPACING = 10
MIN_GRID_COLUMNS = 2  # floor so a very narrow window still shows a usable grid
TILE_NAME_HEIGHT = 46  # fixed regardless of name length, so every tile in a
                       # row lines up -- a short name ("Kamigawa...") and a
                       # long one ("Commander Legends: Battle for Baldur's
                       # Gate...") previously wrapped to different line
                       # counts and threw off every price/button row below.


def _columns_for_width(available_width: int) -> int:
    """How many fixed-width tiles fit side by side in available_width, used
    to make the holdings/pack grids scale with the window instead of being
    stuck at a hardcoded column count that's too few on a wide monitor and
    wraps early, or too many to fit comfortably on a small one."""
    columns = (available_width + GRID_SPACING) // (TILE_WIDTH + GRID_SPACING)
    return max(MIN_GRID_COLUMNS, int(columns))


class BreakProductTile(QFrame):
    """LLD 14.2/14.3: a visual product tile, clickable to add one pack, plus
    explicit +/- controls. Rebuilding tiles is always deferred (see
    StreamsScreen._change_quantity) rather than done synchronously inside a
    button's own click handler -- destroying a widget mid-signal is a real
    crash risk in Qt, and it's exactly what used to happen here."""

    def __init__(self, product_id: str, name: str, image_path, unit_price: Decimal,
                 available: int, selected: int, enabled: bool, on_add, on_remove):
        super().__init__()

        self.product_name = name

        self.setFixedWidth(TILE_WIDTH)
        self._apply_border_style(selected > 0)

        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignTop)

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setFixedSize(TILE_IMAGE_WIDTH, TILE_IMAGE_HEIGHT)

        if image_path:
            pixmap = QPixmap(str(image_path)).scaled(
                TILE_IMAGE_WIDTH, TILE_IMAGE_HEIGHT, Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            image_label.setPixmap(pixmap)
        else:
            image_label.setText("No Image")

        can_add = enabled and available > 0
        can_remove = enabled and selected > 0

        def handle_image_click(event, product_id=product_id):
            if event.button() == Qt.RightButton:
                if can_remove:
                    on_remove(product_id)
            elif can_add:
                on_add(product_id)

        if can_add or can_remove:
            image_label.setCursor(Qt.PointingHandCursor)
            image_label.setToolTip("Left-click: add a pack. Right-click: remove a pack.")
            image_label.mousePressEvent = handle_image_click

        name_label = QLabel(name)
        name_label.setWordWrap(True)
        name_label.setAlignment(Qt.AlignTop)
        name_label.setFixedHeight(TILE_NAME_HEIGHT)
        name_label.setStyleSheet("font-weight: bold; font-size: 11px;")

        info_label = QLabel(f"Available: {available}   In this break: {selected}")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("font-size: 10px;")

        price_label = QLabel(f"${unit_price:.2f} / pack")
        price_label.setStyleSheet("font-weight: bold; font-size: 11px;")

        button_row = QHBoxLayout()
        minus_button = QPushButton("-")
        minus_button.setEnabled(enabled and selected > 0)
        minus_button.clicked.connect(lambda: on_remove(product_id))
        plus_button = QPushButton("+")
        plus_button.setEnabled(can_add)
        plus_button.clicked.connect(lambda: on_add(product_id))
        button_row.addWidget(minus_button)
        button_row.addWidget(plus_button)

        layout.addWidget(image_label)
        layout.addWidget(name_label)
        layout.addWidget(info_label)
        layout.addWidget(price_label)
        layout.addLayout(button_row)

        self.setLayout(layout)

    def _apply_border_style(self, is_selected: bool):
        # Visual confirmation that a product has packs selected in the
        # current break -- border goes from neutral gray to a thick, vivid
        # green. Previously 2px in a muted green, which was too subtle to
        # notice at a glance during a fast-moving live stream; also tints
        # the background so it reads clearly even at a quick glance.
        background_color = "#e8f8ec" if is_selected else "white"
        border_color = "#00c853" if is_selected else "#999999"
        border_width = 5 if is_selected else 1
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {background_color}; border: {border_width}px solid {border_color};
                border-radius: 8px; padding: 6px;
            }}
            QLabel {{ color: black; background-color: transparent; border: none; }}
        """)


class HoldingsPreviewTile(QFrame):
    """Read-only preview tile for the pre-stream "browse your inventory"
    view -- no interaction, just image/name/held-quantity/price, so a
    streamer can scroll through and plan what to open before starting."""

    def __init__(self, name: str, image_path, held: int, resolved_pack_price, price_status: str):
        super().__init__()

        self.product_name = name

        self.setFixedWidth(TILE_WIDTH)
        self.setStyleSheet("""
            QFrame { background-color: white; border: 1px solid #999999; border-radius: 8px; padding: 6px; }
            QLabel { color: black; background-color: transparent; border: none; }
        """)

        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignTop)

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setFixedSize(TILE_IMAGE_WIDTH, TILE_IMAGE_HEIGHT)

        if image_path:
            pixmap = QPixmap(str(image_path)).scaled(
                TILE_IMAGE_WIDTH, TILE_IMAGE_HEIGHT, Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            image_label.setPixmap(pixmap)
        else:
            image_label.setText("No Image")

        name_label = QLabel(name)
        name_label.setWordWrap(True)
        name_label.setAlignment(Qt.AlignTop)
        name_label.setFixedHeight(TILE_NAME_HEIGHT)
        name_label.setStyleSheet("font-weight: bold; font-size: 11px;")

        held_label = QLabel(f"You hold: {held}")
        held_label.setStyleSheet("font-size: 10px;")

        if resolved_pack_price is not None and price_status not in ("UNRESOLVED", "AMBIGUOUS"):
            price_text = f"${resolved_pack_price:.2f} / pack"
        else:
            price_text = "Price not yet resolved"
        price_label = QLabel(price_text)
        price_label.setStyleSheet("font-weight: bold; font-size: 11px;")

        layout.addWidget(image_label)
        layout.addWidget(name_label)
        layout.addWidget(held_label)
        layout.addWidget(price_label)

        self.setLayout(layout)


class StreamsScreen(QWidget):
    def __init__(self, current_user):
        super().__init__()

        self.current_user = current_user
        self.stream = None
        self.active_break = None
        self._breaks: list = []
        self._product_names: dict = {}
        self._pack_grid_stretch_state: dict = {}
        self._holdings_grid_stretch_state: dict = {}
        self._price_refresh_worker = None
        self._pack_tile_reload_pending = False
        # Responsive column count (see _columns_for_width): _last_*_columns
        # tracks what the grid was last built with so a resize only
        # triggers an actual rebuild when the column count would change,
        # not on every pixel of a window drag; _*_trailing_column tracks
        # which column currently holds the trailing stretch (LLD/grid_stretch
        # left-justify fix) so it can be reset to 0 before moving it.
        self._regrid_pending = False
        self._last_holdings_columns = None
        self._last_pack_columns = None
        self._holdings_grid_trailing_column = None
        self._pack_grid_trailing_column = None

        layout = QVBoxLayout()

        title = QLabel("Streams")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")

        self.status_label = QLabel()

        # --- Pre-stream state: browse what you're holding, a reminder to
        # refresh prices, then a big hard-to-miss Start Stream button --
        # previously this was just one plain button with nothing else on
        # the screen to help decide what to open.
        self.holdings_title_label = QLabel("Your inventory -- browse before you start:")
        self.holdings_title_label.setStyleSheet("font-weight: bold;")

        self.holdings_scroll_area = QScrollArea()
        self.holdings_scroll_area.setWidgetResizable(True)
        self.holdings_scroll_area.setMinimumHeight(320)
        self.holdings_grid_container = QWidget()
        self.holdings_grid_layout = QGridLayout()
        self.holdings_grid_layout.setSpacing(GRID_SPACING)
        self.holdings_grid_container.setLayout(self.holdings_grid_layout)
        self.holdings_scroll_area.setWidget(self.holdings_grid_container)

        self.holdings_empty_label = QLabel(
            "You aren't holding any packs yet -- claim some from My Inventory first."
        )
        self.holdings_empty_label.setVisible(False)

        self.refresh_prices_banner_label = QLabel(
            "Remember to refresh prices before going live -- every pack needs an accepted "
            "price before a stream can start."
        )
        self.refresh_prices_banner_label.setWordWrap(True)
        self.refresh_prices_banner_label.setStyleSheet(
            "background-color: #fff3cd; color: black; border: 1px solid #cc9900; "
            "border-radius: 6px; padding: 8px;"
        )
        self.refresh_prices_now_button = QPushButton("Refresh Prices Now")
        self.refresh_prices_now_button.clicked.connect(self.refresh_prices_before_stream)

        refresh_banner_row = QHBoxLayout()
        refresh_banner_row.addWidget(self.refresh_prices_banner_label, stretch=1)
        refresh_banner_row.addWidget(self.refresh_prices_now_button)
        self.refresh_prices_banner_container = QWidget()
        self.refresh_prices_banner_container.setLayout(refresh_banner_row)

        self.start_button = QPushButton("Start Stream")
        self.start_button.setStyleSheet("""
            QPushButton {
                background-color: #1a7f37; color: white; font-weight: bold;
                font-size: 18px; padding: 14px; border-radius: 8px;
            }
            QPushButton:hover { background-color: #15602b; }
            QPushButton:disabled { background-color: #999999; }
        """)
        self.start_button.clicked.connect(self.start_stream)

        # --- Active-stream workspace ---
        self.action_button_row_container = QWidget()
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        self.start_break_button = QPushButton("Start New Break")
        self.start_break_button.clicked.connect(self.start_new_break)
        self.end_break_button = QPushButton("End Break")
        self.end_break_button.clicked.connect(self.end_break)
        self.end_stream_button = QPushButton("End Stream")
        self.end_stream_button.clicked.connect(self.open_end_stream_review)
        self.cancel_stream_button = QPushButton("Cancel Stream")
        self.cancel_stream_button.clicked.connect(self.cancel_stream)

        button_row.addWidget(self.start_break_button)
        button_row.addWidget(self.end_break_button)
        button_row.addWidget(self.end_stream_button)
        button_row.addWidget(self.cancel_stream_button)
        self.action_button_row_container.setLayout(button_row)

        self.current_break_label = QLabel("Current break -- click a product to add a pack, or use +/-:")

        self.pack_search_row_container = QWidget()
        pack_search_row = QHBoxLayout()
        pack_search_row.setContentsMargins(0, 0, 0, 0)
        pack_search_row.addWidget(QLabel("Search:"))
        self.pack_search_input = QLineEdit()
        self.pack_search_input.setPlaceholderText("Filter your packs by name or set code...")
        self.pack_search_input.textChanged.connect(self._schedule_pack_search)
        pack_search_row.addWidget(self.pack_search_input, stretch=1)
        self.pack_search_row_container.setLayout(pack_search_row)

        self._pack_search_timer = QTimer()
        self._pack_search_timer.setSingleShot(True)
        self._pack_search_timer.timeout.connect(self.reload_pack_tiles)

        self.pack_scroll_area = QScrollArea()
        self.pack_scroll_area.setWidgetResizable(True)
        self.pack_scroll_area.setMinimumHeight(320)
        self.pack_grid_container = QWidget()
        self.pack_grid_layout = QGridLayout()
        self.pack_grid_layout.setSpacing(GRID_SPACING)
        self.pack_grid_container.setLayout(self.pack_grid_layout)
        self.pack_scroll_area.setWidget(self.pack_grid_container)

        # Always-visible running total for the break currently being built
        # -- previously the only way to see this was to end the break and
        # look at the breaks table afterward.
        self.break_total_label = QLabel()
        self.break_total_label.setStyleSheet("font-size: 16px; font-weight: bold;")

        self.slot_tracker = SlotValueTracker()

        side_panel = QVBoxLayout()
        side_panel.addWidget(self.break_total_label)
        side_panel.addWidget(self.slot_tracker)
        side_panel.addStretch(1)
        self.side_panel_container = QWidget()
        self.side_panel_container.setLayout(side_panel)
        self.side_panel_container.setFixedWidth(240)

        workspace_row = QHBoxLayout()
        workspace_row.addWidget(self.pack_scroll_area, stretch=1)
        workspace_row.addWidget(self.side_panel_container)
        self.workspace_row_container = QWidget()
        self.workspace_row_container.setLayout(workspace_row)

        self.breaks_this_stream_label = QLabel("Breaks this stream:")

        self.breaks_table = QTableWidget(0, 5)
        self.breaks_table.setHorizontalHeaderLabels(["#", "Status", "Packs Opened", "Gross", "Profit"])
        self.breaks_table.setEditTriggers(QTableWidget.NoEditTriggers)

        breaks_panel_layout = QVBoxLayout()
        breaks_panel_layout.setContentsMargins(0, 0, 0, 0)
        breaks_panel_layout.addWidget(self.breaks_this_stream_label)
        breaks_panel_layout.addWidget(self.breaks_table)
        self.breaks_panel_container = QWidget()
        self.breaks_panel_container.setLayout(breaks_panel_layout)

        # Drag the handle between the pack catalog and the breaks table to
        # trade space between them -- the table scrolls internally
        # (QTableWidget's own vertical scrollbar) so shrinking its pane
        # never cuts off rows, it just shows fewer at once.
        self.workspace_splitter = QSplitter(Qt.Vertical)
        self.workspace_splitter.addWidget(self.workspace_row_container)
        self.workspace_splitter.addWidget(self.breaks_panel_container)
        self.workspace_splitter.setStretchFactor(0, 3)
        self.workspace_splitter.setStretchFactor(1, 1)

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(self.status_label)
        layout.addWidget(self.holdings_title_label)
        layout.addWidget(self.holdings_scroll_area)
        layout.addWidget(self.holdings_empty_label)
        layout.addWidget(self.refresh_prices_banner_container)
        layout.addWidget(self.start_button)
        layout.addWidget(self.action_button_row_container)
        layout.addWidget(self.current_break_label)
        layout.addWidget(self.pack_search_row_container)
        layout.addWidget(self.workspace_splitter, stretch=1)
        layout.addWidget(self.message_label)

        self.setLayout(layout)

        self.reload()

    def reload(self):
        self.stream = stream_service.resume_check(self.current_user.streamer_database_name)

        if self.stream is None:
            self._show_no_stream_state()
            return

        self._product_names = {
            entry["product_id"]: entry["product_name_at_snapshot"] for entry in self.stream.price_snapshot
        }
        self.active_break = streamer_repo.find_active_break(self.current_user.streamer_database_name, self.stream.id)
        self._show_workspace_state()

    def _show_no_stream_state(self):
        for w in (self.holdings_title_label, self.holdings_scroll_area,
                  self.refresh_prices_banner_container, self.start_button):
            w.setVisible(True)

        for w in (self.action_button_row_container, self.current_break_label, self.pack_search_row_container,
                  self.workspace_splitter, self.workspace_row_container,
                  self.breaks_this_stream_label, self.breaks_table):
            w.setVisible(False)

        self.status_label.setText("No active stream.")
        self.reload_holdings_preview()

    def _show_workspace_state(self):
        for w in (self.holdings_title_label, self.holdings_scroll_area,
                  self.refresh_prices_banner_container, self.start_button, self.holdings_empty_label):
            w.setVisible(False)

        for w in (self.action_button_row_container, self.current_break_label, self.pack_search_row_container,
                  self.workspace_splitter, self.workspace_row_container,
                  self.breaks_this_stream_label, self.breaks_table):
            w.setVisible(True)
        self.start_break_button.setVisible(self.active_break is None)
        self.end_break_button.setVisible(self.active_break is not None)

        self.status_label.setText(
            f"Active stream ({self.stream.date}), started {self.stream.start_time}. "
            f"{'Break in progress.' if self.active_break else 'No break in progress.'}"
        )

        self.reload_pack_tiles()
        self.reload_breaks_table()

    def _clear_holdings_grid(self):
        while self.holdings_grid_layout.count():
            item = self.holdings_grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _compute_holdings_columns(self) -> int:
        return _columns_for_width(self.holdings_scroll_area.viewport().width())

    def _compute_pack_columns(self) -> int:
        return _columns_for_width(self.pack_scroll_area.viewport().width())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_responsive_regrid()

    def _schedule_responsive_regrid(self):
        # Debounced and coalesced the same way pack-tile reloads are
        # (StreamsScreen._schedule_pack_tile_reload) -- resize events fire
        # continuously while a window is being dragged, and rebuilding the
        # tile grid on every one of them would be wasteful at best and a
        # widget-lifetime crash risk at worst.
        if self._regrid_pending:
            return

        self._regrid_pending = True
        QTimer.singleShot(150, self._run_scheduled_regrid)

    def _run_scheduled_regrid(self):
        self._regrid_pending = False

        if self.stream is None:
            if self._compute_holdings_columns() != self._last_holdings_columns:
                self.reload_holdings_preview()
        elif self._compute_pack_columns() != self._last_pack_columns:
            self.reload_pack_tiles()

    def reload_holdings_preview(self):
        self._clear_holdings_grid()

        rows = [
            r for r in inventory_service.get_streamer_inventory_view(self.current_user.streamer_database_name)
            if r["current_packs"] > 0
        ]

        columns = self._compute_holdings_columns()
        self._last_holdings_columns = columns
        if self._holdings_grid_trailing_column is not None:
            self.holdings_grid_layout.setColumnStretch(self._holdings_grid_trailing_column, 0)
        self.holdings_grid_layout.setColumnStretch(columns, 1)
        self._holdings_grid_trailing_column = columns
        row_idx = -1
        for index, row in enumerate(rows):
            product = row["product"]
            image_path = None
            if product.image_url:
                image_path = sealed_image_cache_service.ensure_product_image_cached(product.id, product.image_url)

            tile = HoldingsPreviewTile(
                name=product.name, image_path=image_path, held=row["current_packs"],
                resolved_pack_price=row["resolved_pack_price"], price_status=row["price_status"],
            )
            row_idx, col = divmod(index, columns)
            self.holdings_grid_layout.addWidget(tile, row_idx, col)

        apply_trailing_stretch(self.holdings_grid_layout, self._holdings_grid_stretch_state, row_idx + 1, columns)
        self.holdings_empty_label.setVisible(not rows)

    def refresh_prices_before_stream(self):
        self.refresh_prices_now_button.setEnabled(False)
        self.show_message("Refreshing prices...", error=False)

        self._price_refresh_worker = PriceRefreshWorker(self.current_user.id)
        self._price_refresh_worker.finished_success.connect(safe_callback(self._on_pre_stream_refresh_finished))
        self._price_refresh_worker.failed.connect(safe_callback(self._on_pre_stream_refresh_failed))
        run_worker(self._price_refresh_worker)

    def _on_pre_stream_refresh_finished(self, session_id: str):
        self.refresh_prices_now_button.setEnabled(True)
        self.show_message("Prices refreshed.", error=False)
        self.reload_holdings_preview()

    def _on_pre_stream_refresh_failed(self, error: str):
        self.refresh_prices_now_button.setEnabled(True)
        self.show_message(f"Price refresh failed: {error}", error=True)

    def _schedule_pack_search(self):
        self._pack_search_timer.start(200)

    def _clear_pack_grid(self):
        while self.pack_grid_layout.count():
            item = self.pack_grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def reload_pack_tiles(self):
        self._clear_pack_grid()

        break_total = self.active_break.total_pack_market_value if self.active_break else Decimal("0")
        self.break_total_label.setText(f"Current Break Total: ${break_total:.2f}")
        self.slot_tracker.set_compare_value(break_total if self.active_break else None)
        self.slot_tracker.set_input_enabled(self.active_break is not None)

        availability = break_service.get_availability(self.stream, None, self.current_user.streamer_database_name)
        current_lines = {
            line["product_id"]: line["quantity"] for line in (self.active_break.pack_lines if self.active_break else [])
        }

        entries = self.stream.price_snapshot
        search_text = self.pack_search_input.text().strip().lower()
        if search_text:
            entries = [
                e for e in entries
                if search_text in e["product_name_at_snapshot"].lower()
                or search_text in (e.get("set_code") or "").lower()
            ]
        columns = self._compute_pack_columns()
        self._last_pack_columns = columns
        if self._pack_grid_trailing_column is not None:
            self.pack_grid_layout.setColumnStretch(self._pack_grid_trailing_column, 0)
        self.pack_grid_layout.setColumnStretch(columns, 1)
        self._pack_grid_trailing_column = columns

        # price_snapshot doesn't carry image_url (it's a pricing snapshot,
        # not a catalog mirror), so look products up once per reload rather
        # than showing "No Image" for anything the admin hasn't personally
        # previewed yet in Product Catalog. Already-cached images resolve
        # from disk (fast); only genuinely new ones hit the network.
        products_by_id = {p.id: p for p in product_service.list_products()}

        row = -1
        for index, entry in enumerate(entries):
            product_id = entry["product_id"]
            selected = current_lines.get(product_id, 0)
            avail = availability.get(product_id, 0)

            product = products_by_id.get(product_id)
            image_path = None
            if product and product.image_url:
                image_path = sealed_image_cache_service.ensure_product_image_cached(product_id, product.image_url)

            tile = BreakProductTile(
                product_id=product_id,
                name=entry["product_name_at_snapshot"],
                image_path=image_path,
                unit_price=entry["resolved_pack_price"],
                available=avail,
                selected=selected,
                enabled=self.active_break is not None,
                on_add=self.on_add_pack,
                on_remove=self.on_remove_pack,
            )

            row, col = divmod(index, columns)
            self.pack_grid_layout.addWidget(tile, row, col)

        apply_trailing_stretch(self.pack_grid_layout, self._pack_grid_stretch_state, row + 1, columns)

    def reload_breaks_table(self):
        self._breaks = streamer_repo.list_breaks_for_stream(self.current_user.streamer_database_name, self.stream.id)
        self.breaks_table.setRowCount(len(self._breaks))

        for row, b in enumerate(self._breaks):
            self.breaks_table.setItem(row, 0, QTableWidgetItem(str(b.sequence_number)))
            self.breaks_table.setItem(row, 1, QTableWidgetItem(BREAK_STATUS_LABELS.get(b.status, b.status)))
            self.breaks_table.setItem(row, 2, QTableWidgetItem(_pack_summary(b, self._product_names)))
            self.breaks_table.setItem(row, 3, QTableWidgetItem(f"${b.break_gross:.2f}" if b.break_gross is not None else ""))
            self.breaks_table.setItem(row, 4, QTableWidgetItem(f"${b.break_profit:.2f}" if b.break_profit is not None else ""))

        self.breaks_table.resizeColumnsToContents()
        self.breaks_table.resizeRowsToContents()

    def on_add_pack(self, product_id: str):
        self._change_quantity(product_id, +1)

    def on_remove_pack(self, product_id: str):
        self._change_quantity(product_id, -1)

    def _change_quantity(self, product_id: str, delta: int):
        if self.active_break is None:
            return

        current = self.active_break.quantity_for_product(product_id)
        new_value = max(0, current + delta)

        try:
            self.active_break = break_service.set_break_pack_line_quantity(
                self.stream, self.current_user.streamer_database_name, self.active_break, product_id, new_value,
            )
        except (break_service.BreakValidationError, break_service.InsufficientAvailabilityError) as e:
            self.show_message(str(e), error=True)

        self._schedule_pack_tile_reload()

    def _schedule_pack_tile_reload(self):
        # Deferred: rebuilding the tile grid destroys the very button whose
        # click handler is still on the call stack right now. Doing that
        # synchronously is a real Qt crash risk. Coalesced to at most one
        # pending rebuild: several +/- clicks (or stray clicks landing on
        # tiles while regaining window focus after alt-tabbing to OBS/
        # Discord mid-stream) each scheduling their own singleShot(0, ...)
        # let overlapping rebuilds destroy widgets a still-queued click
        # event was about to target -- that reentrant tile-replacement is
        # what actually crashed the app mid-stream, not any single click.
        if self._pack_tile_reload_pending:
            return

        self._pack_tile_reload_pending = True
        QTimer.singleShot(0, self._run_scheduled_pack_tile_reload)

    def _run_scheduled_pack_tile_reload(self):
        self._pack_tile_reload_pending = False
        self.reload_pack_tiles()

    def start_stream(self):
        try:
            self.stream = stream_service.start_stream(self.current_user.id, self.current_user.streamer_database_name)
        except (stream_service.StreamStartBlockedError, lock_service.LockConflictError) as e:
            self.show_message(str(e), error=True)
            return

        self.show_message("Stream started.", error=False)
        self.reload()

    def start_new_break(self):
        try:
            self.active_break = break_service.start_new_break(self.stream, self.current_user.streamer_database_name)
        except break_service.BreakValidationError as e:
            self.show_message(str(e), error=True)
            return

        self.slot_tracker.reset()
        self.show_message("New break started.", error=False)
        self.reload()

    def end_break(self):
        dialog = EndBreakDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return

        try:
            gross = Decimal(dialog.gross_input.text().strip())
        except InvalidOperation:
            self.show_message("Enter a valid break gross.", error=True)
            return

        try:
            break_service.end_break(
                self.current_user.streamer_database_name, self.active_break, gross, ended_by=self.current_user.id
            )
        except break_service.BreakValidationError as e:
            self.show_message(str(e), error=True)
            return

        self.show_message("Break ended.", error=False)
        self.reload()

    def open_end_stream_review(self):
        dialog = EndStreamDialog(self.stream, self.current_user.streamer_database_name, self)

        if dialog.exec() == QDialog.Accepted:
            self.show_message("Stream completed.", error=False)

        self.reload()

    def cancel_stream(self):
        if QMessageBox.question(self, "Cancel Stream", "Cancel this stream? No inventory will be affected.") != QMessageBox.Yes:
            return

        try:
            stream_service.cancel_stream(
                self.stream.id, self.current_user.id, self.current_user.streamer_database_name,
                canceled_by=self.current_user.id,
            )
        except stream_service.StreamAuthorizationError as e:
            self.show_message(str(e), error=True)
            return

        self.show_message("Stream canceled.", error=False)
        self.reload()

    def show_message(self, text: str, error: bool):
        self.message_label.setStyleSheet("color: #b00020;" if error else "color: #1a7f37;")
        self.message_label.setText(text)
