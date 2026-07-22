from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QObject, QThread, Signal
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.context import AppContext
from app.services import ingredient_service, open_prices_service, price_service
from app.ui.dialogs import (
    AddPriceDialog,
    OpenPricesImportDialog,
    OpenPricesSuggestionDialog,
    confirm_dialog,
    error_dialog,
    info_dialog,
    prompt_int,
)
from app.ui.widgets import COLOR_CRITICAL, PageHeader


class _OpenPricesAutoImportWorker(QObject):
    progress = Signal(int, int, str)
    item_finished = Signal(int, int, object)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, ingredients: list[tuple[int, str, str | None]], year: int) -> None:
        super().__init__()
        self.ingredients = ingredients
        self.year = year

    def run(self) -> None:
        results: list[open_prices_service.OpenPricesImportResult] = []
        total = len(self.ingredients)
        try:
            for index, (ingredient_id, ingredient_name, default_unit) in enumerate(self.ingredients, start=1):
                self.progress.emit(index, total, ingredient_name)
                result = open_prices_service.import_price_for_ingredient(
                    ingredient_id,
                    ingredient_name,
                    target_unit=default_unit,
                    year=self.year,
                )
                results.append(result)
                self.item_finished.emit(index, total, result)
        except Exception as exc:  # noqa: BLE001 - Fehler soll in der UI angezeigt werden
            self.failed.emit(str(exc))
            return

        self.finished.emit(results)


class PricesView(QWidget):
    """Preisverwaltung: aktuelle Preise je Zutat, fehlende Preise, Jahresübernahme."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._auto_import_thread: QThread | None = None
        self._auto_import_worker: _OpenPricesAutoImportWorker | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(PageHeader("Preise", "Zutatenpreise je Jahr erfassen und prüfen"))

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Jahr:", self))
        self.year_spin = QSpinBox(self)
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setValue(datetime.now().year)
        self.year_spin.valueChanged.connect(self.refresh)
        top_row.addWidget(self.year_spin)

        add_button = QPushButton("Preis erfassen", self)
        add_button.clicked.connect(self._add_price)
        open_prices_button = QPushButton("Aus Open Prices importieren", self)
        open_prices_button.clicked.connect(self._import_open_prices)
        auto_open_prices_button = QPushButton("Fehlende Preise automatisch suchen", self)
        auto_open_prices_button.clicked.connect(self._auto_import_open_prices)
        copy_button = QPushButton("Preise aus Vorjahr übernehmen", self)
        copy_button.clicked.connect(self._copy_from_previous_year)
        top_row.addWidget(add_button)
        top_row.addWidget(open_prices_button)
        top_row.addWidget(auto_open_prices_button)
        top_row.addWidget(copy_button)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        self.missing_label = QLabel("", self)
        layout.addWidget(self.missing_label)

        self.status_label = QLabel("", self)
        self.status_label.setStyleSheet("color: #666;")
        layout.addWidget(self.status_label)

        self.import_log = QTextEdit(self)
        self.import_log.setReadOnly(True)
        self.import_log.setPlaceholderText("Automatischer Open-Prices-Import: Suchbegriffe, Treffer, Preis und Datum erscheinen hier.")
        self.import_log.setFixedHeight(140)
        layout.addWidget(self.import_log)

        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(["Zutat", "Preis", "Einheit", "Quelle", "Laden", "Notizen"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        self.action_buttons: list[QPushButton] = [
            add_button,
            open_prices_button,
            auto_open_prices_button,
            copy_button,
        ]

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
            self.missing_label.setText(f"Fehlende Preise für {year} ({len(missing)}): {names}{suffix}")
            self.missing_label.setStyleSheet(f"color: {COLOR_CRITICAL};")
        else:
            self.missing_label.setText(f"Alle aktiven Zutaten haben einen Preis für {year}.")
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
            error_dialog(self, "Bitte gültige Werte angeben.")
            return

        with self.context.session() as session:
            from app.models import IngredientPrice

            session.add(IngredientPrice(**data))
        self.refresh()

    def _import_open_prices(self) -> None:
        with self.context.session() as session:
            ingredients = [(i.id, i.name) for i in ingredient_service.search_ingredients(session)]
        if not ingredients:
            error_dialog(self, "Es sind noch keine Zutaten angelegt.")
            return

        dialog = OpenPricesImportDialog(ingredients, self.year_spin.value(), self)
        if dialog.exec() != OpenPricesImportDialog.DialogCode.Accepted:
            return
        data = dialog.result_data()
        if data is None:
            error_dialog(self, "Bitte eine Zutat und einen Barcode angeben.")
            return

        try:
            lookup = open_prices_service.lookup_product_prices(data["barcode"])
        except open_prices_service.OpenPricesLookupError as exc:
            error_dialog(self, str(exc))
            return
        except open_prices_service.OpenPricesUnavailableError as exc:
            error_dialog(self, str(exc))
            return

        observation = lookup.latest_observation
        if observation is None:
            error_dialog(self, "Für diesen Barcode wurden keine Preisbeobachtungen gefunden.")
            return

        with self.context.session() as session:
            from app.models import Ingredient

            ingredient = session.get(Ingredient, data["ingredient_id"])
            if ingredient is None:
                error_dialog(self, "Die ausgewählte Zutat wurde nicht gefunden.")
                return

            price_record = open_prices_service.build_ingredient_price_from_observation(
                data["ingredient_id"],
                observation,
                product_quantity=lookup.product.quantity,
                target_unit=ingredient.default_unit,
                notes_prefix=data["notes"],
            )
            price_record.year = data["year"]
            session.add(price_record)

        quantity = f" ({lookup.product.quantity})" if lookup.product.quantity else ""
        store = f" bei {observation.store_name}" if observation.store_name else ""
        imported_unit_text = f" pro {price_record.unit}"
        info_dialog(
            self,
            (
                f"Preis für {lookup.product.name}{quantity} importiert: "
                f"{price_record.price_per_unit} {observation.currency}{imported_unit_text}{store} "
                f"vom {observation.date.isoformat() if observation.date else 'unbekannten Datum'}."
            ),
        )
        self.refresh()

    def _auto_import_open_prices(self) -> None:
        if self._auto_import_thread is not None:
            info_dialog(self, "Der automatische Open-Prices-Import läuft bereits.")
            return

        year = self.year_spin.value()
        if not confirm_dialog(
            self,
            "Open Prices",
            f"Fehlende Preise für {year} automatisch anhand der Zutatennamen suchen und importieren?",
        ):
            return

        with self.context.session() as session:
            missing_ingredients = price_service.missing_price_ingredients(session, year=year)
            ingredients_to_import = [(ingredient.id, ingredient.name, ingredient.default_unit) for ingredient in missing_ingredients]

        if not ingredients_to_import:
            info_dialog(self, f"Es fehlen keine Preise für {year}.")
            return

        self._set_import_running(True)
        self.status_label.setText(f"Open Prices sucht Preise für 0/{len(ingredients_to_import)} Zutaten ...")
        self.import_log.clear()
        self.import_log.append(f"Starte Preisermittlung für Jahr {year} mit {len(ingredients_to_import)} fehlenden Zutaten.")

        self._auto_import_thread = QThread(self)
        self._auto_import_worker = _OpenPricesAutoImportWorker(ingredients_to_import, year)
        self._auto_import_worker.moveToThread(self._auto_import_thread)
        self._auto_import_thread.started.connect(self._auto_import_worker.run)
        self._auto_import_worker.progress.connect(self._on_auto_import_progress)
        self._auto_import_worker.item_finished.connect(self._on_auto_import_item_finished)
        self._auto_import_worker.finished.connect(self._on_auto_import_finished)
        self._auto_import_worker.failed.connect(self._on_auto_import_failed)
        self._auto_import_worker.finished.connect(self._auto_import_thread.quit)
        self._auto_import_worker.failed.connect(self._auto_import_thread.quit)
        self._auto_import_thread.finished.connect(self._cleanup_auto_import_thread)
        self._auto_import_thread.start()

    def _on_auto_import_progress(self, current: int, total: int, ingredient_name: str) -> None:
        self.status_label.setText(f"Open Prices sucht {current}/{total}: {ingredient_name}")

    def _on_auto_import_item_finished(
        self,
        current: int,
        total: int,
        result: open_prices_service.OpenPricesImportResult,
    ) -> None:
        if result.status == "imported":
            price_text = f"{result.matched_price} {result.matched_currency}" if result.matched_price is not None else "Preis unbekannt"
            date_text = result.matched_date.isoformat() if result.matched_date else "Datum unbekannt"
            product_text = result.matched_product_name or "-"
            query_text = result.query_used or result.ingredient_name
            self.import_log.append(
                f"[{current}/{total}] {result.ingredient_name} | Suche: {query_text} | Treffer: {product_text} | Preis: {price_text} | Stand: {date_text}"
            )
        else:
            query_text = result.query_used or result.ingredient_name
            suggestion_text = ""
            if result.suggestions:
                suggestion_text = " | Ähnliche Produkte verfügbar"
            self.import_log.append(
                f"[{current}/{total}] {result.ingredient_name} | Suche: {query_text} | Kein Treffer: {result.message}{suggestion_text}"
            )

    def _on_auto_import_finished(self, results: list[open_prices_service.OpenPricesImportResult]) -> None:
        imported_count = 0
        skipped_messages: list[str] = []

        with self.context.session() as session:
            for result in results:
                if result.status == "imported" and result.price_record is not None:
                    session.add(result.price_record)
                    imported_count += 1
                else:
                    skipped_messages.append(f"{result.ingredient_name}: {result.message}")

        selected_suggestion_count = self._review_suggestions(results)
        imported_count += selected_suggestion_count

        self._set_import_running(False)
        self.status_label.setText("")
        self.import_log.append(f"Fertig: {imported_count} Preise importiert, {len(skipped_messages)} Zutaten ohne verwertbaren Treffer.")

        summary = f"{imported_count} Preise aus Open Prices importiert."
        if skipped_messages:
            preview = "\n".join(skipped_messages[:8])
            more = "\n..." if len(skipped_messages) > 8 else ""
            summary = f"{summary}\n\nNicht gefunden / übersprungen:\n{preview}{more}"
        info_dialog(self, summary, title="Open Prices Import")
        self.refresh()

    def _on_auto_import_failed(self, message: str) -> None:
        self._set_import_running(False)
        self.status_label.setText("")
        self.import_log.append(f"Fehler: {message}")
        error_dialog(self, f"Der automatische Open-Prices-Import ist fehlgeschlagen.\n\n{message}")

    def _cleanup_auto_import_thread(self) -> None:
        if self._auto_import_worker is not None:
            self._auto_import_worker.deleteLater()
        if self._auto_import_thread is not None:
            self._auto_import_thread.deleteLater()
        self._auto_import_worker = None
        self._auto_import_thread = None

    def _set_import_running(self, running: bool) -> None:
        for button in self.action_buttons:
            button.setEnabled(not running)
        self.year_spin.setEnabled(not running)

    def _review_suggestions(self, results: list[open_prices_service.OpenPricesImportResult]) -> int:
        imported_count = 0
        for result in results:
            if result.status == "imported" or not result.suggestions:
                continue

            dialog = OpenPricesSuggestionDialog(result.ingredient_name, result.suggestions, self)
            if dialog.exec() != OpenPricesSuggestionDialog.DialogCode.Accepted:
                continue

            suggestion = dialog.selected_suggestion()
            with self.context.session() as session:
                from app.models import Ingredient

                ingredient = session.get(Ingredient, result.ingredient_id)
                if ingredient is None:
                    continue
                price_record = open_prices_service.build_ingredient_price_from_suggestion(
                    result.ingredient_id,
                    suggestion,
                    target_unit=ingredient.default_unit,
                )
                price_record.year = result.year
                session.add(price_record)
                imported_count += 1

            date_text = suggestion.observation.date.isoformat() if suggestion.observation.date else "Datum unbekannt"
            self.import_log.append(
                f"Manuell gewählt für {result.ingredient_name}: {suggestion.product.name} | "
                f"{suggestion.observation.price} {suggestion.observation.currency} | {date_text}"
            )

        return imported_count

    def _copy_from_previous_year(self) -> None:
        target_year = self.year_spin.value()
        source_year = prompt_int(self, "Preise übernehmen", "Quelljahr:", default=target_year - 1, minimum=2000, maximum=2100)
        if source_year is None:
            return
        with self.context.session() as session:
            copied = price_service.copy_prices_from_year(session, source_year=source_year, target_year=target_year)
        info_dialog(self, f"{copied} Preise aus {source_year} nach {target_year} übernommen.")
        self.refresh()
