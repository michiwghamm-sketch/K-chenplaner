from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
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
from app.models import CampYear, Recipe
from app.services import feedback_service
from app.ui.dialogs import error_dialog, info_dialog

REPEAT_OPTIONS = ("Unbekannt", "Ja", "Nein")


class FeedbackView(QWidget):
    """Rezeptfeedback: Historie je Rezept und Erfassung neuer Rueckmeldungen."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self.recipe_combo = QComboBox(self)
        self.recipe_combo.currentIndexChanged.connect(self._reload_history)
        top_row.addWidget(self.recipe_combo)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        self.history_table = QTableWidget(0, 8, self)
        self.history_table.setHorizontalHeaderLabels(
            ["Jahr", "Bewertung", "Wiederholen", "Geplant", "Gekocht", "Rest", "Faktor", "Tipps"]
        )
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.history_table)

        form = QFormLayout()
        self.camp_year_combo = QComboBox(self)
        self.rating_spin = QSpinBox(self)
        self.rating_spin.setRange(1, 5)
        self.repeat_combo = QComboBox(self)
        self.repeat_combo.addItems(REPEAT_OPTIONS)
        self.planned_spin = QSpinBox(self)
        self.planned_spin.setRange(0, 2000)
        self.planned_spin.valueChanged.connect(self._update_factor_preview)
        self.cooked_spin = QSpinBox(self)
        self.cooked_spin.setRange(0, 2000)
        self.cooked_spin.valueChanged.connect(self._update_factor_preview)
        self.factor_line = QLineEdit(self)
        self.factor_line.setReadOnly(True)
        self.leftover_qty_spin = QDoubleSpinBox(self)
        self.leftover_qty_spin.setDecimals(3)
        self.leftover_qty_spin.setRange(0, 100000)
        self.leftover_unit_edit = QLineEdit(self)
        self.process_tips_edit = QPlainTextEdit(self)
        self.process_tips_edit.setFixedHeight(50)
        self.what_went_well_edit = QPlainTextEdit(self)
        self.what_went_well_edit.setFixedHeight(50)
        self.what_to_change_edit = QPlainTextEdit(self)
        self.what_to_change_edit.setFixedHeight(50)

        form.addRow("Camp-Jahr", self.camp_year_combo)
        form.addRow("Bewertung (1-5)", self.rating_spin)
        form.addRow("Wiederholen?", self.repeat_combo)
        form.addRow("Portionen geplant", self.planned_spin)
        form.addRow("Portionen gekocht", self.cooked_spin)
        form.addRow("Mengenfaktor naechstes Mal", self.factor_line)
        form.addRow("Restmenge", self.leftover_qty_spin)
        form.addRow("Einheit Rest", self.leftover_unit_edit)
        form.addRow("Ablauf-Tipps/Tricks", self.process_tips_edit)
        form.addRow("Was lief gut?", self.what_went_well_edit)
        form.addRow("Was aendern?", self.what_to_change_edit)
        layout.addLayout(form)

        save_button = QPushButton("Feedback speichern", self)
        save_button.clicked.connect(self._save_feedback)
        layout.addWidget(save_button)

    def refresh(self) -> None:
        self.recipe_combo.blockSignals(True)
        self.recipe_combo.clear()
        self.camp_year_combo.clear()
        with self.context.session() as session:
            recipes = session.execute(select(Recipe).where(Recipe.active.is_(True)).order_by(Recipe.name)).scalars().all()
            for recipe in recipes:
                self.recipe_combo.addItem(recipe.name, recipe.id)
            camp_years = session.execute(select(CampYear).order_by(CampYear.year.desc())).scalars().all()
            for camp_year in camp_years:
                self.camp_year_combo.addItem(camp_year.name or str(camp_year.year), camp_year.id)
        self.recipe_combo.blockSignals(False)
        self._reload_history()

    def _reload_history(self) -> None:
        self.history_table.setRowCount(0)
        recipe_id = self.recipe_combo.currentData()
        if recipe_id is None:
            return
        with self.context.session() as session:
            recipe = session.get(Recipe, recipe_id)
            if recipe is None:
                return
            for entry in feedback_service.recipe_feedback_history(recipe):
                row = self.history_table.rowCount()
                self.history_table.insertRow(row)
                self.history_table.setItem(row, 0, QTableWidgetItem(str(entry.camp_year.year) if entry.camp_year else ""))
                self.history_table.setItem(row, 1, QTableWidgetItem(str(entry.rating) if entry.rating else ""))
                repeat_text = "Ja" if entry.repeat_next_time else ("Nein" if entry.repeat_next_time is False else "")
                self.history_table.setItem(row, 2, QTableWidgetItem(repeat_text))
                self.history_table.setItem(row, 3, QTableWidgetItem(str(entry.planned_portions or "")))
                self.history_table.setItem(row, 4, QTableWidgetItem(str(entry.cooked_portions or "")))
                leftover = f"{entry.leftover_quantity} {entry.leftover_unit or ''}".strip() if entry.leftover_quantity else ""
                self.history_table.setItem(row, 5, QTableWidgetItem(leftover))
                self.history_table.setItem(row, 6, QTableWidgetItem(str(entry.quantity_factor_next_time or "")))
                self.history_table.setItem(row, 7, QTableWidgetItem(entry.process_tips or ""))

    def _update_factor_preview(self) -> None:
        factor = feedback_service.calculate_quantity_factor(self.planned_spin.value(), self.cooked_spin.value())
        self.factor_line.setText(str(factor) if factor is not None else "-")

    def _save_feedback(self) -> None:
        recipe_id = self.recipe_combo.currentData()
        camp_year_id = self.camp_year_combo.currentData()
        if recipe_id is None or camp_year_id is None:
            error_dialog(self, "Bitte Rezept und Camp-Jahr auswaehlen.")
            return

        repeat_value = self.repeat_combo.currentText()
        repeat_next_time = {"Ja": True, "Nein": False}.get(repeat_value)

        with self.context.session() as session:
            recipe = session.get(Recipe, recipe_id)
            camp_year = session.get(CampYear, camp_year_id)
            try:
                feedback_service.record_feedback(
                    session,
                    camp_year=camp_year,
                    recipe=recipe,
                    rating=self.rating_spin.value(),
                    repeat_next_time=repeat_next_time,
                    planned_portions=self.planned_spin.value() or None,
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
        self._reload_history()
