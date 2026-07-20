from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.context import AppContext
from app.services import ingredient_service, recipe_service
from app.ui.dialogs import AddRecipeIngredientDialog, confirm_dialog, error_dialog
from app.ui.widgets import PageHeader, SearchBar

MEAL_TYPES = ("Fruehstueck", "Mittagessen", "Abendessen", "Brotzeit", "Beilage", "Nachtisch")


class RecipesView(QWidget):
    """Rezeptverwaltung: Liste, Suche/Filter, Detailbearbeitung, Zutaten, Kostenberechnung."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._current_recipe_id: int | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(PageHeader("Rezepte", "Rezepte verwalten, Zutaten pflegen, Kosten berechnen"))

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        outer.addWidget(splitter)

        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        self.search_bar = SearchBar("Rezept suchen...", left)
        self.search_bar.text_changed.connect(self._reload_list)
        self.active_only_checkbox = QCheckBox("Nur aktive Rezepte", left)
        self.active_only_checkbox.setChecked(True)
        self.active_only_checkbox.stateChanged.connect(self._reload_list)
        self.recipe_list = QListWidget(left)
        self.recipe_list.currentItemChanged.connect(self._on_recipe_selected)
        new_button = QPushButton("Neues Rezept", left)
        new_button.clicked.connect(self._create_recipe)

        left_layout.addWidget(self.search_bar)
        left_layout.addWidget(self.active_only_checkbox)
        left_layout.addWidget(self.recipe_list)
        left_layout.addWidget(new_button)
        splitter.addWidget(left)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)

        form = QFormLayout()
        self.name_edit = QLineEdit(right)
        self.category_edit = QLineEdit(right)
        self.meal_type_combo = QComboBox(right)
        self.meal_type_combo.setEditable(True)
        self.meal_type_combo.addItems(MEAL_TYPES)
        self.portions_spin = QSpinBox(right)
        self.portions_spin.setRange(1, 2000)
        self.active_checkbox = QCheckBox("Aktiv", right)
        self.instructions_edit = QPlainTextEdit(right)
        self.instructions_edit.setFixedHeight(90)
        self.notes_edit = QPlainTextEdit(right)
        self.notes_edit.setFixedHeight(60)

        form.addRow("Name", self.name_edit)
        form.addRow("Kategorie", self.category_edit)
        form.addRow("Mahlzeit", self.meal_type_combo)
        form.addRow("Standardportionen", self.portions_spin)
        form.addRow("", self.active_checkbox)
        form.addRow("Kochanleitung", self.instructions_edit)
        form.addRow("Notizen", self.notes_edit)
        right_layout.addLayout(form)

        right_layout.addWidget(QLabel("Zutaten", right))
        self.ingredients_table = QTableWidget(0, 4, right)
        self.ingredients_table.setHorizontalHeaderLabels(["Zutat", "Menge", "Einheit", "Notizen"])
        self.ingredients_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ingredients_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        right_layout.addWidget(self.ingredients_table)

        ingredient_buttons = QHBoxLayout()
        add_ingredient_button = QPushButton("Zutat hinzufuegen", right)
        add_ingredient_button.clicked.connect(self._add_ingredient)
        remove_ingredient_button = QPushButton("Zutat entfernen", right)
        remove_ingredient_button.clicked.connect(self._remove_ingredient)
        ingredient_buttons.addWidget(add_ingredient_button)
        ingredient_buttons.addWidget(remove_ingredient_button)
        right_layout.addLayout(ingredient_buttons)

        cost_row = QHBoxLayout()
        self.cost_portions_spin = QSpinBox(right)
        self.cost_portions_spin.setRange(1, 2000)
        self.cost_portions_spin.setValue(10)
        calc_button = QPushButton("Kosten berechnen", right)
        calc_button.clicked.connect(self._calculate_cost)
        self.cost_label = QLabel("Kosten: -", right)
        cost_row.addWidget(QLabel("Portionen fuer Kostenberechnung:", right))
        cost_row.addWidget(self.cost_portions_spin)
        cost_row.addWidget(calc_button)
        cost_row.addWidget(self.cost_label)
        cost_row.addStretch(1)
        right_layout.addLayout(cost_row)

        button_row = QHBoxLayout()
        save_button = QPushButton("Speichern", right)
        save_button.clicked.connect(self._save_recipe)
        cancel_button = QPushButton("Abbrechen", right)
        cancel_button.clicked.connect(self._reload_detail)
        deactivate_button = QPushButton("Deaktivieren", right)
        deactivate_button.clicked.connect(self._deactivate_recipe)
        button_row.addWidget(save_button)
        button_row.addWidget(cancel_button)
        button_row.addWidget(deactivate_button)
        button_row.addStretch(1)
        right_layout.addLayout(button_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

    def refresh(self) -> None:
        self._reload_list()

    def _reload_list(self) -> None:
        self.recipe_list.blockSignals(True)
        self.recipe_list.clear()
        with self.context.session() as session:
            recipes = recipe_service.search_recipes(
                session,
                query=self.search_bar.text() or None,
                active_only=self.active_only_checkbox.isChecked(),
            )
            for recipe in recipes:
                item = QListWidgetItem(recipe.name)
                item.setData(1000, recipe.id)
                self.recipe_list.addItem(item)
        self.recipe_list.blockSignals(False)
        if self.recipe_list.count():
            self.recipe_list.setCurrentRow(0)
        else:
            self._current_recipe_id = None
            self._clear_detail()

    def _on_recipe_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            self._current_recipe_id = None
            self._clear_detail()
            return
        self._current_recipe_id = current.data(1000)
        self._reload_detail()

    def _clear_detail(self) -> None:
        self.name_edit.clear()
        self.category_edit.clear()
        self.meal_type_combo.setCurrentText("")
        self.portions_spin.setValue(1)
        self.active_checkbox.setChecked(True)
        self.instructions_edit.clear()
        self.notes_edit.clear()
        self.ingredients_table.setRowCount(0)
        self.cost_label.setText("Kosten: -")

    def _reload_detail(self) -> None:
        if self._current_recipe_id is None:
            self._clear_detail()
            return
        with self.context.session() as session:
            recipe = session.get(recipe_service.Recipe, self._current_recipe_id)
            if recipe is None:
                self._clear_detail()
                return
            self.name_edit.setText(recipe.name)
            self.category_edit.setText(recipe.category or "")
            self.meal_type_combo.setCurrentText(recipe.meal_type or "")
            self.portions_spin.setValue(recipe.default_portions or 1)
            self.cost_portions_spin.setValue(recipe.default_portions or 10)
            self.active_checkbox.setChecked(recipe.active)
            self.instructions_edit.setPlainText(recipe.instructions or "")
            self.notes_edit.setPlainText(recipe.notes or "")

            self.ingredients_table.setRowCount(0)
            for item in sorted(recipe.ingredients, key=lambda i: i.sort_order):
                row = self.ingredients_table.rowCount()
                self.ingredients_table.insertRow(row)
                name_item = QTableWidgetItem(item.ingredient.name)
                name_item.setData(1000, item.id)
                self.ingredients_table.setItem(row, 0, name_item)
                self.ingredients_table.setItem(row, 1, QTableWidgetItem(str(item.quantity)))
                self.ingredients_table.setItem(row, 2, QTableWidgetItem(item.unit))
                self.ingredients_table.setItem(row, 3, QTableWidgetItem(item.notes or ""))
        self.cost_label.setText("Kosten: -")

    def _create_recipe(self) -> None:
        with self.context.session() as session:
            recipe = recipe_service.create_recipe(session, name="Neues Rezept")
            self._current_recipe_id = recipe.id
        self._reload_list()
        self._select_recipe_by_id(self._current_recipe_id)

    def _select_recipe_by_id(self, recipe_id: int | None) -> None:
        for row in range(self.recipe_list.count()):
            item = self.recipe_list.item(row)
            if item.data(1000) == recipe_id:
                self.recipe_list.setCurrentRow(row)
                return

    def _save_recipe(self) -> None:
        if self._current_recipe_id is None:
            return
        name = self.name_edit.text().strip()
        if not name:
            error_dialog(self, "Der Rezeptname darf nicht leer sein.")
            return
        with self.context.session() as session:
            recipe = session.get(recipe_service.Recipe, self._current_recipe_id)
            if recipe is None:
                return
            recipe_service.update_recipe(
                recipe,
                name=name,
                category=self.category_edit.text().strip() or None,
                meal_type=self.meal_type_combo.currentText().strip() or None,
                default_portions=self.portions_spin.value(),
                active=self.active_checkbox.isChecked(),
                instructions=self.instructions_edit.toPlainText().strip() or None,
                notes=self.notes_edit.toPlainText().strip() or None,
            )
        self._reload_list()
        self._select_recipe_by_id(self._current_recipe_id)

    def _deactivate_recipe(self) -> None:
        if self._current_recipe_id is None:
            return
        if not confirm_dialog(self, "Rezept deaktivieren", "Soll dieses Rezept wirklich deaktiviert werden?"):
            return
        with self.context.session() as session:
            recipe = session.get(recipe_service.Recipe, self._current_recipe_id)
            if recipe is not None:
                recipe_service.deactivate_recipe(recipe)
        self._reload_list()

    def _add_ingredient(self) -> None:
        if self._current_recipe_id is None:
            error_dialog(self, "Bitte zuerst ein Rezept auswaehlen oder anlegen.")
            return
        with self.context.session() as session:
            ingredients = [(i.id, i.name) for i in ingredient_service.search_ingredients(session)]
        if not ingredients:
            error_dialog(self, "Es sind noch keine Zutaten angelegt.")
            return

        dialog = AddRecipeIngredientDialog(ingredients, self)
        if dialog.exec() != AddRecipeIngredientDialog.DialogCode.Accepted:
            return
        data = dialog.result_data()
        if data is None:
            error_dialog(self, "Bitte eine Einheit angeben.")
            return

        with self.context.session() as session:
            recipe = session.get(recipe_service.Recipe, self._current_recipe_id)
            recipe_service.add_ingredient_to_recipe(session, recipe, **data)
        self._reload_detail()

    def _remove_ingredient(self) -> None:
        row = self.ingredients_table.currentRow()
        if row < 0:
            return
        link_id = self.ingredients_table.item(row, 0).data(1000)
        if not confirm_dialog(self, "Zutat entfernen", "Soll diese Zutat aus dem Rezept entfernt werden?"):
            return
        with self.context.session() as session:
            link = session.get(recipe_service.RecipeIngredient, link_id)
            if link is not None:
                recipe_service.remove_ingredient_from_recipe(session, link)
        self._reload_detail()

    def _calculate_cost(self) -> None:
        if self._current_recipe_id is None:
            return
        with self.context.session() as session:
            recipe = session.get(recipe_service.Recipe, self._current_recipe_id)
            if recipe is None or not recipe.ingredients:
                self.cost_label.setText("Kosten: keine Zutaten")
                return
            result = recipe_service.calculate_recipe_cost(session, recipe, portions=self.cost_portions_spin.value())
        text = f"Gesamt: {result.total_cost} EUR | pro Portion: {result.cost_per_portion} EUR"
        if result.missing_price_ingredients:
            text += f" (fehlende Preise: {', '.join(result.missing_price_ingredients)})"
        self.cost_label.setText(text)
