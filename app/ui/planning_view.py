from __future__ import annotations

from datetime import date, datetime

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.context import AppContext
from app.models import CampYear, Recipe
from app.services import planning_service
from app.ui.dialogs import CampYearDialog, DayResponsibleDialog, MealCellDialog, error_dialog, info_dialog
from app.ui.theme import TEXT_MUTED
from app.ui.widgets import COLOR_CRITICAL, PageHeader

ROW_LABELS = ("Verantwortlich",) + planning_service.DEFAULT_MEAL_TYPES


class PlanningView(QWidget):
    """Wochenplan: die Zeltlagerwoche mit Tagesverantwortlichen und Mahlzeiten je Tag."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._day_dates: list[date] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            PageHeader("Wochenplan", "Zeltlagerwoche planen: Tagesverantwortliche und Mahlzeiten je Tag")
        )

        top_row = QHBoxLayout()
        self.camp_year_combo = QComboBox(self)
        self.camp_year_combo.currentIndexChanged.connect(self._on_camp_year_changed)
        top_row.addWidget(self.camp_year_combo)

        new_year_button = QPushButton("Neue Zeltlagerwoche", self)
        new_year_button.clicked.connect(self._create_camp_year)
        edit_year_button = QPushButton("Zeitraum bearbeiten", self)
        edit_year_button.clicked.connect(self._edit_camp_year)
        generate_button = QPushButton("Wochenplan-Raster anlegen", self)
        generate_button.clicked.connect(self._generate_slots)
        top_row.addWidget(new_year_button)
        top_row.addWidget(edit_year_button)
        top_row.addWidget(generate_button)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        hint = QLabel("Doppelklick auf ein Feld zum Bearbeiten.", self)
        hint.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(hint)

        self.table = QTableWidget(len(ROW_LABELS), 0, self)
        self.table.setVerticalHeaderLabels(list(ROW_LABELS))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self.table)

    def refresh(self) -> None:
        self._reload_camp_years()

    def _reload_camp_years(self) -> None:
        self.camp_year_combo.blockSignals(True)
        self.camp_year_combo.clear()
        with self.context.session() as session:
            camp_years = session.execute(select(CampYear).order_by(CampYear.year.desc())).scalars().all()
            for camp_year in camp_years:
                self.camp_year_combo.addItem(camp_year.name or str(camp_year.year), camp_year.id)
        self.camp_year_combo.blockSignals(False)

        if self.context.current_camp_year_id is not None:
            index = self.camp_year_combo.findData(self.context.current_camp_year_id)
            if index >= 0:
                self.camp_year_combo.setCurrentIndex(index)
        self._on_camp_year_changed()

    def _on_camp_year_changed(self) -> None:
        self.context.current_camp_year_id = self.camp_year_combo.currentData()
        self._reload_grid()

    def _reload_grid(self) -> None:
        camp_year_id = self.context.current_camp_year_id
        self._day_dates = []
        self.table.setColumnCount(0)
        if camp_year_id is None:
            return

        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)
            if camp_year is None:
                return

            self._day_dates = planning_service.camp_day_range(camp_year)
            self.table.setColumnCount(len(self._day_dates))
            self.table.setHorizontalHeaderLabels(
                [f"{planning_service.weekday_name(day)}\n{day.strftime('%d.%m.')}" for day in self._day_dates]
            )

            camp_days_by_date = {camp_day.day_date: camp_day for camp_day in camp_year.camp_days}
            entries_by_key = {(entry.meal_date, entry.meal_type): entry for entry in camp_year.meal_plan_entries}

            for col, day in enumerate(self._day_dates):
                camp_day = camp_days_by_date.get(day)
                responsible_item = QTableWidgetItem(camp_day.responsible_person if camp_day else "")
                self.table.setItem(0, col, responsible_item)

                for row, meal_type in enumerate(planning_service.DEFAULT_MEAL_TYPES, start=1):
                    entry = entries_by_key.get((day, meal_type))
                    text = ""
                    if entry is not None and entry.recipe is not None:
                        text = entry.recipe.name
                        if entry.planned_portions:
                            text += f" ({entry.planned_portions})"
                    item = QTableWidgetItem(text)
                    if entry is not None and entry.status == "abgesagt":
                        item.setForeground(QColor(TEXT_MUTED))
                    elif entry is not None and entry.recipe is not None and not entry.planned_portions:
                        item.setForeground(QColor(COLOR_CRITICAL))
                    self.table.setItem(row, col, item)

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        if self.context.current_camp_year_id is None or col >= len(self._day_dates):
            return
        day = self._day_dates[col]
        day_label = f"{planning_service.weekday_name(day)} {day.strftime('%d.%m.%Y')}"

        if row == 0:
            self._edit_day_responsible(day, day_label)
        else:
            meal_type = planning_service.DEFAULT_MEAL_TYPES[row - 1]
            self._edit_meal_entry(day, meal_type, f"{meal_type} - {day_label}")

    def _edit_day_responsible(self, day: date, day_label: str) -> None:
        camp_year_id = self.context.current_camp_year_id
        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)
            camp_day = planning_service.get_or_create_camp_day(session, camp_year, day)
            current_person = camp_day.responsible_person or ""
            current_notes = camp_day.notes or ""

        dialog = DayResponsibleDialog(day_label, current_person, current_notes, self)
        if dialog.exec() != DayResponsibleDialog.DialogCode.Accepted:
            return
        data = dialog.result_data()

        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)
            camp_day = planning_service.get_or_create_camp_day(session, camp_year, day)
            planning_service.set_day_responsible(camp_day, **data)
        self._reload_grid()

    def _edit_meal_entry(self, day: date, meal_type: str, cell_label: str) -> None:
        camp_year_id = self.context.current_camp_year_id
        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)
            recipes = [
                (recipe.id, recipe.name)
                for recipe in session.execute(
                    select(Recipe).where(Recipe.active.is_(True)).order_by(Recipe.name)
                ).scalars()
            ]
            entry = planning_service.get_or_create_meal_entry(session, camp_year, day, meal_type)
            current_recipe_id = entry.recipe_id
            current_portions = entry.planned_portions or 0
            current_target_group = entry.target_group or ""
            current_status = entry.status or "geplant"
            current_notes = entry.notes or ""

        dialog = MealCellDialog(
            cell_label,
            recipes,
            current_recipe_id=current_recipe_id,
            current_portions=current_portions,
            current_target_group=current_target_group,
            current_status=current_status,
            current_notes=current_notes,
            status_options=planning_service.ALLOWED_STATUSES,
            parent=self,
        )
        if dialog.exec() != MealCellDialog.DialogCode.Accepted:
            return
        data = dialog.result_data()

        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)
            entry = planning_service.get_or_create_meal_entry(session, camp_year, day, meal_type)
            entry.recipe = session.get(Recipe, data["recipe_id"]) if data["recipe_id"] else None
            entry.planned_portions = data["planned_portions"]
            entry.target_group = data["target_group"]
            entry.notes = data["notes"]
            try:
                planning_service.set_status(entry, data["status"])
            except ValueError as exc:
                error_dialog(self, str(exc))
                return
        self._reload_grid()

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

    def _edit_camp_year(self) -> None:
        camp_year_id = self.context.current_camp_year_id
        if camp_year_id is None:
            error_dialog(self, "Bitte zuerst eine Zeltlagerwoche auswaehlen oder anlegen.")
            return

        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)
            if camp_year is None:
                return
            initial = {
                "year": camp_year.year,
                "name": camp_year.name,
                "start_date": camp_year.start_date,
                "end_date": camp_year.end_date,
                "notes": camp_year.notes,
            }

        dialog = CampYearDialog(datetime.now().year, self, initial=initial, allow_year_edit=False)
        if dialog.exec() != CampYearDialog.DialogCode.Accepted:
            return
        data = dialog.result_data()
        data.pop("year", None)

        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)
            planning_service.update_camp_year(session, camp_year, **data)
        self._reload_grid()

    def _generate_slots(self) -> None:
        camp_year_id = self.context.current_camp_year_id
        if camp_year_id is None:
            error_dialog(self, "Bitte zuerst eine Zeltlagerwoche auswaehlen oder anlegen.")
            return
        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)
            try:
                created = planning_service.generate_daily_meal_slots(session, camp_year)
            except ValueError as exc:
                error_dialog(self, str(exc))
                return
        info_dialog(self, f"{len(created)} neue Mahlzeiten-Slots angelegt.")
        self._reload_grid()
