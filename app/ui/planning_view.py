from __future__ import annotations

from datetime import date, datetime
from xml.sax.saxutils import escape

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
from app.models import CampYear, MealPlanEntry, Recipe
from app.services import planning_service
from app.ui.dialogs import CampYearDialog, DayResponsibleDialog, MealSlotDialog, error_dialog, info_dialog
from app.ui.theme import TEXT_MUTED
from app.ui.widgets import COLOR_CRITICAL, DIET_TYPE_COLORS, PageHeader

ROW_LABELS = ("Verantwortlich",) + planning_service.DEFAULT_MEAL_TYPES + ("Auswertung",)
DAY_COLUMN_WIDTH = 210


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
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(DAY_COLUMN_WIDTH)
        self.table.horizontalHeader().setMinimumSectionSize(DAY_COLUMN_WIDTH)
        # Wenn eine Spalte breiter/schmaler gezogen wird, muessen die (wortumbruchbehafteten)
        # Zellen neu umgebrochen und die Zeilenhoehen entsprechend angepasst werden.
        self.table.horizontalHeader().sectionResized.connect(self._on_column_resized)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setMinimumSectionSize(48)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self.table)
        layout.addStretch(1)

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

        if camp_year_id is not None:
            with self.context.session() as session:
                camp_year = session.get(CampYear, camp_year_id)
                if camp_year is not None:
                    self._populate_grid(session, camp_year)

        self._resize_rows_to_content()
        self._update_table_fixed_height()

    def _populate_grid(self, session, camp_year: CampYear) -> None:
        self._day_dates = planning_service.camp_day_range(camp_year)
        self.table.setColumnCount(len(self._day_dates))
        self.table.setHorizontalHeaderLabels(
            [f"{planning_service.weekday_name(day)}\n{day.strftime('%d.%m.')}" for day in self._day_dates]
        )
        for col in range(len(self._day_dates)):
            self.table.setColumnWidth(col, DAY_COLUMN_WIDTH)

        camp_days_by_date = {camp_day.day_date: camp_day for camp_day in camp_year.camp_days}
        summary_row = len(ROW_LABELS) - 1

        for col, day in enumerate(self._day_dates):
            camp_day = camp_days_by_date.get(day)
            responsible_item = QTableWidgetItem(camp_day.responsible_person if camp_day else "")
            self.table.setItem(0, col, responsible_item)

            for row, meal_type in enumerate(planning_service.DEFAULT_MEAL_TYPES, start=1):
                dishes = planning_service.meal_entries_for_slot(camp_year, day, meal_type)
                label = self._build_dish_cell(dishes)
                self.table.setCellWidget(row, col, label)

            summary = planning_service.day_summary(session, camp_year, day)
            summary_label = self._build_summary_cell(summary)
            self.table.setCellWidget(summary_row, col, summary_label)

    def _on_column_resized(self, *_args: object) -> None:
        self._resize_rows_to_content()
        self._update_table_fixed_height()

    def _resize_rows_to_content(self) -> None:
        """Zeilenhoehe je Zeile aus dem tatsaechlichen Platzbedarf (mit Wortumbruch) aller
        Zellen dieser Zeile bei der jeweils AKTUELLEN Spaltenbreite berechnen.

        Bewusst ueber QLabel.heightForWidth() statt QTableWidget.resizeRowsToContents():
        Cell-Widgets melden ihre reale Groesse erst nach dem naechsten Qt-Layout-Durchlauf,
        resizeRowsToContents() wuerde also mit veralteten Groessen rechnen. heightForWidth()
        berechnet dagegen sofort und unabhaengig vom Layout-Zyklus.
        """
        min_row_height = self.table.verticalHeader().minimumSectionSize()
        for row in range(self.table.rowCount()):
            row_height = min_row_height
            for col in range(self.table.columnCount()):
                label = self.table.cellWidget(row, col)
                if label is None:
                    continue
                content_width = max(self.table.columnWidth(col) - 12, 1)
                row_height = max(row_height, label.heightForWidth(content_width) + 12)
            self.table.setRowHeight(row, row_height)

    def _update_table_fixed_height(self) -> None:
        # Tabellenhoehe an den tatsaechlichen Inhalt anpassen (Header + Zeilenhoehen),
        # statt die Tabelle per Layout-Stretch unnoetig viel Leerraum fuellen zu lassen.
        # Header-Hoehe bewusst aus der Schrift berechnet (zwei Zeilen: Wochentag + Datum)
        # statt per horizontalHeader().height() gemessen - dieser Wert ist direkt nach
        # setHorizontalHeaderLabels() noch nicht auf die zweizeiligen Labels aktualisiert.
        header_height = 2 * self.table.fontMetrics().height() + 16
        scrollbar_allowance = self.table.horizontalScrollBar().sizeHint().height()
        total_height = header_height + scrollbar_allowance + 2 * self.table.frameWidth() + 4
        for row in range(self.table.rowCount()):
            total_height += self.table.rowHeight(row)
        self.table.setFixedHeight(total_height)

    def _build_dish_cell(self, dishes: list[MealPlanEntry]) -> QLabel:
        lines = []
        for entry in dishes:
            if entry.recipe is None:
                continue
            text = escape(entry.recipe.name)
            if entry.planned_portions:
                text += f" ({entry.planned_portions})"
            if entry.target_group:
                text += f" · {escape(entry.target_group)}"

            if entry.status == "abgesagt":
                lines.append(f'<span style="color:{TEXT_MUTED};">{text} (abgesagt)</span>')
                continue
            if not entry.planned_portions:
                lines.append(f'<span style="color:{COLOR_CRITICAL};">{text}</span>')
                continue
            color = DIET_TYPE_COLORS.get(entry.recipe.diet_type or "")
            if color:
                lines.append(f'<span style="color:{color};">{text}</span>')
            else:
                lines.append(text)

        label = QLabel("<br>".join(lines), self.table)
        # Wortumbruch aktiv, damit lange Gerichtnamen nicht am Zellrand abgeschnitten werden -
        # die Zeilenhoehe wird in _resize_rows_to_content() passend dazu berechnet.
        label.setWordWrap(True)
        label.setMargin(4)
        label.setContentsMargins(4, 2, 4, 2)
        return label

    def _build_summary_cell(self, summary: "planning_service.DaySummary") -> QLabel:
        if not summary.meals:
            label = QLabel("-", self.table)
        else:
            text = f"{summary.total_portions} Portionen · {summary.total_cost:.2f} EUR"
            if summary.has_missing_prices:
                text += " ⚠"
                label = QLabel(text, self.table)
                label.setStyleSheet(f"color: {COLOR_CRITICAL};")
            else:
                label = QLabel(text, self.table)
        label.setWordWrap(True)
        label.setMargin(4)
        return label

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        if self.context.current_camp_year_id is None or col >= len(self._day_dates):
            return
        day = self._day_dates[col]
        day_label = f"{planning_service.weekday_name(day)} {day.strftime('%d.%m.%Y')}"

        summary_row = len(ROW_LABELS) - 1
        if row == 0:
            self._edit_day_responsible(day, day_label)
        elif row == summary_row:
            self._show_day_summary(day, day_label)
        else:
            meal_type = planning_service.DEFAULT_MEAL_TYPES[row - 1]
            self._edit_meal_entry(day, meal_type, f"{meal_type} - {day_label}")

    def _show_day_summary(self, day: date, day_label: str) -> None:
        camp_year_id = self.context.current_camp_year_id
        if camp_year_id is None:
            return
        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)
            summary = planning_service.day_summary(session, camp_year, day)

        if not summary.meals:
            info_dialog(self, "Für diesen Tag sind keine Gerichte geplant.", title=day_label)
            return

        lines = [
            f"{meal.meal_type}: {meal.recipe_name} ({meal.portions} Portionen) - {meal.cost:.2f} EUR"
            + (" (Preise unvollständig)" if meal.has_missing_prices else "")
            for meal in summary.meals
        ]
        lines.append("")
        lines.append(f"Gesamt: {summary.total_portions} Portionen, {summary.total_cost:.2f} EUR")
        if summary.has_missing_prices:
            lines.append("Achtung: Für mindestens eine Zutat fehlt ein Preis - die Kosten sind unvollständig.")
        info_dialog(self, "\n".join(lines), title=day_label)

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
            dishes = [
                {
                    "id": entry.id,
                    "recipe_id": entry.recipe_id,
                    "planned_portions": entry.planned_portions or 0,
                    "target_group": entry.target_group or "",
                    "status": entry.status or "geplant",
                    "notes": entry.notes or "",
                    "has_feedback": entry.feedback is not None,
                }
                for entry in planning_service.meal_entries_for_slot(camp_year, day, meal_type)
            ]

        dialog = MealSlotDialog(
            cell_label,
            dishes,
            recipes,
            status_options=planning_service.ALLOWED_STATUSES,
            parent=self,
        )
        if dialog.exec() != MealSlotDialog.DialogCode.Accepted:
            return
        data = dialog.result_data()

        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)

            for removed_id in data["removed_ids"]:
                entry = session.get(MealPlanEntry, removed_id)
                if entry is None:
                    continue
                try:
                    planning_service.delete_meal_entry(session, entry)
                except ValueError as exc:
                    error_dialog(self, str(exc))

            for dish in data["dishes"]:
                recipe = session.get(Recipe, dish["recipe_id"]) if dish["recipe_id"] else None
                if dish["id"] is not None:
                    entry = session.get(MealPlanEntry, dish["id"])
                    if entry is None:
                        continue
                    entry.recipe = recipe
                    entry.planned_portions = dish["planned_portions"]
                    entry.target_group = dish["target_group"]
                    entry.notes = dish["notes"]
                elif recipe is not None or dish["planned_portions"] or dish["notes"]:
                    entry = planning_service.add_meal_entry(
                        session,
                        camp_year,
                        day,
                        meal_type,
                        recipe=recipe,
                        planned_portions=dish["planned_portions"],
                        target_group=dish["target_group"],
                    )
                    entry.notes = dish["notes"]
                else:
                    continue
                try:
                    planning_service.set_status(entry, dish["status"])
                except ValueError as exc:
                    error_dialog(self, str(exc))
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
            error_dialog(self, "Bitte zuerst eine Zeltlagerwoche auswählen oder anlegen.")
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
            error_dialog(self, "Bitte zuerst eine Zeltlagerwoche auswählen oder anlegen.")
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
