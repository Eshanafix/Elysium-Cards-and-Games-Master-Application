"""
Admin Product Catalog screen (LLD section 8, 24.3).

Creating a product is search-driven (docs/IMPLEMENTATION_PLAN.md Phase 3
UX revision): the admin searches for a set by name, picks it, then picks
the loose-pack product from a short auto-filtered candidate list -- booster
type, box product, image, packs-per-box, and set name/code are all derived
automatically where possible and always left editable. Raw TCGCSV ids are
still shown (read-only) for transparency/debugging but never typed by hand.

Editing an existing product uses a simpler direct-field form, since by
that point the mapping already exists and rarely needs re-deriving from
scratch.
"""

import hashlib

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from elysium.models.products import BOOSTER_TYPES, Product
from elysium.services import product_service, sealed_image_cache_service, tcgcsv_catalog_service
from elysium.ui.background import run_worker, safe_callback
from elysium.ui.dialog_sizing import clamp_to_screen
from elysium.ui.no_scroll_combo import NoScrollComboBox
from elysium.ui.numeric_inputs import SelectAllSpinBox
from elysium.ui.prices import PriceRefreshWorker
from elysium.ui.table_scaling import make_columns_stretch, resize_columns_to_contents

SEARCH_DEBOUNCE_MS = 250


def _stable_cache_key(url: str) -> str:
    # Python's built-in hash() is per-process randomized for strings, so it
    # can't be used as a stable local cache key across app runs.
    return f"preview-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}"


class SetSearchPanel(QWidget):
    """The search-driven set/product picker used only in create mode.
    Calls back into the owning dialog as selections resolve."""

    def __init__(self, on_selection_resolved):
        super().__init__()

        self.on_selection_resolved = on_selection_resolved
        self._selected_group: dict | None = None
        self._raw_products_by_id: dict[str, dict] = {}
        self._loose_candidates = []
        self._box_candidates = []

        layout = QVBoxLayout()

        cache_count = tcgcsv_catalog_service.groups_cache_count()

        self.cache_status_label = QLabel(
            f"{cache_count} sets cached." if cache_count else
            "No sets cached yet -- click Refresh Set List first."
        )

        self.refresh_sets_button = QPushButton("Refresh Set List")
        self.refresh_sets_button.clicked.connect(self.refresh_set_cache)

        top_row = QHBoxLayout()
        top_row.addWidget(self.cache_status_label, stretch=1)
        top_row.addWidget(self.refresh_sets_button)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search set name (e.g. Dominaria)...")
        self.search_input.textChanged.connect(self.schedule_search)

        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.run_search)

        self.results_list = QListWidget()
        self.results_list.setMinimumHeight(240)
        self.results_list.itemClicked.connect(self.select_group)

        self.selected_set_label = QLabel("No set selected.")

        self.loose_combo = NoScrollComboBox()
        self.loose_combo.currentIndexChanged.connect(self.on_loose_changed)

        self.box_combo = NoScrollComboBox()
        self.box_combo.currentIndexChanged.connect(self.on_box_changed)

        layout.addLayout(top_row)
        layout.addWidget(self.search_input)
        layout.addWidget(self.results_list)
        layout.addWidget(self.selected_set_label)
        layout.addWidget(QLabel("Loose pack:"))
        layout.addWidget(self.loose_combo)
        layout.addWidget(QLabel("Box:"))
        layout.addWidget(self.box_combo)

        self.setLayout(layout)

    def refresh_set_cache(self):
        self.refresh_sets_button.setEnabled(False)
        self.cache_status_label.setText("Refreshing...")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        try:
            count = tcgcsv_catalog_service.refresh_groups_cache(started_by="ui")
            self.cache_status_label.setText(f"{count} sets cached.")
        except Exception as e:
            self.cache_status_label.setText(f"Refresh failed: {e}")
        finally:
            QApplication.restoreOverrideCursor()
            self.refresh_sets_button.setEnabled(True)

    def schedule_search(self):
        self.search_timer.start(SEARCH_DEBOUNCE_MS)

    def run_search(self):
        query = self.search_input.text().strip()
        self.results_list.clear()

        if not query:
            return

        for group in tcgcsv_catalog_service.search_groups(query):
            label = group["name"]
            if group.get("abbreviation"):
                label += f" ({group['abbreviation']})"

            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, group)
            self.results_list.addItem(item)

    def select_group(self, item: QListWidgetItem):
        group = item.data(Qt.UserRole)
        self._selected_group = group
        self.selected_set_label.setText(f"Selected set: {group['name']}")

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            products = tcgcsv_catalog_service.fetch_group_products(group["category_id"], group["group_id"])
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.selected_set_label.setText(f"Could not load products for this set: {e}")
            return
        QApplication.restoreOverrideCursor()

        self._raw_products_by_id = {
            str(p["productId"]): p for p in products if p.get("productId") is not None
        }
        self._loose_candidates, self._box_candidates = tcgcsv_catalog_service.classify_sealed_candidates(products)

        self.loose_combo.blockSignals(True)
        self.loose_combo.clear()
        for candidate in self._loose_candidates:
            self.loose_combo.addItem(candidate.name, candidate)
        self.loose_combo.blockSignals(False)

        self.box_combo.blockSignals(True)
        self.box_combo.clear()
        for candidate in self._box_candidates:
            self.box_combo.addItem(candidate.name, candidate)
        self.box_combo.blockSignals(False)

        if self._loose_candidates:
            self.loose_combo.setCurrentIndex(0)
            self.on_loose_changed(0)
        elif not self._box_candidates:
            # Some TCGCSV groups are real but genuinely empty (e.g.
            # "Mystery Booster Cards" / MB1 has zero products listed under
            # it -- the actual sellable Mystery Booster packs/boxes are
            # catalogued under separate, differently-abbreviated groups).
            # Silently leaving both dropdowns empty here reads as a bug;
            # naming the likely fix is more useful than nothing.
            self.selected_set_label.setText(
                f"Selected set: {group['name']} -- no sealed pack/box products found in this TCGPlayer "
                "group. If there's more than one search result for this set name, try a different one "
                "(e.g. a set can have separate \"Retail\" and \"Convention\" groups)."
            )

    def on_loose_changed(self, index: int):
        if index < 0 or not self._loose_candidates:
            return

        candidate = self.loose_combo.itemData(index)

        if candidate is None:
            return

        # Auto-select a box candidate of the same derived booster type, if
        # there's exactly one match -- otherwise leave it for a manual pick.
        if candidate.booster_type:
            matches = [
                i for i in range(self.box_combo.count())
                if self.box_combo.itemData(i) and self.box_combo.itemData(i).booster_type == candidate.booster_type
            ]
            if len(matches) == 1:
                self.box_combo.setCurrentIndex(matches[0])

        self._emit_resolved(loose=candidate)

    def on_box_changed(self, index: int):
        if index < 0 or not self._box_candidates:
            return

        candidate = self.box_combo.itemData(index)

        if candidate is None:
            return

        self._emit_resolved(box=candidate)

    def _emit_resolved(self, loose=None, box=None):
        loose = loose or self.loose_combo.currentData()
        box = box or self.box_combo.currentData()

        box_raw = self._raw_products_by_id.get(box.product_id) if box else None
        booster_type = (loose.booster_type if loose else None) or (box.booster_type if box else None)

        parsed_packs_per_box = tcgcsv_catalog_service.parse_packs_per_box(box_raw) if box_raw else None
        packs_per_box = parsed_packs_per_box or (
            tcgcsv_catalog_service.default_packs_per_box(booster_type) if booster_type else 36
        )

        self.on_selection_resolved({
            "group": self._selected_group,
            "loose": loose,
            "box": box,
            "booster_type": booster_type,
            "packs_per_box": packs_per_box,
            "packs_per_box_was_parsed": parsed_packs_per_box is not None,
        })


class ProductDialog(QDialog):
    """Create mode (product=None) shows the search-driven picker above the
    review fields. Edit mode shows just the direct-editing fields."""

    def __init__(self, parent=None, product: Product | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit Product" if product else "New Product")
        # Create mode only asks for what's actually needed to add a
        # product (set, booster type, packs per box) so a much bigger
        # results list fits without the dialog getting unreasonably tall;
        # edit mode still shows every field since fixing a wrong TCGCSV
        # mapping/image after the fact needs full visibility. 520 wasn't
        # actually tall enough to show the whole search panel + review
        # fields without scrolling -- clamp_to_screen still caps this to
        # whatever actually fits on a smaller monitor.
        clamp_to_screen(self, 520, 780 if product is None else 700)
        self._name_was_auto_suggested = product is None

        # Fields go in a scroll area and the OK/Cancel buttons stay pinned
        # outside it -- on a short screen (or with a large UI zoom) the
        # dialog can be shorter than its natural content height without
        # ever making the buttons unreachable, which is exactly what
        # happened before this fix (LLD n/a; local UX fix).
        layout = QVBoxLayout()

        if product is None:
            self.search_panel = SetSearchPanel(on_selection_resolved=self._apply_resolved_selection)
            layout.addWidget(self.search_panel)
            layout.addWidget(QLabel("Review and confirm:"))
        else:
            self.search_panel = None

        self.name_input = QLineEdit(product.name if product else "")
        self.name_input.setPlaceholderText("Product name")
        self.name_input.textEdited.connect(self._mark_name_as_manually_edited)

        self.set_name_input = QLineEdit((product.set_name or "") if product else "")
        self.set_name_input.setPlaceholderText("Set name")

        self.set_code_input = QLineEdit((product.set_code or "") if product else "")
        self.set_code_input.setPlaceholderText("Set code")

        self.booster_type_combo = NoScrollComboBox()
        self.booster_type_combo.addItems(BOOSTER_TYPES)
        if product:
            self.booster_type_combo.setCurrentText(product.booster_type)

        self.packs_per_box_input = SelectAllSpinBox()
        self.packs_per_box_input.setRange(1, 999)
        self.packs_per_box_input.setValue(product.packs_per_box if product else 36)

        self.tcgcsv_category_id_input = QLineEdit(product.tcgcsv_category_id if product else "1")
        self.tcgcsv_group_id_input = QLineEdit(product.tcgcsv_group_id if product else "")
        self.loose_tcgcsv_id_input = QLineEdit(product.loose_pack_tcgcsv_product_id if product else "")
        self.box_tcgcsv_id_input = QLineEdit(product.box_tcgcsv_product_id if product else "")

        if product is None:
            # Auto-filled by the search picker above -- shown read-only for
            # transparency, never hand-typed.
            for field in (
                self.tcgcsv_category_id_input, self.tcgcsv_group_id_input,
                self.loose_tcgcsv_id_input, self.box_tcgcsv_id_input,
            ):
                field.setReadOnly(True)
                field.setStyleSheet("color: gray; background-color: #f0f0f0;")

        self.image_url_input = QLineEdit(product.image_url if product else "")
        self.image_url_input.setPlaceholderText("Product image URL")

        self.preview_button = QPushButton("Preview Image")
        self.preview_button.clicked.connect(self.load_preview)

        self.image_preview_label = QLabel("No preview")
        self.image_preview_label.setFixedSize(120, 168)
        self.image_preview_label.setAlignment(Qt.AlignCenter)
        self.image_preview_label.setStyleSheet("border: 1px solid gray;")

        self.english_confirmed_checkbox = QCheckBox("Confirmed English-language product")
        if product:
            self.english_confirmed_checkbox.setChecked(product.english_confirmed)
        else:
            # Not shown/asked about in create mode (per feedback: not
            # needed for now) -- default to confirmed rather than silently
            # submitting False with no way for the admin to have set it.
            self.english_confirmed_checkbox.setChecked(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        # Create mode: only what's actually needed to add a product -- the
        # set (via the search picker above), booster type, and packs per
        # box. Set name/code, raw TCGCSV ids, image URL/preview, and the
        # English-language checkbox are all still auto-filled and submitted
        # (field_values() below), just not shown -- there's nothing to
        # confirm about them at creation time, and hiding them is what
        # leaves room for a results list that doesn't need scrolling for
        # every search. Edit mode keeps every field visible, since fixing a
        # wrong mapping/image after the fact needs full control.
        for widget in (
            QLabel("Name:"), self.name_input,
            QLabel("Booster type:"), self.booster_type_combo,
            QLabel("Packs per box:"), self.packs_per_box_input,
        ):
            layout.addWidget(widget)

        if product is not None:
            for widget in (
                QLabel("Set name:"), self.set_name_input,
                QLabel("Set code:"), self.set_code_input,
                QLabel("TCGCSV category id:"), self.tcgcsv_category_id_input,
                QLabel("TCGCSV group id:"), self.tcgcsv_group_id_input,
                QLabel("Loose-pack TCGCSV product id:"), self.loose_tcgcsv_id_input,
                QLabel("Box TCGCSV product id:"), self.box_tcgcsv_id_input,
                QLabel("Image URL:"), self.image_url_input,
            ):
                layout.addWidget(widget)

            preview_row = QHBoxLayout()
            preview_row.addWidget(self.preview_button)
            preview_row.addWidget(self.image_preview_label)
            layout.addLayout(preview_row)

            layout.addWidget(self.english_confirmed_checkbox)

        scroll_content = QWidget()
        scroll_content.setLayout(layout)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(scroll_content)

        outer_layout = QVBoxLayout()
        outer_layout.addWidget(scroll_area, stretch=1)
        outer_layout.addWidget(buttons)

        self.setLayout(outer_layout)

        if self.search_panel is not None:
            # So an admin can start typing a set name immediately instead
            # of having to click into the search bar first.
            self.search_panel.search_input.setFocus()

    def _mark_name_as_manually_edited(self):
        self._name_was_auto_suggested = False

    def _apply_resolved_selection(self, resolution: dict):
        group = resolution["group"]
        loose = resolution["loose"]
        box = resolution["box"]
        booster_type = resolution["booster_type"]

        if group:
            self.set_name_input.setText(group.get("name", ""))
            self.set_code_input.setText(group.get("abbreviation") or "")
            self.tcgcsv_category_id_input.setText(str(group.get("category_id", "")))
            self.tcgcsv_group_id_input.setText(str(group.get("group_id", "")))

        if loose:
            self.loose_tcgcsv_id_input.setText(loose.product_id)
            if loose.image_url:
                self.image_url_input.setText(loose.image_url)

        if box:
            self.box_tcgcsv_id_input.setText(box.product_id)

        if booster_type:
            self.booster_type_combo.setCurrentText(booster_type)

        self.packs_per_box_input.setValue(resolution["packs_per_box"])

        if (not self.name_input.text().strip()) or self._name_was_auto_suggested:
            set_name = (group or {}).get("name", "")
            if set_name and booster_type:
                self.name_input.setText(tcgcsv_catalog_service.suggest_product_name(set_name, booster_type))
                self._name_was_auto_suggested = True

    def load_preview(self):
        url = self.image_url_input.text().strip()

        if not url:
            self.image_preview_label.setText("No URL")
            return

        path = sealed_image_cache_service.ensure_product_image_cached(_stable_cache_key(url), url)

        if path:
            pixmap = QPixmap(str(path)).scaled(120, 168, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image_preview_label.setPixmap(pixmap)
        else:
            self.image_preview_label.setText("Failed to load")

    def field_values(self) -> dict:
        return dict(
            name=self.name_input.text().strip(),
            set_name=self.set_name_input.text().strip() or None,
            set_code=self.set_code_input.text().strip() or None,
            booster_type=self.booster_type_combo.currentText(),
            packs_per_box=self.packs_per_box_input.value(),
            tcgcsv_category_id=self.tcgcsv_category_id_input.text().strip(),
            tcgcsv_group_id=self.tcgcsv_group_id_input.text().strip(),
            loose_pack_tcgcsv_product_id=self.loose_tcgcsv_id_input.text().strip(),
            box_tcgcsv_product_id=self.box_tcgcsv_id_input.text().strip(),
            image_url=self.image_url_input.text().strip(),
            english_confirmed=self.english_confirmed_checkbox.isChecked(),
        )


class ProductsScreen(QWidget):
    def __init__(self, current_user):
        super().__init__()

        self.current_user = current_user
        self._columns_sized = False

        layout = QVBoxLayout()

        title = QLabel("Product Catalog")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")

        button_row = QHBoxLayout()
        self.new_button = QPushButton("New Product")
        self.new_button.clicked.connect(self.open_create_dialog)
        self.edit_button = QPushButton("Edit")
        self.edit_button.clicked.connect(self.open_edit_dialog)
        self.toggle_active_button = QPushButton("Toggle Active/Inactive")
        self.toggle_active_button.clicked.connect(self.toggle_selected_active)

        button_row.addWidget(self.new_button)
        button_row.addWidget(self.edit_button)
        button_row.addWidget(self.toggle_active_button)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Name", "Booster Type", "Packs/Box", "Active", "Set", "Set Code"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        make_columns_stretch(self.table)

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addLayout(button_row)
        layout.addWidget(self.table)
        layout.addWidget(self.message_label)

        self.setLayout(layout)

        self.reload_products()

    def reload_products(self):
        products = product_service.list_products()
        self._products_by_row = products

        self.table.setRowCount(len(products))

        for row, product in enumerate(products):
            self.table.setItem(row, 0, QTableWidgetItem(product.name))
            self.table.setItem(row, 1, QTableWidgetItem(product.booster_type))
            self.table.setItem(row, 2, QTableWidgetItem(str(product.packs_per_box)))
            self.table.setItem(row, 3, QTableWidgetItem("Yes" if product.is_active else "No"))
            self.table.setItem(row, 4, QTableWidgetItem(product.set_name or ""))
            self.table.setItem(row, 5, QTableWidgetItem(product.set_code or ""))

        # Only auto-size once -- creating/editing/toggling a product calls
        # reload_products() again, and resizing on every call would keep
        # undoing a manually-widened column.
        if not self._columns_sized:
            resize_columns_to_contents(self.table)
            self._columns_sized = True

    def selected_product(self) -> Product | None:
        rows = self.table.selectionModel().selectedRows()

        if not rows:
            return None

        return self._products_by_row[rows[0].row()]

    def open_create_dialog(self):
        dialog = ProductDialog(self)

        if dialog.exec() != QDialog.Accepted:
            return

        values = dialog.field_values()

        try:
            product_service.create_product(created_by=self.current_user.id, **values)
        except (product_service.ProductValidationError, product_service.DuplicateProductError) as e:
            self.show_message(str(e), error=True)
            return
        except Exception as e:
            self.show_message(f"Could not create product: {e}", error=True)
            return

        self.reload_products()
        self._auto_refresh_prices_after_create(values["name"])

    def _auto_refresh_prices_after_create(self, product_name: str):
        """A newly created product has no price yet -- refresh automatically
        instead of making the admin remember to go press it separately on
        Shared Sealed Prices."""
        self.show_message(f"Product '{product_name}' created. Refreshing prices...", error=False)

        self._price_refresh_worker = PriceRefreshWorker(self.current_user.id)
        self._price_refresh_worker.finished_success.connect(safe_callback(
            lambda session_id: self.show_message(f"Product '{product_name}' created; prices refreshed.", error=False)
        ))
        self._price_refresh_worker.failed.connect(safe_callback(
            lambda err: self.show_message(f"Product '{product_name}' created, but price refresh failed: {err}", error=True)
        ))
        run_worker(self._price_refresh_worker)

    def open_edit_dialog(self):
        product = self.selected_product()

        if not product:
            self.show_message("Select a product first.", error=True)
            return

        dialog = ProductDialog(self, product=product)

        if dialog.exec() != QDialog.Accepted:
            return

        values = dialog.field_values()

        try:
            product_service.update_product(product.id, values, updated_by=self.current_user.id)
        except product_service.DuplicateProductError as e:
            self.show_message(str(e), error=True)
            return
        except Exception as e:
            self.show_message(f"Could not update product: {e}", error=True)
            return

        self.show_message(f"Product '{values['name']}' updated.", error=False)
        self.reload_products()

    def toggle_selected_active(self):
        product = self.selected_product()

        if not product:
            self.show_message("Select a product first.", error=True)
            return

        new_state = not product.is_active
        confirm = QMessageBox.question(
            self, "Toggle Active",
            f"{'Activate' if new_state else 'Deactivate'} '{product.name}'?",
        )

        if confirm != QMessageBox.Yes:
            return

        product_service.update_product(product.id, {"is_active": new_state}, updated_by=self.current_user.id)
        self.show_message(f"'{product.name}' is now {'active' if new_state else 'inactive'}.", error=False)
        self.reload_products()

    def show_message(self, text: str, error: bool):
        self.message_label.setStyleSheet("color: #ff6b6b;" if error else "color: #4caf50;")
        self.message_label.setText(text)
