from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget

NAV_ITEMS = (
    ("dashboard", "Dashboard"),
    ("planning", "Wochenplan"),
    ("recipes", "Rezepte"),
    ("ingredients", "Zutaten"),
    ("shopping", "Einkaufsliste"),
    ("feedback", "Feedback"),
    ("import_export", "Export & Backup"),
    ("settings", "Einstellungen"),
)


class Sidebar(QListWidget):
    """Seitenleiste zur Navigation zwischen den App-Modulen."""

    page_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(190)
        self.setObjectName("Sidebar")

        for key, label in NAV_ITEMS:
            item = QListWidgetItem(label)
            item.setData(1000, key)
            self.addItem(item)

        self.currentItemChanged.connect(self._on_item_changed)
        self.setCurrentRow(0)

    def _on_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is not None:
            self.page_selected.emit(current.data(1000))
