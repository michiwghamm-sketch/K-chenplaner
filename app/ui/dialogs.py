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
