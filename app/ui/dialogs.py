from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
import random
import re
from types import SimpleNamespace

from PySide6.QtCore import QDate, QObject, QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
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
from app.services import open_prices_category_service, open_prices_service, shopping_service
from app.services.sync_service import SyncConflict
from app.ui.widgets import UnitComboBox


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


@dataclass(slots=True)
class RecipeIngredientChoice:
    """Eine im 'Zutat hinzufuegen/bearbeiten'-Dialog auswaehlbare Zutat, mitsamt den Einheiten,
    die fuer sie im Rezept erlaubt sind (siehe unit_service.compatible_units)."""

    id: int
    name: str
    default_unit: str | None
    compatible_units: list[str]


class AddRecipeIngredientDialog(QDialog):
    """Dialog zum Hinzufügen oder Bearbeiten einer Rezeptzutat (Menge, Einheit, Teilstück).

    Die Einheit ist bewusst auf die zur gewaehlten Zutat passenden Einheiten eingeschraenkt
    (gleiche Art wie ihre Standardeinheit, z. B. kg/g) - eine Rezeptzutat soll nicht irgendeine
    beliebige Poolschreibweise wie 'Zehe' fuer eine in kg gefuehrte Zutat verwenden koennen.
    """

    def __init__(
        self,
        ingredients: list[RecipeIngredientChoice],
        components: list[tuple[int, str]],
        all_units: list[str],
        parent: QWidget | None = None,
        *,
        initial: dict | None = None,
        title: str | None = None,
    ) -> None:
        super().__init__(parent)
        initial = initial or {}
        # Eine "ingredient_id" ist nur gesetzt, wenn eine bestehende Rezeptzutat bearbeitet wird -
        # initial kann beim Neuanlegen trotzdem nicht-leer sein (z. B. {"component_id": ...}, wenn
        # "+ Zutat" innerhalb eines bestimmten Teilstuecks geklickt wurde), daher reicht ein reines
        # bool(initial) hier nicht aus (zeigte bisher faelschlich "Zutat entfernen" beim Neuanlegen).
        is_editing_existing = "ingredient_id" in initial
        self._delete_requested = False
        self._add_another_requested = False
        self._choices_by_id = {choice.id: choice for choice in ingredients}
        self._all_units = all_units
        self.setWindowTitle(title or ("Zutat bearbeiten" if is_editing_existing else "Zutat hinzufügen"))

        self.ingredient_combo = QComboBox(self)
        self.ingredient_combo.setEditable(True)
        self.ingredient_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for choice in ingredients:
            self.ingredient_combo.addItem(choice.name, choice.id)
        ingredient_index = self.ingredient_combo.findData(initial.get("ingredient_id"))
        if ingredient_index >= 0:
            self.ingredient_combo.setCurrentIndex(ingredient_index)

        self.component_combo = QComboBox(self)
        self.component_combo.addItem(NO_COMPONENT_LABEL, None)
        for component_id, name in components:
            self.component_combo.addItem(name, component_id)
        component_index = self.component_combo.findData(initial.get("component_id"))
        self.component_combo.setCurrentIndex(component_index if component_index >= 0 else 0)

        # Eine bestehende "nach Geschmack"-Zutat (optional=True, Menge 0 - z. B. Salz/Pfeffer aus
        # dem Excel-Import) erkennen wir an Menge 0 + optional; ohne diese Sonderbehandlung wuerde
        # QDoubleSpinBox.setValue(0) unten stillschweigend auf die Mindestmenge 0.001 hochklemmen.
        raw_quantity = initial.get("quantity", 1)
        is_to_taste_initial = bool(initial.get("optional")) and Decimal(str(raw_quantity)) == 0

        self.quantity_spin = QDoubleSpinBox(self)
        self.quantity_spin.setDecimals(3)
        self.quantity_spin.setRange(0.001, 100000)
        self.quantity_spin.setValue(1 if is_to_taste_initial else float(raw_quantity))

        self.to_taste_checkbox = QCheckBox("nach Geschmack (ohne feste Menge)", self)
        self.to_taste_checkbox.setToolTip(
            "Menge wird nicht mitgezählt (z. B. Salz, Pfeffer) - erscheint in Kostenberechnung "
            "und Einkaufsliste ohne feste Menge, statt eine Zahl vorzutäuschen."
        )
        self.to_taste_checkbox.toggled.connect(self.quantity_spin.setDisabled)
        self.to_taste_checkbox.setChecked(is_to_taste_initial)

        self.unit_combo = UnitComboBox(self)
        self.unit_hint_label = QLabel("", self)
        self.unit_hint_label.setWordWrap(True)
        self.notes_edit = QLineEdit(self)
        self.notes_edit.setText(initial.get("notes") or "")

        form = QFormLayout()
        form.addRow("Zutat", self.ingredient_combo)
        form.addRow("Teilstück", self.component_combo)
        form.addRow("Menge", self.quantity_spin)
        form.addRow("", self.to_taste_checkbox)
        form.addRow("Einheit", self.unit_combo)
        form.addRow("", self.unit_hint_label)
        form.addRow("Notizen", self.notes_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        if is_editing_existing:
            delete_button = buttons.addButton("Zutat entfernen", QDialogButtonBox.ButtonRole.DestructiveRole)
            delete_button.clicked.connect(self._request_delete)
        else:
            # Nur beim Neuanlegen sinnvoll: spart bei mehreren Zutaten desselben Teilstuecks
            # (z. B. 15 Zutaten fuer ein neues Rezept) den kompletten Dialog-Neuaufbau je Zutat.
            add_another_button = buttons.addButton("Speichern & nächste Zutat", QDialogButtonBox.ButtonRole.ActionRole)
            add_another_button.clicked.connect(self._accept_and_add_another)

        layout = QFormLayout(self)
        layout.addRow(form)
        layout.addRow(buttons)

        self.ingredient_combo.currentIndexChanged.connect(lambda _index: self._update_unit_options())
        self.ingredient_combo.editTextChanged.connect(lambda _text: self._update_unit_options())
        self._update_unit_options(preserve_current=False)
        if initial.get("unit"):
            self.unit_combo.set_current_unit(initial["unit"])

    def _resolve_current_ingredient_id(self) -> int | None:
        typed_name = self.ingredient_combo.currentText().strip()
        if not typed_name:
            return None
        matching_index = self.ingredient_combo.findText(typed_name, Qt.MatchFlag.MatchFixedString)
        if matching_index >= 0:
            return self.ingredient_combo.itemData(matching_index)
        return None

    def _update_unit_options(self, *, preserve_current: bool = True) -> None:
        previous_unit = self.unit_combo.current_unit() if preserve_current else None
        typed_name = self.ingredient_combo.currentText().strip()
        ingredient_id = self._resolve_current_ingredient_id()
        choice = self._choices_by_id.get(ingredient_id) if ingredient_id is not None else None

        if choice is not None and choice.default_unit:
            options = choice.compatible_units or [choice.default_unit]
            self.unit_hint_label.setText(f"Passend zur Standardeinheit '{choice.default_unit}' von '{choice.name}'.")
        elif choice is not None:
            options = self._all_units
            self.unit_hint_label.setText(
                f"'{choice.name}' hat noch keine Standardeinheit - die hier gewählte Einheit wird übernommen."
            )
        elif typed_name:
            options = self._all_units
            self.unit_hint_label.setText("Neue Zutat - die gewählte Einheit wird als Standardeinheit übernommen.")
        else:
            options = self._all_units
            self.unit_hint_label.setText("")

        self.unit_combo.set_units(options, allow_empty=False)
        if previous_unit and previous_unit in options:
            self.unit_combo.set_current_unit(previous_unit)
        elif choice is not None and choice.default_unit in options:
            self.unit_combo.set_current_unit(choice.default_unit)
        elif options:
            self.unit_combo.setCurrentIndex(0)

    def _request_delete(self) -> None:
        self._delete_requested = True
        self.accept()

    def was_delete_requested(self) -> bool:
        return self._delete_requested

    def _accept_and_add_another(self) -> None:
        self._add_another_requested = True
        self.accept()

    def wants_add_another(self) -> bool:
        return self._add_another_requested

    def result_data(self) -> dict | None:
        unit = self.unit_combo.current_unit()
        if not unit:
            return None
        typed_ingredient_name = self.ingredient_combo.currentText().strip()
        ingredient_id = self._resolve_current_ingredient_id()
        is_to_taste = self.to_taste_checkbox.isChecked()
        return {
            "ingredient_id": ingredient_id,
            "new_ingredient_name": typed_ingredient_name if ingredient_id is None else None,
            "component_id": self.component_combo.currentData(),
            "quantity": Decimal("0") if is_to_taste else Decimal(str(self.quantity_spin.value())),
            "unit": unit,
            "optional": is_to_taste,
            "notes": self.notes_edit.text().strip() or None,
        }


class AddPriceDialog(QDialog):
    """Dialog zum Erfassen eines neuen Zutatenpreises."""

    def __init__(
        self,
        ingredients: list[tuple[int, str]],
        units: list[str],
        default_year: int,
        parent: QWidget | None = None,
        *,
        selected_ingredient_id: int | None = None,
        default_unit: str | None = None,
        default_source: str | None = None,
        default_store: str | None = None,
        default_notes: str | None = None,
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

        self.unit_edit = UnitComboBox(self)
        self.unit_edit.set_units(units, allow_empty=False)
        if default_unit:
            self.unit_edit.set_current_unit(default_unit)
        self.source_edit = QLineEdit(self)
        if default_source:
            self.source_edit.setText(default_source)
        self.store_edit = QLineEdit(self)
        if default_store:
            self.store_edit.setText(default_store)

        self.year_spin = QSpinBox(self)
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setValue(default_year)

        self.notes_edit = QLineEdit(self)
        if default_notes:
            self.notes_edit.setText(default_notes)

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
        unit = self.unit_edit.current_unit()
        if not unit:
            return None
        try:
            price = Decimal(str(self.price_spin.value()))
        except InvalidOperation:
            return None
        return {
            "ingredient_id": self.ingredient_combo.currentData(),
            "price_per_unit": price,
            "unit": unit,
            "source": self.source_edit.text().strip() or None,
            "store": self.store_edit.text().strip() or None,
            "year": self.year_spin.value(),
            "notes": self.notes_edit.text().strip() or None,
        }


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


class ReplaceIngredientDialog(QDialog):
    """Angeboten beim Loeschen einer noch verwendeten Zutat: statt die Loeschung nur abzulehnen,
    kann die Zutat durch eine bestehende ersetzt werden. Alle Verwendungen (Rezepte, Preise,
    Einkaufslisten-Positionen) wandern automatisch zur Ersatzzutat (siehe
    ingredient_service.merge_ingredients), danach wird die Ausgangszutat geloescht - ein
    effektiver Weg, um Dubletten zusammenzufuehren."""

    def __init__(
        self,
        ingredient_name: str,
        usage_lines: list[str],
        candidates: list[tuple[int, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Zutat wird noch verwendet")
        self.setMinimumWidth(440)

        shown_usage = usage_lines[:10]
        usage_text = "\n".join(f"- {line}" for line in shown_usage)
        if len(usage_lines) > 10:
            usage_text += f"\n... und {len(usage_lines) - 10} weitere"

        message = QLabel(
            f"'{ingredient_name}' wird noch verwendet und kann nicht direkt gelöscht werden:\n\n"
            f"{usage_text}\n\n"
            "Du kannst sie stattdessen durch eine bestehende Zutat ersetzen - alle Verwendungen "
            f"wandern automatisch zur ausgewählten Zutat, und '{ingredient_name}' wird danach "
            "gelöscht. Ohne Auswahl bitte abbrechen und stattdessen deaktivieren.",
            self,
        )
        message.setWordWrap(True)

        self.replacement_combo = QComboBox(self)
        self.replacement_combo.setEditable(True)
        self.replacement_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for ingredient_id, name in candidates:
            self.replacement_combo.addItem(name, ingredient_id)
        self.replacement_combo.setCurrentIndex(-1)
        self.replacement_combo.lineEdit().setPlaceholderText("Ersatzzutat suchen...")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Ersetzen und löschen")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(message)
        layout.addWidget(self.replacement_combo)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if self.selected_replacement_id() is None:
            error_dialog(self, "Bitte eine Ersatzzutat aus der Liste auswählen.")
            return
        self.accept()

    def selected_replacement_id(self) -> int | None:
        typed_name = self.replacement_combo.currentText().strip()
        if not typed_name:
            return None
        matching_index = self.replacement_combo.findText(typed_name, Qt.MatchFlag.MatchFixedString)
        if matching_index < 0:
            return None
        return self.replacement_combo.itemData(matching_index)


@dataclass(slots=True)
class ProductSearchResult:
    suggestion: OpenPricesSuggestion
    image_bytes: bytes | None


@dataclass(slots=True)
class OpenPricesCandidateResult:
    candidate: open_prices_category_service.ProductCandidate
    image_bytes: bytes | None


class _OpenPricesCandidateSearchWorker(QObject):
    finished = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        query: str,
        target_unit: str | None,
        category_tag: str | None,
        brand_filter: str,
    ) -> None:
        super().__init__()
        self.query = query
        self.target_unit = target_unit
        self.category_tag = category_tag
        self.brand_filter = brand_filter.lower()

    def run(self) -> None:
        try:
            candidates = self._load_candidates()
        except OpenPricesError as exc:
            self.failed.emit(str(exc))
            return

        if self.brand_filter:
            candidates = [
                candidate
                for candidate in candidates
                if self.brand_filter in (candidate.brands or "").lower()
                or self.brand_filter in candidate.product_name.lower()
            ]

        results: list[OpenPricesCandidateResult] = []
        for candidate in candidates[:30]:
            candidate = _enrich_candidate_from_product_lookup(candidate)
            image_bytes = fetch_image_bytes(candidate.image_url, timeout=8) if candidate.image_url else None
            results.append(OpenPricesCandidateResult(candidate=candidate, image_bytes=image_bytes))
        self.finished.emit(results)

    def _load_candidates(self) -> list[open_prices_category_service.ProductCandidate]:
        candidates: list[open_prices_category_service.ProductCandidate] = []
        barcode = _barcode_digits(self.query)
        if barcode is not None:
            try:
                lookup = open_prices_service.lookup_product_prices(barcode, size=1)
            except OpenPricesError:
                lookup = None
            if lookup is not None and lookup.latest_observation is not None:
                candidates.append(_candidate_from_product_lookup(lookup))

        if self.category_tag:
            profile = SimpleNamespace(category_tag=self.category_tag)
            candidates.extend(open_prices_category_service.find_product_candidates_for_profile(profile, pages=4))

        for suggestion in open_prices_service.suggest_matches_for_query(
            self.query,
            target_unit=self.target_unit,
            limit=10,
            search_size=30,
            max_product_checks=10,
        ):
            observation = suggestion.observation
            candidates.append(
                open_prices_category_service.ProductCandidate(
                    product_code=suggestion.product.code,
                    product_name=suggestion.product.name,
                    brands=suggestion.product.brands,
                    quantity=suggestion.product.quantity,
                    image_url=suggestion.product.image_url,
                    price=observation.price,
                    currency=observation.currency,
                    price_date=observation.date,
                    store_name=observation.store_name,
                    country_code=None,
                    price_count=suggestion.product.price_count,
                )
            )

        deduped: dict[str, open_prices_category_service.ProductCandidate] = {}
        for candidate in candidates:
            if candidate.product_code and candidate.product_code not in deduped:
                deduped[candidate.product_code] = candidate
        return list(deduped.values())


class OpenPricesProductPriceDialog(QDialog):
    """Produktsuche aus Open Prices fuer eine konkrete Zutat, optional mit Tag, Suchbegriff und Marke."""

    def __init__(
        self,
        ingredient_name: str,
        target_unit: str | None,
        profile,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open Prices Produkt suchen")
        self.setMinimumSize(680, 520)
        self._ingredient_name = ingredient_name
        self._target_unit = target_unit
        self._profile = profile
        self._category_tag = profile.category_tag if profile and profile.category_tag else None
        self._results: list[OpenPricesCandidateResult] = []
        self._thread: QThread | None = None
        self._worker: _OpenPricesCandidateSearchWorker | None = None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.query_edit = QLineEdit(self)
        self.query_edit.setText(ingredient_name)
        self.query_edit.returnPressed.connect(self._search)
        self.brand_edit = QLineEdit(self)
        self.brand_edit.setPlaceholderText("optional, z. B. Ja!, Barilla, Gut & Günstig")
        tag_text = profile.category_tag if profile and profile.category_tag else "kein Tag"
        self.tag_label = QLabel(tag_text, self)
        form.addRow("Suchbegriff", self.query_edit)
        form.addRow("Marke", self.brand_edit)
        form.addRow("Open-Prices-Tag", self.tag_label)
        layout.addLayout(form)

        self.search_button = QPushButton("Suchen", self)
        self.search_button.clicked.connect(self._search)
        layout.addWidget(self.search_button)

        self.status_label = QLabel("", self)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.result_list = QListWidget(self)
        self.result_list.setIconSize(QSize(72, 72))
        self.result_list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.result_list, stretch=1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Produkt verwenden")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._search()

    def _search(self) -> None:
        if self._thread is not None:
            return
        self.result_list.clear()
        self._results = []
        self.status_label.setText("Suche laeuft ...")
        self._set_search_running(True)
        query = self.query_edit.text().strip() or self._ingredient_name
        self._thread = QThread(self)
        self._worker = _OpenPricesCandidateSearchWorker(
            query,
            self._target_unit,
            self._category_tag,
            self.brand_edit.text().strip(),
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_search_finished)
        self._worker.failed.connect(self._on_search_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_search_thread)
        self._thread.start()

    def _on_search_finished(self, results: list[OpenPricesCandidateResult]) -> None:
        self._results = results
        for result in results:
            item = QListWidgetItem(self._candidate_label(result.candidate))
            if result.image_bytes:
                pixmap = QPixmap()
                if pixmap.loadFromData(result.image_bytes):
                    item.setIcon(QIcon(pixmap))
            self.result_list.addItem(item)
        self.status_label.setText(f"{len(self._results)} Treffer")
        self._set_search_running(False)

    def _on_search_failed(self, message: str) -> None:
        self.status_label.setText(f"Fehler: {message}")
        self._set_search_running(False)

    def _cleanup_search_thread(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        if self._thread is not None:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None

    def _set_search_running(self, running: bool) -> None:
        self.search_button.setEnabled(not running)
        self.query_edit.setEnabled(not running)
        self.brand_edit.setEnabled(not running)
        self.result_list.setEnabled(not running)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not running)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setEnabled(not running)
        self.progress_bar.setVisible(running)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt hook
        if self._thread is not None:
            event.ignore()
            return
        super().closeEvent(event)

    def _candidate_label(self, candidate: open_prices_category_service.ProductCandidate) -> str:
        date_text = candidate.price_date.isoformat() if candidate.price_date else "Datum unbekannt"
        brand_text = f" ({candidate.brands})" if candidate.brands else ""
        quantity_text = f" | Packung: {candidate.quantity}" if candidate.quantity else ""
        price_text = _price_preview(candidate, self._target_unit)
        store_text = f" | {candidate.store_name}" if candidate.store_name else ""
        return (
            f"{candidate.product_name}{brand_text}{quantity_text}\n"
            f"Barcode {candidate.product_code} | {candidate.price} {candidate.currency}"
            f"{price_text} | {date_text}{store_text}"
        )

    def selected_candidate(self) -> open_prices_category_service.ProductCandidate | None:
        row = self.result_list.currentRow()
        if row < 0 or row >= len(self._results):
            return None
        return self._results[row].candidate


def _price_preview(candidate: open_prices_category_service.ProductCandidate, target_unit: str | None) -> str:
    normalized_target_unit = _clean_unit(target_unit)
    if normalized_target_unit is None:
        return ""
    observation = open_prices_service.OpenPriceObservation(
        product_code=candidate.product_code,
        product_name=candidate.product_name,
        price=candidate.price,
        currency=candidate.currency,
        date=candidate.price_date,
        store_name=candidate.store_name,
        location_name=candidate.store_name,
        proof_type=None,
        price_is_discounted=False,
    )
    price = open_prices_service.build_ingredient_price_from_observation(
        0,
        observation,
        product_quantity=candidate.quantity,
        target_unit=normalized_target_unit,
    )
    if price.unit == normalized_target_unit:
        return f" | = {price.price_per_unit} {candidate.currency}/{price.unit}"
    return " | Grundpreis nicht sicher berechenbar"


def _enrich_candidate_from_product_lookup(
    candidate: open_prices_category_service.ProductCandidate,
) -> open_prices_category_service.ProductCandidate:
    try:
        lookup = open_prices_service.lookup_product_prices(candidate.product_code, size=1)
    except OpenPricesError:
        return candidate
    product = lookup.product
    return replace(
        candidate,
        product_name=product.name or candidate.product_name,
        brands=product.brands or candidate.brands,
        quantity=product.quantity or candidate.quantity,
        image_url=product.image_url or candidate.image_url,
        price_count=product.price_count or candidate.price_count,
    )


def _candidate_from_product_lookup(
    lookup: open_prices_service.OpenPricesLookupResult,
) -> open_prices_category_service.ProductCandidate:
    observation = lookup.latest_observation
    if observation is None:
        raise ValueError("Open Prices lookup has no price observation.")
    return open_prices_category_service.ProductCandidate(
        product_code=lookup.product.code,
        product_name=lookup.product.name,
        brands=lookup.product.brands,
        quantity=lookup.product.quantity,
        image_url=lookup.product.image_url,
        price=observation.price,
        currency=observation.currency,
        price_date=observation.date,
        store_name=observation.store_name,
        country_code=None,
        price_count=lookup.product.price_count,
    )


def _barcode_digits(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    compact = value.replace(" ", "").replace("-", "")
    if len(digits) >= 8 and len(digits) == len(compact):
        return digits
    return None


def _clean_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    cleaned = unit.strip().lower()
    for prefix in ("€/", "eur/"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    if cleaned in {"stueck", "stück"}:
        return "stk"
    return cleaned or None


class _ProductSearchWorker(QObject):
    """Sucht in Open Prices nach Produkten und laedt Vorschaubilder - reine Netzwerkarbeit, kein
    DB-Zugriff (laeuft in einem eigenen QThread, damit die UI waehrenddessen nicht einfriert)."""

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
        self.setWindowTitle("Open Prices suchen")
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

        self.children_spin = QSpinBox(self)
        self.children_spin.setRange(0, 1000)
        self.children_spin.setValue(initial.get("participant_count_children") or 0)

        self.children_vegetarian_spin = QSpinBox(self)
        self.children_vegetarian_spin.setRange(0, 1000)
        self.children_vegetarian_spin.setValue(initial.get("participant_count_children_vegetarian") or 0)

        self.children_meat_spin = QSpinBox(self)
        self.children_meat_spin.setRange(0, 1000)
        self.children_meat_spin.setValue(initial.get("participant_count_children_meat") or 0)

        self.adults_spin = QSpinBox(self)
        self.adults_spin.setRange(0, 1000)
        self.adults_spin.setValue(initial.get("participant_count_adults") or 0)

        self.adults_vegetarian_spin = QSpinBox(self)
        self.adults_vegetarian_spin.setRange(0, 1000)
        self.adults_vegetarian_spin.setValue(initial.get("participant_count_adults_vegetarian") or 0)

        self.adults_meat_spin = QSpinBox(self)
        self.adults_meat_spin.setRange(0, 1000)
        self.adults_meat_spin.setValue(initial.get("participant_count_adults_meat") or 0)

        self.location_edit = QLineEdit(self)
        self.location_edit.setText(initial.get("location") or "")

        self.notes_edit = QTextEdit(self)
        self.notes_edit.setPlainText(initial.get("notes") or "")
        self.notes_edit.setFixedHeight(60)

        form = QFormLayout()
        form.addRow("Jahr", self.year_spin)
        form.addRow("Name", self.name_edit)
        form.addRow("Startdatum", self.start_date_edit)
        form.addRow("Enddatum", self.end_date_edit)
        form.addRow("Ort", self.location_edit)
        form.addRow("Teilnehmer Kinder", self.children_spin)
        form.addRow("   davon Vegetarier", self.children_vegetarian_spin)
        form.addRow("   davon Fleischesser", self.children_meat_spin)
        form.addRow("Teilnehmer Betreuer", self.adults_spin)
        form.addRow("   davon Vegetarier", self.adults_vegetarian_spin)
        form.addRow("   davon Fleischesser", self.adults_meat_spin)
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
            "location": self.location_edit.text().strip() or None,
            "participant_count_children": self.children_spin.value() or None,
            "participant_count_children_vegetarian": self.children_vegetarian_spin.value() or None,
            "participant_count_children_meat": self.children_meat_spin.value() or None,
            "participant_count_adults": self.adults_spin.value() or None,
            "participant_count_adults_vegetarian": self.adults_vegetarian_spin.value() or None,
            "participant_count_adults_meat": self.adults_meat_spin.value() or None,
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
DIET_SCOPE_OPTIONS = ("Alle", "Vegetarisch", "Fleisch")
NO_DIET_SCOPE_LABEL = "- keine Angabe -"


class MealSlotDialog(QDialog):
    """Dialog zum Verwalten aller Gerichte eines Tag/Mahlzeitart-Slots im Wochenplan-Raster.

    Ein Slot kann mehrere Gerichte enthalten (z. B. eine Fleisch- und eine
    Veggi-Variante); jede Tabellenzeile entspricht einem Gericht.
    """

    _COLUMNS = ("Rezept", "Portionen", "Zielgruppe", "Ernährung", "Status", "Notizen")

    def __init__(
        self,
        cell_label: str,
        dishes: list[dict],
        recipes: list[tuple[int, str]],
        *,
        status_options: tuple[str, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(cell_label)
        self.setMinimumWidth(900)
        self._recipes = recipes
        self._status_options = status_options
        self._removed_ids: list[int] = []

        self.table = QTableWidget(0, len(self._COLUMNS), self)
        self.table.setHorizontalHeaderLabels(list(self._COLUMNS))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        # Das Rezept-Feld braucht deutlich mehr Platz als die anderen Spalten, sonst
        # sind Rezeptnamen in der Combobox nicht lesbar.
        for column, width in enumerate((330, 90, 130, 130, 120, 170)):
            self.table.horizontalHeader().resizeSection(column, width)
        self.table.verticalHeader().setVisible(False)

        for dish in dishes:
            self._add_row(dish)
        if not dishes:
            self._add_row(None)

        row_buttons = QHBoxLayout()
        add_button = QPushButton("+ Gericht hinzufügen", self)
        add_button.clicked.connect(lambda: self._add_row(None))
        remove_button = QPushButton("Gericht entfernen", self)
        remove_button.clicked.connect(self._remove_selected_row)
        row_buttons.addWidget(add_button)
        row_buttons.addWidget(remove_button)
        row_buttons.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(row_buttons)
        layout.addWidget(buttons)

    def _add_row(self, dish: dict | None) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        recipe_combo = QComboBox(self.table)
        recipe_combo.setEditable(True)
        recipe_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        recipe_combo.addItem("- kein Rezept -", None)
        for recipe_id, name in self._recipes:
            recipe_combo.addItem(name, recipe_id)
        recipe_combo.setProperty("entry_id", dish["id"] if dish else None)
        if dish and dish.get("recipe_id"):
            index = recipe_combo.findData(dish["recipe_id"])
            recipe_combo.setCurrentIndex(index if index >= 0 else 0)
        self.table.setCellWidget(row, 0, recipe_combo)

        portions_spin = QSpinBox(self.table)
        portions_spin.setRange(0, 2000)
        portions_spin.setValue(dish["planned_portions"] if dish else 0)
        self.table.setCellWidget(row, 1, portions_spin)

        target_group_combo = QComboBox(self.table)
        target_group_combo.addItem(NO_TARGET_GROUP_LABEL)
        target_group_combo.addItems(TARGET_GROUP_OPTIONS)
        current_target_group = dish["target_group"] if dish else ""
        if current_target_group and current_target_group not in TARGET_GROUP_OPTIONS:
            target_group_combo.addItem(current_target_group)
        target_group_index = target_group_combo.findText(current_target_group) if current_target_group else 0
        target_group_combo.setCurrentIndex(target_group_index if target_group_index >= 0 else 0)
        self.table.setCellWidget(row, 2, target_group_combo)

        diet_scope_combo = QComboBox(self.table)
        diet_scope_combo.addItem(NO_DIET_SCOPE_LABEL)
        diet_scope_combo.addItems(DIET_SCOPE_OPTIONS)
        current_diet_scope = dish["diet_scope"] if dish else ""
        if current_diet_scope and current_diet_scope not in DIET_SCOPE_OPTIONS:
            diet_scope_combo.addItem(current_diet_scope)
        diet_scope_index = diet_scope_combo.findText(current_diet_scope) if current_diet_scope else 0
        diet_scope_combo.setCurrentIndex(diet_scope_index if diet_scope_index >= 0 else 0)
        self.table.setCellWidget(row, 3, diet_scope_combo)

        status_combo = QComboBox(self.table)
        status_combo.addItems(self._status_options)
        current_status = dish["status"] if dish else "geplant"
        status_index = status_combo.findText(current_status)
        status_combo.setCurrentIndex(status_index if status_index >= 0 else 0)
        self.table.setCellWidget(row, 4, status_combo)

        notes_edit = QLineEdit(dish["notes"] if dish else "", self.table)
        self.table.setCellWidget(row, 5, notes_edit)

        # Widget-Hoehe (Combo/Spin/LineEdit) ist unabhaengig von der Spaltenbreite bekannt,
        # daher hier direkt und ohne Verzoegerung berechenbar (anders als bei Text mit
        # Zeilenumbruch, siehe PlanningView._reload_grid()).
        self.table.resizeRowsToContents()

    def _remove_selected_row(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        recipe_combo = self.table.cellWidget(row, 0)
        entry_id = recipe_combo.property("entry_id")
        if entry_id is not None:
            self._removed_ids.append(entry_id)
        self.table.removeRow(row)

    def result_data(self) -> dict:
        dishes = []
        for row in range(self.table.rowCount()):
            recipe_combo = self.table.cellWidget(row, 0)
            portions_spin = self.table.cellWidget(row, 1)
            target_group_combo = self.table.cellWidget(row, 2)
            diet_scope_combo = self.table.cellWidget(row, 3)
            status_combo = self.table.cellWidget(row, 4)
            notes_edit = self.table.cellWidget(row, 5)
            target_group_text = target_group_combo.currentText()
            diet_scope_text = diet_scope_combo.currentText()
            dishes.append(
                {
                    "id": recipe_combo.property("entry_id"),
                    "recipe_id": recipe_combo.currentData(),
                    "planned_portions": portions_spin.value() or None,
                    "target_group": target_group_text if target_group_text != NO_TARGET_GROUP_LABEL else None,
                    "diet_scope": diet_scope_text if diet_scope_text != NO_DIET_SCOPE_LABEL else None,
                    "status": status_combo.currentText(),
                    "notes": notes_edit.text().strip() or None,
                }
            )
        return {"dishes": dishes, "removed_ids": self._removed_ids}


class PlanShoppingTripDialog(QDialog):
    """"Einkauf planen"-Assistent: Händler + Teilnehmer wählen, Teilmengen der noch offenen
    Zutaten (mit Gesamtmenge über alle Einkaufstage) auswählen - wird beim Bestätigen
    zufällig gleichmäßig auf die Teilnehmer verteilt (siehe shopping_service.create_shopping_trip)."""

    _COLUMNS = ("Kaufen", "Zutat", "Noch offen", "Menge für diesen Einkauf", "Einheit")

    def __init__(self, groups: list[shopping_service.PlannableIngredientGroup], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Einkauf planen")
        self.setMinimumWidth(720)

        self.store_edit = QLineEdit(self)
        self.store_edit.setPlaceholderText("z. B. Metro")
        self.participants_edit = QLineEdit(self)
        self.participants_edit.setPlaceholderText("z. B. Anna, Ben, Chris (kommagetrennt)")

        form = QFormLayout()
        form.addRow("Händler", self.store_edit)
        form.addRow("Teilnehmer", self.participants_edit)

        self.table = QTableWidget(0, len(self._COLUMNS), self)
        self.table.setHorizontalHeaderLabels(list(self._COLUMNS))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().resizeSection(0, 70)
        self.table.verticalHeader().setVisible(False)
        for group in groups:
            self._add_row(group)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("Zutaten, die bei diesem Einkauf besorgt werden sollen:", self))
        layout.addWidget(self.table)
        layout.addWidget(buttons)

    def _add_row(self, group: shopping_service.PlannableIngredientGroup) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        checkbox = QCheckBox(self.table)
        checkbox.setProperty("ingredient_id", group.ingredient_id)
        checkbox.setProperty("unit", group.unit)
        checkbox_container = QWidget(self.table)
        checkbox_layout = QHBoxLayout(checkbox_container)
        checkbox_layout.addWidget(checkbox)
        checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        self.table.setCellWidget(row, 0, checkbox_container)

        name_item = QTableWidgetItem(group.ingredient_name)
        name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(row, 1, name_item)

        remaining_item = QTableWidgetItem(f"{shopping_service.format_quantity_de(group.remaining_quantity)} {group.unit}")
        remaining_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(row, 2, remaining_item)

        quantity_spin = QDoubleSpinBox(self.table)
        quantity_spin.setDecimals(3)
        quantity_spin.setRange(0, float(group.remaining_quantity))
        quantity_spin.setValue(float(group.remaining_quantity))
        self.table.setCellWidget(row, 3, quantity_spin)

        unit_item = QTableWidgetItem(group.unit)
        unit_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(row, 4, unit_item)

    def result_data(self) -> dict:
        participants = [name.strip() for name in self.participants_edit.text().split(",") if name.strip()]
        selections = []
        for row in range(self.table.rowCount()):
            checkbox = self.table.cellWidget(row, 0).findChild(QCheckBox)
            if not checkbox.isChecked():
                continue
            quantity_spin = self.table.cellWidget(row, 3)
            if quantity_spin.value() <= 0:
                continue
            selections.append((checkbox.property("ingredient_id"), checkbox.property("unit"), Decimal(str(quantity_spin.value()))))
        return {
            "store": self.store_edit.text().strip(),
            "participants": participants,
            "selections": selections,
        }


@dataclass(slots=True)
class TripAllocationRow:
    """Eine Zeile im "Einkauf bearbeiten"-Dialog (siehe EditShoppingTripDialog)."""

    id: int
    ingredient_name: str
    quantity: Decimal
    unit: str
    assigned_to: str | None
    status: str
    # Obergrenze fuer die Mengen-Eingabe: die aktuelle Menge dieser Allocation plus die Menge
    # dieser Zutat, die anderswo in der Liste noch gar keinem Einkauf zugeteilt ist (siehe
    # shopping_service.remaining_quantity_for_ingredient) - mehr kann diese Position nicht
    # bekommen, ohne einer anderen Position ihre Menge wegzunehmen.
    max_quantity: Decimal


class EditShoppingTripDialog(QDialog):
    """Bearbeitet einen bestehenden Einkauf (Trip) als eigenes Objekt: Händler, Teilnehmer und
    die einzelnen Zutaten-Zuteilungen (Person, Status) - inklusive "Neu mischen" und der
    Möglichkeit, einzelne Positionen zu entfernen oder den ganzen Einkauf zu löschen."""

    _COLUMNS = ("Zutat", "Menge", "Zugewiesen an", "Status", "")

    def __init__(
        self,
        *,
        store: str,
        participants_text: str,
        rows: list[TripAllocationRow],
        status_options: tuple[str, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Einkauf bearbeiten - {store}")
        self.setMinimumWidth(760)
        self._status_options = status_options
        self._removed_ids: list[int] = []
        self._delete_requested = False

        self.store_edit = QLineEdit(store, self)
        self.participants_edit = QLineEdit(participants_text, self)
        self.participants_edit.setPlaceholderText("z. B. Anna, Ben, Chris (kommagetrennt)")

        form = QFormLayout()
        form.addRow("Händler", self.store_edit)
        form.addRow("Teilnehmer", self.participants_edit)

        self.table = QTableWidget(0, len(self._COLUMNS), self)
        self.table.setHorizontalHeaderLabels(list(self._COLUMNS))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((220, 100, 160, 130, 90)):
            self.table.horizontalHeader().resizeSection(column, width)
        self.table.verticalHeader().setVisible(False)
        for row_data in rows:
            self._add_row(row_data)

        row_buttons = QHBoxLayout()
        reshuffle_button = QPushButton("Neu mischen", self)
        reshuffle_button.setToolTip("Verteilt die noch offenen (nicht abgehakten) Positionen zufällig neu auf die Teilnehmer.")
        reshuffle_button.clicked.connect(self._reshuffle)
        row_buttons.addWidget(reshuffle_button)
        row_buttons.addStretch(1)
        delete_trip_button = QPushButton("Einkauf komplett löschen", self)
        delete_trip_button.setProperty("role", "secondary")
        delete_trip_button.clicked.connect(self._request_delete)
        row_buttons.addWidget(delete_trip_button)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.table)
        layout.addLayout(row_buttons)
        layout.addWidget(buttons)

    def _add_row(self, row_data: TripAllocationRow) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        name_item = QTableWidgetItem(row_data.ingredient_name)
        name_item.setData(1000, row_data.id)
        name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(row, 0, name_item)

        quantity_spin = QDoubleSpinBox(self.table)
        quantity_spin.setDecimals(3)
        quantity_spin.setSuffix(f" {row_data.unit}" if row_data.unit else "")
        quantity_spin.setRange(0.001, float(max(row_data.max_quantity, row_data.quantity)))
        quantity_spin.setValue(float(row_data.quantity))
        quantity_spin.setToolTip(
            f"Maximal {shopping_service.format_quantity_de(row_data.max_quantity)} {row_data.unit} "
            "(diese Position plus noch nicht verplante Restmenge dieser Zutat)."
        )
        self.table.setCellWidget(row, 1, quantity_spin)

        assigned_edit = QLineEdit(row_data.assigned_to or "", self.table)
        assigned_edit.setPlaceholderText("Person...")
        self.table.setCellWidget(row, 2, assigned_edit)

        status_combo = QComboBox(self.table)
        status_combo.addItems(self._status_options)
        status_index = status_combo.findText(row_data.status)
        status_combo.setCurrentIndex(status_index if status_index >= 0 else 0)
        self.table.setCellWidget(row, 3, status_combo)

        remove_button = QPushButton("Entfernen", self.table)
        remove_button.clicked.connect(lambda: self._remove_row(row_data.id))
        self.table.setCellWidget(row, 4, remove_button)

    def _remove_row(self, allocation_id: int) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(1000) == allocation_id:
                self._removed_ids.append(allocation_id)
                self.table.removeRow(row)
                return

    def _reshuffle(self) -> None:
        participants = [name.strip() for name in self.participants_edit.text().split(",") if name.strip()]
        if not participants:
            error_dialog(self, "Bitte zuerst mindestens einen Teilnehmer eintragen.")
            return
        open_rows = [row for row in range(self.table.rowCount()) if self.table.cellWidget(row, 3).currentText() != "gekauft"]
        shuffled = list(open_rows)
        random.shuffle(shuffled)
        for index, row in enumerate(shuffled):
            person = participants[index % len(participants)]
            self.table.cellWidget(row, 2).setText(person)

    def _request_delete(self) -> None:
        self._delete_requested = True
        self.accept()

    def was_delete_requested(self) -> bool:
        return self._delete_requested

    def result_data(self) -> dict:
        rows = []
        for row in range(self.table.rowCount()):
            quantity_spin = self.table.cellWidget(row, 1)
            assigned_edit = self.table.cellWidget(row, 2)
            status_combo = self.table.cellWidget(row, 3)
            rows.append(
                {
                    "id": self.table.item(row, 0).data(1000),
                    "quantity": Decimal(str(quantity_spin.value())),
                    "assigned_to": assigned_edit.text().strip() or None,
                    "status": status_combo.currentText(),
                }
            )
        return {
            "store": self.store_edit.text().strip(),
            "participants_text": self.participants_edit.text().strip(),
            "rows": rows,
            "removed_ids": self._removed_ids,
        }


class AddManualShoppingItemDialog(QDialog):
    """"Position hinzufügen"-Dialog: haengt eine spontane Position (Sonderwunsch) ohne
    Rezeptbezug an die aktuelle Einkaufsliste an. Zutaten-Auswahl wie bei
    AddRecipeIngredientDialog (editierbare Combobox, tippen legt bei Bedarf eine neue Zutat an) -
    absichtlich OHNE Non-Food-Filter, ein Sonderwunsch darf auch Non-Food sein."""

    def __init__(self, ingredients: list[RecipeIngredientChoice], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Position hinzufügen")
        self._choices_by_id = {choice.id: choice for choice in ingredients}
        self._all_units: list[str] = sorted({unit for choice in ingredients for unit in choice.compatible_units})

        self.ingredient_combo = QComboBox(self)
        self.ingredient_combo.setEditable(True)
        self.ingredient_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for choice in ingredients:
            self.ingredient_combo.addItem(choice.name, choice.id)
        self.ingredient_combo.setCurrentIndex(-1)

        self.quantity_spin = QDoubleSpinBox(self)
        self.quantity_spin.setDecimals(3)
        self.quantity_spin.setRange(0.001, 100000)
        self.quantity_spin.setValue(1)

        self.unit_combo = UnitComboBox(self)
        self.unit_combo.set_units(self._all_units, allow_empty=False)

        self.requested_by_edit = QLineEdit(self)
        self.requested_by_edit.setPlaceholderText("z. B. Björn")
        self.notes_edit = QLineEdit(self)

        form = QFormLayout()
        form.addRow("Zutat", self.ingredient_combo)
        form.addRow("Menge", self.quantity_spin)
        form.addRow("Einheit", self.unit_combo)
        form.addRow("Gewünscht von", self.requested_by_edit)
        form.addRow("Notizen", self.notes_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow(form)
        layout.addRow(buttons)

        self.ingredient_combo.currentIndexChanged.connect(lambda _index: self._update_unit_options())
        self.ingredient_combo.editTextChanged.connect(lambda _text: self._update_unit_options())
        self._update_unit_options()

    def _resolve_current_ingredient_id(self) -> int | None:
        typed_name = self.ingredient_combo.currentText().strip()
        if not typed_name:
            return None
        matching_index = self.ingredient_combo.findText(typed_name, Qt.MatchFlag.MatchFixedString)
        if matching_index >= 0:
            return self.ingredient_combo.itemData(matching_index)
        return None

    def _update_unit_options(self) -> None:
        previous_unit = self.unit_combo.current_unit()
        ingredient_id = self._resolve_current_ingredient_id()
        choice = self._choices_by_id.get(ingredient_id) if ingredient_id is not None else None
        options = choice.compatible_units if choice and choice.compatible_units else self._all_units
        self.unit_combo.set_units(options, allow_empty=False)
        if previous_unit and previous_unit in options:
            self.unit_combo.set_current_unit(previous_unit)
        elif choice and choice.default_unit in options:
            self.unit_combo.set_current_unit(choice.default_unit)

    def result_data(self) -> dict:
        ingredient_id = self._resolve_current_ingredient_id()
        typed_name = self.ingredient_combo.currentText().strip()
        return {
            "ingredient_id": ingredient_id,
            "new_ingredient_name": None if ingredient_id is not None else typed_name,
            "quantity": Decimal(str(self.quantity_spin.value())),
            "unit": self.unit_combo.current_unit(),
            "requested_by": self.requested_by_edit.text().strip() or None,
            "notes": self.notes_edit.text().strip() or None,
        }


@dataclass(slots=True)
class StandardShoppingItemRow:
    """Eine Zeile im "Verbrauchsmittel verwalten"-Dialog."""

    id: int | None
    ingredient_id: int | None
    ingredient_name: str
    quantity: Decimal
    unit: str
    active: bool
    typical_stock_note: str | None
    previous_year_hint: str | None


class ManageStandardItemsDialog(QDialog):
    """Verwaltet die dauerhafte Liste wiederkehrender Verbrauchsmittel (v.a. Non-Food),
    die bei jeder neuen Einkaufsliste automatisch mit uebernommen werden."""

    _COLUMNS = ("Zutat", "Menge", "Einheit", "Lagerbestand-Hinweis", "Aktiv", "")

    def __init__(
        self, rows: list[StandardShoppingItemRow], ingredients: list[RecipeIngredientChoice], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Verbrauchsmittel verwalten")
        self.setMinimumWidth(820)
        self._ingredients = ingredients
        self._removed_ids: list[int] = []

        self.table = QTableWidget(0, len(self._COLUMNS), self)
        self.table.setHorizontalHeaderLabels(list(self._COLUMNS))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((220, 90, 110, 220, 70, 90)):
            self.table.horizontalHeader().resizeSection(column, width)
        self.table.verticalHeader().setVisible(False)
        for row_data in rows:
            self._add_row(row_data)

        add_button = QPushButton("+ Position hinzufügen", self)
        add_button.clicked.connect(lambda: self._add_row(None))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Diese Verbrauchsmittel werden bei jeder neu generierten Einkaufsliste automatisch mit übernommen.", self)
        )
        layout.addWidget(self.table)
        layout.addWidget(add_button)
        layout.addWidget(buttons)

    def _add_row(self, row_data: StandardShoppingItemRow | None) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        ingredient_combo = QComboBox(self.table)
        ingredient_combo.setEditable(True)
        ingredient_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for choice in self._ingredients:
            ingredient_combo.addItem(choice.name, choice.id)
        ingredient_combo.setProperty("entry_id", row_data.id if row_data else None)
        if row_data and row_data.ingredient_id is not None:
            index = ingredient_combo.findData(row_data.ingredient_id)
            ingredient_combo.setCurrentIndex(index if index >= 0 else -1)
        else:
            ingredient_combo.setCurrentIndex(-1)
        self.table.setCellWidget(row, 0, ingredient_combo)

        quantity_spin = QDoubleSpinBox(self.table)
        quantity_spin.setDecimals(3)
        quantity_spin.setRange(0.001, 100000)
        quantity_spin.setValue(float(row_data.quantity) if row_data else 1)
        if row_data and row_data.previous_year_hint:
            quantity_spin.setToolTip(row_data.previous_year_hint)
        self.table.setCellWidget(row, 1, quantity_spin)

        unit_combo = UnitComboBox(self.table)
        all_units = sorted({unit for choice in self._ingredients for unit in choice.compatible_units})
        unit_combo.set_units(all_units, allow_empty=False)
        if row_data and row_data.unit:
            unit_combo.set_current_unit(row_data.unit)
        self.table.setCellWidget(row, 2, unit_combo)

        stock_note_edit = QLineEdit(row_data.typical_stock_note or "" if row_data else "", self.table)
        stock_note_edit.setPlaceholderText("z. B. meist noch ~3 da")
        self.table.setCellWidget(row, 3, stock_note_edit)

        active_checkbox = QCheckBox(self.table)
        active_checkbox.setChecked(row_data.active if row_data else True)
        self.table.setCellWidget(row, 4, active_checkbox)

        remove_button = QPushButton("Entfernen", self.table)
        remove_button.clicked.connect(lambda: self._remove_row(ingredient_combo))
        self.table.setCellWidget(row, 5, remove_button)

    def _remove_row(self, marker_widget: QWidget) -> None:
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 0) is marker_widget:
                entry_id = marker_widget.property("entry_id")
                if entry_id is not None:
                    self._removed_ids.append(entry_id)
                self.table.removeRow(row)
                return

    def result_data(self) -> dict:
        rows = []
        for row in range(self.table.rowCount()):
            ingredient_combo = self.table.cellWidget(row, 0)
            quantity_spin = self.table.cellWidget(row, 1)
            unit_combo = self.table.cellWidget(row, 2)
            stock_note_edit = self.table.cellWidget(row, 3)
            active_checkbox = self.table.cellWidget(row, 4)
            typed_name = ingredient_combo.currentText().strip()
            rows.append(
                {
                    "id": ingredient_combo.property("entry_id"),
                    "ingredient_id": ingredient_combo.currentData(),
                    "new_ingredient_name": None if ingredient_combo.currentData() is not None else typed_name,
                    "quantity": Decimal(str(quantity_spin.value())),
                    "unit": unit_combo.current_unit(),
                    "typical_stock_note": stock_note_edit.text().strip() or None,
                    "active": active_checkbox.isChecked(),
                }
            )
        return {"rows": rows, "removed_ids": self._removed_ids}


class ScaleRecipeDialog(QDialog):
    """Dialog zum Skalieren aller Zutatenmengen eines Rezepts mit einem Faktor oder direkt auf
    eine Zielportionenzahl - beide Felder sind gekoppelt (sofern die aktuelle Portionenzahl des
    Rezepts bekannt ist), damit man z. B. "von 50 auf 100 Portionen" nicht erst im Kopf in einen
    Faktor 2.0 umrechnen muss."""

    def __init__(
        self,
        suggested_factor: Decimal | None,
        parent: QWidget | None = None,
        *,
        current_portions: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mengen skalieren")
        self._current_portions = current_portions
        self._syncing = False

        self.factor_spin = QDoubleSpinBox(self)
        self.factor_spin.setDecimals(3)
        self.factor_spin.setRange(0.001, 100)
        self.factor_spin.setSingleStep(0.05)
        self.factor_spin.setValue(float(suggested_factor) if suggested_factor else 1.0)
        self.factor_spin.valueChanged.connect(self._sync_target_portions_from_factor)

        self.target_portions_spin = QSpinBox(self)
        self.target_portions_spin.setRange(1, 20000)
        self.target_portions_spin.setEnabled(bool(current_portions))
        if current_portions:
            self.target_portions_spin.setValue(max(1, round(current_portions * self.factor_spin.value())))
        self.target_portions_spin.valueChanged.connect(self._sync_factor_from_target_portions)

        hint_text = (
            f"Vorschlag aus letztem Feedback: Faktor {suggested_factor}"
            if suggested_factor is not None
            else "Kein Feedback-Faktor bekannt - bitte Faktor oder Zielportionen manuell eintragen."
        )
        if not current_portions:
            hint_text += " Rezept hat keine Standardportionenzahl - Zielportionen nicht berechenbar."
        self.hint_label = QLabel(hint_text, self)
        self.hint_label.setWordWrap(True)

        self.reason_edit = QLineEdit(self)
        self.reason_edit.setPlaceholderText("z. B. 'zu viel übrig geblieben 2026'")

        form = QFormLayout()
        form.addRow(self.hint_label)
        if current_portions:
            form.addRow(f"Zielportionen (bisher {current_portions})", self.target_portions_spin)
        form.addRow("Faktor", self.factor_spin)
        form.addRow("Grund (optional)", self.reason_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow(form)
        layout.addRow(buttons)

    def _sync_target_portions_from_factor(self, value: float) -> None:
        if self._syncing or not self._current_portions:
            return
        self._syncing = True
        self.target_portions_spin.setValue(max(1, round(self._current_portions * value)))
        self._syncing = False

    def _sync_factor_from_target_portions(self, value: int) -> None:
        if self._syncing or not self._current_portions:
            return
        self._syncing = True
        self.factor_spin.setValue(value / self._current_portions)
        self._syncing = False

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


class SyncConflictDialog(QDialog):
    """Zeigt Datensaetze, die seit dem letzten Cloud-Sync sowohl offline als auch von jemand
    anderem in der Cloud veraendert wurden - pro Zeile muss entschieden werden, welche Version
    gelten soll (siehe sync_service.analyze/apply)."""

    def __init__(self, conflicts: list[SyncConflict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sync-Konflikte")
        self.setMinimumSize(760, 420)
        self._conflicts = conflicts

        info = QLabel(
            f"{len(conflicts)} Eintrag/Einträge wurden seit dem letzten Abgleich sowohl offline "
            "als auch in der Cloud verändert. Bitte pro Zeile auswählen, welche Version gelten soll "
            "- die jeweils andere Version geht dabei verloren.",
            self,
        )
        info.setWordWrap(True)

        self.table = QTableWidget(len(conflicts), 4, self)
        self.table.setHorizontalHeaderLabels(["Tabelle", "Eintrag", "Zeitpunkte", "Auswahl"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)

        self._choice_combos: list[QComboBox] = []
        for row, conflict in enumerate(conflicts):
            self.table.setItem(row, 0, QTableWidgetItem(conflict.table_name))
            self.table.setItem(row, 1, QTableWidgetItem(conflict.label))
            local_time = conflict.local_row.get("updated_at", "-")
            cloud_time = conflict.cloud_row.get("updated_at", "-")
            self.table.setItem(row, 2, QTableWidgetItem(f"Du: {local_time}\nCloud: {cloud_time}"))

            combo = QComboBox(self.table)
            combo.addItem("Meine Version behalten", "local")
            combo.addItem("Cloud-Version behalten", "cloud")
            self.table.setCellWidget(row, 3, combo)
            self._choice_combos.append(combo)
        self.table.resizeRowsToContents()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Übernehmen und synchronisieren")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(buttons)

    def resolutions(self) -> dict[tuple[str, tuple], str]:
        return {conflict.key: combo.currentData() for conflict, combo in zip(self._conflicts, self._choice_combos)}
