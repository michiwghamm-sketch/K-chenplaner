from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.context import AppContext
from app.services import ingredient_service
from app.ui.dialogs import confirm_dialog, error_dialog, prompt_text
from app.ui.widgets import SearchBar


class IngredientsView(QWidget):
    """Zutatenverwaltung: Liste, Suche, Detail, Aliasnamen."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._current_ingredient_id: int | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        outer.addWidget(splitter)

        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        self.search_bar = SearchBar("Zutat suchen...", left)
        self.search_bar.text_changed.connect(self._reload_list)
        self.active_only_checkbox = QCheckBox("Nur aktive Zutaten", left)
        self.active_only_checkbox.setChecked(True)
        self.active_only_checkbox.stateChanged.connect(self._reload_list)
        self.ingredient_list = QListWidget(left)
        self.ingredient_list.currentItemChanged.connect(self._on_selected)
        new_button = QPushButton("Neue Zutat", left)
        new_button.clicked.connect(self._create_ingredient)

        left_layout.addWidget(self.search_bar)
        left_layout.addWidget(self.active_only_checkbox)
        left_layout.addWidget(self.ingredient_list)
        left_layout.addWidget(new_button)
        splitter.addWidget(left)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        form = QFormLayout()
        self.name_edit = QLineEdit(right)
        self.unit_edit = QLineEdit(right)
        self.category_edit = QLineEdit(right)
        self.storage_edit = QLineEdit(right)
        self.active_checkbox = QCheckBox("Aktiv", right)
        self.notes_edit = QPlainTextEdit(right)
        self.notes_edit.setFixedHeight(70)

        form.addRow("Name", self.name_edit)
        form.addRow("Standardeinheit", self.unit_edit)
        form.addRow("Kategorie", self.category_edit)
        form.addRow("Lagerart", self.storage_edit)
        form.addRow("", self.active_checkbox)
        form.addRow("Notizen", self.notes_edit)
        right_layout.addLayout(form)

        right_layout.addWidget(QLabel("Aliasnamen", right))
        self.alias_list = QListWidget(right)
        right_layout.addWidget(self.alias_list)

        alias_row = QHBoxLayout()
        add_alias_button = QPushButton("Alias hinzufuegen", right)
        add_alias_button.clicked.connect(self._add_alias)
        remove_alias_button = QPushButton("Alias entfernen", right)
        remove_alias_button.clicked.connect(self._remove_alias)
        alias_row.addWidget(add_alias_button)
        alias_row.addWidget(remove_alias_button)
        right_layout.addLayout(alias_row)

        button_row = QHBoxLayout()
        save_button = QPushButton("Speichern", right)
        save_button.clicked.connect(self._save_ingredient)
        cancel_button = QPushButton("Abbrechen", right)
        cancel_button.clicked.connect(self._reload_detail)
        deactivate_button = QPushButton("Deaktivieren", right)
        deactivate_button.clicked.connect(self._deactivate_ingredient)
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
        self.ingredient_list.blockSignals(True)
        self.ingredient_list.clear()
        with self.context.session() as session:
            ingredients = ingredient_service.search_ingredients(
                session,
                query=self.search_bar.text() or None,
                active_only=self.active_only_checkbox.isChecked(),
            )
            for ingredient in ingredients:
                item = QListWidgetItem(ingredient.name)
                item.setData(1000, ingredient.id)
                self.ingredient_list.addItem(item)
        self.ingredient_list.blockSignals(False)
        if self.ingredient_list.count():
            self.ingredient_list.setCurrentRow(0)
        else:
            self._current_ingredient_id = None
            self._clear_detail()

    def _on_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            self._current_ingredient_id = None
            self._clear_detail()
            return
        self._current_ingredient_id = current.data(1000)
        self._reload_detail()

    def _clear_detail(self) -> None:
        self.name_edit.clear()
        self.unit_edit.clear()
        self.category_edit.clear()
        self.storage_edit.clear()
        self.active_checkbox.setChecked(True)
        self.notes_edit.clear()
        self.alias_list.clear()

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
            self.unit_edit.setText(ingredient.default_unit or "")
            self.category_edit.setText(ingredient.category or "")
            self.storage_edit.setText(ingredient.storage_type or "")
            self.active_checkbox.setChecked(ingredient.active)
            self.notes_edit.setPlainText(ingredient.notes or "")

            self.alias_list.clear()
            for alias in ingredient.aliases:
                item = QListWidgetItem(alias.alias)
                item.setData(1000, alias.id)
                self.alias_list.addItem(item)

    def _create_ingredient(self) -> None:
        with self.context.session() as session:
            ingredient = ingredient_service.create_ingredient(session, name="Neue Zutat")
            self._current_ingredient_id = ingredient.id
        self._reload_list()
        self._select_ingredient_by_id(self._current_ingredient_id)

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
            ingredient = session.get(ingredient_service.Ingredient, self._current_ingredient_id)
            if ingredient is None:
                return
            ingredient_service.update_ingredient(
                ingredient,
                name=name,
                default_unit=self.unit_edit.text().strip() or None,
                category=self.category_edit.text().strip() or None,
                storage_type=self.storage_edit.text().strip() or None,
                active=self.active_checkbox.isChecked(),
                notes=self.notes_edit.toPlainText().strip() or None,
            )
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

    def _add_alias(self) -> None:
        if self._current_ingredient_id is None:
            return
        alias = prompt_text(self, "Alias hinzufuegen", "Alternativer Name / Tippfehler-Variante:")
        if not alias:
            return
        with self.context.session() as session:
            ingredient = session.get(ingredient_service.Ingredient, self._current_ingredient_id)
            ingredient_service.add_alias(session, ingredient, alias)
        self._reload_detail()

    def _remove_alias(self) -> None:
        item = self.alias_list.currentItem()
        if item is None:
            return
        alias_id = item.data(1000)
        with self.context.session() as session:
            alias = session.get(ingredient_service.IngredientAlias, alias_id)
            if alias is not None:
                ingredient_service.remove_alias(session, alias)
        self._reload_detail()
