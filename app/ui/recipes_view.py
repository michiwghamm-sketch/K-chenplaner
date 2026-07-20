from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
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
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.context import AppContext
from app.services import export_service, ingredient_service, recipe_service
from app.ui.dialogs import (
    AddRecipeIngredientDialog,
    ScaleRecipeDialog,
    confirm_dialog,
    error_dialog,
    info_dialog,
    prompt_text,
)
from app.ui.theme import ORANGE
from app.ui.widgets import COLOR_CRITICAL, PageHeader, SearchBar

MEAL_TYPES = ("Fruehstueck", "Mittagessen", "Abendessen", "Brotzeit", "Beilage", "Nachtisch")


class RecipesView(QWidget):
    """Rezeptverwaltung: Liste, Suche/Filter, Teilstuecke mit Zutaten und Kosten, Historie, Feedback, PDF-Export."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._current_recipe_id: int | None = None
        self._build_ui()
        self.refresh()

    # --- UI-Aufbau -------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(PageHeader("Rezepte", "Rezepte, Teilstuecke, Kosten, Historie und Feedback"))

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
        self.instructions_edit.setFixedHeight(80)
        self.notes_edit = QPlainTextEdit(right)
        self.notes_edit.setFixedHeight(50)

        form.addRow("Name", self.name_edit)
        form.addRow("Kategorie", self.category_edit)
        form.addRow("Mahlzeit", self.meal_type_combo)
        form.addRow("Standardportionen", self.portions_spin)
        form.addRow("", self.active_checkbox)
        form.addRow("Kochanleitung", self.instructions_edit)
        form.addRow("Notizen", self.notes_edit)
        right_layout.addLayout(form)

        button_row = QHBoxLayout()
        save_button = QPushButton("Speichern", right)
        save_button.clicked.connect(self._save_recipe)
        cancel_button = QPushButton("Abbrechen", right)
        cancel_button.clicked.connect(self._reload_detail)
        deactivate_button = QPushButton("Deaktivieren", right)
        deactivate_button.clicked.connect(self._deactivate_recipe)
        pdf_button = QPushButton("Als PDF exportieren", right)
        pdf_button.clicked.connect(self._export_pdf)
        button_row.addWidget(save_button)
        button_row.addWidget(cancel_button)
        button_row.addWidget(deactivate_button)
        button_row.addWidget(pdf_button)
        button_row.addStretch(1)
        right_layout.addLayout(button_row)

        self.tabs = QTabWidget(right)
        right_layout.addWidget(self.tabs)
        self.tabs.addTab(self._build_ingredients_tab(right), "Zutaten")
        self.tabs.addTab(self._build_history_tab(right), "Historie")
        self.tabs.addTab(self._build_feedback_tab(right), "Feedback")

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

    def _build_ingredients_tab(self, parent: QWidget) -> QWidget:
        tab = QWidget(parent)
        layout = QVBoxLayout(tab)

        scroll = QScrollArea(tab)
        scroll.setWidgetResizable(True)
        self.components_container = QWidget(scroll)
        self.components_container_layout = QVBoxLayout(self.components_container)
        self.components_container_layout.addStretch(1)
        scroll.setWidget(self.components_container)
        layout.addWidget(scroll)

        add_component_row = QHBoxLayout()
        add_component_button = QPushButton("Teilstueck hinzufuegen", tab)
        add_component_button.clicked.connect(self._add_component)
        add_component_row.addWidget(add_component_button)
        add_component_row.addStretch(1)
        layout.addLayout(add_component_row)

        cost_row = QHBoxLayout()
        cost_row.addWidget(QLabel("Portionen fuer Kostenberechnung:", tab))
        self.cost_portions_spin = QSpinBox(tab)
        self.cost_portions_spin.setRange(1, 2000)
        self.cost_portions_spin.setValue(10)
        calc_button = QPushButton("Kosten berechnen", tab)
        calc_button.clicked.connect(self._calculate_cost)
        self.cost_label = QLabel("Kosten: -", tab)
        cost_row.addWidget(self.cost_portions_spin)
        cost_row.addWidget(calc_button)
        cost_row.addWidget(self.cost_label)
        cost_row.addStretch(1)
        layout.addLayout(cost_row)

        return tab

    def _build_history_tab(self, parent: QWidget) -> QWidget:
        tab = QWidget(parent)
        layout = QVBoxLayout(tab)

        scale_row = QHBoxLayout()
        scale_button = QPushButton("Mengen skalieren", tab)
        scale_button.clicked.connect(self._scale_recipe)
        scale_row.addWidget(scale_button)
        scale_row.addStretch(1)
        layout.addLayout(scale_row)

        layout.addWidget(QLabel("Versionen (neueste zuerst)", tab))
        self.version_table = QTableWidget(0, 3, tab)
        self.version_table.setHorizontalHeaderLabels(["Version", "Datum", "Notiz"])
        self.version_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.version_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.version_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.version_table.itemSelectionChanged.connect(self._on_version_selected)
        self.version_table.setMaximumHeight(160)
        layout.addWidget(self.version_table)

        layout.addWidget(QLabel("Zutaten dieser Version", tab))
        self.version_detail_table = QTableWidget(0, 4, tab)
        self.version_detail_table.setHorizontalHeaderLabels(["Teilstueck", "Zutat", "Menge", "Einheit"])
        self.version_detail_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.version_detail_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.version_detail_table)

        return tab

    def _build_feedback_tab(self, parent: QWidget) -> QWidget:
        tab = QWidget(parent)
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Feedback aus allen Camp-Jahren zu diesem Rezept", tab))
        self.feedback_table = QTableWidget(0, 7, tab)
        self.feedback_table.setHorizontalHeaderLabels(
            ["Jahr", "Datum", "Bewertung", "Geplant", "Gekocht", "Faktor", "Tipps"]
        )
        self.feedback_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.feedback_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.feedback_table)
        return tab

    # --- Laden / Anzeigen -------------------------------------------------------------

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

    def _clear_layout(self, layout, *, keep_last: bool = False) -> None:
        count = layout.count() - (1 if keep_last else 0)
        while count > 0:
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            count -= 1

    def _clear_detail(self) -> None:
        self.name_edit.clear()
        self.category_edit.clear()
        self.meal_type_combo.setCurrentText("")
        self.portions_spin.setValue(1)
        self.active_checkbox.setChecked(True)
        self.instructions_edit.clear()
        self.notes_edit.clear()
        self._clear_layout(self.components_container_layout, keep_last=True)
        self.version_table.setRowCount(0)
        self.version_detail_table.setRowCount(0)
        self.feedback_table.setRowCount(0)
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

            cost_result = None
            if recipe.ingredients:
                cost_result = recipe_service.calculate_recipe_cost(session, recipe, portions=recipe.default_portions or 1)
            self._rebuild_ingredient_sections(recipe, cost_result)
            self._reload_versions(recipe)
            self._reload_feedback(recipe)

        self._set_cost_label(cost_result)

    def _set_cost_label(self, cost_result: recipe_service.RecipeCostResult | None) -> None:
        if cost_result is None:
            self.cost_label.setText("Kosten: -")
            return
        text = f"Gesamt: {cost_result.total_cost} EUR | pro Portion: {cost_result.cost_per_portion} EUR"
        if cost_result.missing_price_ingredients:
            text += f" (fehlende Preise: {', '.join(cost_result.missing_price_ingredients)})"
        self.cost_label.setText(text)

    # --- Teilstuecke / Zutaten ---------------------------------------------------------

    def _rebuild_ingredient_sections(self, recipe, cost_result: recipe_service.RecipeCostResult | None) -> None:
        self._clear_layout(self.components_container_layout, keep_last=True)

        sorted_items = sorted(recipe.ingredients, key=lambda i: i.sort_order)
        lines_by_item_id = {}
        if cost_result is not None:
            for item, line in zip(sorted_items, cost_result.lines):
                lines_by_item_id[item.id] = line

        groups: dict[int | None, list] = {}
        for item in sorted_items:
            groups.setdefault(item.component_id, []).append(item)

        sections_added = 0
        for component in recipe.components:
            section = self._build_component_section(component, groups.get(component.id, []), lines_by_item_id)
            self.components_container_layout.insertWidget(self.components_container_layout.count() - 1, section)
            sections_added += 1

        unassigned_items = groups.get(None, [])
        if unassigned_items or sections_added == 0:
            section = self._build_component_section(None, unassigned_items, lines_by_item_id)
            self.components_container_layout.insertWidget(self.components_container_layout.count() - 1, section)

    def _build_component_section(self, component, items: list, lines_by_item_id: dict) -> QWidget:
        section = QWidget(self.components_container)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 4, 0, 10)

        header_row = QHBoxLayout()
        name = component.name if component is not None else recipe_service.UNASSIGNED_COMPONENT_LABEL
        name_label = QLabel(name, section)
        name_label.setStyleSheet(f"font-weight: 600; color: {ORANGE}; font-size: 13px;")
        header_row.addWidget(name_label)
        header_row.addStretch(1)
        add_button = QPushButton("Zutat hinzufuegen", section)
        component_id = component.id if component is not None else None
        add_button.clicked.connect(lambda _checked=False, cid=component_id: self._add_ingredient(cid))
        header_row.addWidget(add_button)
        if component is not None:
            delete_button = QPushButton("Teilstueck loeschen", section)
            delete_button.clicked.connect(lambda _checked=False, comp_id=component.id: self._delete_component(comp_id))
            header_row.addWidget(delete_button)
        layout.addLayout(header_row)

        table = QTableWidget(0, 5, section)
        table.setHorizontalHeaderLabels(["Zutat", "Menge", "Einheit", "Preis/Einheit", "Gesamtpreis"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.cellDoubleClicked.connect(lambda _row, _col, t=table: self._edit_ingredient_from_table(t))
        table.setMinimumHeight(34 + 28 * max(len(items), 1))
        table.setMaximumHeight(34 + 28 * max(len(items), 1))

        for item in items:
            row = table.rowCount()
            table.insertRow(row)
            name_item = QTableWidgetItem(item.ingredient.name)
            name_item.setData(1000, item.id)
            table.setItem(row, 0, name_item)
            table.setItem(row, 1, QTableWidgetItem(str(item.quantity)))
            table.setItem(row, 2, QTableWidgetItem(item.unit))
            line = lines_by_item_id.get(item.id)
            if line is not None and line.price_per_unit is not None:
                table.setItem(row, 3, QTableWidgetItem(f"{line.price_per_unit:.2f} EUR"))
                table.setItem(row, 4, QTableWidgetItem(f"{line.line_cost:.2f} EUR"))
            else:
                missing_item = QTableWidgetItem("fehlt")
                missing_item.setForeground(QColor(COLOR_CRITICAL))
                table.setItem(row, 3, missing_item)
                table.setItem(row, 4, QTableWidgetItem("-"))
        layout.addWidget(table)

        remove_row = QHBoxLayout()
        remove_button = QPushButton("Ausgewaehlte Zutat entfernen", section)
        remove_button.clicked.connect(lambda _checked=False, t=table: self._remove_ingredient_from_table(t))
        remove_row.addWidget(remove_button)
        remove_row.addStretch(1)
        layout.addLayout(remove_row)

        return section

    def _edit_ingredient_from_table(self, table: QTableWidget) -> None:
        row = table.currentRow()
        if row < 0:
            return
        link_id = table.item(row, 0).data(1000)
        self._edit_ingredient(link_id)

    def _remove_ingredient_from_table(self, table: QTableWidget) -> None:
        row = table.currentRow()
        if row < 0:
            error_dialog(self, "Bitte zuerst eine Zutat in der Tabelle auswaehlen.")
            return
        link_id = table.item(row, 0).data(1000)
        if not confirm_dialog(self, "Zutat entfernen", "Soll diese Zutat aus dem Rezept entfernt werden?"):
            return
        with self.context.session() as session:
            link = session.get(recipe_service.RecipeIngredient, link_id)
            if link is not None:
                recipe_service.remove_ingredient_from_recipe(session, link)
        self._reload_detail()

    def _add_component(self) -> None:
        if self._current_recipe_id is None:
            error_dialog(self, "Bitte zuerst ein Rezept auswaehlen oder anlegen.")
            return
        name = prompt_text(self, "Teilstueck hinzufuegen", "Name des Teilstuecks (z. B. 'Soße'):")
        if not name:
            return
        with self.context.session() as session:
            recipe = session.get(recipe_service.Recipe, self._current_recipe_id)
            recipe_service.create_component(session, recipe, name)
        self._reload_detail()

    def _delete_component(self, component_id: int) -> None:
        if not confirm_dialog(
            self,
            "Teilstueck loeschen",
            "Das Teilstueck wird geloescht. Die Zutaten bleiben erhalten und wandern nach "
            f"'{recipe_service.UNASSIGNED_COMPONENT_LABEL}'. Fortfahren?",
        ):
            return
        with self.context.session() as session:
            component = session.get(recipe_service.RecipeComponent, component_id)
            if component is not None:
                recipe_service.delete_component(session, component)
        self._reload_detail()

    def _add_ingredient(self, component_id: int | None) -> None:
        if self._current_recipe_id is None:
            error_dialog(self, "Bitte zuerst ein Rezept auswaehlen oder anlegen.")
            return
        with self.context.session() as session:
            recipe = session.get(recipe_service.Recipe, self._current_recipe_id)
            ingredients = [(i.id, i.name) for i in ingredient_service.search_ingredients(session)]
            components = [(c.id, c.name) for c in recipe.components]
        if not ingredients:
            error_dialog(self, "Es sind noch keine Zutaten angelegt.")
            return

        dialog = AddRecipeIngredientDialog(
            ingredients,
            components,
            self,
            initial={"component_id": component_id} if component_id is not None else None,
            title="Zutat hinzufuegen",
        )
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

    def _edit_ingredient(self, link_id: int) -> None:
        with self.context.session() as session:
            link = session.get(recipe_service.RecipeIngredient, link_id)
            if link is None:
                return
            recipe = session.get(recipe_service.Recipe, self._current_recipe_id)
            ingredients = [(i.id, i.name) for i in ingredient_service.search_ingredients(session)]
            components = [(c.id, c.name) for c in recipe.components]
            initial = {
                "ingredient_id": link.ingredient_id,
                "component_id": link.component_id,
                "quantity": link.quantity,
                "unit": link.unit,
                "notes": link.notes,
            }

        dialog = AddRecipeIngredientDialog(ingredients, components, self, initial=initial, title="Zutat bearbeiten")
        if dialog.exec() != AddRecipeIngredientDialog.DialogCode.Accepted:
            return
        data = dialog.result_data()
        if data is None:
            error_dialog(self, "Bitte eine Einheit angeben.")
            return

        with self.context.session() as session:
            recipe = session.get(recipe_service.Recipe, self._current_recipe_id)
            link = session.get(recipe_service.RecipeIngredient, link_id)
            if link.quantity != data["quantity"] or link.unit != data["unit"]:
                recipe_service.update_ingredient_quantity(
                    session, recipe, link, quantity=data["quantity"], unit=data["unit"]
                )
            else:
                link.quantity = data["quantity"]
                link.unit = data["unit"]
            link.ingredient_id = data["ingredient_id"]
            link.component_id = data["component_id"]
            link.notes = data["notes"]
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
            self._rebuild_ingredient_sections(recipe, result)
        self._set_cost_label(result)

    # --- Historie / Skalierung ---------------------------------------------------------

    def _reload_versions(self, recipe) -> None:
        self.version_table.setRowCount(0)
        self.version_detail_table.setRowCount(0)
        for version in recipe_service.list_versions(recipe):
            row = self.version_table.rowCount()
            self.version_table.insertRow(row)
            num_item = QTableWidgetItem(str(version.version_number))
            num_item.setData(1000, version.id)
            self.version_table.setItem(row, 0, num_item)
            self.version_table.setItem(row, 1, QTableWidgetItem(version.created_at.strftime("%Y-%m-%d %H:%M")))
            self.version_table.setItem(row, 2, QTableWidgetItem(version.change_note or ""))

    def _on_version_selected(self) -> None:
        row = self.version_table.currentRow()
        self.version_detail_table.setRowCount(0)
        if row < 0:
            return
        version_id = self.version_table.item(row, 0).data(1000)
        with self.context.session() as session:
            version = session.get(recipe_service.RecipeVersion, version_id)
            if version is None:
                return
            snapshot = recipe_service.parse_version_snapshot(version)
        for entry in snapshot:
            row_index = self.version_detail_table.rowCount()
            self.version_detail_table.insertRow(row_index)
            self.version_detail_table.setItem(row_index, 0, QTableWidgetItem(entry["component_name"]))
            self.version_detail_table.setItem(row_index, 1, QTableWidgetItem(entry["ingredient_name"]))
            self.version_detail_table.setItem(row_index, 2, QTableWidgetItem(entry["quantity"]))
            self.version_detail_table.setItem(row_index, 3, QTableWidgetItem(entry["unit"]))

    def _scale_recipe(self) -> None:
        if self._current_recipe_id is None:
            error_dialog(self, "Bitte zuerst ein Rezept auswaehlen.")
            return
        with self.context.session() as session:
            recipe = session.get(recipe_service.Recipe, self._current_recipe_id)
            if recipe is None or not recipe.ingredients:
                error_dialog(self, "Dieses Rezept hat noch keine Zutaten.")
                return
            suggested = recipe_service.suggested_scale_factor(recipe)

        dialog = ScaleRecipeDialog(suggested, self)
        if dialog.exec() != ScaleRecipeDialog.DialogCode.Accepted:
            return
        data = dialog.result_data()

        with self.context.session() as session:
            recipe = session.get(recipe_service.Recipe, self._current_recipe_id)
            try:
                recipe_service.scale_recipe_ingredients(
                    session,
                    recipe,
                    data["factor"],
                    change_note=data["reason"],
                )
            except ValueError as exc:
                error_dialog(self, str(exc))
                return
        info_dialog(self, "Mengen wurden skaliert. Die vorherige Version wurde in der Historie gespeichert.")
        self._reload_detail()

    # --- Feedback ------------------------------------------------------------------------

    def _reload_feedback(self, recipe) -> None:
        self.feedback_table.setRowCount(0)
        for entry in recipe_service.feedback_history(recipe):
            row = self.feedback_table.rowCount()
            self.feedback_table.insertRow(row)
            self.feedback_table.setItem(row, 0, QTableWidgetItem(str(entry.camp_year.year) if entry.camp_year else ""))
            meal_date = ""
            if entry.meal_plan_entry is not None and entry.meal_plan_entry.meal_date is not None:
                meal_date = entry.meal_plan_entry.meal_date.isoformat()
            self.feedback_table.setItem(row, 1, QTableWidgetItem(meal_date))
            self.feedback_table.setItem(row, 2, QTableWidgetItem(str(entry.rating) if entry.rating else ""))
            self.feedback_table.setItem(row, 3, QTableWidgetItem(str(entry.planned_portions or "")))
            self.feedback_table.setItem(row, 4, QTableWidgetItem(str(entry.cooked_portions or "")))
            self.feedback_table.setItem(row, 5, QTableWidgetItem(str(entry.quantity_factor_next_time or "")))
            self.feedback_table.setItem(row, 6, QTableWidgetItem(entry.process_tips or ""))

    # --- PDF-Export ------------------------------------------------------------------------

    def _export_pdf(self) -> None:
        if self._current_recipe_id is None:
            error_dialog(self, "Bitte zuerst ein Rezept auswaehlen.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Rezept als PDF exportieren", "rezept.pdf", "PDF-Dateien (*.pdf)")
        if not path:
            return
        with self.context.session() as session:
            recipe = session.get(recipe_service.Recipe, self._current_recipe_id)
            if not recipe.ingredients:
                error_dialog(self, "Dieses Rezept hat noch keine Zutaten.")
                return
            portions = self.cost_portions_spin.value() or recipe.default_portions or 1
            cost_result = recipe_service.calculate_recipe_cost(session, recipe, portions=portions)
            export_service.export_recipe_to_pdf(recipe, cost_result, Path(path))
        info_dialog(self, f"Rezept exportiert nach:\n{path}")

    # --- Grunddaten ------------------------------------------------------------------------

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
