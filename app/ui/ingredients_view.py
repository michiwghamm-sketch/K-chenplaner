from __future__ import annotations

from datetime import datetime
from xml.sax.saxutils import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.context import AppContext
from app.models import INGREDIENT_CATEGORIES, NON_FOOD_CATEGORY
from app.services import ingredient_service, open_prices_category_service, open_prices_service, price_service, shopping_service, unit_service
from app.ui.dialogs import (
    AddPriceDialog,
    BarcodeSearchDialog,
    ManageStandardItemsDialog,
    OpenPricesProductPriceDialog,
    RecipeIngredientChoice,
    ReplaceIngredientDialog,
    SimilarIngredientsWarningDialog,
    StandardShoppingItemRow,
    confirm_dialog,
    error_dialog,
    info_dialog,
    prompt_int,
    prompt_text,
)
from app.ui.widgets import COLOR_CRITICAL, PageHeader, SearchBar, UnitComboBox


def _manual_price_notes(barcode: str | None, barcode_label: str | None) -> str | None:
    if not barcode:
        return None
    if barcode_label:
        return f"Open Prices Produkt: {barcode_label} | Barcode: {barcode}"
    return f"Open Prices Barcode: {barcode}"


def _standard_item_ingredient_choices(session) -> list[RecipeIngredientChoice]:
    """Nur Non-Food-Zutaten im Verbrauchsmittel-Dialog anbieten.

    Bereits bestehende StandardShoppingItem-Zuordnungen bleiben sichtbar, selbst wenn alte Daten
    noch nicht als Non-Food markiert sind; beim Speichern werden sie nachgezogen.
    """
    standard_item_ingredient_ids = {
        item.ingredient_id for item in shopping_service.list_standard_items(session) if item.ingredient_id is not None
    }
    return [
        RecipeIngredientChoice(
            id=ingredient.id,
            name=ingredient.name,
            default_unit=ingredient.default_unit,
            compatible_units=unit_service.compatible_units(session, ingredient.default_unit),
        )
        for ingredient in ingredient_service.search_ingredients(session, active_only=False)
        if ingredient.category == NON_FOOD_CATEGORY or ingredient.id in standard_item_ingredient_ids
    ]


class IngredientsView(QWidget):
    """Zutatenverwaltung: Liste, Suche, Detail und zentrale Preise.

    Preise sind bewusst hier statt in einer eigenen Ansicht verwaltet - eine Zutat
    und ihr Preis gehoeren fachlich zusammen, ein separater Reiter erforderte
    staendiges Hin- und Herwechseln.
    """

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._current_ingredient_id: int | None = None
        self._unit_names: list[str] = []
        self._category_suggestions: list[str] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(PageHeader("Zutaten", "Zutatenstammdaten, Open-Prices-Produkte und Preise pflegen"))

        price_toolbar = QHBoxLayout()
        price_toolbar.addWidget(QLabel("Preisjahr:", self))
        self.year_spin = QSpinBox(self)
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setValue(datetime.now().year)
        self.year_spin.valueChanged.connect(self._reload_price_overview)
        price_toolbar.addWidget(self.year_spin)
        self.copy_prices_button = QPushButton("Preise aus Vorjahr übernehmen", self)
        self.copy_prices_button.clicked.connect(self._copy_from_previous_year)
        price_toolbar.addWidget(self.copy_prices_button)
        price_toolbar.addStretch(1)
        outer.addLayout(price_toolbar)

        self.missing_prices_label = QLabel("", self)
        self.missing_prices_label.setTextFormat(Qt.TextFormat.RichText)
        self.missing_prices_label.setWordWrap(True)
        self.missing_prices_label.linkActivated.connect(self._on_missing_price_link_clicked)
        outer.addWidget(self.missing_prices_label)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        outer.addWidget(splitter, stretch=1)

        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        self.search_bar = SearchBar("Zutat suchen...", left)
        self.search_bar.text_changed.connect(self._reload_list)
        self.active_only_checkbox = QCheckBox("Nur aktive Zutaten", left)
        self.active_only_checkbox.setChecked(True)
        self.active_only_checkbox.stateChanged.connect(self._reload_list)
        self.without_price_checkbox = QCheckBox("Nur Zutaten ohne Preis", left)
        self.without_price_checkbox.stateChanged.connect(self._reload_list)
        self.ingredient_list = QListWidget(left)
        self.ingredient_list.currentItemChanged.connect(self._on_selected)
        new_button = QPushButton("Neue Zutat", left)
        new_button.clicked.connect(self._create_ingredient)
        self.assign_barcodes_button = QPushButton("Fehlende Barcodes zuordnen", left)
        self.assign_barcodes_button.clicked.connect(self._assign_missing_barcodes)
        self.manage_standard_items_button = QPushButton("Verbrauchsmittel verwalten...", left)
        self.manage_standard_items_button.setToolTip(
            "Wiederkehrende Verbrauchsmittel (z. B. Non-Food), die bei jeder neuen "
            "Einkaufsliste automatisch mit übernommen werden."
        )
        self.manage_standard_items_button.clicked.connect(self._manage_standard_items)

        left_layout.addWidget(self.search_bar)
        left_layout.addWidget(self.active_only_checkbox)
        left_layout.addWidget(self.without_price_checkbox)
        left_layout.addWidget(self.ingredient_list)
        left_layout.addWidget(new_button)
        left_layout.addWidget(self.assign_barcodes_button)
        left_layout.addWidget(self.manage_standard_items_button)
        splitter.addWidget(left)

        right_content = QWidget(self)
        right_layout = QVBoxLayout(right_content)

        columns_row = QHBoxLayout()
        right_layout.addLayout(columns_row, stretch=1)

        # Linke Spalte: Stammdaten + Barcode-Verknuepfung.
        left_column = QVBoxLayout()
        columns_row.addLayout(left_column, stretch=1)

        form = QFormLayout()
        self.name_edit = QLineEdit(right_content)
        self.unit_edit = UnitComboBox(right_content)
        self.active_checkbox = QCheckBox("Aktiv", right_content)
        self.category_combo = QComboBox(right_content)
        self.category_combo.setEditable(True)
        self.category_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.category_combo.setToolTip(
            "Kategorie fuer die Sortierung in der Einkaufsliste (z. B. Obst, Gemüse, Tiefkühl, "
            "Trockenware) - freier Text, eigene Kategorien moeglich. \"Non-Food\" blendet die "
            "Zutat zusaetzlich aus der Rezept-Zutaten-Auswahl aus, taucht aber weiterhin normal "
            "in der Einkaufsliste auf."
        )
        self.notes_edit = QPlainTextEdit(right_content)
        self.notes_edit.setFixedHeight(70)

        form.addRow("Name", self.name_edit)
        form.addRow("Standardeinheit", self.unit_edit)
        form.addRow("Kategorie", self.category_combo)
        form.addRow("", self.active_checkbox)
        form.addRow("Notizen", self.notes_edit)
        left_column.addLayout(form)

        self.barcode_label = QLabel("Kein Produkt verknuepft", right_content)
        self.barcode_label.setWordWrap(True)
        barcode_row = QHBoxLayout()
        self.search_barcode_button = QPushButton("Open Prices suchen", right_content)
        self.search_barcode_button.clicked.connect(self._search_open_prices_product)
        self.remove_barcode_button = QPushButton("Verknuepfung entfernen", right_content)
        self.remove_barcode_button.clicked.connect(self._remove_barcode_link)
        barcode_row.addWidget(self.search_barcode_button)
        barcode_row.addWidget(self.remove_barcode_button)
        left_column.addWidget(self.barcode_label)
        left_column.addLayout(barcode_row)

        left_column.addWidget(QLabel("Preise", right_content))
        self.price_table = QTableWidget(0, 6, right_content)
        self.price_table.setHorizontalHeaderLabels(["Jahr", "Preis", "Einheit", "Quelle", "Laden", "Notizen"])
        self.price_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.price_table.setSortingEnabled(True)
        self.price_table.setMaximumHeight(150)
        left_column.addWidget(self.price_table)

        price_button_row = QHBoxLayout()
        self.add_price_button = QPushButton("Preis erfassen", right_content)
        self.add_price_button.clicked.connect(self._add_price)
        self.delete_price_button = QPushButton("Preis loeschen", right_content)
        self.delete_price_button.setProperty("role", "danger")
        self.delete_price_button.clicked.connect(self._delete_selected_price)
        price_button_row.addWidget(self.add_price_button)
        price_button_row.addWidget(self.delete_price_button)
        price_button_row.addStretch(1)
        left_column.addLayout(price_button_row)
        left_column.addStretch(1)

        # Rechte Spalte: nur die Rezeptverwendung.
        right_column = QVBoxLayout()
        columns_row.addLayout(right_column, stretch=1)

        right_column.addWidget(QLabel("Verwendet in Rezepten", right_content))
        self.recipe_usage_list = QListWidget(right_content)
        right_column.addWidget(self.recipe_usage_list, stretch=1)

        button_row = QHBoxLayout()
        save_button = QPushButton("Speichern", right_content)
        save_button.clicked.connect(self._save_ingredient)
        cancel_button = QPushButton("Abbrechen", right_content)
        cancel_button.clicked.connect(self._reload_detail)
        deactivate_button = QPushButton("Deaktivieren", right_content)
        deactivate_button.clicked.connect(self._deactivate_ingredient)
        delete_button = QPushButton("Löschen", right_content)
        delete_button.setProperty("role", "danger")
        delete_button.clicked.connect(self._delete_ingredient)
        button_row.addWidget(save_button)
        button_row.addWidget(cancel_button)
        button_row.addWidget(deactivate_button)
        button_row.addWidget(delete_button)
        button_row.addStretch(1)
        right_layout.addLayout(button_row)

        right_scroll = QScrollArea(self)
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(right_content)
        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

    def refresh(self) -> None:
        with self.context.session() as session:
            self._unit_names = unit_service.list_unit_names(session)
            used_categories = ingredient_service.list_used_categories(session)
        self._category_suggestions = list(INGREDIENT_CATEGORIES) + [
            category for category in used_categories if category not in INGREDIENT_CATEGORIES
        ]
        self._reload_list()
        self._reload_price_overview()

    def _reload_list(self) -> None:
        target_id = self._current_ingredient_id
        self.ingredient_list.blockSignals(True)
        self.ingredient_list.clear()
        with self.context.session() as session:
            ingredients = ingredient_service.search_ingredients(
                session,
                query=self.search_bar.text() or None,
                active_only=self.active_only_checkbox.isChecked(),
                without_price=self.without_price_checkbox.isChecked(),
            )
            for ingredient in ingredients:
                item = QListWidgetItem(ingredient.name)
                item.setData(1000, ingredient.id)
                self.ingredient_list.addItem(item)
        self.ingredient_list.blockSignals(False)

        if not self.ingredient_list.count():
            self._current_ingredient_id = None
            self._clear_detail()
            return

        # Nach dem Neuaufbau der Liste die zuvor ausgewählte Zeile wiederfinden, statt
        # blind auf Zeile 0 zu springen (sonst landet man z. B. nach dem Speichern oder
        # Anlegen einer Zutat scheinbar zufällig bei einer ganz anderen Zutat).
        if target_id is not None:
            for row in range(self.ingredient_list.count()):
                if self.ingredient_list.item(row).data(1000) == target_id:
                    self.ingredient_list.setCurrentRow(row)
                    return
        self.ingredient_list.setCurrentRow(0)

    def _reload_price_overview(self) -> None:
        year = self.year_spin.value()
        with self.context.session() as session:
            missing = price_service.missing_price_ingredients(session, year=year)

        if missing:
            # Jeder Name ist ein anklickbarer Link (href=Zutat-ID) statt reinem Text - Klick
            # springt direkt zur Zutat, statt dass man sie erst in der Liste links suchen muss.
            links = [
                f'<a href="{i.id}" style="color:{COLOR_CRITICAL};">{escape(i.name)}</a>' for i in missing[:10]
            ]
            suffix = " ..." if len(missing) > 10 else ""
            self.missing_prices_label.setText(
                f'<span style="color:{COLOR_CRITICAL};">Fehlende Preise für {year} '
                f"({len(missing)}): {', '.join(links)}{suffix}</span>"
            )
            self.missing_prices_label.setStyleSheet("")
        else:
            self.missing_prices_label.setText(f"Alle aktiven Zutaten haben einen Preis für {year}.")
            self.missing_prices_label.setStyleSheet("")

    def _on_missing_price_link_clicked(self, href: str) -> None:
        try:
            ingredient_id = int(href)
        except ValueError:
            return
        self._select_ingredient_by_id(ingredient_id)

    def _on_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            self._current_ingredient_id = None
            self._clear_detail()
            return
        self._current_ingredient_id = current.data(1000)
        self._reload_detail()

    def _clear_detail(self) -> None:
        self.name_edit.clear()
        self.unit_edit.set_units(self._unit_names)
        self.unit_edit.set_current_unit(None)
        self.active_checkbox.setChecked(True)
        self.category_combo.clear()
        self.category_combo.addItems(self._category_suggestions)
        self.category_combo.setCurrentIndex(-1)
        self.notes_edit.clear()
        self.barcode_label.setText("Kein Produkt verknuepft")
        self.remove_barcode_button.setEnabled(False)
        self.price_table.setRowCount(0)
        self.recipe_usage_list.clear()

    def _reload_detail(self) -> None:
        if self._current_ingredient_id is None:
            self._clear_detail()
            return
        with self.context.session() as session:
            ingredient = session.get(ingredient_service.Ingredient, self._current_ingredient_id)
            if ingredient is None:
                self._clear_detail()
                return
            self.name_edit.setText(ingredient.name)
            self.unit_edit.set_units(self._unit_names)
            self.unit_edit.set_current_unit(ingredient.default_unit)
            self.active_checkbox.setChecked(ingredient.active)
            self.category_combo.clear()
            self.category_combo.addItems(self._category_suggestions)
            self.category_combo.setCurrentText(ingredient.category or "")
            self.notes_edit.setPlainText(ingredient.notes or "")

            if ingredient.barcode:
                label = ingredient.barcode_product_label or ingredient.barcode
                self.barcode_label.setText(f"Verknuepftes Produkt: {label} (Barcode {ingredient.barcode})")
            else:
                self.barcode_label.setText("Kein Produkt verknuepft")
            self.remove_barcode_button.setEnabled(bool(ingredient.barcode))

            self.price_table.setSortingEnabled(False)
            self.price_table.setRowCount(0)
            for price in sorted(ingredient.prices, key=lambda p: p.year or 0, reverse=True):
                row = self.price_table.rowCount()
                self.price_table.insertRow(row)
                year_item = QTableWidgetItem(str(price.year) if price.year else "")
                year_item.setData(1000, price.id)
                self.price_table.setItem(row, 0, year_item)
                self.price_table.setItem(row, 1, QTableWidgetItem(str(price.price_per_unit)))
                self.price_table.setItem(row, 2, QTableWidgetItem(price.unit))
                self.price_table.setItem(row, 3, QTableWidgetItem(price.source or ""))
                self.price_table.setItem(row, 4, QTableWidgetItem(price.store or ""))
                self.price_table.setItem(row, 5, QTableWidgetItem(price.notes or ""))
            self.price_table.setSortingEnabled(True)

            self.recipe_usage_list.clear()
            usage_lines = ingredient_service.describe_recipe_usage(ingredient)
            if usage_lines:
                for line in usage_lines:
                    self.recipe_usage_list.addItem(line)
            else:
                self.recipe_usage_list.addItem("Wird in keinem Rezept verwendet")

    def _create_ingredient(self) -> None:
        with self.context.session() as session:
            default_name = ingredient_service.generate_unique_ingredient_name(session)
        name = prompt_text(self, "Neue Zutat", "Name der Zutat:", default=default_name)
        if not name:
            return
        try:
            with self.context.session() as session:
                ingredient = ingredient_service.create_ingredient(session, name=name)
                self._current_ingredient_id = ingredient.id
        except IntegrityError:
            error_dialog(self, f"Eine Zutat mit dem Namen '{name}' existiert bereits. Bitte einen anderen Namen wählen.")
            return
        self._reload_list()
        self._select_ingredient_by_id(self._current_ingredient_id)
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def _select_ingredient_by_id(self, ingredient_id: int | None) -> None:
        for row in range(self.ingredient_list.count()):
            item = self.ingredient_list.item(row)
            if item.data(1000) == ingredient_id:
                self.ingredient_list.setCurrentRow(row)
                return

    def _save_ingredient(self) -> None:
        if self._current_ingredient_id is None:
            return
        name = self.name_edit.text().strip()
        if not name:
            error_dialog(self, "Der Zutatenname darf nicht leer sein.")
            return

        with self.context.session() as session:
            similar = ingredient_service.find_similar_ingredients(
                session, name, exclude_id=self._current_ingredient_id
            )
            matches = [
                (match.name, similarity, reason, len(match.recipe_links) + len(match.prices))
                for match, similarity, reason in similar
            ]

        if matches:
            dialog = SimilarIngredientsWarningDialog(name, matches, self)
            if dialog.exec() != SimilarIngredientsWarningDialog.DialogCode.Accepted:
                return

        with self.context.session() as session:
            ingredient = session.get(ingredient_service.Ingredient, self._current_ingredient_id)
            if ingredient is None:
                return
            try:
                ingredient_service.update_ingredient(
                    ingredient,
                    name=name,
                    default_unit=self.unit_edit.current_unit(),
                    active=self.active_checkbox.isChecked(),
                    category=self.category_combo.currentText().strip() or None,
                    notes=self.notes_edit.toPlainText().strip() or None,
                )
            except ValueError as exc:
                error_dialog(self, str(exc))
                return
        self._reload_list()
        self._select_ingredient_by_id(self._current_ingredient_id)

    def _deactivate_ingredient(self) -> None:
        if self._current_ingredient_id is None:
            return
        if not confirm_dialog(self, "Zutat deaktivieren", "Soll diese Zutat wirklich deaktiviert werden?"):
            return
        with self.context.session() as session:
            ingredient = session.get(ingredient_service.Ingredient, self._current_ingredient_id)
            if ingredient is not None:
                ingredient_service.deactivate_ingredient(ingredient)
        self._reload_list()

    def _delete_ingredient(self) -> None:
        if self._current_ingredient_id is None:
            return
        with self.context.session() as session:
            ingredient = session.get(ingredient_service.Ingredient, self._current_ingredient_id)
            if ingredient is None:
                return
            name = ingredient.name
            usage_lines = ingredient_service.describe_recipe_usage(ingredient)
            is_used = bool(ingredient.recipe_links)
            candidates = (
                [(i.id, i.name) for i in ingredient_service.search_ingredients(session) if i.id != ingredient.id]
                if is_used
                else []
            )

        if is_used:
            dialog = ReplaceIngredientDialog(name, usage_lines, candidates, self)
            if dialog.exec() != ReplaceIngredientDialog.DialogCode.Accepted:
                return
            replacement_id = dialog.selected_replacement_id()
            with self.context.session() as session:
                keep = session.get(ingredient_service.Ingredient, replacement_id)
                remove = session.get(ingredient_service.Ingredient, self._current_ingredient_id)
                if keep is None or remove is None:
                    return
                replacement_name = keep.name
                ingredient_service.merge_ingredients(session, keep=keep, remove=remove)
            info_dialog(self, f"'{name}' wurde durch '{replacement_name}' ersetzt und gelöscht.")
        else:
            if not confirm_dialog(self, "Zutat löschen", "Diese Zutat wirklich unwiderruflich löschen?"):
                return
            with self.context.session() as session:
                ingredient = session.get(ingredient_service.Ingredient, self._current_ingredient_id)
                if ingredient is None:
                    return
                try:
                    ingredient_service.delete_ingredient(session, ingredient)
                except ValueError as exc:
                    error_dialog(self, str(exc))
                    return
        self._current_ingredient_id = None
        self._reload_list()

    def _remove_barcode_link(self) -> None:
        if self._current_ingredient_id is None:
            return
        if not confirm_dialog(
            self,
            "Verknüpfung entfernen",
            "Die Open-Prices-Produktverknüpfung dieser Zutat wirklich entfernen?",
        ):
            return
        with self.context.session() as session:
            ingredient = session.get(ingredient_service.Ingredient, self._current_ingredient_id)
            if ingredient is not None:
                ingredient.barcode = None
                ingredient.barcode_product_label = None
        self._reload_detail()

    def _assign_missing_barcodes(self) -> None:
        with self.context.session() as session:
            pending = session.execute(
                select(ingredient_service.Ingredient)
                .where(ingredient_service.Ingredient.active.is_(True), ingredient_service.Ingredient.barcode.is_(None))
                .order_by(ingredient_service.Ingredient.name)
            ).scalars().all()
            pending_items = [(i.id, i.name, i.default_unit) for i in pending]

        if not pending_items:
            info_dialog(self, "Alle aktiven Zutaten haben bereits ein verknuepftes Produkt.")
            return

        assigned = 0
        skipped = 0
        total = len(pending_items)
        for index, (ingredient_id, name, default_unit) in enumerate(pending_items, start=1):
            dialog = BarcodeSearchDialog(
                name, default_unit, self, progress_text=f"Zutat {index} von {total}: {name}"
            )
            dialog.exec()
            data = dialog.result_data()
            stopped = dialog.was_stopped()

            if data is not None:
                with self.context.session() as session:
                    ingredient = session.get(ingredient_service.Ingredient, ingredient_id)
                    if ingredient is not None:
                        ingredient.barcode = data["barcode"]
                        ingredient.barcode_product_label = data["label"]
                assigned += 1
            else:
                skipped += 1

            if stopped:
                break

        info_dialog(self, f"{assigned} Zutaten verknuepft, {skipped} uebersprungen/nicht zugeordnet.")
        self._reload_list()
        self._reload_detail()

    def _manage_standard_items(self) -> None:
        from app.models import CampYear

        with self.context.session() as session:
            ingredient_choices = _standard_item_ingredient_choices(session)

            reference_camp_year = None
            if self.context.current_camp_year_id is not None:
                reference_camp_year = session.get(CampYear, self.context.current_camp_year_id)
            if reference_camp_year is None:
                reference_camp_year = session.execute(
                    select(CampYear).order_by(CampYear.year.desc())
                ).scalars().first()

            rows = []
            for item in shopping_service.list_standard_items(session):
                hint = None
                if reference_camp_year is not None:
                    previous_quantity = shopping_service.previous_year_quantity(
                        session, reference_camp_year, item.ingredient_id, item.default_unit
                    )
                    if previous_quantity is not None:
                        hint = f"Vorjahr: {shopping_service.format_quantity_de(previous_quantity)} {item.default_unit or ''}"
                rows.append(
                    StandardShoppingItemRow(
                        id=item.id,
                        ingredient_id=item.ingredient_id,
                        ingredient_name=item.ingredient.name if item.ingredient else "",
                        quantity=item.default_quantity,
                        unit=item.default_unit or "",
                        active=item.active,
                        typical_stock_note=item.typical_stock_note,
                        previous_year_hint=hint,
                    )
                )

        dialog = ManageStandardItemsDialog(rows, ingredient_choices, self)
        if dialog.exec() != ManageStandardItemsDialog.DialogCode.Accepted:
            return
        result = dialog.result_data()

        with self.context.session() as session:
            existing_by_id = {item.id: item for item in shopping_service.list_standard_items(session)}
            for entry_id in result["removed_ids"]:
                item = existing_by_id.get(entry_id)
                if item is not None:
                    shopping_service.delete_standard_item(session, item)

            for row in result["rows"]:
                ingredient_id = row["ingredient_id"]
                if ingredient_id is None:
                    name = (row["new_ingredient_name"] or "").strip()
                    if not name:
                        continue
                    ingredient = ingredient_service.find_or_create_ingredient(session, name=name, default_unit=row["unit"])
                    ingredient_id = ingredient.id
                else:
                    ingredient = session.get(ingredient_service.Ingredient, ingredient_id)
                    if ingredient is None:
                        continue
                ingredient.category = NON_FOOD_CATEGORY
                ingredient.active = True
                if row["unit"] and not ingredient.default_unit:
                    ingredient.default_unit = row["unit"]

                if row["id"] is not None and row["id"] in existing_by_id:
                    item = existing_by_id[row["id"]]
                    shopping_service.update_standard_item(
                        item,
                        ingredient_id=ingredient_id,
                        default_quantity=row["quantity"],
                        default_unit=row["unit"],
                        typical_stock_note=row["typical_stock_note"],
                        active=row["active"],
                    )
                else:
                    try:
                        shopping_service.create_standard_item(
                            session,
                            ingredient=ingredient,
                            default_quantity=row["quantity"],
                            default_unit=row["unit"],
                            typical_stock_note=row["typical_stock_note"],
                        )
                    except ValueError as exc:
                        error_dialog(self, str(exc))

        info_dialog(self, "Verbrauchsmittel gespeichert.")

    def _add_price(self) -> None:
        if self._current_ingredient_id is None:
            error_dialog(self, "Bitte zuerst eine Zutat auswählen oder anlegen.")
            return
        with self.context.session() as session:
            ingredient = session.get(ingredient_service.Ingredient, self._current_ingredient_id)
            if ingredient is None:
                return
            ingredients = [(ingredient.id, ingredient.name)]
            default_unit = ingredient.default_unit
            barcode = ingredient.barcode
            barcode_label = ingredient.barcode_product_label
            units = unit_service.list_unit_names(session)

        if barcode:
            self._add_price_from_linked_barcode(
                ingredient_id=self._current_ingredient_id,
                ingredient_name=ingredients[0][1],
                default_unit=default_unit,
                barcode=barcode,
                barcode_label=barcode_label,
            )
            return

        dialog = AddPriceDialog(
            ingredients,
            units,
            self.year_spin.value(),
            self,
            selected_ingredient_id=self._current_ingredient_id,
            default_unit=default_unit,
            default_source="Manuell (verknuepftes Open-Prices-Produkt)" if barcode else "Manuell",
            default_notes=_manual_price_notes(barcode, barcode_label),
        )
        if dialog.exec() != AddPriceDialog.DialogCode.Accepted:
            return
        data = dialog.result_data()
        if data is None:
            error_dialog(self, "Bitte gültige Werte angeben.")
            return

        with self.context.session() as session:
            from app.models import IngredientPrice

            session.add(IngredientPrice(**data))
        self._reload_detail()
        self._reload_price_overview()

    def _add_price_from_linked_barcode(
        self,
        *,
        ingredient_id: int,
        ingredient_name: str,
        default_unit: str | None,
        barcode: str,
        barcode_label: str | None,
    ) -> None:
        lookup_error: str | None = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            lookup = open_prices_service.lookup_product_prices(barcode, size=1)
        except open_prices_service.OpenPricesError as exc:
            lookup = None
            lookup_error = str(exc)
        finally:
            QApplication.restoreOverrideCursor()
        if lookup is None:
            error_dialog(self, f"Für den verknüpften Barcode wurde kein Open-Prices-Preis gefunden.\n\n{lookup_error}")
            return

        observation = lookup.latest_observation
        if observation is None:
            error_dialog(self, "Für den verknüpften Barcode wurden keine Preisbeobachtungen gefunden.")
            return

        label = barcode_label or lookup.product.name
        price_record = open_prices_service.build_ingredient_price_from_observation(
            ingredient_id,
            observation,
            product_quantity=lookup.product.quantity,
            target_unit=default_unit,
            notes_prefix=f"Ueber verknuepften Barcode gefunden | Produkt: {label} | Barcode: {barcode}",
        )
        price_record.year = self.year_spin.value()

        with self.context.session() as session:
            session.add(price_record)

        quantity = f" ({lookup.product.quantity})" if lookup.product.quantity else ""
        store = f" bei {observation.store_name}" if observation.store_name else ""
        info_dialog(
            self,
            (
                f"Preis fuer {ingredient_name} aus Open Prices erfasst: "
                f"{price_record.price_per_unit} {observation.currency} pro {price_record.unit} "
                f"aus {lookup.product.name}{quantity}{store}."
            ),
        )
        self._reload_detail()
        self._reload_price_overview()

    def _search_open_prices_product(self) -> None:
        if self._current_ingredient_id is None:
            error_dialog(self, "Bitte zuerst eine Zutat auswaehlen oder anlegen.")
            return
        with self.context.session() as session:
            ingredient = session.get(ingredient_service.Ingredient, self._current_ingredient_id)
            if ingredient is None:
                return
            if ingredient.price_profile is None:
                suggestion = open_prices_category_service.suggest_category_for_ingredient(session, ingredient)
                if suggestion is not None:
                    open_prices_category_service.create_or_update_profile_from_suggestion(session, ingredient, suggestion)
                    session.flush()
            ingredient_name = ingredient.name
            default_unit = ingredient.default_unit
            profile_id = ingredient.price_profile.id if ingredient.price_profile else None

        with self.context.session() as session:
            profile = session.get(open_prices_category_service.IngredientPriceProfile, profile_id) if profile_id else None
            dialog = OpenPricesProductPriceDialog(ingredient_name, default_unit, profile, self)
            if dialog.exec() != OpenPricesProductPriceDialog.DialogCode.Accepted:
                return
            candidate = dialog.selected_candidate()
        if candidate is None:
            error_dialog(self, "Bitte ein Open-Prices-Produkt auswaehlen.")
            return

        with self.context.session() as session:
            ingredient = session.get(ingredient_service.Ingredient, self._current_ingredient_id)
            if ingredient is None:
                return
            open_prices_category_service.assign_product_to_ingredient(ingredient, candidate)
            observation = open_prices_service.OpenPriceObservation(
                product_code=candidate.product_code,
                product_name=candidate.product_name,
                price=candidate.price,
                currency=candidate.currency,
                date=candidate.price_date,
                store_name=candidate.store_name,
                location_name=candidate.store_name,
                proof_type=None,
                price_is_discounted=False,
            )
            price_record = open_prices_service.build_ingredient_price_from_observation(
                ingredient.id,
                observation,
                product_quantity=candidate.quantity,
                target_unit=ingredient.default_unit,
                notes_prefix=f"Open Prices Produktauswahl | Produkt: {candidate.product_name} | Barcode: {candidate.product_code}",
            )
            price_record.year = self.year_spin.value()
            session.add(price_record)

        quantity = f" ({candidate.quantity})" if candidate.quantity else ""
        store = f" bei {candidate.store_name}" if candidate.store_name else ""
        info_dialog(
            self,
            (
                f"Preis fuer {candidate.product_name}{quantity} importiert: "
                f"{price_record.price_per_unit} {candidate.currency} pro {price_record.unit}{store}."
            ),
        )
        self._reload_detail()
        self._reload_price_overview()

    def _delete_selected_price(self) -> None:
        if self._current_ingredient_id is None:
            return
        row = self.price_table.currentRow()
        if row < 0:
            error_dialog(self, "Bitte zuerst einen Preis in der Tabelle auswaehlen.")
            return
        price_id = self.price_table.item(row, 0).data(1000)
        if price_id is None:
            return
        if not confirm_dialog(self, "Preis loeschen", "Diesen Preis wirklich aus der Zutatenhistorie loeschen?"):
            return
        with self.context.session() as session:
            from app.models import IngredientPrice

            price = session.get(IngredientPrice, price_id)
            if price is not None:
                price_service.delete_price(session, price)
        self._reload_detail()
        self._reload_price_overview()

    def _copy_from_previous_year(self) -> None:
        target_year = self.year_spin.value()
        source_year = prompt_int(self, "Preise übernehmen", "Quelljahr:", default=target_year - 1, minimum=2000, maximum=2100)
        if source_year is None:
            return
        with self.context.session() as session:
            copied = price_service.copy_prices_from_year(session, source_year=source_year, target_year=target_year)
        info_dialog(self, f"{copied} Preise aus {source_year} nach {target_year} übernommen.")
        self.refresh()
        self._reload_detail()
