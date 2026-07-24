from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.context import AppContext
from app.models import Ingredient, IngredientPriceProfile
from app.services import open_prices_category_service, open_prices_service
from app.ui.dialogs import confirm_dialog, error_dialog, info_dialog
from app.ui.widgets import COLOR_CRITICAL, COLOR_OK, COLOR_WARNING, PageHeader


class OpenPricesView(QWidget):
    """Pflegeansicht fuer Open-Prices-Kategorie-Tags und dauerhafte Produkt/Barcode-Zuordnung."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._current_profile_id: int | None = None
        self._product_candidates: list[open_prices_category_service.ProductCandidate] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(PageHeader("Open Prices", "Kategorie-Tags und Produkt-Barcodes fuer Zutaten pflegen"))

        action_row = QHBoxLayout()
        sync_button = QPushButton("Kategorien synchronisieren", self)
        sync_button.clicked.connect(self._sync_categories)
        suggest_button = QPushButton("Tags vorschlagen", self)
        suggest_button.clicked.connect(self._suggest_profiles)
        confirm_button = QPushButton("Tag bestaetigen", self)
        confirm_button.clicked.connect(self._confirm_selected_profile)
        change_tag_button = QPushButton("Tag aendern", self)
        change_tag_button.clicked.connect(self._change_selected_tag)
        action_row.addWidget(sync_button)
        action_row.addWidget(suggest_button)
        action_row.addWidget(confirm_button)
        action_row.addWidget(change_tag_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.status_label = QLabel("", self)
        layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        layout.addWidget(splitter, stretch=1)

        left = QWidget(splitter)
        left_layout = QVBoxLayout(left)
        self.profile_table = QTableWidget(0, 6, left)
        self.profile_table.setHorizontalHeaderLabels(["Zutat", "Einheit", "Tag", "Kategorie", "Status", "Barcode"])
        self.profile_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.profile_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.profile_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.profile_table.itemSelectionChanged.connect(self._on_profile_selected)
        left_layout.addWidget(self.profile_table)
        splitter.addWidget(left)

        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        self.detail_label = QLabel("Bitte eine Zutat auswaehlen.", right)
        self.detail_label.setWordWrap(True)
        right_layout.addWidget(self.detail_label)

        product_button_row = QHBoxLayout()
        load_products_button = QPushButton("Produktkandidaten laden", right)
        load_products_button.clicked.connect(self._load_product_candidates)
        assign_product_button = QPushButton("Ausgewaehltes Produkt uebernehmen", right)
        assign_product_button.clicked.connect(self._assign_selected_product)
        product_button_row.addWidget(load_products_button)
        product_button_row.addWidget(assign_product_button)
        product_button_row.addStretch(1)
        right_layout.addLayout(product_button_row)

        self.product_list = QListWidget(right)
        self.product_list.setIconSize(QSize(72, 72))
        right_layout.addWidget(self.product_list, stretch=1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

    def refresh(self) -> None:
        selected_profile_id = self._current_profile_id
        self.profile_table.blockSignals(True)
        self.profile_table.setRowCount(0)

        with self.context.session() as session:
            rows = (
                session.execute(
                    select(Ingredient)
                    .where(Ingredient.active.is_(True))
                    .order_by(Ingredient.name)
                )
                .scalars()
                .all()
            )
            for ingredient in rows:
                profile = ingredient.price_profile
                row = self.profile_table.rowCount()
                self.profile_table.insertRow(row)
                self.profile_table.setItem(row, 0, QTableWidgetItem(ingredient.name))
                self.profile_table.setItem(row, 1, QTableWidgetItem(ingredient.default_unit or ""))
                self.profile_table.setItem(row, 2, QTableWidgetItem(profile.category_tag if profile else ""))
                category_label = ""
                if profile and profile.category:
                    category_label = profile.category.name_de or profile.category.name_en or ""
                self.profile_table.setItem(row, 3, QTableWidgetItem(category_label))
                status_item = QTableWidgetItem(profile.status if profile else "needs_review")
                status_item.setForeground(_status_color(profile.status if profile else "needs_review"))
                self.profile_table.setItem(row, 4, status_item)
                self.profile_table.setItem(row, 5, QTableWidgetItem(ingredient.barcode_product_label or ingredient.barcode or ""))
                self.profile_table.item(row, 0).setData(1000, profile.id if profile else None)
                self.profile_table.item(row, 0).setData(1001, ingredient.id)

        self.profile_table.blockSignals(False)
        self._select_profile_row(selected_profile_id)
        self._update_overview_status()

    def _sync_categories(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            with self.context.session() as session:
                count = open_prices_category_service.sync_categories(session)
        except open_prices_service.OpenPricesError as exc:
            error_dialog(self, str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        info_dialog(self, f"{count} Open-Food-Facts-Kategorien synchronisiert.", title="Open Prices")
        self.refresh()

    def _suggest_profiles(self) -> None:
        if not confirm_dialog(
            self,
            "Tags vorschlagen",
            "Kategorie-Tags fuer alle aktiven Zutaten vorschlagen? Bereits bestaetigte Profile bleiben unveraendert.",
        ):
            return
        with self.context.session() as session:
            suggested, skipped = open_prices_category_service.suggest_profiles_for_all(session)
        info_dialog(self, f"{suggested} Tags vorgeschlagen, {skipped} Zutaten ohne sicheren Vorschlag.", title="Open Prices")
        self.refresh()

    def _confirm_selected_profile(self) -> None:
        if self._current_profile_id is None:
            error_dialog(self, "Bitte zuerst eine Zutat mit vorgeschlagenem Tag auswaehlen.")
            return
        with self.context.session() as session:
            profile = session.get(IngredientPriceProfile, self._current_profile_id)
            if profile is None:
                return
            open_prices_category_service.confirm_profile(profile)
        self.refresh()

    def _change_selected_tag(self) -> None:
        if self._current_profile_id is None:
            error_dialog(self, "Bitte zuerst eine Zutat mit Preisprofil auswaehlen.")
            return
        dialog = CategorySearchDialog(self.context, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        category_tag = dialog.selected_tag()
        if not category_tag:
            return
        with self.context.session() as session:
            profile = session.get(IngredientPriceProfile, self._current_profile_id)
            if profile is None:
                return
            terms = profile.search_terms
            open_prices_category_service.update_profile_category(
                profile,
                category_tag=category_tag,
                search_terms=terms,
                confirm=True,
            )
        self.refresh()

    def _on_profile_selected(self) -> None:
        selected = self.profile_table.selectedItems()
        if not selected:
            self._current_profile_id = None
            self.detail_label.setText("Bitte eine Zutat auswaehlen.")
            self.product_list.clear()
            self._product_candidates = []
            return
        row = selected[0].row()
        profile_id = self.profile_table.item(row, 0).data(1000)
        ingredient_id = self.profile_table.item(row, 0).data(1001)
        self._current_profile_id = profile_id
        self.product_list.clear()
        self._product_candidates = []

        with self.context.session() as session:
            ingredient = session.get(Ingredient, ingredient_id)
            if ingredient is None:
                return
            profile = ingredient.price_profile
            if profile is None:
                self.detail_label.setText(
                    f"{ingredient.name}: noch kein Kategorie-Tag. Erst 'Tags vorschlagen' ausfuehren."
                )
                return
            category_label = (profile.category.name_de or profile.category.name_en) if profile.category else profile.category_tag
            self.detail_label.setText(
                f"{ingredient.name}: {profile.category_tag} ({category_label}) | Status: {profile.status}"
            )

    def _load_product_candidates(self) -> None:
        if self._current_profile_id is None:
            error_dialog(self, "Bitte zuerst eine Zutat mit Kategorie-Tag auswaehlen.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            with self.context.session() as session:
                profile = session.get(IngredientPriceProfile, self._current_profile_id)
                if profile is None:
                    return
                candidates = open_prices_category_service.find_product_candidates_for_profile(profile)
        except open_prices_service.OpenPricesError as exc:
            error_dialog(self, str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        self._product_candidates = candidates[:30]
        self.product_list.clear()
        for candidate in self._product_candidates:
            item = QListWidgetItem(_candidate_label(candidate))
            if candidate.image_url:
                image_bytes = open_prices_service.fetch_image_bytes(candidate.image_url, timeout=8)
                if image_bytes:
                    pixmap = QPixmap()
                    if pixmap.loadFromData(image_bytes):
                        item.setIcon(QIcon(pixmap))
            self.product_list.addItem(item)
        self.detail_label.setText(f"{len(self._product_candidates)} deutsche Produktkandidaten geladen.")

    def _assign_selected_product(self) -> None:
        row = self.product_list.currentRow()
        if row < 0 or row >= len(self._product_candidates) or self._current_profile_id is None:
            error_dialog(self, "Bitte zuerst ein Produkt auswaehlen.")
            return
        candidate = self._product_candidates[row]
        with self.context.session() as session:
            profile = session.get(IngredientPriceProfile, self._current_profile_id)
            if profile is None or profile.ingredient is None:
                return
            open_prices_category_service.assign_product_to_ingredient(profile.ingredient, candidate)
        info_dialog(self, f"Barcode {candidate.product_code} wurde dauerhaft mit der Zutat verknuepft.", title="Open Prices")
        self.refresh()

    def _select_profile_row(self, profile_id: int | None) -> None:
        if profile_id is None:
            return
        for row in range(self.profile_table.rowCount()):
            if self.profile_table.item(row, 0).data(1000) == profile_id:
                self.profile_table.selectRow(row)
                return

    def _update_overview_status(self) -> None:
        total = self.profile_table.rowCount()
        confirmed = 0
        suggested = 0
        for row in range(total):
            status = self.profile_table.item(row, 4).text()
            if status == open_prices_category_service.PROFILE_STATUS_CONFIRMED:
                confirmed += 1
            elif status == open_prices_category_service.PROFILE_STATUS_SUGGESTED:
                suggested += 1
        self.status_label.setText(
            f"{total} aktive Zutaten | {confirmed} bestaetigt | {suggested} vorgeschlagen | {total - confirmed - suggested} offen"
        )


def _candidate_label(candidate: open_prices_category_service.ProductCandidate) -> str:
    date_text = candidate.price_date.isoformat() if candidate.price_date else "Datum unbekannt"
    quantity_text = f" | {candidate.quantity}" if candidate.quantity else ""
    brand_text = f" ({candidate.brands})" if candidate.brands else ""
    store_text = f" | {candidate.store_name}" if candidate.store_name else ""
    return (
        f"{candidate.product_name}{brand_text}{quantity_text}\n"
        f"Barcode {candidate.product_code} | {candidate.price} {candidate.currency} | {date_text}{store_text}"
    )


def _status_color(status: str):
    from PySide6.QtGui import QColor

    if status == open_prices_category_service.PROFILE_STATUS_CONFIRMED:
        return QColor(COLOR_OK)
    if status == open_prices_category_service.PROFILE_STATUS_SUGGESTED:
        return QColor(COLOR_WARNING)
    return QColor(COLOR_CRITICAL)


class CategorySearchDialog(QDialog):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setWindowTitle("Open-Prices-Tag waehlen")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Tag oder Kategoriename suchen, z. B. apple-compotes")
        self.search_edit.returnPressed.connect(self._search)
        layout.addWidget(self.search_edit)

        search_button = QPushButton("Suchen", self)
        search_button.clicked.connect(self._search)
        layout.addWidget(search_button)

        self.result_combo = QComboBox(self)
        layout.addWidget(self.result_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _search(self) -> None:
        query = self.search_edit.text().strip()
        self.result_combo.clear()
        if not query:
            return
        with self.context.session() as session:
            categories = open_prices_category_service.search_categories(session, query)
            for category in categories:
                label = _category_label(category)
                self.result_combo.addItem(label, category.tag)

    def selected_tag(self) -> str | None:
        value = self.result_combo.currentData()
        return str(value) if value else None


def _category_label(category) -> str:
    name = category.name_de or category.name_en or ""
    suffix = f" - {name}" if name else ""
    return f"{category.tag}{suffix}"
