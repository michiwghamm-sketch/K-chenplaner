from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.context import AppContext
from app.models import CampYear, MealPlanEntry, Recipe
from app.services import planning_service
from app.ui.dialogs import CampYearDialog, confirm_dialog, error_dialog, info_dialog
from app.ui.widgets import COLOR_CRITICAL

STATUS_OPTIONS = planning_service.ALLOWED_STATUSES


class PlanningView(QWidget):
    """Jahresplanung: Camp-Jahre anlegen, Mahlzeiten-Slots generieren und pflegen."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._current_entry_id: int | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self.camp_year_combo = QComboBox(self)
        self.camp_year_combo.currentIndexChanged.connect(self._on_camp_year_changed)
        top_row.addWidget(self.camp_year_combo)

        new_year_button = QPushButton("Neues Camp-Jahr", self)
        new_year_button.clicked.connect(self._create_camp_year)
        generate_button = QPushButton("Mahlzeiten-Slots generieren", self)
        generate_button.clicked.connect(self._generate_slots)
        top_row.addWidget(new_year_button)
        top_row.addWidget(generate_button)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        self.table = QTableWidget(0, 7, self)
        self.table.setHorizontalHeaderLabels(
            ["Datum", "Wochentag", "Mahlzeit", "Rezept", "Portionen", "Zielgruppe", "Status"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        layout.addWidget(self.table)

        form = QFormLayout()
        self.recipe_combo = QComboBox(self)
        self.portions_spin = QSpinBox(self)
        self.portions_spin.setRange(0, 2000)
        self.target_group_edit = QLineEdit(self)
        self.status_combo = QComboBox(self)
        self.status_combo.addItems(STATUS_OPTIONS)
        self.notes_edit = QPlainTextEdit(self)
        self.notes_edit.setFixedHeight(50)

        form.addRow("Rezept", self.recipe_combo)
        form.addRow("Portionen", self.portions_spin)
        form.addRow("Zielgruppe", self.target_group_edit)
        form.addRow("Status", self.status_combo)
        form.addRow("Notizen", self.notes_edit)
        layout.addLayout(form)

        save_button = QPushButton("Speichern", self)
        save_button.clicked.connect(self._save_entry)
        layout.addWidget(save_button)

    def refresh(self) -> None:
        self._reload_camp_years()

    def _reload_camp_years(self) -> None:
        self.camp_year_combo.blockSignals(True)
        self.camp_year_combo.clear()
        with self.context.session() as session:
            camp_years = session.execute(select(CampYear).order_by(CampYear.year.desc())).scalars().all()
            for camp_year in camp_years:
                self.camp_year_combo.addItem(camp_year.name or str(camp_year.year), camp_year.id)
            recipes = session.execute(select(Recipe).where(Recipe.active.is_(True)).order_by(Recipe.name)).scalars().all()
            self.recipe_combo.clear()
            self.recipe_combo.addItem("- kein Rezept -", None)
            for recipe in recipes:
                self.recipe_combo.addItem(recipe.name, recipe.id)
        self.camp_year_combo.blockSignals(False)

        if self.context.current_camp_year_id is not None:
            index = self.camp_year_combo.findData(self.context.current_camp_year_id)
            if index >= 0:
                self.camp_year_combo.setCurrentIndex(index)
        self._on_camp_year_changed()

    def _on_camp_year_changed(self) -> None:
        self.context.current_camp_year_id = self.camp_year_combo.currentData()
        self._reload_table()

    def _reload_table(self) -> None:
        self.table.setRowCount(0)
        camp_year_id = self.context.current_camp_year_id
        if camp_year_id is None:
            return
        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)
            if camp_year is None:
                return
            entries = sorted(
                camp_year.meal_plan_entries,
                key=lambda e: (e.meal_date or datetime.min.date(), e.meal_type or ""),
            )
            for entry in entries:
                row = self.table.rowCount()
                self.table.insertRow(row)
                date_item = QTableWidgetItem(entry.meal_date.isoformat() if entry.meal_date else "")
                date_item.setData(1000, entry.id)
                self.table.setItem(row, 0, date_item)
                self.table.setItem(row, 1, QTableWidgetItem(entry.weekday or ""))
                self.table.setItem(row, 2, QTableWidgetItem(entry.meal_type or ""))
                self.table.setItem(row, 3, QTableWidgetItem(entry.recipe.name if entry.recipe else ""))
                self.table.setItem(row, 4, QTableWidgetItem(str(entry.planned_portions or "")))
                self.table.setItem(row, 5, QTableWidgetItem(entry.target_group or ""))
                status_item = QTableWidgetItem(entry.status or "")
                if entry.recipe is not None and not entry.planned_portions and entry.status != "abgesagt":
                    date_item.setForeground(QColor(COLOR_CRITICAL))
                self.table.setItem(row, 6, status_item)

    def _on_row_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self._current_entry_id = None
            return
        self._current_entry_id = self.table.item(row, 0).data(1000)
        with self.context.session() as session:
            entry = session.get(MealPlanEntry, self._current_entry_id)
            if entry is None:
                return
            recipe_index = self.recipe_combo.findData(entry.recipe_id)
            self.recipe_combo.setCurrentIndex(recipe_index if recipe_index >= 0 else 0)
            self.portions_spin.setValue(entry.planned_portions or 0)
            self.target_group_edit.setText(entry.target_group or "")
            status_index = self.status_combo.findText(entry.status or "geplant")
            self.status_combo.setCurrentIndex(status_index if status_index >= 0 else 0)
            self.notes_edit.setPlainText(entry.notes or "")

    def _create_camp_year(self) -> None:
        dialog = CampYearDialog(datetime.now().year, self)
        if dialog.exec() != CampYearDialog.DialogCode.Accepted:
            return
        data = dialog.result_data()
        with self.context.session() as session:
            try:
                camp_year = planning_service.create_camp_year(session, **data)
            except ValueError as exc:
                error_dialog(self, str(exc))
                return
            self.context.current_camp_year_id = camp_year.id
        self._reload_camp_years()

    def _generate_slots(self) -> None:
        camp_year_id = self.context.current_camp_year_id
        if camp_year_id is None:
            error_dialog(self, "Bitte zuerst ein Camp-Jahr auswaehlen oder anlegen.")
            return
        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)
            try:
                created = planning_service.generate_daily_meal_slots(session, camp_year)
            except ValueError as exc:
                error_dialog(self, str(exc))
                return
        info_dialog(self, f"{len(created)} neue Mahlzeiten-Slots angelegt.")
        self._reload_table()

    def _save_entry(self) -> None:
        if self._current_entry_id is None:
            error_dialog(self, "Bitte zuerst eine Mahlzeit in der Tabelle auswaehlen.")
            return
        with self.context.session() as session:
            entry = session.get(MealPlanEntry, self._current_entry_id)
            if entry is None:
                return
            recipe_id = self.recipe_combo.currentData()
            recipe = session.get(Recipe, recipe_id) if recipe_id else None
            planning_service.set_meal_recipe(
                entry,
                recipe=recipe,
                planned_portions=self.portions_spin.value() or None,
                target_group=self.target_group_edit.text().strip() or None,
            )
            try:
                planning_service.set_status(entry, self.status_combo.currentText())
            except ValueError as exc:
                error_dialog(self, str(exc))
                return
            entry.notes = self.notes_edit.toPlainText().strip() or None
        self._reload_table()
