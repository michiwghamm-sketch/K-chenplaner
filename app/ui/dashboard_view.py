from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

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
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.context import AppContext
from app.models import CampYear
from app.services import feedback_service, planning_service, price_service, stats_service, validation_service
from app.ui.dialogs import CampYearDialog, error_dialog
from app.ui.theme import BG_SURFACE, BORDER, ORANGE, TEXT_DARK, TEXT_MUTED
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

_NAV_LABELS = {
    "planning": "Wochenplan",
    "ingredients": "Zutaten",
    "shopping": "Einkaufsliste",
    "feedback": "Feedback",
    "recipes": "Rezepte",
}


@dataclass(slots=True)
class ActionItem:
    """Eine Zeile in der 'Nächste Schritte'-Liste: was fehlt noch, wie dringend, wohin fuehrt der Klick."""

    text: str
    level: str
    nav_key: str | None


class DashboardView(QWidget):
    """Übersicht fuer die Vorbereitung des ausgewaehlten Zeltlagers: Status, offene Punkte und
    naechste Schritte stehen vorn: Rezeptbuch-weite Statistiken sind als Referenz nach unten
    verschoben - beim Vorbereiten EINES Zeltlagers interessiert zuerst dessen eigener Stand."""

    navigate_requested = Signal(str)

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._build_ui()
        self.refresh()

    # --- Aufbau ------------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget(scroll)
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.addWidget(PageHeader("Dashboard", "Status des ausgewählten Zeltlagers auf einen Blick"))

        self._state_stack = QStackedWidget(content)
        layout.addWidget(self._state_stack)
        self._state_stack.addWidget(self._build_empty_state())
        self._state_stack.addWidget(self._build_camp_year_content())

        layout.addWidget(self._divider())
        self._build_recipe_book_section(layout)
        layout.addStretch(1)

    def _divider(self) -> QFrame:
        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {BORDER};")
        return line

    def _build_empty_state(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addStretch(1)

        title = QLabel("Noch kein Zeltlager angelegt", widget)
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title)

        subtitle = QLabel(
            "Lege ein Zeltlager mit Zeitraum und Teilnehmerzahl an, um mit der Wochenplanung "
            "und der Kostenkalkulation zu starten.",
            widget,
        )
        subtitle.setStyleSheet(f"color: {TEXT_MUTED};")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        create_button = QPushButton("Neues Zeltlager anlegen", widget)
        create_button.setMinimumHeight(36)
        create_button.clicked.connect(self._create_camp_year)
        button_row.addWidget(create_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        layout.addStretch(2)
        return widget

    def _build_camp_year_content(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # Kontextzeile: welches Zeltlager, Zeitraum/Countdown/Teilnehmer, anlegen/bearbeiten.
        context_frame = QFrame(widget)
        context_frame.setStyleSheet(
            f"QFrame {{ background-color: {BG_SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; }}"
        )
        context_layout = QVBoxLayout(context_frame)

        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Zeltlager:", context_frame))
        self.camp_year_combo = QComboBox(context_frame)
        self.camp_year_combo.setMinimumWidth(220)
        self.camp_year_combo.currentIndexChanged.connect(self._on_camp_year_changed)
        selector_row.addWidget(self.camp_year_combo)
        new_button = QPushButton("Neues Zeltlager", context_frame)
        new_button.clicked.connect(self._create_camp_year)
        selector_row.addWidget(new_button)
        edit_button = QPushButton("Bearbeiten...", context_frame)
        edit_button.clicked.connect(self._edit_camp_year)
        selector_row.addWidget(edit_button)
        selector_row.addStretch(1)
        context_layout.addLayout(selector_row)

        self.countdown_label = QLabel("", context_frame)
        self.countdown_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        context_layout.addWidget(self.countdown_label)

        self.camp_info_label = QLabel("", context_frame)
        self.camp_info_label.setStyleSheet(f"color: {TEXT_MUTED};")
        self.camp_info_label.setWordWrap(True)
        context_layout.addWidget(self.camp_info_label)

        layout.addWidget(context_frame)

        # Zweispaltig: links KPIs, rechts naechste Schritte - nutzt breite Bildschirme besser aus
        # und vermeidet eine lange, einspaltige Liste, durch die man scrollen muesste.
        columns_row = QHBoxLayout()
        columns_row.setSpacing(16)
        layout.addLayout(columns_row)

        kpi_column = QVBoxLayout()
        columns_row.addLayout(kpi_column, stretch=3)
        kpi_grid = QGridLayout()
        self.kpi_plan_progress = KpiCard("Wochenplan-Fortschritt")
        self.kpi_portions = KpiCard("Geplante Portionen")
        self.kpi_budget = KpiCard("Geplantes Budget (EUR)")
        self.kpi_portion_cost = KpiCard("Ø Kosten je Portion (EUR)")
        self.kpi_missing_prices = KpiCard("Fehlende Preise")
        self.kpi_open_shopping = KpiCard("Offene Einkäufe")
        for index, card in enumerate(
            (
                self.kpi_plan_progress,
                self.kpi_portions,
                self.kpi_budget,
                self.kpi_portion_cost,
                self.kpi_missing_prices,
                self.kpi_open_shopping,
            )
        ):
            kpi_grid.addWidget(card, index // 3, index % 3)
        kpi_column.addLayout(kpi_grid)
        kpi_column.addStretch(1)

        action_column = QVBoxLayout()
        columns_row.addLayout(action_column, stretch=2)
        action_column.addWidget(self._section_title("Nächste Schritte"))
        self.action_list = QListWidget(widget)
        self.action_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.action_list.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.action_list.itemClicked.connect(self._on_action_item_clicked)
        action_column.addWidget(self.action_list, stretch=1)

        return widget

    def _build_recipe_book_section(self, layout: QVBoxLayout) -> None:
        layout.addWidget(self._section_title("Rezeptbuch & Historie", muted=True))

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

        self.camp_year_chart_view = self._make_chart_view("Kosten je Zeltlager (EUR)", legend=False)
        camp_year_row.addWidget(self.camp_year_chart_view, 1)

        camp_year_table_column = QVBoxLayout()
        camp_year_table_column.addWidget(QLabel("Zeltlager im Überblick", self))
        self.camp_year_table = QTableWidget(0, 4, self)
        self.camp_year_table.setHorizontalHeaderLabels(["Jahr", "Portionen", "Kosten (EUR)", "Ø je Portion (EUR)"])
        self.camp_year_table.verticalHeader().setVisible(False)
        self.camp_year_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        camp_year_table_column.addWidget(self.camp_year_table)
        camp_year_row.addLayout(camp_year_table_column, 1)

        layout.addLayout(camp_year_row)

    def _section_title(self, text: str, *, muted: bool = False) -> QLabel:
        label = QLabel(text, self)
        color = f"color: {TEXT_MUTED};" if muted else ""
        label.setStyleSheet(f"font-weight: 600; font-size: 15px; padding-top: 6px; {color}")
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
        view.setMinimumHeight(220)
        view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return view

    # --- Laden ---------------------------------------------------------------------------

    def refresh(self) -> None:
        self._reload_global_stats()
        self._reload_camp_year_combo()

    def _reload_camp_year_combo(self) -> None:
        self.camp_year_combo.blockSignals(True)
        self.camp_year_combo.clear()
        with self.context.session() as session:
            camp_years = session.execute(select(CampYear).order_by(CampYear.year.desc())).scalars().all()
            for camp_year in camp_years:
                self.camp_year_combo.addItem(camp_year.name or str(camp_year.year), camp_year.id)
        self.camp_year_combo.blockSignals(False)

        if not camp_years:
            self._state_stack.setCurrentIndex(0)
            return
        self._state_stack.setCurrentIndex(1)

        if self.context.current_camp_year_id is not None:
            index = self.camp_year_combo.findData(self.context.current_camp_year_id)
            if index >= 0:
                self.camp_year_combo.setCurrentIndex(index)
        self._on_camp_year_changed()

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
        self._reload_camp_year_combo()

    def _edit_camp_year(self) -> None:
        camp_year_id = self.context.current_camp_year_id
        if camp_year_id is None:
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
                "location": camp_year.location,
                "participant_count_children": camp_year.participant_count_children,
                "participant_count_adults": camp_year.participant_count_adults,
                "notes": camp_year.notes,
            }

        dialog = CampYearDialog(datetime.now().year, self, initial=initial, allow_year_edit=False)
        if dialog.exec() != CampYearDialog.DialogCode.Accepted:
            return
        data = dialog.result_data()
        data.pop("year", None)
        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)
            if camp_year is not None:
                planning_service.update_camp_year(session, camp_year, **data)
        self._reload_camp_year_combo()

    def _on_camp_year_changed(self) -> None:
        self.context.current_camp_year_id = self.camp_year_combo.currentData()
        self._reload_camp_year_details()

    def _reload_camp_year_details(self) -> None:
        camp_year_id = self.context.current_camp_year_id
        if camp_year_id is None:
            return

        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)
            if camp_year is None:
                return

            self.countdown_label.setText(self._format_countdown(camp_year))
            self.camp_info_label.setText(self._format_camp_info(camp_year))

            filled, total = planning_service.meal_plan_completeness(camp_year)
            self.kpi_plan_progress.set_value(f"{filled} / {total}" if total else "0 / 0")
            self.kpi_plan_progress.set_level("ok" if total and filled == total else "warnung" if total else "info")

            active_entries = [e for e in camp_year.meal_plan_entries if planning_service.is_active_status(e.status)]
            total_portions = sum(e.planned_portions or 0 for e in active_entries)
            self.kpi_portions.set_value(str(total_portions))

            camp_costs = {c.camp_year_id: c for c in stats_service.camp_year_costs(session)}
            cost_entry = camp_costs.get(camp_year.id)
            total_budget = cost_entry.total_cost if cost_entry else 0
            self.kpi_budget.set_value(f"{total_budget:.2f}")
            per_portion = (total_budget / total_portions) if total_portions else None
            self.kpi_portion_cost.set_value(f"{per_portion:.2f}" if per_portion else "-")

            missing_prices = price_service.missing_price_ingredients(session, year=camp_year.year)
            self.kpi_missing_prices.set_value(str(len(missing_prices)))
            self.kpi_missing_prices.set_level("kritisch" if missing_prices else "ok")

            open_items = sum(
                1
                for shopping_list in camp_year.shopping_lists
                for item in shopping_list.items
                if item.status == "offen"
            )
            self.kpi_open_shopping.set_value(str(open_items))
            self.kpi_open_shopping.set_level("warnung" if open_items else "ok")

            missing_recipe_count = sum(1 for e in active_entries if e.recipe_id is None)
            missing_portions = validation_service.find_meal_plan_without_portions(session, camp_year)
            feedback_pending = [
                entry for entry in feedback_service.list_feedback_candidates(session, camp_year) if entry.feedback is None
            ]

            self._reload_action_list(
                camp_year,
                missing_recipe_count=missing_recipe_count,
                missing_portions_count=len(missing_portions),
                missing_prices_count=len(missing_prices),
                open_shopping_count=open_items,
                feedback_pending_count=len(feedback_pending),
            )

    def _format_countdown(self, camp_year: CampYear) -> str:
        days = planning_service.days_until_start(camp_year)
        if days is None:
            return "Kein Startdatum hinterlegt."
        if camp_year.end_date and camp_year.start_date and camp_year.start_date <= date.today() <= camp_year.end_date:
            return "Das Zeltlager läuft gerade!"
        if days > 1:
            return f"Noch {days} Tage bis zum Zeltlagerstart"
        if days == 1:
            return "Zeltlager startet morgen!"
        if days == 0:
            return "Zeltlager startet heute!"
        return "Zeltlager ist beendet."

    def _format_camp_info(self, camp_year: CampYear) -> str:
        parts = []
        if camp_year.start_date and camp_year.end_date:
            parts.append(f"Zeitraum: {camp_year.start_date} bis {camp_year.end_date}")
        if camp_year.location:
            parts.append(f"Ort: {camp_year.location}")
        if camp_year.participant_count_total:
            parts.append(
                f"Teilnehmer: {camp_year.participant_count_total} "
                f"({camp_year.participant_count_children or 0} Kinder, {camp_year.participant_count_adults or 0} Erwachsene)"
            )
        else:
            parts.append("Teilnehmerzahl noch nicht hinterlegt")
        return " · ".join(parts)

    def _reload_action_list(
        self,
        camp_year: CampYear,
        *,
        missing_recipe_count: int,
        missing_portions_count: int,
        missing_prices_count: int,
        open_shopping_count: int,
        feedback_pending_count: int,
    ) -> None:
        items: list[ActionItem] = []
        if missing_recipe_count:
            items.append(
                ActionItem(f"{missing_recipe_count} Mahlzeiten ohne Rezept", "kritisch", "planning")
            )
        if missing_portions_count:
            items.append(
                ActionItem(f"{missing_portions_count} Mahlzeiten ohne Portionenzahl", "warnung", "planning")
            )
        if missing_prices_count:
            items.append(
                ActionItem(
                    f"{missing_prices_count} Zutaten ohne Preis für {camp_year.year}", "kritisch", "ingredients"
                )
            )
        if open_shopping_count:
            items.append(ActionItem(f"{open_shopping_count} offene Einkäufe", "warnung", "shopping"))
        if feedback_pending_count:
            items.append(
                ActionItem(f"{feedback_pending_count} Mahlzeiten ohne Feedback", "hinweis", "feedback")
            )

        self.action_list.clear()
        if not items:
            list_item = QListWidgetItem("Alles im grünen Bereich für dieses Zeltlager!")
            list_item.setForeground(QColor(COLOR_OK))
            self.action_list.addItem(list_item)
            return

        colors = {"kritisch": COLOR_CRITICAL, "warnung": COLOR_WARNING, "hinweis": COLOR_INFO}
        for action in items:
            nav_label = f"  ->  {_NAV_LABELS.get(action.nav_key, '')}" if action.nav_key else ""
            list_item = QListWidgetItem(f"{action.text}{nav_label}")
            list_item.setForeground(QColor(colors.get(action.level, COLOR_INFO)))
            if action.nav_key:
                list_item.setData(Qt.ItemDataRole.UserRole, action.nav_key)
            self.action_list.addItem(list_item)

    def _on_action_item_clicked(self, item: QListWidgetItem) -> None:
        nav_key = item.data(Qt.ItemDataRole.UserRole)
        if nav_key:
            self.navigate_requested.emit(nav_key)

    # --- Rezeptbuch & Historie (global, alle Zeltlager) -----------------------------------

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
