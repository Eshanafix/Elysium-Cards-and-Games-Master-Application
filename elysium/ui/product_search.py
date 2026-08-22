"""
Type-to-filter product picker (LLD n/a; local UX fix). Used anywhere an admin
or streamer needs to pick one product out of the full catalog, instead of a
single QComboBox listing every product at once -- at 90+ products that combo
took up nearly the whole screen and made the one you wanted hard to find.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from elysium.ui.dialog_sizing import clamp_to_screen


class ProductSearchDialog(QDialog):
    def __init__(self, products: list, parent=None, title: str = "Select Product"):
        super().__init__(parent)
        self.setWindowTitle(title)
        clamp_to_screen(self, 420, 480)

        self._products = sorted(products, key=lambda p: p.name.lower())
        self._selected_product = None

        layout = QVBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search products...")
        self.search_input.textChanged.connect(self._populate)

        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(self._accept_item)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_current)
        buttons.rejected.connect(self.reject)

        layout.addWidget(QLabel("Product:"))
        layout.addWidget(self.search_input)
        layout.addWidget(self.results_list)
        layout.addWidget(buttons)

        self.setLayout(layout)

        self._populate("")
        self.search_input.setFocus()

    def _populate(self, query: str):
        self.results_list.clear()
        query = query.strip().lower()

        for product in self._products:
            if query and query not in product.name.lower():
                continue

            item = QListWidgetItem(product.name)
            item.setData(Qt.UserRole, product)
            self.results_list.addItem(item)

        if self.results_list.count() > 0:
            self.results_list.setCurrentRow(0)

    def _accept_item(self, item: QListWidgetItem):
        self._selected_product = item.data(Qt.UserRole)
        self.accept()

    def _accept_current(self):
        item = self.results_list.currentItem()

        if item is None:
            return

        self._selected_product = item.data(Qt.UserRole)
        self.accept()

    def selected_product(self):
        return self._selected_product
