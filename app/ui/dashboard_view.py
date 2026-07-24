from __future__ import annotations

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QHorizontalStackedBarSeries,
    QPieSeries,
    QValueAxis,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.context import AppContext
from app.models import CampYear, Recipe
from app.services import price_service, recipe_service, stats_service, validation_service
from app.ui.theme import BG_SURFACE, ORANGE, TEXT_DARK, TEXT_MUTED
from app.ui.widgets import (
    COLOR_CRITICAL,
    COLOR_INFO,
    COLOR_OK,
    COLOR_WARNING,
    DIET_TYPE_COLORS,
    KpiCard,
    PageHeader,
    UNKNOWN_DIET_TYPE_COLOR,
)

_SEVERITY_LABELS = {"kritisch": "Kritisch", "warnung": "Warnung", "hinweis": "Hinweis"}
_SEVERITY_COLORS = {"kritisch": COLOR_CRITICAL, "warnung": COLOR_WARNING, "hinweis": COLOR_INFO}
_SEVERITY_ORDER = ("kritisch", "warnung", "hinweis")


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

        charts_row = QHBoxLayout()
        charts_row.setSpacing(12)

        self.diet_chart_view = self._make_chart_view("Rezepte nach Ernährungstyp", legend=True)
        self._diet_pie_series = QPieSeries()
        self._diet_pie_series.setHoleSize(0.55)
        self.diet_chart_view.chart().addSeries(self._diet_pie_series)
        charts_row.addWidget(self.diet_chart_view, 1)

        self.most_planned_chart_view = self._make_chart_view("Am häufigsten geplant", legend=False)
        charts_row.addWidget(self.most_planned_chart_view, 1)

        layout.addLayout(charts_row)

        camp_year_row = QHBoxLayout()
        camp_year_row.setSpacing(12)

        self.camp_year_chart_view = self._make_chart_view("Kosten je Camp-Jahr (EUR)", legend=False)
        camp_year_row.addWidget(self.camp_year_chart_view, 1)

        camp_year_table_column = QVBoxLayout()
        camp_year_table_column.addWidget(self._section_title("Camp-Jahre im Überblick"))
        self.camp_year_table = QTableWidget(0, 4, self)
        self.camp_year_table.setHorizontalHeaderLabels(["Jahr", "Portionen", "Kosten (EUR)", "Ø je Portion (EUR)"])
        self.camp_year_table.verticalHeader().setVisible(False)
        self.camp_year_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        camp_year_table_column.addWidget(self.camp_year_table)
        camp_year_row.addLayout(camp_year_table_column, 1)

        layout.addLayout(camp_year_row)

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

        layout.addWidget(self._section_title("Warnungen und Hinweise"))
        self.warnings_table = QTableWidget(0, 1, self)
        self.warnings_table.horizontalHeader().setVisible(False)
        self.warnings_table.verticalHeader().setVisible(False)
        self.warnings_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.warnings_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.warnings_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.warnings_table, stretch=1)

    def _section_title(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setStyleSheet("font-weight: 600; font-size: 15px; padding-top: 6px;")
        return label

    def _make_chart_view(self, title: str, *, legend: bool) -> QChartView:
        chart = QChart()
        chart.setTitle(title)
        chart.legend().setVisible(legend)
        if legend:
            chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        chart.setBackgroundVisible(False)
        view = QChartView(chart, self)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setMinimumHeight(240)
        return view

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
            self._update_diet_chart(diet_counts)

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

            most_planned = stats_service.most_planned_recipes(session, limit=8)
            self._update_most_planned_chart(most_planned)

            camp_costs = stats_service.camp_year_costs(session)
            self._update_camp_year_chart(camp_costs)

            self.camp_year_table.setRowCount(0)
            for camp_cost in camp_costs:
                row = self.camp_year_table.rowCount()
                self.camp_year_table.insertRow(row)
                self.camp_year_table.setItem(row, 0, QTableWidgetItem(camp_cost.label))
                self.camp_year_table.setItem(row, 1, QTableWidgetItem(str(camp_cost.total_portions)))
                self.camp_year_table.setItem(row, 2, QTableWidgetItem(f"{camp_cost.total_cost:.2f}"))
                per_portion = (camp_cost.total_cost / camp_cost.total_portions) if camp_cost.total_portions else None
                self.camp_year_table.setItem(row, 3, QTableWidgetItem(f"{per_portion:.2f}" if per_portion else "-"))

    def _update_diet_chart(self, counts: dict[str, int]) -> None:
        series = self._diet_pie_series
        series.clear()
        order = ["Fleisch", "Vegetarisch", "Vegan", stats_service.UNKNOWN_DIET_TYPE_LABEL]
        colors = {**DIET_TYPE_COLORS, stats_service.UNKNOWN_DIET_TYPE_LABEL: UNKNOWN_DIET_TYPE_COLOR}
        for label in order:
            count = counts.get(label, 0)
            if not count:
                continue
            pie_slice = series.append(f"{label} ({count})", count)
            pie_slice.setLabelVisible(True)
            pie_slice.setColor(QColor(colors[label]))
            pie_slice.setLabelColor(QColor(TEXT_DARK))
            pie_slice.setBorderColor(QColor(BG_SURFACE))
            pie_slice.setBorderWidth(2)

    def _update_most_planned_chart(self, entries: list[stats_service.RecipePlanCount]) -> None:
        chart = self.most_planned_chart_view.chart()
        chart.removeAllSeries()
        for axis in list(chart.axes()):
            chart.removeAxis(axis)
        if not entries:
            return

        ordered = list(reversed(entries))  # Platz 1 soll oben stehen
        series = QHorizontalStackedBarSeries()
        series.setLabelsVisible(True)
        series.setLabelsFormat("@value")
        categories = []
        for index, entry in enumerate(ordered):
            categories.append(entry.recipe_name)
            values = [0] * len(ordered)
            values[index] = entry.plan_count
            bar_set = QBarSet("")
            bar_set.append(values)
            bar_set.setColor(QColor(DIET_TYPE_COLORS.get(entry.diet_type or "", ORANGE)))
            series.append(bar_set)
        chart.addSeries(series)

        axis_y = QBarCategoryAxis()
        axis_y.append(categories)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)

        axis_x = QValueAxis()
        axis_x.setLabelFormat("%d")
        max_count = max(e.plan_count for e in entries)
        axis_x.setRange(0, max_count + 1)
        axis_x.setTickCount(max_count + 2)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis_x)

    def _update_camp_year_chart(self, costs: list[stats_service.CampYearCost]) -> None:
        chart = self.camp_year_chart_view.chart()
        chart.removeAllSeries()
        for axis in list(chart.axes()):
            chart.removeAxis(axis)
        if not costs:
            return

        ordered = list(reversed(costs))  # aeltestes Jahr zuerst
        bar_set = QBarSet("Kosten (EUR)")
        bar_set.append([float(c.total_cost) for c in ordered])
        bar_set.setColor(QColor(ORANGE))
        series = QBarSeries()
        series.setBarWidth(0.5)
        series.append(bar_set)
        series.setLabelsVisible(True)
        series.setLabelsFormat("@value")
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append([c.label for c in ordered])
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setLabelFormat("%.2f")
        max_cost = max((float(c.total_cost) for c in ordered), default=0)
        axis_y.setRange(0, max_cost * 1.15 if max_cost else 1)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)

    def _on_camp_year_changed(self) -> None:
        self.context.current_camp_year_id = self.camp_year_combo.currentData()
        self._reload_kpis()

    def _reload_kpis(self) -> None:
        camp_year_id = self.context.current_camp_year_id
        if camp_year_id is None:
            self.period_label.setText("Kein Camp-Jahr angelegt.")
            self.warnings_table.setRowCount(0)
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
            self._reload_warnings_table(report)

    def _reload_warnings_table(self, report: validation_service.ValidationReport) -> None:
        table = self.warnings_table
        table.setRowCount(0)

        if not report.issues:
            self._add_warnings_band("Alles in Ordnung - keine Warnungen für dieses Camp-Jahr.", COLOR_OK)
            return

        issues_by_severity: dict[str, list] = {severity: [] for severity in _SEVERITY_ORDER}
        for issue in report.issues:
            issues_by_severity.setdefault(issue.severity, []).append(issue)

        for severity in _SEVERITY_ORDER:
            issues = issues_by_severity.get(severity) or []
            if not issues:
                continue
            label = _SEVERITY_LABELS.get(severity, severity.title())
            self._add_warnings_band(f"{label} ({len(issues)})", _SEVERITY_COLORS.get(severity, COLOR_INFO))
            for issue in issues:
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(row, 0, QTableWidgetItem(f"[{issue.category}] {issue.message}"))

    def _add_warnings_band(self, text: str, color: str) -> None:
        table = self.warnings_table
        row = table.rowCount()
        table.insertRow(row)
        band_label = QLabel(f"  {text}", table)
        band_label.setStyleSheet(f"background-color: {color}; color: white; font-weight: 600; padding: 5px;")
        table.setCellWidget(row, 0, band_label)
