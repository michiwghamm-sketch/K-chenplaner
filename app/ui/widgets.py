from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

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
        title_label.setStyleSheet("color: palette(mid); font-size: 12px;")

        layout.addWidget(self.value_label)
        layout.addWidget(title_label)

        self.setStyleSheet(
            "KpiCard { border: 1px solid palette(mid); border-radius: 6px; background: palette(base); }"
        )
        self.set_level(level)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)

    def set_level(self, level: str) -> None:
        color = _STATUS_COLORS.get(level, COLOR_INFO)
        self.value_label.setStyleSheet(f"font-size: 22px; font-weight: 600; color: {color};")
