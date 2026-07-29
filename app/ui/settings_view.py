from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.context import AppContext
from app.models import Unit
from app.services import unit_service
from app.ui.dialogs import confirm_dialog, error_dialog, info_dialog, prompt_text
from app.ui.widgets import PageHeader, StatusBadge
from app.utils.drive_detection import get_drive_warning
from app.utils.paths import get_user_settings_path

APP_VERSION = "0.1.0 (Prototyp)"


class UnitsManagementDialog(QDialog):
    """Verwaltung des Einheiten-Pools (siehe unit_service): anlegen, umbenennen, (de)aktivieren,
    loeschen. Nur Einheiten aus diesem Pool sind bei Zutaten, Rezepten und Preisen waehlbar."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setWindowTitle("Einheiten verwalten")
        self.setMinimumSize(420, 480)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Nur Einheiten aus diesem Pool koennen bei Zutaten, Rezepten und Preisen ausgewaehlt "
            "werden. Deaktivierte Einheiten bleiben bei bereits gespeicherten Daten sichtbar, "
            "stehen aber in neuen Auswahllisten nicht mehr zur Verfügung.",
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.unit_list = QListWidget(self)
        self.unit_list.currentItemChanged.connect(self._update_toggle_label)
        layout.addWidget(self.unit_list, stretch=1)

        button_row = QHBoxLayout()
        add_button = QPushButton("Hinzufügen", self)
        add_button.clicked.connect(self._add_unit)
        rename_button = QPushButton("Umbenennen", self)
        rename_button.clicked.connect(self._rename_unit)
        self.toggle_button = QPushButton("Deaktivieren", self)
        self.toggle_button.clicked.connect(self._toggle_active)
        delete_button = QPushButton("Löschen", self)
        delete_button.setProperty("role", "secondary")
        delete_button.clicked.connect(self._delete_unit)
        button_row.addWidget(add_button)
        button_row.addWidget(rename_button)
        button_row.addWidget(self.toggle_button)
        button_row.addWidget(delete_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close_buttons.rejected.connect(self.accept)
        layout.addWidget(close_buttons)

        self._reload()

    def _current_unit_id(self) -> int | None:
        item = self.unit_list.currentItem()
        return item.data(1000) if item else None

    def _reload(self) -> None:
        selected_id = self._current_unit_id()
        self.unit_list.clear()
        with self.context.session() as session:
            units = unit_service.list_units(session, active_only=False)
            for unit in units:
                label = unit.name if unit.active else f"{unit.name} (inaktiv)"
                item = QListWidgetItem(label)
                item.setData(1000, unit.id)
                self.unit_list.addItem(item)

        for row in range(self.unit_list.count()):
            if self.unit_list.item(row).data(1000) == selected_id:
                self.unit_list.setCurrentRow(row)
                return
        if self.unit_list.count():
            self.unit_list.setCurrentRow(0)

    def _update_toggle_label(self, *_args: object) -> None:
        unit_id = self._current_unit_id()
        if unit_id is None:
            return
        with self.context.session() as session:
            unit = session.get(Unit, unit_id)
            if unit is not None:
                self.toggle_button.setText("Aktivieren" if not unit.active else "Deaktivieren")

    def _add_unit(self) -> None:
        name = prompt_text(self, "Einheit hinzufügen", "Name der neuen Einheit (z. B. 'Zweig'):")
        if not name:
            return
        with self.context.session() as session:
            try:
                unit_service.add_unit(session, name)
            except ValueError as exc:
                error_dialog(self, str(exc))
                return
        self._reload()

    def _rename_unit(self) -> None:
        unit_id = self._current_unit_id()
        if unit_id is None:
            return
        with self.context.session() as session:
            unit = session.get(Unit, unit_id)
            if unit is None:
                return
            current_name = unit.name
        new_name = prompt_text(self, "Einheit umbenennen", "Neuer Name:", default=current_name)
        if not new_name:
            return
        with self.context.session() as session:
            unit = session.get(Unit, unit_id)
            if unit is None:
                return
            try:
                unit_service.rename_unit(session, unit, new_name)
            except ValueError as exc:
                error_dialog(self, str(exc))
                return
        self._reload()

    def _toggle_active(self) -> None:
        unit_id = self._current_unit_id()
        if unit_id is None:
            return
        with self.context.session() as session:
            unit = session.get(Unit, unit_id)
            if unit is None:
                return
            if unit.active:
                unit_service.deactivate_unit(unit)
            else:
                unit_service.activate_unit(unit)
        self._reload()

    def _delete_unit(self) -> None:
        unit_id = self._current_unit_id()
        if unit_id is None:
            return
        with self.context.session() as session:
            unit = session.get(Unit, unit_id)
            if unit is None:
                return
            name = unit.name
        if not confirm_dialog(self, "Einheit löschen", f"Einheit '{name}' wirklich unwiderruflich löschen?"):
            return
        with self.context.session() as session:
            unit = session.get(Unit, unit_id)
            if unit is None:
                return
            try:
                unit_service.delete_unit(session, unit)
            except ValueError as exc:
                error_dialog(self, str(exc))
                return
        self._reload()


class SettingsView(QWidget):
    """Einstellungen: Datenbankpfad, Laufwerkswarnung, Systeminfo."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(PageHeader("Einstellungen", "Datenbankpfad und Systeminformationen"))

        form = QFormLayout()
        self.db_path_edit = QLineEdit(self)
        self.db_path_edit.setReadOnly(True)
        change_row = QHBoxLayout()
        change_row.addWidget(self.db_path_edit)
        change_button = QPushButton("Ändern...", self)
        change_button.clicked.connect(self._change_database_path)
        change_row.addWidget(change_button)
        form.addRow("Datenbankpfad", change_row)

        self.backups_dir_label = QLabel(self)
        form.addRow("Backup-Ordner", self.backups_dir_label)

        self.version_label = QLabel(APP_VERSION, self)
        form.addRow("Version", self.version_label)

        layout.addLayout(form)

        units_row = QHBoxLayout()
        units_row.addWidget(QLabel("Einheiten-Pool", self))
        manage_units_button = QPushButton("Einheiten verwalten...", self)
        manage_units_button.clicked.connect(self._manage_units)
        units_row.addWidget(manage_units_button)
        units_row.addStretch(1)
        layout.addLayout(units_row)

        self.drive_warning_badge = StatusBadge("", "info", self)
        self.drive_warning_badge.setWordWrap(True)
        layout.addWidget(self.drive_warning_badge)
        layout.addStretch(1)

    def refresh(self) -> None:
        self.db_path_edit.setText(str(self.context.config.database_path))
        self.backups_dir_label.setText(str(self.context.config.project_root / "backups"))

        warning = get_drive_warning(self.context.config.database_path)
        if warning:
            self.drive_warning_badge.setText(warning)
            self.drive_warning_badge.set_level("kritisch")
            self.drive_warning_badge.show()
        else:
            self.drive_warning_badge.setText("Der Datenbankpfad liegt auf einem lokalen, sicheren Laufwerk.")
            self.drive_warning_badge.set_level("ok")
            self.drive_warning_badge.show()

    def _manage_units(self) -> None:
        dialog = UnitsManagementDialog(self.context, self)
        dialog.exec()

    def _change_database_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Neuen Datenbankpfad wählen",
            str(self.context.config.database_path),
            "SQLite-Datenbank (*.sqlite3)",
        )
        if not path:
            return

        settings_path = get_user_settings_path()
        settings_path.write_text(json.dumps({"database_path": path}, indent=2), encoding="utf-8")
        info_dialog(
            self,
            "Der neue Datenbankpfad wurde gespeichert. Bitte die Anwendung neu starten, "
            "damit die Änderung wirksam wird.",
        )
