from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.context import AppContext
from app.services import ingredient_service, price_service
from app.ui.dialogs import AddPriceDialog, error_dialog, info_dialog, prompt_int
from app.ui.widgets import COLOR_CRITICAL


class PricesView(QWidget):
    """Preisverwaltung: aktuelle Preise je Zutat, fehlende Preise, Jahresuebernahme."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Jahr:", self))
        self.year_spin = QSpinBox(self)
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setValue(datetime.now().year)
        self.year_spin.valueChanged.connect(self.refresh)
        top_row.addWidget(self.year_spin)

        add_button = QPushButton("Preis erfassen", self)
        add_button.clicked.connect(self._add_price)
        copy_button = QPushButton("Preise aus Vorjahr uebernehmen", self)
        copy_button.clicked.connect(self._copy_from_previous_year)
        top_row.addWidget(add_button)
        top_row.addWidget(copy_button)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        self.missing_label = QLabel("", self)
        layout.addWidget(self.missing_label)

        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(["Zutat", "Preis", "Einheit", "Quelle", "Laden", "Notizen"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

    def refresh(self) -> None:
        year = self.year_spin.value()
        with self.context.session() as session:
            ingredients = ingredient_service.search_ingredients(session)
            missing = price_service.missing_price_ingredients(session, year=year)

            self.table.setSortingEnabled(False)
            self.table.setRowCount(0)
            for ingredient in ingredients:
                price = next((p for p in ingredient.prices if p.year == year), None)
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(ingredient.name))
                if price is None:
                    price_item = QTableWidgetItem("fehlt")
                    price_item.setForeground(QColor(COLOR_CRITICAL))
                    self.table.setItem(row, 1, price_item)
                    for col in (2, 3, 4, 5):
                        self.table.setItem(row, col, QTableWidgetItem(""))
                else:
                    self.table.setItem(row, 1, QTableWidgetItem(str(price.price_per_unit)))
                    self.table.setItem(row, 2, QTableWidgetItem(price.unit))
                    self.table.setItem(row, 3, QTableWidgetItem(price.source or ""))
                    self.table.setItem(row, 4, QTableWidgetItem(price.store or ""))
                    self.table.setItem(row, 5, QTableWidgetItem(price.notes or ""))
            self.table.setSortingEnabled(True)

        if missing:
            names = ", ".join(i.name for i in missing[:10])
            suffix = " ..." if len(missing) > 10 else ""
            self.missing_label.setText(f"Fehlende Preise fuer {year} ({len(missing)}): {names}{suffix}")
            self.missing_label.setStyleSheet(f"color: {COLOR_CRITICAL};")
        else:
            self.missing_label.setText(f"Alle aktiven Zutaten haben einen Preis fuer {year}.")
            self.missing_label.setStyleSheet("")

    def _add_price(self) -> None:
        with self.context.session() as session:
            ingredients = [(i.id, i.name) for i in ingredient_service.search_ingredients(session)]
        if not ingredients:
            error_dialog(self, "Es sind noch keine Zutaten angelegt.")
            return

        dialog = AddPriceDialog(ingredients, self.year_spin.value(), self)
        if dialog.exec() != AddPriceDialog.DialogCode.Accepted:
            return
        data = dialog.result_data()
        if data is None:
            error_dialog(self, "Bitte gueltige Werte angeben.")
            return

        with self.context.session() as session:
            from app.models import IngredientPrice

            session.add(IngredientPrice(**data))
        self.refresh()

    def _copy_from_previous_year(self) -> None:
        target_year = self.year_spin.value()
        source_year = prompt_int(self, "Preise uebernehmen", "Quelljahr:", default=target_year - 1, minimum=2000, maximum=2100)
        if source_year is None:
            return
        with self.context.session() as session:
            copied = price_service.copy_prices_from_year(session, source_year=source_year, target_year=target_year)
        info_dialog(self, f"{copied} Preise aus {source_year} nach {target_year} uebernommen.")
        self.refresh()
