from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
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
from app.models import CampYear, ShoppingList, ShoppingListItem
from app.services import export_service, shopping_service
from app.ui.dialogs import error_dialog, info_dialog
from app.ui.widgets import COLOR_CRITICAL


class ShoppingView(QWidget):
    """Einkaufsliste: Generierung aus der Jahresplanung, Statuspflege, Export."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self.camp_year_combo = QComboBox(self)
        self.camp_year_combo.currentIndexChanged.connect(self._on_camp_year_changed)
        top_row.addWidget(self.camp_year_combo)

        generate_button = QPushButton("Einkaufsliste generieren", self)
        generate_button.clicked.connect(self._generate_list)
        top_row.addWidget(generate_button)

        self.list_combo = QComboBox(self)
        self.list_combo.currentIndexChanged.connect(self._reload_table)
        top_row.addWidget(self.list_combo)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        self.total_label = QLabel("Gesamtsumme: -", self)
        layout.addWidget(self.total_label)

        self.table = QTableWidget(0, 9, self)
        self.table.setHorizontalHeaderLabels(
            ["Zutat", "Menge", "Einheit", "Preis/Einheit", "Gesamtpreis", "Kategorie", "Einkaufstag", "Status", "Rezepte"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        export_row = QHBoxLayout()
        export_csv_button = QPushButton("Export als CSV", self)
        export_csv_button.clicked.connect(self._export_csv)
        export_excel_button = QPushButton("Export als Excel", self)
        export_excel_button.clicked.connect(self._export_excel)
        export_row.addWidget(export_csv_button)
        export_row.addWidget(export_excel_button)
        export_row.addStretch(1)
        layout.addLayout(export_row)

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
        self._reload_list_combo()

    def _reload_list_combo(self) -> None:
        self.list_combo.blockSignals(True)
        self.list_combo.clear()
        camp_year_id = self.context.current_camp_year_id
        if camp_year_id is not None:
            with self.context.session() as session:
                camp_year = session.get(CampYear, camp_year_id)
                if camp_year is not None:
                    for shopping_list in sorted(camp_year.shopping_lists, key=lambda s: s.generated_at, reverse=True):
                        label = f"{shopping_list.name} ({shopping_list.generated_at:%Y-%m-%d %H:%M})"
                        self.list_combo.addItem(label, shopping_list.id)
        self.list_combo.blockSignals(False)
        self._reload_table()

    def _reload_table(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        shopping_list_id = self.list_combo.currentData()
        if shopping_list_id is None:
            self.total_label.setText("Gesamtsumme: -")
            self.table.setSortingEnabled(True)
            return
        with self.context.session() as session:
            shopping_list = session.get(ShoppingList, shopping_list_id)
            if shopping_list is None:
                self.table.setSortingEnabled(True)
                return
            for item in shopping_list.items:
                row = self.table.rowCount()
                self.table.insertRow(row)
                name_item = QTableWidgetItem(item.ingredient.name if item.ingredient else "")
                name_item.setData(1000, item.id)
                self.table.setItem(row, 0, name_item)
                self.table.setItem(row, 1, QTableWidgetItem(str(item.quantity)))
                self.table.setItem(row, 2, QTableWidgetItem(item.unit or ""))
                price_item = QTableWidgetItem(str(item.estimated_price_per_unit) if item.estimated_price_per_unit is not None else "fehlt")
                if item.estimated_price_per_unit is None:
                    price_item.setForeground(QColor(COLOR_CRITICAL))
                self.table.setItem(row, 3, price_item)
                self.table.setItem(row, 4, QTableWidgetItem(str(item.estimated_total_price or "")))
                self.table.setItem(row, 5, QTableWidgetItem(item.category or ""))
                self.table.setItem(row, 6, QTableWidgetItem(item.shopping_date.isoformat() if item.shopping_date else ""))

                status_combo = QComboBox()
                status_combo.addItems(shopping_service.ALLOWED_ITEM_STATUSES)
                status_combo.setCurrentText(item.status or "offen")
                status_combo.currentTextChanged.connect(lambda status, item_id=item.id: self._update_status(item_id, status))
                self.table.setCellWidget(row, 7, status_combo)

                self.table.setItem(row, 8, QTableWidgetItem(item.linked_recipes_text or ""))

            self.total_label.setText(f"Gesamtsumme: {shopping_service.total_estimated_cost(shopping_list)} EUR")
        self.table.setSortingEnabled(True)

    def _update_status(self, item_id: int, status: str) -> None:
        with self.context.session() as session:
            item = session.get(ShoppingListItem, item_id)
            if item is not None:
                shopping_service.set_item_status(item, status)

    def _generate_list(self) -> None:
        camp_year_id = self.context.current_camp_year_id
        if camp_year_id is None:
            error_dialog(self, "Bitte zuerst ein Camp-Jahr in der Jahresplanung auswaehlen.")
            return
        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)
            shopping_list = shopping_service.generate_shopping_list(session, camp_year)
            session.flush()
            item_count = len(shopping_list.items)
        info_dialog(self, f"Einkaufsliste mit {item_count} Positionen erstellt.")
        self._reload_list_combo()

    def _export_csv(self) -> None:
        self._export(export_service.export_shopping_list_to_csv, "CSV-Dateien (*.csv)", ".csv")

    def _export_excel(self) -> None:
        self._export(export_service.export_shopping_list_to_excel, "Excel-Dateien (*.xlsx)", ".xlsx")

    def _export(self, export_function, file_filter: str, suffix: str) -> None:
        shopping_list_id = self.list_combo.currentData()
        if shopping_list_id is None:
            error_dialog(self, "Es ist keine Einkaufsliste ausgewaehlt.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Einkaufsliste exportieren", f"einkaufsliste{suffix}", file_filter)
        if not path:
            return
        with self.context.session() as session:
            shopping_list = session.get(ShoppingList, shopping_list_id)
            export_function(shopping_list, Path(path))
        info_dialog(self, f"Einkaufsliste exportiert nach:\n{path}")
