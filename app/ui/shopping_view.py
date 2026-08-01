from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
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
from app.ui.dialogs import confirm_dialog, error_dialog, info_dialog
from app.ui.theme import ORANGE
from app.ui.widgets import COLOR_CRITICAL, PageHeader

SHOPPING_TABLE_COLUMNS = (
    "Zutat", "Gesamtmenge", "Einheit", "Preis je Einheit", "Gesamtpreis Position", "Haendler",
    "Bedarfsdatum", "Einkaufstag", "Status", "Rezepte",
)
GROUP_MODES = (("Keine Gruppierung", "none"), ("Nach Einkaufstag", "day"), ("Nach Händler", "store"))


class ShoppingView(QWidget):
    """Einkaufsliste: Generierung aus der Jahresplanung, Statuspflege, Export."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._known_stores: list[str] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(PageHeader("Einkaufsliste", "Aus der Jahresplanung generierte Einkaufsliste"))

        top_row = QHBoxLayout()
        self.camp_year_combo = QComboBox(self)
        self.camp_year_combo.currentIndexChanged.connect(self._on_camp_year_changed)
        top_row.addWidget(self.camp_year_combo)

        generate_button = QPushButton("Einkaufsliste generieren", self)
        generate_button.clicked.connect(self._generate_list)
        top_row.addWidget(generate_button)

        self.total_list_checkbox = QCheckBox("Gesamtliste (ohne Einkaufstage)", self)
        self.total_list_checkbox.setToolTip(
            "Erzeugt eine Gesamtliste ohne Aufteilung nach Einkaufstagen - "
            "das Bedarfsdatum je Zutat wird trotzdem angezeigt."
        )
        top_row.addWidget(self.total_list_checkbox)

        self.list_combo = QComboBox(self)
        self.list_combo.currentIndexChanged.connect(self._reload_table)
        top_row.addWidget(self.list_combo)

        delete_button = QPushButton("Einkaufsliste löschen", self)
        delete_button.setProperty("role", "secondary")
        delete_button.clicked.connect(self._delete_list)
        top_row.addWidget(delete_button)

        top_row.addStretch(1)
        layout.addLayout(top_row)

        group_row = QHBoxLayout()
        group_row.addWidget(QLabel("Anzeige:", self))
        self.group_combo = QComboBox(self)
        for label, mode in GROUP_MODES:
            self.group_combo.addItem(label, mode)
        self.group_combo.currentIndexChanged.connect(self._reload_table)
        group_row.addWidget(self.group_combo)
        group_row.addStretch(1)
        self.total_label = QLabel("Gesamtsumme: -", self)
        group_row.addWidget(self.total_label)
        layout.addLayout(group_row)

        self.table = QTableWidget(0, len(SHOPPING_TABLE_COLUMNS), self)
        self.table.setHorizontalHeaderLabels(list(SHOPPING_TABLE_COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        export_row = QHBoxLayout()
        export_csv_button = QPushButton("Export als CSV", self)
        export_csv_button.clicked.connect(self._export_csv)
        export_excel_button = QPushButton("Export als Excel", self)
        export_excel_button.clicked.connect(self._export_excel)
        export_pdf_button = QPushButton("Als PDF-Checkliste exportieren", self)
        export_pdf_button.clicked.connect(self._export_pdf)
        export_row.addWidget(export_csv_button)
        export_row.addWidget(export_excel_button)
        export_row.addWidget(export_pdf_button)
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
                        label = f"{shopping_list.name} ({shopping_list.generated_at:%d.%m.%Y %H:%M})"
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
        mode = self.group_combo.currentData()
        with self.context.session() as session:
            shopping_list = session.get(ShoppingList, shopping_list_id)
            if shopping_list is None:
                self.table.setSortingEnabled(True)
                return
            self._known_stores = shopping_service.list_known_stores(session)

            if mode == "day":
                for shopping_date, items in shopping_service.grouped_by_day_ordered(shopping_list):
                    self._add_band_row(shopping_service.format_shopping_day_label(shopping_date), items)
                    for item in items:
                        self._add_item_row(item)
            elif mode == "store":
                for store, items in shopping_service.grouped_by_store_ordered(shopping_list):
                    self._add_band_row(store or shopping_service.UNASSIGNED_STORE_LABEL, items)
                    for item in items:
                        self._add_item_row(item)
            else:
                for item in _aggregate_total_view_items(shopping_list.items):
                    self._add_item_row(item, editable=False)

            self.total_label.setText(
                f"Gesamtpreis Einkauf: {_format_money(shopping_service.total_estimated_cost(shopping_list))}"
            )
        # Sortieren wuerde die Gruppen-Baender und ihre Zeilen auseinanderreissen.
        self.table.setSortingEnabled(mode == "none")

    def _add_band_row(self, label: str, items: list[ShoppingListItem] | None = None) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setSpan(row, 0, 1, len(SHOPPING_TABLE_COLUMNS))
        total_text = ""
        if items is not None:
            total_text = f" | Gesamt: {_format_money(shopping_service.total_items_estimated_cost(items))}"
        band_label = QLabel(f"  {label}{total_text}", self.table)
        band_label.setStyleSheet(f"background-color: {ORANGE}; color: white; font-weight: 600; padding: 5px;")
        self.table.setCellWidget(row, 0, band_label)

    def _add_item_row(self, item: ShoppingListItem, *, editable: bool = True) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        name_item = QTableWidgetItem(item.ingredient.name if item.ingredient else "")
        name_item.setData(1000, item.id)
        self.table.setItem(row, 0, name_item)
        self.table.setItem(row, 1, QTableWidgetItem(_format_decimal(item.quantity)))
        self.table.setItem(row, 2, QTableWidgetItem(item.unit or ""))
        price_item = QTableWidgetItem(
            _format_money(item.estimated_price_per_unit) if item.estimated_price_per_unit is not None else "fehlt"
        )
        if item.estimated_price_per_unit is None:
            price_item.setForeground(QColor(COLOR_CRITICAL))
        self.table.setItem(row, 3, price_item)
        self.table.setItem(row, 4, QTableWidgetItem(_format_money(item.estimated_total_price) if item.estimated_total_price is not None else ""))

        if editable:
            store_combo = QComboBox()
            store_combo.setEditable(True)
            store_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            store_combo.addItem("")
            store_combo.addItems(self._known_stores)
            store_combo.setCurrentText(item.store or "")
            store_combo.lineEdit().setPlaceholderText("Haendler...")
            # editingFinished deckt frei getippten Text ab (Verlassen des Feldes/Enter),
            # activated das Auswaehlen eines Vorschlags aus der Dropdown-Liste per Klick - beides
            # soll sofort speichern, ohne bei jedem Tastenanschlag einen DB-Schreibzugriff
            # auszuloesen (anders als z. B. currentTextChanged).
            store_combo.lineEdit().editingFinished.connect(
                lambda item_id=item.id, combo=store_combo: self._update_store(item_id, combo.currentText())
            )
            store_combo.activated.connect(
                lambda _index, item_id=item.id, combo=store_combo: self._update_store(item_id, combo.currentText())
            )
            self.table.setCellWidget(row, 5, store_combo)
        else:
            self.table.setItem(row, 5, QTableWidgetItem(item.store or ""))

        self.table.setItem(row, 6, QTableWidgetItem(shopping_service.format_date_de(item.needed_date)))
        self.table.setItem(row, 7, QTableWidgetItem(shopping_service.format_date_de(item.shopping_date)))

        if editable:
            status_combo = QComboBox()
            status_combo.addItems(shopping_service.ALLOWED_ITEM_STATUSES)
            status_combo.setCurrentText(item.status or "offen")
            status_combo.currentTextChanged.connect(lambda status, item_id=item.id: self._update_status(item_id, status))
            self.table.setCellWidget(row, 8, status_combo)
        else:
            self.table.setItem(row, 8, QTableWidgetItem(item.status or ""))

        self.table.setItem(row, 9, QTableWidgetItem(item.linked_recipes_text or ""))

    def _update_status(self, item_id: int, status: str) -> None:
        with self.context.session() as session:
            item = session.get(ShoppingListItem, item_id)
            if item is not None:
                shopping_service.set_item_status(item, status)

    def _update_store(self, item_id: int, store: str) -> None:
        with self.context.session() as session:
            item = session.get(ShoppingListItem, item_id)
            if item is not None:
                shopping_service.set_item_store(item, store)

    def _generate_list(self) -> None:
        camp_year_id = self.context.current_camp_year_id
        if camp_year_id is None:
            error_dialog(self, "Bitte zuerst ein Camp-Jahr in der Jahresplanung auswählen.")
            return
        assign_shopping_dates = not self.total_list_checkbox.isChecked()
        with self.context.session() as session:
            camp_year = session.get(CampYear, camp_year_id)
            shopping_list = shopping_service.generate_shopping_list(
                session, camp_year, assign_shopping_dates=assign_shopping_dates
            )
            session.flush()
            item_count = len(shopping_list.items)
        info_dialog(self, f"Einkaufsliste mit {item_count} Positionen erstellt.")
        self._reload_list_combo()

    def _delete_list(self) -> None:
        shopping_list_id = self.list_combo.currentData()
        if shopping_list_id is None:
            error_dialog(self, "Es ist keine Einkaufsliste ausgewählt.")
            return
        label = self.list_combo.currentText()
        if not confirm_dialog(self, "Einkaufsliste löschen", f"'{label}' wirklich unwiderruflich löschen?"):
            return
        with self.context.session() as session:
            shopping_list = session.get(ShoppingList, shopping_list_id)
            if shopping_list is not None:
                shopping_service.delete_shopping_list(session, shopping_list)
        self._reload_list_combo()

    def _export_csv(self) -> None:
        self._export(export_service.export_shopping_list_to_csv, "CSV-Dateien (*.csv)", ".csv")

    def _export_excel(self) -> None:
        self._export(export_service.export_shopping_list_to_excel, "Excel-Dateien (*.xlsx)", ".xlsx")

    def _export_pdf(self) -> None:
        group_by = self.group_combo.currentData()
        self._export(
            lambda shopping_list, path: export_service.export_shopping_list_to_pdf(shopping_list, path, group_by=group_by),
            "PDF-Dateien (*.pdf)",
            ".pdf",
        )

    def _export(self, export_function, file_filter: str, suffix: str) -> None:
        shopping_list_id = self.list_combo.currentData()
        if shopping_list_id is None:
            error_dialog(self, "Es ist keine Einkaufsliste ausgewählt.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Einkaufsliste exportieren", f"einkaufsliste{suffix}", file_filter)
        if not path:
            return
        with self.context.session() as session:
            shopping_list = session.get(ShoppingList, shopping_list_id)
            export_function(shopping_list, Path(path))
        info_dialog(self, f"Einkaufsliste exportiert nach:\n{path}")


def _format_decimal(value: Decimal) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _format_money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))} EUR"


def _aggregate_total_view_items(items) -> list:
    grouped = defaultdict(list)
    for item in items:
        grouped[(item.ingredient_id, item.unit)].append(item)

    aggregated = []
    for (_ingredient_id, unit), group in grouped.items():
        first = group[0]
        quantity = sum((item.quantity or Decimal("0") for item in group), Decimal("0")).quantize(Decimal("0.001"))
        total = sum((item.estimated_total_price or Decimal("0") for item in group), Decimal("0")).quantize(Decimal("0.01"))
        has_complete_prices = all(item.estimated_total_price is not None for item in group)
        price_per_unit = (total / quantity).quantize(Decimal("0.0001")) if has_complete_prices and quantity else None
        recipe_names = sorted(
            {
                recipe.strip()
                for item in group
                for recipe in (item.linked_recipes_text or "").split(",")
                if recipe.strip()
            }
        )
        statuses = {item.status for item in group if item.status}
        stores = {item.store for item in group if item.store}
        aggregated.append(
            SimpleNamespace(
                id=first.id,
                ingredient=first.ingredient,
                ingredient_id=first.ingredient_id,
                quantity=quantity,
                unit=unit,
                estimated_price_per_unit=price_per_unit,
                estimated_total_price=total if has_complete_prices else None,
                store=", ".join(sorted(stores)) if stores else "",
                needed_date=min((item.needed_date for item in group if item.needed_date), default=None),
                shopping_date=None,
                status=", ".join(sorted(statuses)) if statuses else "",
                linked_recipes_text=", ".join(recipe_names),
            )
        )
    return sorted(aggregated, key=lambda item: ((item.ingredient.name if item.ingredient else "").lower(), item.unit or ""))
