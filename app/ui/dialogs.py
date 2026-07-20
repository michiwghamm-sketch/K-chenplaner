from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTextEdit,
    QWidget,
)


def confirm_dialog(parent: QWidget | None, title: str, message: str) -> bool:
    """Bestaetigungsdialog vor kritischen Aktionen (Loeschen, Deaktivieren, Restore)."""
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


class AddRecipeIngredientDialog(QDialog):
    """Dialog zum Hinzufuegen einer Zutat zu einem Rezept mit Menge und Einheit."""

    def __init__(self, ingredients: list[tuple[int, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Zutat hinzufuegen")
        self._ingredients = ingredients

        self.ingredient_combo = QComboBox(self)
        for ingredient_id, name in ingredients:
            self.ingredient_combo.addItem(name, ingredient_id)

        self.quantity_spin = QDoubleSpinBox(self)
        self.quantity_spin.setDecimals(3)
        self.quantity_spin.setRange(0.001, 100000)
        self.quantity_spin.setValue(1)

        self.unit_edit = QLineEdit(self)
        self.notes_edit = QLineEdit(self)

        form = QFormLayout()
        form.addRow("Zutat", self.ingredient_combo)
        form.addRow("Menge", self.quantity_spin)
        form.addRow("Einheit", self.unit_edit)
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
        return {
            "ingredient_id": self.ingredient_combo.currentData(),
            "quantity": Decimal(str(self.quantity_spin.value())),
            "unit": self.unit_edit.text().strip(),
            "notes": self.notes_edit.text().strip() or None,
        }


class AddPriceDialog(QDialog):
    """Dialog zum Erfassen eines neuen Zutatenpreises."""

    def __init__(self, ingredients: list[tuple[int, str]], default_year: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preis erfassen")

        self.ingredient_combo = QComboBox(self)
        for ingredient_id, name in ingredients:
            self.ingredient_combo.addItem(name, ingredient_id)

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


class CampYearDialog(QDialog):
    """Dialog zum Anlegen eines neuen Camp-Jahrs."""

    def __init__(self, default_year: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neues Camp-Jahr")

        self.year_spin = QSpinBox(self)
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setValue(default_year)

        self.name_edit = QLineEdit(self)
        self.name_edit.setText(f"Zeltlager {default_year}")

        self.start_date_edit = QDateEdit(self)
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDate(QDate(default_year, 8, 1))

        self.end_date_edit = QDateEdit(self)
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDate(QDate(default_year, 8, 10))

        self.notes_edit = QTextEdit(self)
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
