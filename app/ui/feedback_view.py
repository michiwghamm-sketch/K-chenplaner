from __future__ import annotations

from decimal import Decimal

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.context import AppContext
from app.models import CampYear, MealPlanEntry
from app.services import feedback_service
from app.ui.dialogs import error_dialog, info_dialog
from app.ui.theme import TEXT_MUTED
from app.ui.widgets import COLOR_OK, PageHeader

REPEAT_OPTIONS = ("Unbekannt", "Ja", "Nein")


class FeedbackView(QWidget):
    """Feedback: Wochenplan eines Camp-Jahrs durchgehen und je Mahlzeit Rückmeldung erfassen."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._current_entry_id: int | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            PageHeader("Feedback", "Wochenplan durchgehen und je Mahlzeit Feedback erfassen")
        )

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Camp-Jahr:", self))
        self.camp_year_combo = QComboBox(self)
        self.camp_year_combo.currentIndexChanged.connect(self._on_camp_year_changed)
        top_row.addWidget(self.camp_year_combo)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        splitter = QSplitter(self)
        layout.addWidget(splitter, stretch=1)

        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Mahlzeiten im Wochenplan", left))
        self.meal_table = QTableWidget(0, 4, left)
        self.meal_table.setHorizontalHeaderLabels(["Datum", "Mahlzeit", "Rezept", "Feedback"])
        self.meal_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.meal_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.meal_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.meal_table.itemSelectionChanged.connect(self._on_meal_selected)
        left_layout.addWidget(self.meal_table)
        splitter.addWidget(left)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)

        self.meal_info_label = QLabel("Bitte links eine Mahlzeit auswählen.", right)
        self.meal_info_label.setStyleSheet("font-weight: 600; font-size: 15px;")
        right_layout.addWidget(self.meal_info_label)

        form = QFormLayout()
        self.rating_spin = QSpinBox(right)
        self.rating_spin.setRange(1, 5)
        self.quantity_sufficient_combo = QComboBox(right)
        self.quantity_sufficient_combo.addItems(feedback_service.QUANTITY_SUFFICIENT_OPTIONS)
        self.cooked_spin = QSpinBox(right)
        self.cooked_spin.setRange(0, 2000)
        self.cooked_spin.valueChanged.connect(self._update_factor_preview)
        self.factor_line = QLineEdit(right)
        self.factor_line.setReadOnly(True)
        self.leftover_qty_spin = QDoubleSpinBox(right)
        self.leftover_qty_spin.setDecimals(3)
        self.leftover_qty_spin.setRange(0, 100000)
        self.leftover_unit_edit = QLineEdit(right)
        self.repeat_combo = QComboBox(right)
        self.repeat_combo.addItems(REPEAT_OPTIONS)
        self.process_tips_edit = QPlainTextEdit(right)
        self.process_tips_edit.setFixedHeight(50)
        self.what_went_well_edit = QPlainTextEdit(right)
        self.what_went_well_edit.setFixedHeight(50)
        self.what_to_change_edit = QPlainTextEdit(right)
        self.what_to_change_edit.setFixedHeight(50)

        form.addRow("Wie kam es an? (1-5)", self.rating_spin)
        form.addRow("Hat die Menge gereicht?", self.quantity_sufficient_combo)
        form.addRow("Portionen gekocht", self.cooked_spin)
        form.addRow("Mengenfaktor nächstes Mal", self.factor_line)
        form.addRow("Restmenge", self.leftover_qty_spin)
        form.addRow("Einheit Rest", self.leftover_unit_edit)
        form.addRow("Wiederholen?", self.repeat_combo)
        form.addRow("Ablauf-Tipps/Tricks", self.process_tips_edit)
        form.addRow("Was lief gut?", self.what_went_well_edit)
        form.addRow("Was ändern?", self.what_to_change_edit)
        right_layout.addLayout(form)

        save_button = QPushButton("Feedback speichern", right)
        save_button.clicked.connect(self._save_feedback)
        right_layout.addWidget(save_button)

        self._set_form_enabled(False)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

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
        self._reload_meal_list()

    def _reload_meal_list(self) -> None:
        self.meal_table.setRowCount(0)
        self._current_entry_id = None
        self._clear_form()
        self._set_form_enabled(False)

        camp_year_id = self.context.current_camp_year_id
        if camp_year_id is None:
            return

        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)
            if camp_year is None:
                return
            for entry in feedback_service.list_feedback_candidates(session, camp_year):
                row = self.meal_table.rowCount()
                self.meal_table.insertRow(row)
                date_item = QTableWidgetItem(entry.meal_date.isoformat() if entry.meal_date else "")
                date_item.setData(1000, entry.id)
                self.meal_table.setItem(row, 0, date_item)
                self.meal_table.setItem(row, 1, QTableWidgetItem(entry.meal_type or ""))
                self.meal_table.setItem(row, 2, QTableWidgetItem(entry.recipe.name if entry.recipe else ""))

                has_feedback = entry.feedback is not None and entry.feedback.rating is not None
                status_item = QTableWidgetItem("Erledigt" if has_feedback else "Offen")
                status_item.setForeground(QColor(COLOR_OK if has_feedback else TEXT_MUTED))
                self.meal_table.setItem(row, 3, status_item)

    def _on_meal_selected(self) -> None:
        row = self.meal_table.currentRow()
        if row < 0:
            self._current_entry_id = None
            self._clear_form()
            self._set_form_enabled(False)
            return

        self._current_entry_id = self.meal_table.item(row, 0).data(1000)
        with self.context.session() as session:
            entry = session.get(MealPlanEntry, self._current_entry_id)
            if entry is None:
                return
            date_text = entry.meal_date.isoformat() if entry.meal_date else "ohne Datum"
            self.meal_info_label.setText(
                f"{entry.recipe.name if entry.recipe else '-'} - {entry.meal_type} am {date_text} "
                f"(geplant: {entry.planned_portions or '-'} Portionen)"
            )
            feedback = entry.feedback
            self.rating_spin.setValue(feedback.rating if feedback and feedback.rating else 1)
            quantity_index = self.quantity_sufficient_combo.findText(
                feedback.quantity_sufficient if feedback and feedback.quantity_sufficient else "Unbekannt"
            )
            self.quantity_sufficient_combo.setCurrentIndex(quantity_index if quantity_index >= 0 else 0)
            self.cooked_spin.setValue(feedback.cooked_portions if feedback and feedback.cooked_portions else 0)
            self.leftover_qty_spin.setValue(float(feedback.leftover_quantity) if feedback and feedback.leftover_quantity else 0)
            self.leftover_unit_edit.setText(feedback.leftover_unit if feedback and feedback.leftover_unit else "")
            repeat_text = "Unbekannt"
            if feedback and feedback.repeat_next_time is True:
                repeat_text = "Ja"
            elif feedback and feedback.repeat_next_time is False:
                repeat_text = "Nein"
            self.repeat_combo.setCurrentIndex(self.repeat_combo.findText(repeat_text))
            self.process_tips_edit.setPlainText(feedback.process_tips if feedback else "")
            self.what_went_well_edit.setPlainText(feedback.what_went_well if feedback else "")
            self.what_to_change_edit.setPlainText(feedback.what_to_change if feedback else "")
        self._set_form_enabled(True)
        self._update_factor_preview()

    def _clear_form(self) -> None:
        self.meal_info_label.setText("Bitte links eine Mahlzeit auswählen.")
        self.rating_spin.setValue(1)
        self.quantity_sufficient_combo.setCurrentIndex(0)
        self.cooked_spin.setValue(0)
        self.leftover_qty_spin.setValue(0)
        self.leftover_unit_edit.clear()
        self.repeat_combo.setCurrentIndex(0)
        self.process_tips_edit.clear()
        self.what_went_well_edit.clear()
        self.what_to_change_edit.clear()
        self.factor_line.clear()

    def _set_form_enabled(self, enabled: bool) -> None:
        for widget in (
            self.rating_spin,
            self.quantity_sufficient_combo,
            self.cooked_spin,
            self.leftover_qty_spin,
            self.leftover_unit_edit,
            self.repeat_combo,
            self.process_tips_edit,
            self.what_went_well_edit,
            self.what_to_change_edit,
        ):
            widget.setEnabled(enabled)

    def _update_factor_preview(self) -> None:
        if self._current_entry_id is None:
            self.factor_line.setText("-")
            return
        with self.context.session() as session:
            entry = session.get(MealPlanEntry, self._current_entry_id)
            planned = entry.planned_portions if entry else None
        factor = feedback_service.calculate_quantity_factor(planned, self.cooked_spin.value())
        self.factor_line.setText(str(factor) if factor is not None else "-")

    def _save_feedback(self) -> None:
        if self._current_entry_id is None:
            error_dialog(self, "Bitte zuerst eine Mahlzeit auswählen.")
            return

        repeat_value = self.repeat_combo.currentText()
        repeat_next_time = {"Ja": True, "Nein": False}.get(repeat_value)
        quantity_sufficient = self.quantity_sufficient_combo.currentText()

        with self.context.session() as session:
            entry = session.get(MealPlanEntry, self._current_entry_id)
            if entry is None:
                return
            try:
                feedback_service.save_meal_feedback(
                    session,
                    entry,
                    rating=self.rating_spin.value(),
                    repeat_next_time=repeat_next_time,
                    quantity_sufficient=quantity_sufficient if quantity_sufficient != "Unbekannt" else None,
                    cooked_portions=self.cooked_spin.value() or None,
                    leftover_quantity=Decimal(str(self.leftover_qty_spin.value())) if self.leftover_qty_spin.value() else None,
                    leftover_unit=self.leftover_unit_edit.text().strip() or None,
                    process_tips=self.process_tips_edit.toPlainText().strip() or None,
                    what_went_well=self.what_went_well_edit.toPlainText().strip() or None,
                    what_to_change=self.what_to_change_edit.toPlainText().strip() or None,
                )
            except ValueError as exc:
                error_dialog(self, str(exc))
                return
        info_dialog(self, "Feedback gespeichert.")
        saved_entry_id = self._current_entry_id
        self._reload_meal_list()
        self._select_meal_by_entry_id(saved_entry_id)

    def _select_meal_by_entry_id(self, entry_id: int | None) -> None:
        if entry_id is None:
            return
        for row in range(self.meal_table.rowCount()):
            if self.meal_table.item(row, 0).data(1000) == entry_id:
                self.meal_table.setCurrentCell(row, 0)
                return
