from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate, QObject, QSize, QThread, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.open_prices_service import (
    OpenPricesError,
    OpenPricesSuggestion,
    fetch_image_bytes,
    lookup_product_prices,
    suggest_matches_for_query,
)


def confirm_dialog(parent: QWidget | None, title: str, message: str) -> bool:
    """Bestätigungsdialog vor kritischen Aktionen (Löschen, Deaktivieren, Restore)."""
    result = QMessageBox.question(
        parent,
        title,
        message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return result == QMessageBox.StandardButton.Yes


def error_dialog(parent: QWidget | None, message: str, *, title: str = "Fehler") -> None:
    QMessageBox.critical(parent, title, message)


def warning_dialog(parent: QWidget | None, message: str, *, title: str = "Warnung") -> None:
    QMessageBox.warning(parent, title, message)


def info_dialog(parent: QWidget | None, message: str, *, title: str = "Hinweis") -> None:
    QMessageBox.information(parent, title, message)


def prompt_text(parent: QWidget | None, title: str, label: str, default: str = "") -> str | None:
    text, ok = QInputDialog.getText(parent, title, label, text=default)
    if not ok or not text.strip():
        return None
    return text.strip()


def prompt_int(parent: QWidget | None, title: str, label: str, default: int = 1, minimum: int = 1, maximum: int = 100000) -> int | None:
    value, ok = QInputDialog.getInt(parent, title, label, value=default, minValue=minimum, maxValue=maximum)
    if not ok:
        return None
    return value


def prompt_choice(parent: QWidget | None, title: str, label: str, options: list[str], *, default_index: int = 0) -> str | None:
    choice, ok = QInputDialog.getItem(parent, title, label, options, current=default_index, editable=False)
    if not ok:
        return None
    return choice


NO_COMPONENT_LABEL = "- Sonstiges -"


class AddRecipeIngredientDialog(QDialog):
    """Dialog zum Hinzufügen oder Bearbeiten einer Rezeptzutat (Menge, Einheit, Teilstück)."""

    def __init__(
        self,
        ingredients: list[tuple[int, str]],
        components: list[tuple[int, str]],
        parent: QWidget | None = None,
        *,
        initial: dict | None = None,
        title: str | None = None,
    ) -> None:
        super().__init__(parent)
        initial = initial or {}
        self._delete_requested = False
        self.setWindowTitle(title or ("Zutat bearbeiten" if initial else "Zutat hinzufügen"))

        self.ingredient_combo = QComboBox(self)
        for ingredient_id, name in ingredients:
            self.ingredient_combo.addItem(name, ingredient_id)
        ingredient_index = self.ingredient_combo.findData(initial.get("ingredient_id"))
        if ingredient_index >= 0:
            self.ingredient_combo.setCurrentIndex(ingredient_index)

        self.component_combo = QComboBox(self)
        self.component_combo.addItem(NO_COMPONENT_LABEL, None)
        for component_id, name in components:
            self.component_combo.addItem(name, component_id)
        component_index = self.component_combo.findData(initial.get("component_id"))
        self.component_combo.setCurrentIndex(component_index if component_index >= 0 else 0)

        self.quantity_spin = QDoubleSpinBox(self)
        self.quantity_spin.setDecimals(3)
        self.quantity_spin.setRange(0.001, 100000)
        self.quantity_spin.setValue(float(initial.get("quantity", 1)))

        self.unit_edit = QLineEdit(self)
        self.unit_edit.setText(initial.get("unit", ""))
        self.notes_edit = QLineEdit(self)
        self.notes_edit.setText(initial.get("notes") or "")

        form = QFormLayout()
        form.addRow("Zutat", self.ingredient_combo)
        form.addRow("Teilstück", self.component_combo)
        form.addRow("Menge", self.quantity_spin)
        form.addRow("Einheit", self.unit_edit)
        form.addRow("Notizen", self.notes_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        if initial:
            delete_button = buttons.addButton("Zutat entfernen", QDialogButtonBox.ButtonRole.DestructiveRole)
            delete_button.clicked.connect(self._request_delete)

        layout = QFormLayout(self)
        layout.addRow(form)
        layout.addRow(buttons)

    def _request_delete(self) -> None:
        self._delete_requested = True
        self.accept()

    def was_delete_requested(self) -> bool:
        return self._delete_requested

    def result_data(self) -> dict | None:
        if not self.unit_edit.text().strip():
            return None
        return {
            "ingredient_id": self.ingredient_combo.currentData(),
            "component_id": self.component_combo.currentData(),
            "quantity": Decimal(str(self.quantity_spin.value())),
            "unit": self.unit_edit.text().strip(),
            "notes": self.notes_edit.text().strip() or None,
        }


class AddPriceDialog(QDialog):
    """Dialog zum Erfassen eines neuen Zutatenpreises."""

    def __init__(
        self,
        ingredients: list[tuple[int, str]],
        default_year: int,
        parent: QWidget | None = None,
        *,
        selected_ingredient_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preis erfassen")

        self.ingredient_combo = QComboBox(self)
        for ingredient_id, name in ingredients:
            self.ingredient_combo.addItem(name, ingredient_id)
        if selected_ingredient_id is not None:
            index = self.ingredient_combo.findData(selected_ingredient_id)
            if index >= 0:
                self.ingredient_combo.setCurrentIndex(index)
            self.ingredient_combo.setEnabled(False)

        self.price_spin = QDoubleSpinBox(self)
        self.price_spin.setDecimals(2)
        self.price_spin.setRange(0, 100000)

        self.unit_edit = QLineEdit(self)
        self.source_edit = QLineEdit(self)
        self.store_edit = QLineEdit(self)

        self.year_spin = QSpinBox(self)
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setValue(default_year)

        self.notes_edit = QLineEdit(self)

        form = QFormLayout()
        form.addRow("Zutat", self.ingredient_combo)
        form.addRow("Preis", self.price_spin)
        form.addRow("Einheit", self.unit_edit)
        form.addRow("Quelle", self.source_edit)
        form.addRow("Laden", self.store_edit)
        form.addRow("Jahr", self.year_spin)
        form.addRow("Notizen", self.notes_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow(form)
        layout.addRow(buttons)

    def result_data(self) -> dict | None:
        if not self.unit_edit.text().strip():
            return None
        try:
            price = Decimal(str(self.price_spin.value()))
        except InvalidOperation:
            return None
        return {
            "ingredient_id": self.ingredient_combo.currentData(),
            "price_per_unit": price,
            "unit": self.unit_edit.text().strip(),
            "source": self.source_edit.text().strip() or None,
            "store": self.store_edit.text().strip() or None,
            "year": self.year_spin.value(),
            "notes": self.notes_edit.text().strip() or None,
        }


class OpenPricesImportDialog(QDialog):
    """Dialog für den Import eines externen Preises über einen Barcode."""

    def __init__(
        self,
        ingredients: list[tuple[int, str]],
        default_year: int,
        parent: QWidget | None = None,
        *,
        selected_ingredient_id: int | None = None,
        default_barcode: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preis aus Open Prices importieren")

        self.ingredient_combo = QComboBox(self)
        for ingredient_id, name in ingredients:
            self.ingredient_combo.addItem(name, ingredient_id)
        if selected_ingredient_id is not None:
            index = self.ingredient_combo.findData(selected_ingredient_id)
            if index >= 0:
                self.ingredient_combo.setCurrentIndex(index)
            self.ingredient_combo.setEnabled(False)

        self.barcode_edit = QLineEdit(self)
        self.barcode_edit.setPlaceholderText("z. B. 3017620422003")
        if default_barcode:
            self.barcode_edit.setText(default_barcode)

        self.year_spin = QSpinBox(self)
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setValue(default_year)

        self.notes_edit = QLineEdit(self)
        self.notes_edit.setPlaceholderText("optional, z. B. Packungsware / Testimport")

        form = QFormLayout()
        form.addRow("Zutat", self.ingredient_combo)
        form.addRow("Barcode", self.barcode_edit)
        form.addRow("Jahr", self.year_spin)
        form.addRow("Notiz", self.notes_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow(form)
        layout.addRow(buttons)

    def result_data(self) -> dict | None:
        barcode = self.barcode_edit.text().strip()
        if not barcode:
            return None
        return {
            "ingredient_id": self.ingredient_combo.currentData(),
            "barcode": barcode,
            "year": self.year_spin.value(),
            "notes": self.notes_edit.text().strip() or None,
        }


class OpenPricesSuggestionDialog(QDialog):
    """Erlaubt die Auswahl eines ähnlichen Open-Prices-Produkts für eine Zutat."""

    def __init__(
        self,
        ingredient_name: str,
        suggestions: list[OpenPricesSuggestion],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Ähnliche Produkte für {ingredient_name}")
        self._suggestions = suggestions

        self.combo = QComboBox(self)
        for index, suggestion in enumerate(suggestions):
            date_text = suggestion.observation.date.isoformat() if suggestion.observation.date else "Datum unbekannt"
            quantity_text = f" | {suggestion.product.quantity}" if suggestion.product.quantity else ""
            label = (
                f"{suggestion.product.name}{quantity_text} | "
                f"{suggestion.observation.price} {suggestion.observation.currency} | "
                f"{date_text}"
            )
            self.combo.addItem(label, index)

        info = QLabel(
            f"Für '{ingredient_name}' wurde kein eindeutiger Treffer importiert. "
            "Du kannst einen ähnlichen Open-Prices-Eintrag auswählen oder abbrechen.",
            self,
        )
        info.setWordWrap(True)

        form = QFormLayout()
        form.addRow(info)
        form.addRow("Vorschlag", self.combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow(form)
        layout.addRow(buttons)

    def selected_suggestion(self) -> OpenPricesSuggestion:
        return self._suggestions[self.combo.currentData()]


class SimilarIngredientsWarningDialog(QDialog):
    """Warnt beim Anlegen/Umbenennen einer Zutat vor moeglichen Dubletten - reiner Hinweis, kein Zwang."""

    def __init__(
        self,
        name: str,
        matches: list[tuple[str, float, str, int]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ähnliche Zutaten gefunden")

        info = QLabel(
            f"'{name}' ist folgenden bestehenden Zutaten sehr ähnlich. Eventuell ist das bereits "
            "dieselbe Zutat unter einem anderen Namen oder Tippfehler.",
            self,
        )
        info.setWordWrap(True)

        list_widget = QListWidget(self)
        for match_name, similarity, reason, usage_count in matches:
            usage_text = f", {usage_count}x in Rezepten/Preisen verwendet" if usage_count else ""
            list_widget.addItem(f"{match_name} ({similarity:.0%} - {reason}{usage_text})")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Trotzdem speichern")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addWidget(list_widget)
        layout.addWidget(buttons)


@dataclass(slots=True)
class ProductSearchResult:
    suggestion: OpenPricesSuggestion
    image_bytes: bytes | None


class _ProductSearchWorker(QObject):
    """Sucht in Open Prices nach Produkten und laedt Vorschaubilder - reine Netzwerkarbeit, kein
    DB-Zugriff (gleiches Muster wie _OpenPricesAutoImportWorker in ingredients_view.py)."""

    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, query: str, target_unit: str | None) -> None:
        super().__init__()
        self.query = query
        self.target_unit = target_unit

    def run(self) -> None:
        try:
            suggestions = suggest_matches_for_query(self.query, target_unit=self.target_unit, limit=8)
        except OpenPricesError as exc:
            self.failed.emit(str(exc))
            return

        results: list[ProductSearchResult] = []
        for suggestion in suggestions:
            image_bytes = fetch_image_bytes(suggestion.product.image_url) if suggestion.product.image_url else None
            results.append(ProductSearchResult(suggestion=suggestion, image_bytes=image_bytes))
        self.finished.emit(results)


class BarcodeSearchDialog(QDialog):
    """Sucht in Open Prices nach passenden Produkten (mit Bild-Vorschau) und verknuepft die Auswahl
    per Barcode mit einer Zutat. Wird sowohl fuer einzelne Zutaten als auch im gefuehrten
    Batch-Modus fuer Bestandszutaten ohne Barcode verwendet (siehe IngredientsView)."""

    def __init__(
        self,
        ingredient_name: str,
        target_unit: str | None,
        parent: QWidget | None = None,
        *,
        progress_text: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Produkt/Barcode suchen")
        self.setMinimumSize(560, 420)

        self._target_unit = target_unit
        self._results: list[ProductSearchResult] = []
        self._selected: dict | None = None
        self._stopped = False
        self._thread: QThread | None = None
        self._worker: _ProductSearchWorker | None = None

        layout = QVBoxLayout(self)

        if progress_text:
            progress_label = QLabel(progress_text, self)
            progress_label.setStyleSheet("font-weight: bold;")
            layout.addWidget(progress_label)

        search_row = QHBoxLayout()
        self.query_edit = QLineEdit(self)
        self.query_edit.setText(ingredient_name)
        self.query_edit.returnPressed.connect(self._start_search)
        search_button = QPushButton("Suchen", self)
        search_button.clicked.connect(self._start_search)
        search_row.addWidget(self.query_edit)
        search_row.addWidget(search_button)
        layout.addLayout(search_row)

        self.status_label = QLabel("", self)
        layout.addWidget(self.status_label)

        self.result_list = QListWidget(self)
        self.result_list.setIconSize(QSize(64, 64))
        self.result_list.itemSelectionChanged.connect(self._update_button_states)
        self.result_list.itemDoubleClicked.connect(lambda _item: self._accept_selected())
        layout.addWidget(self.result_list, stretch=1)

        button_row = QHBoxLayout()
        self.accept_button = QPushButton("Übernehmen", self)
        self.accept_button.setEnabled(False)
        self.accept_button.clicked.connect(self._accept_selected)
        manual_button = QPushButton("Barcode manuell eingeben", self)
        manual_button.clicked.connect(self._enter_manual_barcode)
        skip_button = QPushButton("Überspringen", self)
        skip_button.clicked.connect(self.reject)
        stop_button = QPushButton("Vorgang beenden", self)
        stop_button.clicked.connect(self._stop)
        button_row.addWidget(self.accept_button)
        button_row.addWidget(manual_button)
        button_row.addStretch(1)
        button_row.addWidget(skip_button)
        button_row.addWidget(stop_button)
        layout.addLayout(button_row)

        self._start_search()

    def _start_search(self) -> None:
        if self._thread is not None:
            return  # Suche laeuft bereits
        query = self.query_edit.text().strip()
        if not query:
            return

        self.result_list.clear()
        self.accept_button.setEnabled(False)
        self.status_label.setText("Suche läuft ...")

        self._thread = QThread(self)
        self._worker = _ProductSearchWorker(query, self._target_unit)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_search_finished)
        self._worker.failed.connect(self._on_search_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _on_search_finished(self, results: list[ProductSearchResult]) -> None:
        self._results = results
        self.result_list.clear()
        for result in results:
            product = result.suggestion.product
            observation = result.suggestion.observation
            brand_text = f" ({product.brands})" if product.brands else ""
            quantity_text = f" | {product.quantity}" if product.quantity else ""
            date_text = observation.date.isoformat() if observation.date else "Datum unbekannt"
            label = (
                f"{product.name}{brand_text}{quantity_text} | "
                f"{observation.price} {observation.currency} | {date_text}"
            )
            item = QListWidgetItem(label)
            if result.image_bytes:
                pixmap = QPixmap()
                if pixmap.loadFromData(result.image_bytes):
                    item.setIcon(QIcon(pixmap))
            self.result_list.addItem(item)

        self.status_label.setText(f"{len(results)} Treffer" if results else "Keine Treffer gefunden.")

    def _on_search_failed(self, message: str) -> None:
        self.status_label.setText(f"Fehler: {message}")

    def _cleanup_thread(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        if self._thread is not None:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None

    def _update_button_states(self) -> None:
        self.accept_button.setEnabled(bool(self.result_list.selectedItems()))

    def _accept_selected(self) -> None:
        row = self.result_list.currentRow()
        if row < 0 or row >= len(self._results):
            return
        product = self._results[row].suggestion.product
        brand_text = f" ({product.brands})" if product.brands else ""
        quantity_text = f", {product.quantity}" if product.quantity else ""
        self._selected = {"barcode": product.code, "label": f"{product.name}{brand_text}{quantity_text}"}
        self.accept()

    def _enter_manual_barcode(self) -> None:
        barcode = prompt_text(self, "Barcode manuell eingeben", "Barcode (EAN):")
        if not barcode:
            return
        label = barcode
        try:
            lookup = lookup_product_prices(barcode, size=1)
            label = f"{lookup.product.name} ({lookup.product.brands})" if lookup.product.brands else lookup.product.name
        except OpenPricesError:
            pass  # Barcode nicht in Open Prices bekannt - trotzdem als eingegeben verknuepfen
        self._selected = {"barcode": barcode, "label": label}
        self.accept()

    def _stop(self) -> None:
        self._stopped = True
        self.reject()

    def was_stopped(self) -> bool:
        return self._stopped

    def result_data(self) -> dict | None:
        return self._selected


class CampYearDialog(QDialog):
    """Dialog zum Anlegen eines neuen Camp-Jahrs."""

    def __init__(
        self,
        default_year: int,
        parent: QWidget | None = None,
        *,
        initial: dict | None = None,
        title: str | None = None,
        allow_year_edit: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title or ("Zeltlagerwoche bearbeiten" if initial else "Neue Zeltlagerwoche"))
        initial = initial or {}

        self.year_spin = QSpinBox(self)
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setValue(initial.get("year", default_year))
        self.year_spin.setEnabled(allow_year_edit)

        self.name_edit = QLineEdit(self)
        self.name_edit.setText(initial.get("name") or f"Zeltlager {default_year}")

        start_date = initial.get("start_date")
        self.start_date_edit = QDateEdit(self)
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDate(QDate(start_date.year, start_date.month, start_date.day) if start_date else QDate(default_year, 8, 1))

        end_date = initial.get("end_date")
        self.end_date_edit = QDateEdit(self)
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDate(QDate(end_date.year, end_date.month, end_date.day) if end_date else QDate(default_year, 8, 10))

        self.notes_edit = QTextEdit(self)
        self.notes_edit.setPlainText(initial.get("notes") or "")
        self.notes_edit.setFixedHeight(60)

        form = QFormLayout()
        form.addRow("Jahr", self.year_spin)
        form.addRow("Name", self.name_edit)
        form.addRow("Startdatum", self.start_date_edit)
        form.addRow("Enddatum", self.end_date_edit)
        form.addRow("Notizen", self.notes_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow(form)
        layout.addRow(buttons)

    def result_data(self) -> dict:
        return {
            "year": self.year_spin.value(),
            "name": self.name_edit.text().strip() or None,
            "start_date": self.start_date_edit.date().toPython(),
            "end_date": self.end_date_edit.date().toPython(),
            "notes": self.notes_edit.toPlainText().strip() or None,
        }


class DayResponsibleDialog(QDialog):
    """Dialog zur Pflege des Tagesverantwortlichen im Wochenplan."""

    def __init__(
        self,
        day_label: str,
        current_person: str = "",
        current_notes: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Tagesverantwortlich - {day_label}")

        self.person_edit = QLineEdit(self)
        self.person_edit.setText(current_person)
        self.person_edit.setPlaceholderText("Name der/des Verantwortlichen")

        self.notes_edit = QTextEdit(self)
        self.notes_edit.setPlainText(current_notes)
        self.notes_edit.setFixedHeight(60)

        form = QFormLayout()
        form.addRow("Verantwortlich", self.person_edit)
        form.addRow("Notizen", self.notes_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow(form)
        layout.addRow(buttons)

    def result_data(self) -> dict:
        return {
            "responsible_person": self.person_edit.text().strip() or None,
            "notes": self.notes_edit.toPlainText().strip() or None,
        }


TARGET_GROUP_OPTIONS = ("Alle", "Kinder", "Betreuer")
NO_TARGET_GROUP_LABEL = "- keine Angabe -"


class MealCellDialog(QDialog):
    """Dialog zum Bearbeiten einer einzelnen Mahlzeit im Wochenplan-Raster."""

    def __init__(
        self,
        cell_label: str,
        recipes: list[tuple[int, str]],
        *,
        current_recipe_id: int | None,
        current_portions: int,
        current_target_group: str,
        current_status: str,
        current_notes: str,
        status_options: tuple[str, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(cell_label)

        self.recipe_combo = QComboBox(self)
        self.recipe_combo.addItem("- kein Rezept -", None)
        for recipe_id, name in recipes:
            self.recipe_combo.addItem(name, recipe_id)
        recipe_index = self.recipe_combo.findData(current_recipe_id)
        self.recipe_combo.setCurrentIndex(recipe_index if recipe_index >= 0 else 0)

        self.portions_spin = QSpinBox(self)
        self.portions_spin.setRange(0, 2000)
        self.portions_spin.setValue(current_portions)

        self.target_group_combo = QComboBox(self)
        self.target_group_combo.addItem(NO_TARGET_GROUP_LABEL)
        self.target_group_combo.addItems(TARGET_GROUP_OPTIONS)
        if current_target_group and current_target_group not in TARGET_GROUP_OPTIONS:
            self.target_group_combo.addItem(current_target_group)
        target_group_index = self.target_group_combo.findText(current_target_group) if current_target_group else 0
        self.target_group_combo.setCurrentIndex(target_group_index if target_group_index >= 0 else 0)

        self.status_combo = QComboBox(self)
        self.status_combo.addItems(status_options)
        status_index = self.status_combo.findText(current_status)
        self.status_combo.setCurrentIndex(status_index if status_index >= 0 else 0)

        self.notes_edit = QTextEdit(self)
        self.notes_edit.setPlainText(current_notes)
        self.notes_edit.setFixedHeight(60)

        form = QFormLayout()
        form.addRow("Rezept", self.recipe_combo)
        form.addRow("Portionen", self.portions_spin)
        form.addRow("Zielgruppe", self.target_group_combo)
        form.addRow("Status", self.status_combo)
        form.addRow("Notizen", self.notes_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow(form)
        layout.addRow(buttons)

    def result_data(self) -> dict:
        target_group_text = self.target_group_combo.currentText()
        return {
            "recipe_id": self.recipe_combo.currentData(),
            "planned_portions": self.portions_spin.value() or None,
            "target_group": target_group_text if target_group_text != NO_TARGET_GROUP_LABEL else None,
            "status": self.status_combo.currentText(),
            "notes": self.notes_edit.toPlainText().strip() or None,
        }


class ScaleRecipeDialog(QDialog):
    """Dialog zum Skalieren aller Zutatenmengen eines Rezepts mit einem Faktor."""

    def __init__(self, suggested_factor: Decimal | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mengen skalieren")

        self.factor_spin = QDoubleSpinBox(self)
        self.factor_spin.setDecimals(3)
        self.factor_spin.setRange(0.001, 100)
        self.factor_spin.setSingleStep(0.05)
        self.factor_spin.setValue(float(suggested_factor) if suggested_factor else 1.0)

        hint_text = (
            f"Vorschlag aus letztem Feedback: Faktor {suggested_factor}"
            if suggested_factor is not None
            else "Kein Feedback-Faktor bekannt - bitte Faktor manuell eintragen."
        )
        self.hint_label = QLabel(hint_text, self)
        self.hint_label.setWordWrap(True)

        self.reason_edit = QLineEdit(self)
        self.reason_edit.setPlaceholderText("z. B. 'zu viel übrig geblieben 2026'")

        form = QFormLayout()
        form.addRow(self.hint_label)
        form.addRow("Faktor", self.factor_spin)
        form.addRow("Grund (optional)", self.reason_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow(form)
        layout.addRow(buttons)

    def result_data(self) -> dict:
        return {
            "factor": Decimal(str(self.factor_spin.value())),
            "reason": self.reason_edit.text().strip() or None,
        }


class RecipeStepDialog(QDialog):
    """Dialog zum Anlegen oder Bearbeiten eines Arbeitsschritts der Kochanleitung."""

    def __init__(self, parent: QWidget | None = None, *, initial: dict | None = None) -> None:
        super().__init__(parent)
        initial = initial or {}
        self._delete_requested = False
        self.setWindowTitle("Arbeitsschritt bearbeiten" if initial else "Arbeitsschritt hinzufügen")

        self.title_edit = QLineEdit(self)
        self.title_edit.setText(initial.get("title") or "")
        self.title_edit.setPlaceholderText("z. B. 'Kartoffeln vorgaren'")

        self.description_edit = QTextEdit(self)
        self.description_edit.setPlainText(initial.get("description") or "")
        self.description_edit.setFixedHeight(90)

        self.duration_spin = QSpinBox(self)
        self.duration_spin.setRange(0, 600)
        self.duration_spin.setSuffix(" Min.")
        self.duration_spin.setValue(initial.get("duration_minutes") or 0)

        form = QFormLayout()
        form.addRow("Titel", self.title_edit)
        form.addRow("Anweisung", self.description_edit)
        form.addRow("Dauer", self.duration_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        if initial:
            delete_button = buttons.addButton("Schritt entfernen", QDialogButtonBox.ButtonRole.DestructiveRole)
            delete_button.clicked.connect(self._request_delete)

        layout = QFormLayout(self)
        layout.addRow(form)
        layout.addRow(buttons)

    def _request_delete(self) -> None:
        self._delete_requested = True
        self.accept()

    def was_delete_requested(self) -> bool:
        return self._delete_requested

    def result_data(self) -> dict | None:
        title = self.title_edit.text().strip()
        description = self.description_edit.toPlainText().strip()
        if not title and not description:
            return None
        return {
            "title": title or None,
            "description": description or None,
            "duration_minutes": self.duration_spin.value() or None,
        }
