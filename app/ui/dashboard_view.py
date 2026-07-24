from __future__ import annotations

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.context import AppContext
from app.models import CampYear, Recipe
from app.services import price_service, recipe_service, stats_service, validation_service
from app.ui.theme import TEXT_MUTED
from app.ui.widgets import COLOR_CRITICAL, COLOR_INFO, COLOR_OK, COLOR_WARNING, KpiCard, PageHeader

_SEVERITY_COLORS = {"warnung": COLOR_WARNING, "kritisch": COLOR_CRITICAL, "hinweis": COLOR_INFO}
_DIET_TYPE_COLORS = {"Vegetarisch": COLOR_OK, "Vegan": COLOR_WARNING, "Fleisch": COLOR_CRITICAL}


class DashboardView(QWidget):
    """Übersicht: Rezept-/Kosten-Statistiken über alle Camp-Jahre sowie Details je ausgewähltem Camp-Jahr."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(PageHeader("Dashboard", "Statistiken über alle Rezepte und Camp-Jahre"))

        layout.addWidget(self._section_title("Rezepte im Überblick"))
        recipe_grid = QGridLayout()
        self.kpi_recipes_total = KpiCard("Rezepte gesamt")
        self.kpi_recipes_fleisch = KpiCard("Fleisch")
        self.kpi_recipes_vegetarisch = KpiCard("Vegetarisch")
        self.kpi_recipes_vegan = KpiCard("Vegan")
        self.kpi_avg_recipe_cost = KpiCard("Ø Kosten je Rezept (EUR)")
        self.kpi_avg_portion_cost = KpiCard("Ø Kosten je Portion (EUR)")
        self.kpi_recipes_fleisch.set_level("kritisch")
        self.kpi_recipes_vegetarisch.set_level("ok")
        self.kpi_recipes_vegan.set_level("warnung")
        for index, card in enumerate(
            (
                self.kpi_recipes_total,
                self.kpi_recipes_fleisch,
                self.kpi_recipes_vegetarisch,
                self.kpi_recipes_vegan,
                self.kpi_avg_recipe_cost,
                self.kpi_avg_portion_cost,
            )
        ):
            recipe_grid.addWidget(card, index // 3, index % 3)
        layout.addLayout(recipe_grid)

        self.avg_cost_note = QLabel("", self)
        self.avg_cost_note.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        layout.addWidget(self.avg_cost_note)

        stats_row = QHBoxLayout()

        most_planned_column = QVBoxLayout()
        most_planned_column.addWidget(self._section_title("Am häufigsten geplant"))
        self.most_planned_list = QListWidget(self)
        self.most_planned_list.setMaximumHeight(220)
        most_planned_column.addWidget(self.most_planned_list)
        stats_row.addLayout(most_planned_column, 1)

        camp_year_column = QVBoxLayout()
        camp_year_column.addWidget(self._section_title("Camp-Jahre im Überblick"))
        self.camp_year_table = QTableWidget(0, 4, self)
        self.camp_year_table.setHorizontalHeaderLabels(["Jahr", "Portionen", "Kosten (EUR)", "Ø je Portion (EUR)"])
        self.camp_year_table.verticalHeader().setVisible(False)
        self.camp_year_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.camp_year_table.setMaximumHeight(220)
        camp_year_column.addWidget(self.camp_year_table)
        stats_row.addLayout(camp_year_column, 1)

        layout.addLayout(stats_row)

        layout.addWidget(self._section_title("Details für ausgewähltes Camp-Jahr"))

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Camp-Jahr:", self))
        self.camp_year_combo = QComboBox(self)
        self.camp_year_combo.currentIndexChanged.connect(self._on_camp_year_changed)
        top_row.addWidget(self.camp_year_combo)
        self.period_label = QLabel("", self)
        top_row.addWidget(self.period_label)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        grid = QGridLayout()
        self.kpi_meals = KpiCard("Geplante Mahlzeiten")
        self.kpi_portions = KpiCard("Geplante Portionen")
        self.kpi_budget = KpiCard("Geplantes Budget (EUR)")
        self.kpi_open_shopping = KpiCard("Offene Einkäufe")
        self.kpi_missing_prices = KpiCard("Fehlende Preise")
        self.kpi_missing_feedback = KpiCard("Rezepte ohne Feedback")
        for index, card in enumerate(
            (
                self.kpi_meals,
                self.kpi_portions,
                self.kpi_budget,
                self.kpi_open_shopping,
                self.kpi_missing_prices,
                self.kpi_missing_feedback,
            )
        ):
            grid.addWidget(card, index // 3, index % 3)
        layout.addLayout(grid)

        layout.addWidget(QLabel("Warnungen und Hinweise", self))
        self.warnings_list = QListWidget(self)
        layout.addWidget(self.warnings_list)

    def _section_title(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setStyleSheet("font-weight: 600; font-size: 15px; padding-top: 6px;")
        return label

    def refresh(self) -> None:
        self._reload_global_stats()

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

    def _reload_global_stats(self) -> None:
        with self.context.session() as session:
            diet_counts = stats_service.recipe_counts_by_diet_type(session)
            total_recipes = sum(diet_counts.values())
            self.kpi_recipes_total.set_value(str(total_recipes))
            self.kpi_recipes_fleisch.set_value(str(diet_counts.get("Fleisch", 0)))
            self.kpi_recipes_vegetarisch.set_value(str(diet_counts.get("Vegetarisch", 0)))
            self.kpi_recipes_vegan.set_value(str(diet_counts.get("Vegan", 0)))

            avg_cost = stats_service.average_recipe_cost(session)
            self.kpi_avg_recipe_cost.set_value(
                f"{avg_cost.average_total_cost:.2f}" if avg_cost.average_total_cost is not None else "-"
            )
            self.kpi_avg_portion_cost.set_value(
                f"{avg_cost.average_cost_per_portion:.2f}" if avg_cost.average_cost_per_portion is not None else "-"
            )
            if avg_cost.recipes_considered:
                self.avg_cost_note.setText(
                    f"Durchschnitt basiert auf {avg_cost.recipes_considered} von {avg_cost.recipes_total} Rezepten "
                    "mit mindestens einer bepreisten Zutat - bei vielen fehlenden Preisen ist der Wert nur grob."
                )
            else:
                self.avg_cost_note.setText("Noch keine Rezepte mit hinterlegten Preisen.")

            self.most_planned_list.clear()
            most_planned = stats_service.most_planned_recipes(session, limit=8)
            if not most_planned:
                self.most_planned_list.addItem("Noch keine Mahlzeiten eingeplant.")
            for rank, entry in enumerate(most_planned, start=1):
                item = QListWidgetItem(f"{rank}. {entry.recipe_name} ({entry.plan_count}x geplant)")
                color = _DIET_TYPE_COLORS.get(entry.diet_type or "")
                if color:
                    item.setForeground(QColor(color))
                    font = item.font()
                    font.setWeight(QFont.Weight.DemiBold)
                    item.setFont(font)
                self.most_planned_list.addItem(item)

            self.camp_year_table.setRowCount(0)
            for camp_cost in stats_service.camp_year_costs(session):
                row = self.camp_year_table.rowCount()
                self.camp_year_table.insertRow(row)
                self.camp_year_table.setItem(row, 0, QTableWidgetItem(camp_cost.label))
                self.camp_year_table.setItem(row, 1, QTableWidgetItem(str(camp_cost.total_portions)))
                self.camp_year_table.setItem(row, 2, QTableWidgetItem(f"{camp_cost.total_cost:.2f}"))
                per_portion = (camp_cost.total_cost / camp_cost.total_portions) if camp_cost.total_portions else None
                self.camp_year_table.setItem(row, 3, QTableWidgetItem(f"{per_portion:.2f}" if per_portion else "-"))

    def _on_camp_year_changed(self) -> None:
        self.context.current_camp_year_id = self.camp_year_combo.currentData()
        self._reload_kpis()

    def _reload_kpis(self) -> None:
        camp_year_id = self.context.current_camp_year_id
        if camp_year_id is None:
            self.period_label.setText("Kein Camp-Jahr angelegt.")
            self.warnings_list.clear()
            return

        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)
            if camp_year is None:
                return

            self.period_label.setText(
                f"Zeitraum: {camp_year.start_date or '-'} bis {camp_year.end_date or '-'}"
            )

            active_entries = [e for e in camp_year.meal_plan_entries if e.status != "abgesagt"]
            self.kpi_meals.set_value(str(len(active_entries)))
            total_portions = sum(e.planned_portions or 0 for e in active_entries)
            self.kpi_portions.set_value(str(total_portions))

            total_budget = 0
            for entry in active_entries:
                if entry.recipe is None or not entry.planned_portions:
                    continue
                result = recipe_service.calculate_recipe_cost(
                    session, entry.recipe, portions=entry.planned_portions, year=camp_year.year
                )
                total_budget += result.total_cost
            self.kpi_budget.set_value(f"{total_budget:.2f}")

            open_items = sum(
                1
                for shopping_list in camp_year.shopping_lists
                for item in shopping_list.items
                if item.status == "offen"
            )
            self.kpi_open_shopping.set_value(str(open_items))
            self.kpi_open_shopping.set_level("warnung" if open_items else "ok")

            missing_prices = price_service.missing_price_ingredients(session, year=camp_year.year)
            self.kpi_missing_prices.set_value(str(len(missing_prices)))
            self.kpi_missing_prices.set_level("kritisch" if missing_prices else "ok")

            active_recipes = session.execute(select(Recipe).where(Recipe.active.is_(True))).scalars().all()
            recipes_without_feedback = [r for r in active_recipes if not r.feedback_entries]
            self.kpi_missing_feedback.set_value(str(len(recipes_without_feedback)))
            self.kpi_missing_feedback.set_level("warnung" if recipes_without_feedback else "ok")

            report = validation_service.run_all_checks(session, camp_year=camp_year, year=camp_year.year)
            self.warnings_list.clear()
            if not report.issues:
                item = QListWidgetItem("Keine Warnungen für dieses Camp-Jahr.")
                item.setForeground(QColor(COLOR_OK))
                self.warnings_list.addItem(item)
            for issue in report.issues:
                item = QListWidgetItem(f"[{issue.category}] {issue.message}")
                item.setForeground(QColor(_SEVERITY_COLORS.get(issue.severity, COLOR_INFO)))
                self.warnings_list.addItem(item)
