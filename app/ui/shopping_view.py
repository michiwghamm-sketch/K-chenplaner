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
from app.models import CampYear, ShoppingList, ShoppingListItem, ShoppingListItemAllocation, ShoppingTrip, ingredient_category_sort_key
from app.services import export_service, ingredient_service, shopping_service, unit_service
from app.ui.dialogs import (
    AddManualShoppingItemDialog,
    EditShoppingTripDialog,
    PlanShoppingTripDialog,
    RecipeIngredientChoice,
    TripAllocationRow,
    confirm_dialog,
    error_dialog,
    info_dialog,
    prompt_choice,
)
from app.ui.theme import ORANGE
from app.ui.widgets import COLOR_CRITICAL, PageHeader

SHOPPING_TABLE_COLUMNS = (
    "Zutat",
    "Kategorie",
    "Gesamtmenge",
    "Bereits gekauft",
    "Benoetigte Restmenge",
    "Einheit",
    "Preis je Einheit",
    "Gesamtpreis Position",
    "Haendler",
    "Bedarfsdatum",
    "Einkaufstag",
    "Status",
    "Rezepte",
    "Zugewiesen an",
)
GROUP_MODES = (
    ("Keine Gruppierung", "none"),
    ("Nach Einkaufstag", "day"),
    ("Nach Händler", "store"),
    ("Nach Nutzer", "person"),
)


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
        generate_button.setToolTip("Erzeugt eine komplett neue Einkaufsliste aus dem aktuellen Wochenplan.")
        generate_button.clicked.connect(self._generate_list)
        top_row.addWidget(generate_button)

        update_button = QPushButton("Einkaufsliste aktualisieren", self)
        update_button.setToolTip(
            "Gleicht die ausgewählte Einkaufsliste mit dem aktuellen Wochenplan ab (z. B. nach "
            "geänderten Portionen), statt sie neu zu erstellen - bereits geplante Einkäufe, "
            "Sonderwünsche und Verbrauchsmittel bleiben dabei erhalten."
        )
        update_button.clicked.connect(self._update_list_from_meal_plan)
        top_row.addWidget(update_button)

        plan_trip_button = QPushButton("Einkauf planen...", self)
        plan_trip_button.setToolTip(
            "Wählt Teilmengen der noch offenen Positionen für einen Händler aus und verteilt sie "
            "zufällig gleichmäßig auf die mitkommenden Personen."
        )
        plan_trip_button.clicked.connect(self._plan_shopping_trip)
        top_row.addWidget(plan_trip_button)

        add_item_button = QPushButton("Position hinzufügen...", self)
        add_item_button.setToolTip(
            "Fügt eine spontane Position ohne Rezeptbezug hinzu (Sonderwunsch, Non-Food, ...)."
        )
        add_item_button.clicked.connect(self._add_manual_item)
        top_row.addWidget(add_item_button)

        self.delete_item_button = QPushButton("Position löschen", self)
        self.delete_item_button.setProperty("role", "danger")
        self.delete_item_button.setToolTip(
            "Entfernt die ausgewählte Sonderwunsch-/Verbrauchsmittel-Position wieder aus der Liste "
            "(nur in der Wochenliste-/Gesamtlisten-Ansicht, nicht für Rezept-Positionen)."
        )
        self.delete_item_button.clicked.connect(self._delete_selected_item)
        top_row.addWidget(self.delete_item_button)

        append_standard_items_button = QPushButton("Verbrauchsmittel ergänzen", self)
        append_standard_items_button.setToolTip(
            "Fügt aktive Verbrauchsmittel zu der ausgewählten Einkaufsliste hinzu, ohne die Liste neu zu generieren."
        )
        append_standard_items_button.clicked.connect(self._append_standard_items)
        top_row.addWidget(append_standard_items_button)

        self.total_list_checkbox = QCheckBox("Gesamtliste (ohne Einkaufstage)", self)
        self.total_list_checkbox.setToolTip(
            "Erzeugt eine Gesamtliste ohne Aufteilung nach Einkaufstagen - "
            "das Bedarfsdatum je Zutat wird trotzdem angezeigt."
        )
        top_row.addWidget(self.total_list_checkbox)

        self.list_combo = QComboBox(self)
        self.list_combo.currentIndexChanged.connect(self._on_list_changed)
        top_row.addWidget(self.list_combo)

        delete_button = QPushButton("Einkaufsliste löschen", self)
        delete_button.setProperty("role", "danger")
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
        self.edit_trip_button = QPushButton("Einkauf bearbeiten...", self)
        self.edit_trip_button.clicked.connect(self._edit_selected_trip)
        group_row.addWidget(self.edit_trip_button)
        self.delete_trip_button = QPushButton("Einkauf löschen", self)
        self.delete_trip_button.setProperty("role", "danger")
        self.delete_trip_button.clicked.connect(self._delete_selected_trip)
        group_row.addWidget(self.delete_trip_button)
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
        self._reload_group_combo()
        self._reload_table()

    def _on_list_changed(self) -> None:
        self._reload_group_combo()
        self._reload_table()

    def _reload_group_combo(self, select_mode: str | None = None) -> None:
        current_mode = select_mode or self.group_combo.currentData() or "none"
        shopping_list_id = self.list_combo.currentData()
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        for label, mode in GROUP_MODES:
            self.group_combo.addItem(label, mode)
        if shopping_list_id is not None:
            with self.context.session() as session:
                shopping_list = session.get(ShoppingList, shopping_list_id)
                if shopping_list is not None:
                    shopping_service.migrate_legacy_store_status(session, shopping_list)
                    for trip in sorted(
                        shopping_list.trips,
                        key=lambda trip: (trip.store.lower(), trip.planned_date is None, trip.planned_date, trip.created_at),
                    ):
                        label = f"Einkauf {trip.store}"
                        if trip.planned_date:
                            label = f"{label} am {shopping_service.format_date_de(trip.planned_date)}"
                        elif len([other for other in shopping_list.trips if other.store == trip.store]) > 1:
                            label = f"{label} ({trip.created_at:%d.%m.%Y %H:%M})"
                        self.group_combo.addItem(label, f"trip:{trip.id}")
        index = self.group_combo.findData(current_mode)
        self.group_combo.setCurrentIndex(index if index >= 0 else 0)
        self.group_combo.blockSignals(False)

    def _selected_trip_id(self) -> int | None:
        mode = self.group_combo.currentData()
        if isinstance(mode, str) and mode.startswith("trip:"):
            return int(mode.split(":", 1)[1])
        return None

    def _reload_table(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        selected_trip_id = self._selected_trip_id()
        self.edit_trip_button.setVisible(selected_trip_id is not None)
        self.delete_trip_button.setVisible(selected_trip_id is not None)
        self.delete_item_button.setVisible(self.group_combo.currentData() in ("none", "day"))
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
            # Altdaten (item.store/item.status aus der Zeit vor Trips/Allocations) einmalig
            # in einen "Altbestand"-Trip uebernehmen, bevor Haendler-/Nutzer-Ansicht sie braucht.
            shopping_service.migrate_legacy_store_status(session, shopping_list)

            if mode == "day":
                for shopping_date, items in shopping_service.grouped_by_day_ordered(shopping_list):
                    self._add_band_row(shopping_service.format_shopping_day_label(shopping_date), items=items)
                    for item in items:
                        self._add_item_row(item, shopping_list)
            elif mode == "store":
                for store, allocations in shopping_service.grouped_by_store_ordered_allocations(shopping_list):
                    self._add_band_row(store, on_edit=lambda s=store, allocs=allocations: self._edit_shopping_trip(s, allocs))
                    for allocation in allocations:
                        self._add_allocation_row(allocation)
            elif mode == "person":
                for person, allocations in shopping_service.grouped_by_person_ordered(shopping_list):
                    self._add_band_row(person or shopping_service.UNASSIGNED_PERSON_LABEL)
                    for allocation in allocations:
                        self._add_allocation_row(allocation)
            elif selected_trip_id is not None:
                trip = session.get(ShoppingTrip, selected_trip_id)
                if trip is not None:
                    band_label = f"Einkauf {trip.store}"
                    if trip.planned_date:
                        band_label = f"{band_label} am {shopping_service.format_date_de(trip.planned_date)}"
                    self._add_band_row(band_label)
                    for allocation in sorted(
                        trip.allocations,
                        key=lambda a: (
                            a.status == "gekauft",
                            ingredient_category_sort_key(a.ingredient.category if a.ingredient else None),
                            (a.ingredient.name if a.ingredient else "").lower(),
                        ),
                    ):
                        self._add_allocation_row(allocation)
            else:
                for item in _aggregate_total_view_items(shopping_list.items):
                    self._add_item_row(item, shopping_list)

            self.total_label.setText(
                f"Gesamtpreis Einkauf: {_format_money(shopping_service.total_estimated_cost(shopping_list))}"
            )
        # Ohne das hier bleiben Band-Zeilen mit Cell-Widget (Label + "Neu mischen"-Button) auf
        # der Default-Zeilenhoehe und der Button wird am unteren Rand abgeschnitten.
        self.table.resizeRowsToContents()
        # Sortieren wuerde die Gruppen-Baender und ihre Zeilen auseinanderreissen.
        self.table.setSortingEnabled(mode == "none")

    def _add_band_row(self, label: str, *, items=None, on_edit=None) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setSpan(row, 0, 1, len(SHOPPING_TABLE_COLUMNS))
        total_text = ""
        if items is not None:
            total_text = f" | Gesamt: {_format_money(shopping_service.total_items_estimated_cost(items))}"

        band_widget = QWidget(self.table)
        band_layout = QHBoxLayout(band_widget)
        band_layout.setContentsMargins(5, 2, 5, 2)
        band_label = QLabel(f"{label}{total_text}", band_widget)
        band_label.setStyleSheet("color: white; font-weight: 600;")
        band_layout.addWidget(band_label)
        if on_edit is not None:
            band_layout.addSpacing(12)
            edit_button = QPushButton("Bearbeiten...", band_widget)
            edit_button.setToolTip("Diesen Einkauf bearbeiten: Händler, Teilnehmer, Zuteilungen, neu mischen, löschen.")
            edit_button.clicked.connect(on_edit)
            band_layout.addWidget(edit_button)
        # Stretch NACH Label/Button, sonst wird der Button bei gespannten (11-spaltigen)
        # Zeilen ganz an den rechten Rand gedrueckt und faellt aus dem sichtbaren Bereich.
        band_layout.addStretch(1)
        band_widget.setStyleSheet(f"background-color: {ORANGE};")
        self.table.setCellWidget(row, 0, band_widget)

    def _add_item_row(self, item: ShoppingListItem, shopping_list: ShoppingList | None = None) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        name_item = QTableWidgetItem(item.ingredient.name if item.ingredient else "")
        name_item.setData(1000, item.id)
        self.table.setItem(row, 0, name_item)
        self.table.setItem(row, 1, QTableWidgetItem((item.ingredient.category if item.ingredient else None) or ""))
        self.table.setItem(row, 2, QTableWidgetItem(_format_decimal(item.quantity)))
        shopping_list = shopping_list or item.shopping_list
        _set_purchase_cells(self.table, row, shopping_list, item.ingredient_id, item.unit)
        self.table.setItem(row, 5, QTableWidgetItem(item.unit or ""))
        price_item = QTableWidgetItem(
            _format_money(item.estimated_price_per_unit) if item.estimated_price_per_unit is not None else "fehlt"
        )
        if item.estimated_price_per_unit is None:
            price_item.setForeground(QColor(COLOR_CRITICAL))
        self.table.setItem(row, 6, price_item)
        self.table.setItem(row, 7, QTableWidgetItem(_format_money(item.estimated_total_price) if item.estimated_total_price is not None else ""))
        # Haendler/Status stehen ab jetzt auf den Allocations eines Einkaufs (siehe "Nach
        # Haendler"/"Nach Nutzer") - hier (Wochenliste/Gesamtliste) nur noch Altlast-Anzeige.
        self.table.setItem(row, 8, QTableWidgetItem(item.store or ""))
        self.table.setItem(row, 9, QTableWidgetItem(shopping_service.format_date_de(item.needed_date)))
        self.table.setItem(row, 10, QTableWidgetItem(shopping_service.format_date_de(item.shopping_date)))
        self.table.setItem(row, 11, QTableWidgetItem(item.status or ""))
        if shopping_service.is_manual_item(item):
            label = "Sonderwunsch" + (f" ({item.requested_by})" if item.requested_by else "")
            manual_item = QTableWidgetItem(label)
            manual_item.setForeground(QColor(ORANGE))
            self.table.setItem(row, 12, manual_item)
        else:
            self.table.setItem(row, 12, QTableWidgetItem(item.linked_recipes_text or ""))
        self.table.setItem(row, 13, QTableWidgetItem(""))

    def _add_allocation_row(self, allocation: ShoppingListItemAllocation) -> None:
        shopping_list = allocation.shopping_list
        price_per_unit = shopping_service.ingredient_price_per_unit(shopping_list, allocation.ingredient_id, allocation.unit)
        row = self.table.rowCount()
        self.table.insertRow(row)
        name_item = QTableWidgetItem(allocation.ingredient.name if allocation.ingredient else "")
        name_item.setData(1000, allocation.id)
        self.table.setItem(row, 0, name_item)
        self.table.setItem(row, 1, QTableWidgetItem((allocation.ingredient.category if allocation.ingredient else None) or ""))
        self.table.setItem(row, 2, QTableWidgetItem(_format_decimal(allocation.quantity)))
        _set_purchase_cells(self.table, row, shopping_list, allocation.ingredient_id, allocation.unit)
        self.table.setItem(row, 5, QTableWidgetItem(allocation.unit or ""))
        price_item = QTableWidgetItem(_format_money(price_per_unit) if price_per_unit is not None else "fehlt")
        if price_per_unit is None:
            price_item.setForeground(QColor(COLOR_CRITICAL))
        self.table.setItem(row, 6, price_item)
        allocation_price = price_per_unit * allocation.quantity if price_per_unit is not None else None
        self.table.setItem(row, 7, QTableWidgetItem(_format_money(allocation_price) if allocation_price is not None else ""))
        self.table.setItem(row, 8, QTableWidgetItem(allocation.trip.store))
        # Bedarfsdatum/Einkaufstag sind pro Einkaufstag (ShoppingListItem) verschieden und lassen
        # sich fuer eine zutatenbezogene Allocation nicht eindeutig zuordnen - siehe Wochenliste.
        self.table.setItem(row, 9, QTableWidgetItem(""))
        self.table.setItem(row, 10, QTableWidgetItem(""))
        status_text = allocation.status
        if allocation.status == "gekauft":
            quantity = allocation.purchased_quantity if allocation.purchased_quantity is not None else allocation.quantity
            date_text = shopping_service.format_date_de(allocation.purchased_at.date()) if allocation.purchased_at else ""
            status_text = f"gekauft: {_format_decimal(quantity)} {allocation.unit or ''}"
            if date_text:
                status_text += f" am {date_text}"
        self.table.setItem(row, 11, QTableWidgetItem(status_text))
        self.table.setItem(row, 12, QTableWidgetItem(shopping_service.ingredient_linked_recipes(shopping_list, allocation.ingredient_id, allocation.unit)))
        self.table.setItem(row, 13, QTableWidgetItem(allocation.assigned_to or ""))

    def _edit_selected_trip(self) -> None:
        trip_id = self._selected_trip_id()
        if trip_id is None:
            return
        with self.context.session() as session:
            trip = session.get(ShoppingTrip, trip_id)
            if trip is None:
                return
            self._edit_shopping_trip(trip.store, list(trip.allocations))

    def _delete_selected_trip(self) -> None:
        trip_id = self._selected_trip_id()
        if trip_id is None:
            return
        with self.context.session() as session:
            trip = session.get(ShoppingTrip, trip_id)
            if trip is None:
                return
            label = f"Einkauf {trip.store}"
        if not confirm_dialog(self, "Einkauf löschen", f"{label} mit allen Positionen wirklich löschen?"):
            return
        with self.context.session() as session:
            trip = session.get(ShoppingTrip, trip_id)
            if trip is not None:
                shopping_service.delete_shopping_trip(session, trip)
        self._reload_group_combo(select_mode="store")
        self._reload_table()

    def _edit_shopping_trip(self, store: str, allocations: list[ShoppingListItemAllocation]) -> None:
        trip_ids = sorted({allocation.shopping_trip_id for allocation in allocations})
        if len(trip_ids) > 1:
            with self.context.session() as session:
                trips = [session.get(ShoppingTrip, trip_id) for trip_id in trip_ids]
                labels = [
                    (
                        f"Einkaufstag {shopping_service.format_date_de(trip.planned_date)}"
                        if trip.planned_date
                        else f"angelegt {trip.created_at:%d.%m.%Y %H:%M}"
                    )
                    + f" ({len(trip.allocations)} Positionen)"
                    for trip in trips
                ]
            choice = prompt_choice(
                self, "Einkauf auswählen", f"Mehrere Einkäufe bei '{store}' - welcher soll bearbeitet werden?", labels
            )
            if choice is None:
                return
            trip_id = trip_ids[labels.index(choice)]
        else:
            trip_id = trip_ids[0]

        with self.context.session() as session:
            trip = session.get(ShoppingTrip, trip_id)
            if trip is None:
                return
            shopping_list = trip.shopping_list
            rows = [
                TripAllocationRow(
                    id=allocation.id,
                    ingredient_id=allocation.ingredient_id,
                    ingredient_name=allocation.ingredient.name if allocation.ingredient else "",
                    quantity=allocation.quantity,
                    unit=allocation.unit or "",
                    assigned_to=allocation.assigned_to,
                    status=allocation.status,
                    max_quantity=shopping_service.remaining_quantity_for_ingredient(
                        shopping_list, allocation.ingredient_id, allocation.unit
                    )
                    + allocation.quantity,
                )
                for allocation in trip.allocations
            ]
            available_groups = shopping_service.items_available_for_planning(trip.shopping_list)
            store_value = trip.store
            participants_text = trip.participants_text or ""
            planned_date_value = trip.planned_date

        dialog = EditShoppingTripDialog(
            store=store_value,
            participants_text=participants_text,
            rows=rows,
            available_groups=available_groups,
            status_options=shopping_service.ALLOWED_ITEM_STATUSES,
            planned_date=planned_date_value,
            parent=self,
        )
        if dialog.exec() != EditShoppingTripDialog.DialogCode.Accepted:
            return

        if dialog.was_delete_requested():
            if not confirm_dialog(self, "Einkauf löschen", "Den kompletten Einkauf mit allen Positionen unwiderruflich löschen?"):
                return
            with self.context.session() as session:
                trip = session.get(ShoppingTrip, trip_id)
                if trip is not None:
                    shopping_service.delete_shopping_trip(session, trip)
            self._reload_group_combo(select_mode="store")
            self._reload_table()
            return

        result = dialog.result_data()
        with self.context.session() as session:
            trip = session.get(ShoppingTrip, trip_id)
            if trip is None:
                return
            if result["store"]:
                trip.store = result["store"]
            trip.participants_text = result["participants_text"] or None
            trip.planned_date = result["planned_date"]
            rows_by_id = {row["id"]: row for row in result["rows"]}
            new_selections = [
                (row["ingredient_id"], row["unit"], row["quantity"])
                for row in result["rows"]
                if row["id"] is None
            ]
            for allocation in list(trip.allocations):
                if allocation.id in result["removed_ids"]:
                    shopping_service.delete_allocation(session, allocation)
                    continue
                row = rows_by_id.get(allocation.id)
                if row is None:
                    continue
                if row["quantity"] != allocation.quantity:
                    try:
                        shopping_service.set_allocation_quantity(trip.shopping_list, allocation, row["quantity"])
                    except ValueError as exc:
                        error_dialog(self, str(exc))
                        continue
                shopping_service.set_allocation_assigned_to(allocation, row["assigned_to"])
                shopping_service.set_allocation_status(allocation, row["status"])
            if new_selections:
                try:
                    created_allocations = shopping_service.add_allocations_to_trip(session, trip, new_selections)
                except ValueError as exc:
                    error_dialog(self, str(exc))
                    return
                new_rows = [row for row in result["rows"] if row["id"] is None]
                for allocation, row in zip(created_allocations, new_rows, strict=False):
                    shopping_service.set_allocation_assigned_to(allocation, row["assigned_to"])
                    shopping_service.set_allocation_status(allocation, row["status"])
        self._reload_group_combo(select_mode=f"trip:{trip_id}")
        self._reload_table()

    def _plan_shopping_trip(self) -> None:
        shopping_list_id = self.list_combo.currentData()
        if shopping_list_id is None:
            error_dialog(self, "Es ist keine Einkaufsliste ausgewählt.")
            return
        with self.context.session() as session:
            shopping_list = session.get(ShoppingList, shopping_list_id)
            plannable = shopping_service.items_available_for_planning(shopping_list)
        if not plannable:
            info_dialog(self, "Alle Positionen sind bereits vollständig einem Einkauf zugeteilt.")
            return

        dialog = PlanShoppingTripDialog(plannable, self)
        if dialog.exec() != PlanShoppingTripDialog.DialogCode.Accepted:
            return
        result = dialog.result_data()
        if not result["selections"]:
            error_dialog(self, "Bitte mindestens eine Position auswählen.")
            return

        with self.context.session() as session:
            shopping_list = session.get(ShoppingList, shopping_list_id)
            try:
                trip = shopping_service.create_shopping_trip(
                    session,
                    shopping_list,
                    store=result["store"],
                    participants=result["participants"],
                    selections=result["selections"],
                    planned_date=result["planned_date"],
                )
            except ValueError as exc:
                error_dialog(self, str(exc))
                return
            trip_id = trip.id
        info_dialog(self, "Einkauf angelegt.")
        self._reload_group_combo(select_mode=f"trip:{trip_id}")
        self._reload_table()

    def _append_standard_items(self) -> None:
        shopping_list_id = self.list_combo.currentData()
        if shopping_list_id is None:
            error_dialog(self, "Es ist keine Einkaufsliste ausgewählt.")
            return
        with self.context.session() as session:
            shopping_list = session.get(ShoppingList, shopping_list_id)
            if shopping_list is None:
                return
            created = shopping_service.append_standard_items_to_shopping_list(session, shopping_list)
        if created:
            info_dialog(self, f"{len(created)} Verbrauchsmittel ergänzt.")
        else:
            info_dialog(self, "Alle aktiven Verbrauchsmittel sind bereits in dieser Einkaufsliste.")
        self._reload_group_combo()
        self._reload_table()

    def _add_manual_item(self) -> None:
        shopping_list_id = self.list_combo.currentData()
        if shopping_list_id is None:
            error_dialog(self, "Es ist keine Einkaufsliste ausgewählt.")
            return
        with self.context.session() as session:
            ingredient_choices = [
                RecipeIngredientChoice(
                    id=ingredient.id,
                    name=ingredient.name,
                    default_unit=ingredient.default_unit,
                    compatible_units=unit_service.compatible_units(session, ingredient.default_unit),
                )
                for ingredient in ingredient_service.search_ingredients(session, active_only=False)
            ]

        dialog = AddManualShoppingItemDialog(ingredient_choices, self)
        if dialog.exec() != AddManualShoppingItemDialog.DialogCode.Accepted:
            return
        result = dialog.result_data()
        if result["ingredient_id"] is None and not result["new_ingredient_name"]:
            error_dialog(self, "Bitte eine Zutat auswählen oder einen neuen Namen eingeben.")
            return

        with self.context.session() as session:
            shopping_list = session.get(ShoppingList, shopping_list_id)
            if result["ingredient_id"] is not None:
                ingredient = session.get(ingredient_service.Ingredient, result["ingredient_id"])
            else:
                ingredient = ingredient_service.find_or_create_ingredient(
                    session, name=result["new_ingredient_name"], default_unit=result["unit"]
                )
            try:
                shopping_service.add_manual_shopping_item(
                    session,
                    shopping_list,
                    ingredient=ingredient,
                    quantity=result["quantity"],
                    unit=result["unit"],
                    requested_by=result["requested_by"],
                    notes=result["notes"],
                )
            except ValueError as exc:
                error_dialog(self, str(exc))
                return
        info_dialog(self, "Position hinzugefügt.")
        self._reload_table()

    def _delete_selected_item(self) -> None:
        mode = self.group_combo.currentData()
        if mode not in ("none", "day"):
            error_dialog(self, "Bitte zuerst die Wochenliste- oder Gesamtlisten-Ansicht wählen.")
            return
        row = self.table.currentRow()
        name_item = self.table.item(row, 0) if row >= 0 else None
        item_id = name_item.data(1000) if name_item is not None else None
        if item_id is None:
            error_dialog(self, "Bitte zuerst eine Position in der Tabelle auswählen.")
            return

        with self.context.session() as session:
            item = session.get(ShoppingListItem, item_id)
            if item is None:
                return
            label = item.ingredient.name if item.ingredient else ""
            is_manual = shopping_service.is_manual_item(item)
        if not is_manual:
            error_dialog(
                self,
                f"'{label}' kommt aus dem Wochenplan und kann nicht einzeln gelöscht werden - "
                "stattdessen den Wochenplan anpassen und die Liste aktualisieren.",
            )
            return
        if not confirm_dialog(self, "Position löschen", f"'{label}' wirklich aus der Liste entfernen?"):
            return

        with self.context.session() as session:
            item = session.get(ShoppingListItem, item_id)
            if item is None:
                return
            try:
                shopping_service.delete_shopping_list_item(session, item)
            except ValueError as exc:
                error_dialog(self, str(exc))
                return
        self._reload_table()

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

    def _update_list_from_meal_plan(self) -> None:
        shopping_list_id = self.list_combo.currentData()
        if shopping_list_id is None:
            error_dialog(self, "Es ist keine Einkaufsliste ausgewählt.")
            return
        with self.context.session() as session:
            shopping_list = session.get(ShoppingList, shopping_list_id)
            if shopping_list is None:
                return
            result = shopping_service.update_shopping_list_from_meal_plan(session, shopping_list)
            created_count = len(result.created)
            updated_count = len(result.updated)
            orphaned_names = sorted({item.ingredient.name for item in result.orphaned if item.ingredient})

        message = f"{created_count} Position(en) neu hinzugefügt, {updated_count} Menge(n) aktualisiert."
        if orphaned_names:
            message += (
                "\n\nDiese Positionen kommen im aktuellen Wochenplan nicht mehr vor, wurden aber "
                "nicht automatisch gelöscht (z. B. falls bereits eingekauft/zugeteilt):\n- "
                + "\n- ".join(orphaned_names)
            )
        info_dialog(self, message)
        self._reload_table()

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


def _set_purchase_cells(
    table: QTableWidget,
    row: int,
    shopping_list: ShoppingList,
    ingredient_id: int | None,
    unit: str | None,
) -> None:
    _needed, purchased, remaining, history = shopping_service.need_purchase_remaining_summary(
        shopping_list, ingredient_id, unit
    )
    unit_text = unit or ""
    purchased_item = QTableWidgetItem(f"{_format_decimal(purchased)} {unit_text}".strip())
    remaining_item = QTableWidgetItem(f"{_format_decimal(remaining)} {unit_text}".strip())
    if history:
        purchased_item.setToolTip(history)
    table.setItem(row, 3, purchased_item)
    table.setItem(row, 4, remaining_item)


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
        requested_by_names = {item.requested_by for item in group if item.requested_by}
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
                requested_by=", ".join(sorted(requested_by_names)) if requested_by_names else None,
            )
        )
    return sorted(
        aggregated,
        key=lambda item: (
            ingredient_category_sort_key(item.ingredient.category if item.ingredient else None),
            (item.ingredient.name if item.ingredient else "").lower(),
            item.unit or "",
        ),
    )
