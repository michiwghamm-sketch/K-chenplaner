from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import IntegrityError

from app.context import AppContext
from app.services import export_service, ingredient_service, recipe_service
from app.ui.dialogs import (
    AddRecipeIngredientDialog,
    RecipeStepDialog,
    ScaleRecipeDialog,
    confirm_dialog,
    error_dialog,
    info_dialog,
    prompt_choice,
    prompt_text,
)
from app.ui.theme import ORANGE, ORANGE_TINT, TEXT_MUTED
from app.ui.widgets import COLOR_CRITICAL, COLOR_OK, COLOR_WARNING, PageHeader, SearchBar

MEAL_TYPES = ("Frühstück", "Mittagessen", "Abendessen", "Brotzeit", "Beilage", "Nachtisch")
AUTO_OPTIONAL_NOTE = "Menge nicht in Excel angegeben (nach Geschmack)"
NO_DIET_TYPE_LABEL = "Keine Angabe"
DIET_TYPE_LEVELS = {"Vegetarisch": "ok", "Vegan": "warnung", "Fleisch": "kritisch"}
DIET_TYPE_COLORS = {"Vegetarisch": COLOR_OK, "Vegan": COLOR_WARNING, "Fleisch": COLOR_CRITICAL}


class RecipesView(QWidget):
    """Rezeptverwaltung: Liste, Suche/Filter, drei Tabs (Rezept, Kochanleitung, Historie), PDF-Export."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._current_recipe_id: int | None = None
        self._build_ui()
        self.refresh()

    # --- UI-Aufbau -------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(PageHeader("Rezepte", "Rezept, Kochanleitung und Historie je Rezept"))

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        # Ohne stretch=1 beansprucht der Splitter keinen Vorrang auf uebrigen vertikalen
        # Platz, wodurch Qt ihn stattdessen an PageHeader vergibt - dessen Labels sind
        # nicht vertikal begrenzt und werden dann sichtbar auseinandergezogen.
        outer.addWidget(splitter, stretch=1)

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
        right_layout = QHBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(14)

        # Rezeptdetails stehen als schmale Spalte links neben den Tabs (statt als
        # Kopfbereich darueber), damit die Tabs/Tabellen den vertikalen Platz bekommen.
        meta_group = QGroupBox("Rezeptdetails", right)
        meta_group.setFixedWidth(240)
        meta_layout = QVBoxLayout(meta_group)
        meta_layout.setSpacing(6)

        self.name_edit = QLineEdit(meta_group)
        self.diet_type_combo = QComboBox(meta_group)
        self.diet_type_combo.addItem(NO_DIET_TYPE_LABEL)
        self.diet_type_combo.addItems(recipe_service.DIET_TYPES)
        self.diet_type_combo.currentTextChanged.connect(self._style_diet_combo)
        self.meal_type_combo = QComboBox(meta_group)
        self.meal_type_combo.setEditable(True)
        self.meal_type_combo.addItems(MEAL_TYPES)
        self.portions_spin = QSpinBox(meta_group)
        self.portions_spin.setRange(1, 2000)
        self.active_checkbox = QCheckBox("Aktiv", meta_group)
        self.notes_edit = QPlainTextEdit(meta_group)
        self.notes_edit.setFixedHeight(70)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        form.addRow("Name", self.name_edit)
        form.addRow("Ernährung", self.diet_type_combo)
        form.addRow("Mahlzeit", self.meal_type_combo)
        portions_row = QHBoxLayout()
        portions_row.addWidget(self.portions_spin)
        portions_row.addWidget(self.active_checkbox)
        form.addRow("Portionen", portions_row)
        meta_layout.addLayout(form)

        meta_layout.addWidget(QLabel("Notizen", meta_group))
        meta_layout.addWidget(self.notes_edit)
        meta_layout.addSpacing(6)

        save_button = QPushButton("Speichern", meta_group)
        save_button.clicked.connect(self._save_recipe)
        cancel_button = QPushButton("Abbrechen", meta_group)
        cancel_button.clicked.connect(self._reload_detail)
        deactivate_button = QPushButton("Deaktivieren", meta_group)
        deactivate_button.clicked.connect(self._deactivate_recipe)
        deactivate_button.setProperty("role", "secondary")
        delete_button = QPushButton("Löschen", meta_group)
        delete_button.clicked.connect(self._delete_recipe)
        delete_button.setProperty("role", "secondary")
        pdf_button = QPushButton("Als PDF exportieren", meta_group)
        pdf_button.clicked.connect(self._export_pdf)
        pdf_button.setProperty("role", "secondary")
        veggie_button = QPushButton("Veggi-Variante erstellen", meta_group)
        veggie_button.clicked.connect(self._create_veggie_variant)
        veggie_button.setProperty("role", "secondary")
        meta_layout.addWidget(save_button)
        meta_layout.addWidget(cancel_button)
        meta_layout.addWidget(deactivate_button)
        meta_layout.addWidget(delete_button)
        meta_layout.addWidget(pdf_button)
        meta_layout.addWidget(veggie_button)
        meta_layout.addStretch(1)

        right_layout.addWidget(meta_group)

        self.tabs = QTabWidget(right)
        self.tabs.addTab(self._build_rezept_tab(right), "Rezept")
        self.tabs.addTab(self._build_kochanleitung_tab(right), "Kochanleitung")
        self.tabs.addTab(self._build_history_tab(right), "Historie")
        right_layout.addWidget(self.tabs, stretch=1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

    def _build_rezept_tab(self, parent: QWidget) -> QWidget:
        scroll = QScrollArea(parent)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        tab = QWidget(scroll)
        scroll.setWidget(tab)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 4, 0, 4)

        section_title = QLabel("Zutaten nach Teilstück", tab)
        section_title.setStyleSheet("font-weight: 600; font-size: 15px;")
        layout.addWidget(section_title)

        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        table_column = QVBoxLayout()
        self.ingredients_table = QTableWidget(0, 5, tab)
        self.ingredients_table.setHorizontalHeaderLabels(["Zutat", "Menge", "Einheit", "Preis/Einheit", "Gesamtpreis"])
        self.ingredients_table.verticalHeader().setVisible(False)
        self.ingredients_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.ingredients_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.ingredients_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.ingredients_table.setColumnWidth(0, 200)
        for col in range(1, 5):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)
        self.ingredients_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.ingredients_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.ingredients_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.ingredients_table.cellDoubleClicked.connect(self._on_ingredient_table_double_clicked)
        table_column.addWidget(self.ingredients_table, stretch=1)

        add_component_row = QHBoxLayout()
        add_component_button = QPushButton("+ Teilstück hinzufügen", tab)
        add_component_button.clicked.connect(self._add_component)
        add_component_row.addWidget(add_component_button)
        add_component_row.addStretch(1)
        table_column.addLayout(add_component_row)

        content_row.addLayout(table_column, 1)

        cost_panel = QVBoxLayout()
        cost_panel.setSpacing(6)
        cost_title = QLabel("Kostenberechnung", tab)
        cost_title.setStyleSheet("font-weight: 600; font-size: 15px;")
        cost_panel.addWidget(cost_title)
        portions_label = QLabel("Portionen für Kostenberechnung", tab)
        portions_label.setWordWrap(True)
        cost_panel.addWidget(portions_label)
        self.cost_portions_spin = QSpinBox(tab)
        self.cost_portions_spin.setRange(1, 2000)
        self.cost_portions_spin.setValue(10)
        cost_panel.addWidget(self.cost_portions_spin)
        calc_button = QPushButton("Kosten berechnen", tab)
        calc_button.clicked.connect(self._calculate_cost)
        cost_panel.addWidget(calc_button)
        self.cost_label = QLabel("Kosten: -", tab)
        self.cost_label.setWordWrap(True)
        self.cost_label.setStyleSheet("font-weight: 600;")
        cost_panel.addWidget(self.cost_label)
        cost_panel.addStretch(1)

        cost_container = QWidget(tab)
        cost_container.setLayout(cost_panel)
        cost_container.setFixedWidth(220)
        content_row.addWidget(cost_container)

        layout.addLayout(content_row, 1)

        return scroll

    def _build_kochanleitung_tab(self, parent: QWidget) -> QWidget:
        scroll = QScrollArea(parent)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        tab = QWidget(scroll)
        scroll.setWidget(tab)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 4, 0, 4)

        self.duration_label = QLabel("Gesamtdauer: -", tab)
        self.duration_label.setStyleSheet("font-weight: 600; font-size: 15px;")
        layout.addWidget(self.duration_label)

        self.steps_table = QTableWidget(0, 3, tab)
        self.steps_table.setHorizontalHeaderLabels(["Arbeitsschritt", "Anweisung", "Dauer"])
        self.steps_table.verticalHeader().setVisible(False)
        self.steps_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.steps_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.steps_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.steps_table.setWordWrap(True)
        steps_header = self.steps_table.horizontalHeader()
        steps_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        steps_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        steps_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.steps_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.steps_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.steps_table.cellDoubleClicked.connect(self._on_step_table_double_clicked)
        layout.addWidget(self.steps_table)

        button_row = QHBoxLayout()
        add_step_button = QPushButton("+ Arbeitsschritt hinzufügen", tab)
        add_step_button.clicked.connect(self._add_step)
        move_up_button = QPushButton("Nach oben", tab)
        move_up_button.clicked.connect(lambda: self._move_step(-1))
        move_down_button = QPushButton("Nach unten", tab)
        move_down_button.clicked.connect(lambda: self._move_step(1))
        button_row.addWidget(add_step_button)
        button_row.addWidget(move_up_button)
        button_row.addWidget(move_down_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        layout.addStretch(1)

        return scroll

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
        self.version_detail_table.setHorizontalHeaderLabels(["Teilstück", "Zutat", "Menge", "Einheit"])
        self.version_detail_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.version_detail_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.version_detail_table)
        layout.addStretch(1)

        return tab

    # --- Laden / Anzeigen -------------------------------------------------------------

    def refresh(self) -> None:
        self._reload_list()

    def _reload_list(self) -> None:
        target_id = self._current_recipe_id
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
                color = DIET_TYPE_COLORS.get(recipe.diet_type or "")
                if color:
                    item.setForeground(QColor(color))
                    font = item.font()
                    font.setWeight(QFont.Weight.DemiBold)
                    item.setFont(font)
                self.recipe_list.addItem(item)
        self.recipe_list.blockSignals(False)

        if not self.recipe_list.count():
            self._current_recipe_id = None
            self._clear_detail()
            return

        # Nach dem Neuaufbau der Liste die zuvor ausgewählte Zeile wiederfinden, statt
        # blind auf Zeile 0 zu springen (sonst landet man z. B. nach dem Speichern oder
        # Anlegen eines Rezepts scheinbar zufällig bei einem ganz anderen Rezept).
        if target_id is not None:
            for row in range(self.recipe_list.count()):
                if self.recipe_list.item(row).data(1000) == target_id:
                    self.recipe_list.setCurrentRow(row)
                    return
        self.recipe_list.setCurrentRow(0)

    def _on_recipe_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            self._current_recipe_id = None
            self._clear_detail()
            return
        self._current_recipe_id = current.data(1000)
        self._reload_detail()

    def _style_diet_combo(self, diet_type: str) -> None:
        color = DIET_TYPE_COLORS.get(diet_type)
        if color:
            self.diet_type_combo.setStyleSheet(
                f"QComboBox {{ background-color: {color}; color: white; font-weight: 600; }}"
            )
        else:
            self.diet_type_combo.setStyleSheet("")

    def _clear_detail(self) -> None:
        self.name_edit.clear()
        self.diet_type_combo.setCurrentText(NO_DIET_TYPE_LABEL)
        self._style_diet_combo(NO_DIET_TYPE_LABEL)
        self.meal_type_combo.setCurrentText("")
        self.portions_spin.setValue(1)
        self.active_checkbox.setChecked(True)
        self.notes_edit.clear()
        self.ingredients_table.setRowCount(0)
        self.steps_table.setRowCount(0)
        self.duration_label.setText("Gesamtdauer: -")
        self.version_table.setRowCount(0)
        self.version_detail_table.setRowCount(0)
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
            self.diet_type_combo.setCurrentText(recipe.diet_type or NO_DIET_TYPE_LABEL)
            self._style_diet_combo(recipe.diet_type or NO_DIET_TYPE_LABEL)
            self.meal_type_combo.setCurrentText(recipe.meal_type or "")
            self.portions_spin.setValue(recipe.default_portions or 1)
            self.cost_portions_spin.setValue(recipe.default_portions or 10)
            self.active_checkbox.setChecked(recipe.active)
            self.notes_edit.setPlainText(recipe.notes or "")

            cost_result = None
            if recipe.ingredients:
                cost_result = recipe_service.calculate_recipe_cost(session, recipe, portions=recipe.default_portions or 1)
            self._rebuild_ingredient_sections(recipe, cost_result)
            self._reload_steps(recipe)
            self._reload_versions(recipe)

        self._set_cost_label(cost_result)

    def _set_cost_label(self, cost_result: recipe_service.RecipeCostResult | None) -> None:
        if cost_result is None:
            self.cost_label.setText("Kosten: -")
            return
        text = f"Gesamt: {cost_result.total_cost} EUR | pro Portion: {cost_result.cost_per_portion} EUR"
        if cost_result.missing_price_ingredients:
            text += f" (fehlende Preise: {', '.join(cost_result.missing_price_ingredients)})"
        self.cost_label.setText(text)

    # --- Teilstuecke / Zutaten: eine Tabelle, Excel-aehnlich (Kopfzeile + Teilstueck-Baender) ---

    def _rebuild_ingredient_sections(self, recipe, cost_result: recipe_service.RecipeCostResult | None) -> None:
        table = self.ingredients_table
        table.setRowCount(0)

        sorted_items = sorted(recipe.ingredients, key=lambda i: i.sort_order)
        lines_by_item_id = {}
        if cost_result is not None:
            for item, line in zip(sorted_items, cost_result.lines):
                lines_by_item_id[item.id] = line

        groups: dict[int | None, list] = {}
        for item in sorted_items:
            groups.setdefault(item.component_id, []).append(item)

        ordered_groups = [(component, groups.get(component.id, [])) for component in recipe.components]
        unassigned_items = groups.get(None, [])
        if unassigned_items or not ordered_groups:
            ordered_groups.append((None, unassigned_items))

        banding_index = 0
        for component, items in ordered_groups:
            self._add_band_row(table, component)
            if not items:
                self._add_empty_row(table)
                continue
            for item in items:
                self._add_ingredient_row(table, item, lines_by_item_id.get(item.id), banding_index)
                banding_index += 1

        table.resizeRowsToContents()

    def _add_band_row(self, table: QTableWidget, component) -> None:
        row = table.rowCount()
        table.insertRow(row)
        table.setSpan(row, 0, 1, 3)
        table.setSpan(row, 3, 1, 2)

        name = component.name if component is not None else recipe_service.UNASSIGNED_COMPONENT_LABEL
        name_label = QLabel(f"  {name}", table)
        name_label.setStyleSheet(f"background-color: {ORANGE}; color: white; font-weight: 600; padding: 5px;")
        table.setCellWidget(row, 0, name_label)

        button_bar = QWidget(table)
        button_bar.setStyleSheet(f"background-color: {ORANGE};")
        button_layout = QHBoxLayout(button_bar)
        button_layout.setContentsMargins(4, 3, 6, 3)
        button_layout.addStretch(1)
        band_button_style = (
            "QPushButton { background-color: rgba(255,255,255,0.18); color: white;"
            " border: 1px solid rgba(255,255,255,0.6); border-radius: 4px; padding: 2px 8px; }"
            " QPushButton:hover { background-color: rgba(255,255,255,0.32); }"
        )
        component_id = component.id if component is not None else None
        add_button = QPushButton("+ Zutat", button_bar)
        add_button.setStyleSheet(band_button_style)
        add_button.clicked.connect(lambda _checked=False, cid=component_id: self._add_ingredient(cid))
        button_layout.addWidget(add_button)
        if component is not None:
            delete_button = QPushButton("Löschen", button_bar)
            delete_button.setStyleSheet(band_button_style)
            delete_button.clicked.connect(lambda _checked=False, comp_id=component.id: self._delete_component(comp_id))
            button_layout.addWidget(delete_button)
        table.setCellWidget(row, 3, button_bar)
        table.setRowHeight(row, 32)

    def _add_empty_row(self, table: QTableWidget) -> None:
        row = table.rowCount()
        table.insertRow(row)
        table.setSpan(row, 0, 1, 5)
        empty_item = QTableWidgetItem("Noch keine Zutaten in diesem Teilstück.")
        empty_item.setForeground(QColor(TEXT_MUTED))
        font = empty_item.font()
        font.setItalic(True)
        empty_item.setFont(font)
        table.setItem(row, 0, empty_item)

    def _add_ingredient_row(self, table: QTableWidget, item, line, banding_index: int) -> None:
        row = table.rowCount()
        table.insertRow(row)

        is_to_taste = item.optional and item.quantity == 0
        name_text = item.ingredient.name
        if item.notes and item.notes != AUTO_OPTIONAL_NOTE:
            name_text += f"  ({item.notes})"
        name_item = QTableWidgetItem(name_text)
        name_item.setData(1000, item.id)

        quantity_item = QTableWidgetItem("nach Geschmack" if is_to_taste else str(item.quantity))
        quantity_item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))

        unit_item = QTableWidgetItem("" if is_to_taste else item.unit)
        unit_item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))

        has_price = line is not None and line.price_per_unit is not None
        price_item = QTableWidgetItem(f"{line.price_per_unit:.2f} €" if has_price else "fehlt")
        price_item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        cost_item = QTableWidgetItem(f"{line.line_cost:.2f} €" if has_price else "-")
        cost_item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        if not has_price:
            price_item.setForeground(QColor(COLOR_CRITICAL))
            cost_item.setForeground(QColor(COLOR_CRITICAL))

        background = QColor(ORANGE_TINT) if banding_index % 2 == 1 else QColor("#FFFFFF")
        for cell_item in (name_item, quantity_item, unit_item, price_item, cost_item):
            cell_item.setBackground(background)

        table.setItem(row, 0, name_item)
        table.setItem(row, 1, quantity_item)
        table.setItem(row, 2, unit_item)
        table.setItem(row, 3, price_item)
        table.setItem(row, 4, cost_item)

    def _fit_table_height(self, table: QTableWidget) -> None:
        table.resizeRowsToContents()
        total = table.horizontalHeader().height()
        for row in range(table.rowCount()):
            total += table.rowHeight(row)
        total += 2 * table.frameWidth() + 4
        table.setFixedHeight(max(total, 60))

    def _on_ingredient_table_double_clicked(self, row: int, _column: int) -> None:
        item = self.ingredients_table.item(row, 0)
        if item is None:
            return
        link_id = item.data(1000)
        if link_id is None:
            return
        self._edit_ingredient(link_id)

    def _add_component(self) -> None:
        if self._current_recipe_id is None:
            error_dialog(self, "Bitte zuerst ein Rezept auswählen oder anlegen.")
            return
        name = prompt_text(self, "Teilstück hinzufügen", "Name des Teilstücks (z. B. 'Soße'):")
        if not name:
            return
        with self.context.session() as session:
            recipe = session.get(recipe_service.Recipe, self._current_recipe_id)
            recipe_service.create_component(session, recipe, name)
        self._reload_detail()

    def _delete_component(self, component_id: int) -> None:
        if not confirm_dialog(
            self,
            "Teilstück löschen",
            "Das Teilstück wird gelöscht. Die Zutaten bleiben erhalten und wandern nach "
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
            error_dialog(self, "Bitte zuerst ein Rezept auswählen oder anlegen.")
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
            title="Zutat hinzufügen",
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

        if dialog.was_delete_requested():
            if not confirm_dialog(self, "Zutat entfernen", "Soll diese Zutat aus dem Rezept entfernt werden?"):
                return
            with self.context.session() as session:
                link = session.get(recipe_service.RecipeIngredient, link_id)
                if link is not None:
                    recipe_service.remove_ingredient_from_recipe(session, link)
            self._reload_detail()
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

    # --- Kochanleitung (Arbeitsschritte) -----------------------------------------------

    def _reload_steps(self, recipe) -> None:
        table = self.steps_table
        table.setRowCount(0)

        ordered_steps = sorted(recipe.steps, key=lambda s: s.sort_order)
        for index, step in enumerate(ordered_steps, start=1):
            row = table.rowCount()
            table.insertRow(row)
            title_item = QTableWidgetItem(step.title or f"Schritt {index}")
            title_item.setData(1000, step.id)
            table.setItem(row, 0, title_item)
            description_item = QTableWidgetItem(step.description or "")
            description_item.setToolTip(step.description or "")
            table.setItem(row, 1, description_item)
            duration_item = QTableWidgetItem(f"{step.duration_minutes} Min." if step.duration_minutes else "-")
            duration_item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
            table.setItem(row, 2, duration_item)

        self._fit_table_height(table)
        total_minutes = recipe_service.total_step_duration_minutes(recipe)
        self.duration_label.setText(f"Gesamtdauer: ca. {total_minutes} Min." if total_minutes else "Gesamtdauer: -")

    def _on_step_table_double_clicked(self, row: int, _column: int) -> None:
        item = self.steps_table.item(row, 0)
        if item is None:
            return
        step_id = item.data(1000)
        if step_id is None:
            return
        self._edit_step(step_id)

    def _add_step(self) -> None:
        if self._current_recipe_id is None:
            error_dialog(self, "Bitte zuerst ein Rezept auswählen oder anlegen.")
            return
        dialog = RecipeStepDialog(self)
        if dialog.exec() != RecipeStepDialog.DialogCode.Accepted:
            return
        data = dialog.result_data()
        if data is None:
            error_dialog(self, "Bitte einen Titel oder eine Anweisung angeben.")
            return
        with self.context.session() as session:
            recipe = session.get(recipe_service.Recipe, self._current_recipe_id)
            recipe_service.create_step(session, recipe, **data)
        self._reload_detail()

    def _edit_step(self, step_id: int) -> None:
        with self.context.session() as session:
            step = session.get(recipe_service.RecipeStep, step_id)
            if step is None:
                return
            initial = {
                "title": step.title,
                "description": step.description,
                "duration_minutes": step.duration_minutes,
            }

        dialog = RecipeStepDialog(self, initial=initial)
        if dialog.exec() != RecipeStepDialog.DialogCode.Accepted:
            return

        if dialog.was_delete_requested():
            if not confirm_dialog(self, "Arbeitsschritt entfernen", "Soll dieser Arbeitsschritt entfernt werden?"):
                return
            with self.context.session() as session:
                step = session.get(recipe_service.RecipeStep, step_id)
                if step is not None:
                    recipe_service.delete_step(session, step)
            self._reload_detail()
            return

        data = dialog.result_data()
        if data is None:
            error_dialog(self, "Bitte einen Titel oder eine Anweisung angeben.")
            return

        with self.context.session() as session:
            step = session.get(recipe_service.RecipeStep, step_id)
            recipe_service.update_step(step, **data)
        self._reload_detail()

    def _move_step(self, direction: int) -> None:
        row = self.steps_table.currentRow()
        if row < 0:
            error_dialog(self, "Bitte zuerst einen Arbeitsschritt auswählen.")
            return
        step_id = self.steps_table.item(row, 0).data(1000)
        with self.context.session() as session:
            recipe = session.get(recipe_service.Recipe, self._current_recipe_id)
            step = session.get(recipe_service.RecipeStep, step_id)
            recipe_service.move_step(session, recipe, step, direction=direction)
        self._reload_detail()

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
            error_dialog(self, "Bitte zuerst ein Rezept auswählen.")
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

    # --- PDF-Export ------------------------------------------------------------------------

    def _export_pdf(self) -> None:
        if self._current_recipe_id is None:
            error_dialog(self, "Bitte zuerst ein Rezept auswählen.")
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
            default_name = recipe_service.generate_unique_recipe_name(session)
        name = prompt_text(self, "Neues Rezept", "Name des Rezepts:", default=default_name)
        if not name:
            return
        try:
            with self.context.session() as session:
                recipe = recipe_service.create_recipe(session, name=name)
                self._current_recipe_id = recipe.id
        except IntegrityError:
            error_dialog(self, f"Ein Rezept mit dem Namen '{name}' existiert bereits. Bitte einen anderen Namen wählen.")
            return
        self._reload_list()
        self._select_recipe_by_id(self._current_recipe_id)
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def _create_veggie_variant(self) -> None:
        if self._current_recipe_id is None:
            error_dialog(self, "Bitte zuerst ein Rezept auswählen.")
            return
        diet_type = prompt_choice(
            self, "Veggi-Variante erstellen", "Neue Variante ist:", list(recipe_service.DIET_TYPES[:2])
        )
        if not diet_type:
            return
        with self.context.session() as session:
            source = session.get(recipe_service.Recipe, self._current_recipe_id)
            if source is None:
                return
            default_name = recipe_service.generate_unique_recipe_name(session, f"{source.name} ({diet_type})")
        name = prompt_text(self, "Veggi-Variante erstellen", "Name der neuen Variante:", default=default_name)
        if not name:
            return
        try:
            with self.context.session() as session:
                source = session.get(recipe_service.Recipe, self._current_recipe_id)
                if source is None:
                    return
                new_recipe = recipe_service.duplicate_recipe(session, source, name=name, diet_type=diet_type)
                new_recipe_id = new_recipe.id
        except IntegrityError:
            error_dialog(self, f"Ein Rezept mit dem Namen '{name}' existiert bereits. Bitte einen anderen Namen wählen.")
            return
        self._current_recipe_id = new_recipe_id
        self._reload_list()
        self._select_recipe_by_id(self._current_recipe_id)
        info_dialog(self, f"Variante '{name}' wurde erstellt. Bitte die Zutaten anpassen.")

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
            diet_type = self.diet_type_combo.currentText().strip()
            recipe_service.update_recipe(
                recipe,
                name=name,
                diet_type=diet_type if diet_type in recipe_service.DIET_TYPES else None,
                meal_type=self.meal_type_combo.currentText().strip() or None,
                default_portions=self.portions_spin.value(),
                active=self.active_checkbox.isChecked(),
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

    def _delete_recipe(self) -> None:
        if self._current_recipe_id is None:
            return
        if not confirm_dialog(self, "Rezept löschen", "Dieses Rezept wirklich unwiderruflich löschen?"):
            return
        with self.context.session() as session:
            recipe = session.get(recipe_service.Recipe, self._current_recipe_id)
            if recipe is None:
                return
            try:
                recipe_service.delete_recipe(session, recipe)
            except ValueError as exc:
                error_dialog(self, str(exc))
                return
        self._current_recipe_id = None
        self._reload_list()
