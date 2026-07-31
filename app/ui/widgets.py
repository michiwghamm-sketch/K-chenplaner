from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QVBoxLayout, QWidget

from app.ui.theme import BORDER, BORDER_STRONG, ORANGE, TEXT_MUTED

# Ampel-Farben fuer Status/Warnungen bleiben funktional (gruen/gelb/rot) und sind
# bewusst unabhaengig von der Kolping-Markenfarbe Orange, damit "kritisch" nicht
# mit dem Marken-Akzent verwechselt wird.
COLOR_OK = "#1e7d34"
COLOR_WARNING = "#b8860b"
COLOR_CRITICAL = "#b3261e"
COLOR_INFO = "#1a5fb4"

_STATUS_COLORS = {
    "ok": COLOR_OK,
    "warnung": COLOR_WARNING,
    "kritisch": COLOR_CRITICAL,
    "info": COLOR_INFO,
}

# Einheitliche Ernaehrungstyp-Farben, gemeinsam genutzt von Rezepten, Dashboard und Wochenplan.
DIET_TYPE_COLORS = {"Vegetarisch": COLOR_OK, "Vegan": COLOR_WARNING, "Fleisch": COLOR_CRITICAL}
UNKNOWN_DIET_TYPE_COLOR = BORDER_STRONG


class PageHeader(QWidget):
    """Seitentitel im Stil der Kolpingjugend-Regensburg-Website (grosse, halbfette Ueberschrift mit Orange-Akzent)."""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 10)
        layout.setSpacing(2)

        title_label = QLabel(title, self)
        title_label.setProperty("role", "pageTitle")
        layout.addWidget(title_label)

        rule = QWidget(self)
        rule.setFixedHeight(3)
        rule.setFixedWidth(48)
        rule.setStyleSheet(f"background-color: {ORANGE}; border-radius: 1px;")
        layout.addWidget(rule)

        if subtitle:
            subtitle_label = QLabel(subtitle, self)
            subtitle_label.setProperty("role", "pageSubtitle")
            layout.addWidget(subtitle_label)


class StatusBadge(QLabel):
    """Farbiges Label fuer Status-/Warnhinweise (gruen/gelb/rot/blau)."""

    def __init__(self, text: str = "", level: str = "info", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.set_level(level)
        self.setMargin(4)

    def set_level(self, level: str) -> None:
        color = _STATUS_COLORS.get(level, COLOR_INFO)
        self.setStyleSheet(
            f"QLabel {{ background-color: {color}; color: white; border-radius: 4px; padding: 2px 8px; }}"
        )


class SearchBar(QWidget):
    """Suchfeld mit Debounce-freiem textChanged-Signal, das die UI-Views einbinden koennen."""

    text_changed = Signal(str)

    def __init__(self, placeholder: str = "Suchen...", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.input = QLineEdit(self)
        self.input.setPlaceholderText(placeholder)
        self.input.textChanged.connect(self.text_changed)
        layout.addWidget(self.input)

    def text(self) -> str:
        return self.input.text()

    def clear(self) -> None:
        self.input.clear()


class UnitComboBox(QComboBox):
    """Dropdown fuer Mengeneinheiten aus dem zentralen Einheiten-Pool (siehe unit_service).

    Bewusst nicht editierbar - neue Einheiten muessen ueber die Pool-Verwaltung angelegt werden,
    damit keine neuen Freitext-Varianten (wie frueher '€/kg') mehr in die Datenbank gelangen.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

    def set_units(self, units: list[str], *, allow_empty: bool = True) -> None:
        self.clear()
        if allow_empty:
            self.addItem("", None)
        for unit in units:
            self.addItem(unit, unit)

    def set_current_unit(self, unit: str | None) -> None:
        index = self.findData(unit)
        if index < 0 and unit:
            # Wert steht (noch) nicht im Pool, z. B. unbereinigte Altdaten - trotzdem anzeigen,
            # damit er beim Speichern nicht unbemerkt verloren geht.
            self.addItem(f"{unit} (nicht im Pool)", unit)
            index = self.count() - 1
        self.setCurrentIndex(max(index, 0))

    def current_unit(self) -> str | None:
        return self.currentData()


class KpiCard(QWidget):
    """Kleine Kennzahlen-Kachel fuer das Dashboard."""

    def __init__(self, title: str, value: str = "-", level: str = "info", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)

        self.value_label = QLabel(value, self)
        self.value_label.setStyleSheet("font-size: 22px; font-weight: 600;")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        title_label = QLabel(title, self)
        title_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")

        layout.addWidget(self.value_label)
        layout.addWidget(title_label)

        self.setStyleSheet(f"KpiCard {{ border: 1px solid {BORDER}; border-radius: 6px; background: white; }}")
        self.set_level(level)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)

    def set_level(self, level: str) -> None:
        color = _STATUS_COLORS.get(level, COLOR_INFO)
        self.value_label.setStyleSheet(f"font-size: 22px; font-weight: 600; color: {color};")


@dataclass(slots=True)
class RankingEntry:
    label: str
    value: float
    value_text: str
    color: str = ORANGE


class RankingList(QWidget):
    """Lesbare Rangliste: Name links (voller Text, kein abgeschnittenes Achsen-Label), ein
    proportionaler Balken und der Wert rechts. Ersetzt QtChart-Balkendiagramme mit
    Kategorie-Achse, deren Beschriftungen bei vielen/langen Namen unlesbar werden."""

    BAR_TRACK_WIDTH = 140
    BAR_HEIGHT = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)

    def set_entries(self, entries: list[RankingEntry]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        if not entries:
            empty_label = QLabel("Keine Daten.", self)
            empty_label.setStyleSheet(f"color: {TEXT_MUTED};")
            self._layout.addWidget(empty_label)
            return

        max_value = max((entry.value for entry in entries), default=0) or 1
        for entry in entries:
            row = QHBoxLayout()
            row.setSpacing(8)

            name_label = QLabel(entry.label, self)
            name_label.setWordWrap(True)
            name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            row.addWidget(name_label, stretch=1)

            track = QWidget(self)
            track.setFixedSize(self.BAR_TRACK_WIDTH, self.BAR_HEIGHT)
            track.setStyleSheet(f"background-color: {BORDER}; border-radius: 3px;")
            bar_width = max(4, int(self.BAR_TRACK_WIDTH * entry.value / max_value))
            bar = QWidget(track)
            bar.setGeometry(0, 0, bar_width, self.BAR_HEIGHT)
            bar.setStyleSheet(f"background-color: {entry.color}; border-radius: 3px;")
            row.addWidget(track)

            value_label = QLabel(entry.value_text, self)
            value_label.setMinimumWidth(64)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(value_label)

            self._layout.addLayout(row)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
