from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.config import AppConfig
from app.db import initialize_database, session_scope
from app.models import Ingredient, IngredientPrice, IngredientPriceProfile
from app.services import open_prices_category_service, open_prices_service
from app.ui.theme import apply_theme
from app.utils.paths import get_user_settings_path


@dataclass(slots=True)
class QueueItem:
    ingredient_id: int
    profile_id: int
    name: str
    unit: str | None
    category_tag: str


def load_saved_database_path() -> Path | None:
    settings_path = get_user_settings_path()
    if not settings_path.exists():
        return None
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    raw_path = data.get("database_path")
    return Path(raw_path) if raw_path else None


class YearDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preisjahr waehlen")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Fuer welches Jahr sollen die Open-Prices-Preise gespeichert werden?", self))
        self.year_spin = QSpinBox(self)
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setValue(datetime.now().year)
        layout.addWidget(self.year_spin)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def year(self) -> int:
        return self.year_spin.value()


class QuickAssignWindow(QWidget):
    def __init__(self, session_factory, year: int) -> None:
        super().__init__()
        self.session_factory = session_factory
        self.year = year
        self.queue = self._load_queue()
        self.index = 0
        self.candidates: list[open_prices_category_service.ProductCandidate] = []

        self.setWindowTitle("Open Prices Schnellzuordnung")
        self.resize(760, 620)
        self._build_ui()
        self._load_current()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.progress_label = QLabel("", self)
        self.progress_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.progress_label)

        self.detail_label = QLabel("", self)
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        self.result_list = QListWidget(self)
        self.result_list.setIconSize(QSize(86, 86))
        self.result_list.itemDoubleClicked.connect(lambda _item: self._accept_selected())
        layout.addWidget(self.result_list, stretch=1)

        button_row = QHBoxLayout()
        accept_button = QPushButton("Produkt uebernehmen + Preis speichern", self)
        accept_button.clicked.connect(self._accept_selected)
        skip_button = QPushButton("Ueberspringen", self)
        skip_button.clicked.connect(self._skip)
        stop_button = QPushButton("Beenden", self)
        stop_button.clicked.connect(self.close)
        button_row.addWidget(accept_button)
        button_row.addWidget(skip_button)
        button_row.addStretch(1)
        button_row.addWidget(stop_button)
        layout.addLayout(button_row)

    def _load_queue(self) -> list[QueueItem]:
        with session_scope(self.session_factory) as session:
            ingredients = (
                session.execute(
                    select(Ingredient)
                    .join(IngredientPriceProfile)
                    .where(
                        Ingredient.active.is_(True),
                        Ingredient.barcode.is_(None),
                        IngredientPriceProfile.category_tag.is_not(None),
                    )
                    .order_by(Ingredient.name)
                )
                .scalars()
                .all()
            )
            return [
                QueueItem(
                    ingredient_id=ingredient.id,
                    profile_id=ingredient.price_profile.id,
                    name=ingredient.name,
                    unit=ingredient.default_unit,
                    category_tag=ingredient.price_profile.category_tag or "",
                )
                for ingredient in ingredients
                if ingredient.price_profile is not None
            ]

    def _load_current(self) -> None:
        self.result_list.clear()
        self.candidates = []
        if self.index >= len(self.queue):
            QMessageBox.information(self, "Fertig", "Alle Zutaten im Schnelllauf wurden bearbeitet oder uebersprungen.")
            self.close()
            return

        item = self.queue[self.index]
        self.progress_label.setText(f"{self.index + 1}/{len(self.queue)}: {item.name}")
        self.detail_label.setText(f"Einheit: {item.unit or '-'} | Tag: {item.category_tag} | lade Produktkandidaten ...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            with session_scope(self.session_factory) as session:
                profile = session.get(IngredientPriceProfile, item.profile_id)
                if profile is None:
                    self._skip()
                    return
                self.candidates = open_prices_category_service.find_product_candidates_for_profile(
                    profile,
                    size=60,
                    pages=4,
                )[:25]
        except open_prices_service.OpenPricesError as exc:
            QMessageBox.warning(self, "Open Prices", str(exc))
            self.candidates = []
        finally:
            QApplication.restoreOverrideCursor()

        self.detail_label.setText(
            f"Einheit: {item.unit or '-'} | Tag: {item.category_tag} | {len(self.candidates)} deutsche Kandidaten"
        )
        for candidate in self.candidates:
            list_item = QListWidgetItem(self._candidate_label(candidate, item.unit))
            if candidate.image_url:
                image_bytes = open_prices_service.fetch_image_bytes(candidate.image_url, timeout=8)
                if image_bytes:
                    pixmap = QPixmap()
                    if pixmap.loadFromData(image_bytes):
                        list_item.setIcon(QIcon(pixmap))
            self.result_list.addItem(list_item)

    def _candidate_label(self, candidate: open_prices_category_service.ProductCandidate, unit: str | None) -> str:
        date_text = candidate.price_date.isoformat() if candidate.price_date else "Datum unbekannt"
        brand_text = f" ({candidate.brands})" if candidate.brands else ""
        quantity_text = f" | Packung: {candidate.quantity}" if candidate.quantity else ""
        price_preview = self._price_preview(candidate, unit)
        store_text = f" | {candidate.store_name}" if candidate.store_name else ""
        return (
            f"{candidate.product_name}{brand_text}{quantity_text}\n"
            f"Barcode {candidate.product_code} | {candidate.price} {candidate.currency} Packungspreis"
            f"{price_preview} | {date_text}{store_text}"
        )

    def _price_preview(self, candidate: open_prices_category_service.ProductCandidate, unit: str | None) -> str:
        target_unit = _clean_target_unit(unit)
        if target_unit is None:
            return ""
        observation = _candidate_to_observation(candidate)
        price = open_prices_service.build_ingredient_price_from_observation(
            0,
            observation,
            product_quantity=candidate.quantity,
            target_unit=target_unit,
        )
        if price.unit == target_unit:
            return f" | = {price.price_per_unit} {candidate.currency}/{price.unit}"
        return " | Grundpreis nicht sicher berechenbar"

    def _accept_selected(self) -> None:
        row = self.result_list.currentRow()
        if row < 0 or row >= len(self.candidates):
            QMessageBox.warning(self, "Auswahl", "Bitte zuerst ein Produkt auswaehlen.")
            return
        queue_item = self.queue[self.index]
        candidate = self.candidates[row]
        target_unit = _clean_target_unit(queue_item.unit)

        with session_scope(self.session_factory) as session:
            ingredient = session.get(Ingredient, queue_item.ingredient_id)
            if ingredient is None:
                self._skip()
                return
            open_prices_category_service.assign_product_to_ingredient(ingredient, candidate)

            observation = _candidate_to_observation(candidate)
            price_record = open_prices_service.build_ingredient_price_from_observation(
                ingredient.id,
                observation,
                product_quantity=candidate.quantity,
                target_unit=target_unit,
                notes_prefix=f"Schnellzuordnung Open Prices | Produkt: {candidate.product_name} | Barcode: {candidate.product_code}",
            )
            price_record.year = self.year
            session.add(price_record)

        self.index += 1
        self._load_current()

    def _skip(self) -> None:
        self.index += 1
        self._load_current()


def _candidate_to_observation(candidate: open_prices_category_service.ProductCandidate) -> open_prices_service.OpenPriceObservation:
    return open_prices_service.OpenPriceObservation(
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


def _clean_target_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    cleaned = unit.strip().lower()
    for prefix in ("€/", "eur/"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    if cleaned in {"stueck", "stück"}:
        cleaned = "stk"
    return cleaned or None


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)

    saved_path = load_saved_database_path()
    default_config = AppConfig.load(project_root=PROJECT_ROOT)
    config = AppConfig.load(project_root=PROJECT_ROOT, database_path=saved_path or default_config.database_path)
    _config, _engine, session_factory = initialize_database(config)

    year_dialog = YearDialog()
    if year_dialog.exec() != QDialog.DialogCode.Accepted:
        return 0

    window = QuickAssignWindow(session_factory, year_dialog.year())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
