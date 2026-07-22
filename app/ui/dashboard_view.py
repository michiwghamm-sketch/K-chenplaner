from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget
from sqlalchemy import select

from app.context import AppContext
from app.models import CampYear, Recipe
from app.services import price_service, recipe_service, validation_service
from app.ui.widgets import COLOR_CRITICAL, COLOR_INFO, COLOR_OK, COLOR_WARNING, KpiCard, PageHeader

_SEVERITY_COLORS = {"warnung": COLOR_WARNING, "kritisch": COLOR_CRITICAL, "hinweis": COLOR_INFO}


class DashboardView(QWidget):
    """Übersicht: Kennzahlen und Warnungen für das ausgewählte Camp-Jahr."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(PageHeader("Dashboard", "Kennzahlen und Warnungen für das ausgewählte Camp-Jahr"))

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

    def refresh(self) -> None:
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
