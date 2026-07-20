from __future__ import annotations

import json

from PySide6.QtWidgets import QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from app.context import AppContext
from app.ui.dialogs import info_dialog
from app.ui.widgets import StatusBadge
from app.utils.drive_detection import get_drive_warning
from app.utils.paths import get_user_settings_path

APP_VERSION = "0.1.0 (Prototyp)"


class SettingsView(QWidget):
    """Einstellungen: Datenbankpfad, Laufwerkswarnung, Systeminfo."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.db_path_edit = QLineEdit(self)
        self.db_path_edit.setReadOnly(True)
        change_row = QHBoxLayout()
        change_row.addWidget(self.db_path_edit)
        change_button = QPushButton("Aendern...", self)
        change_button.clicked.connect(self._change_database_path)
        change_row.addWidget(change_button)
        form.addRow("Datenbankpfad", change_row)

        self.backups_dir_label = QLabel(self)
        form.addRow("Backup-Ordner", self.backups_dir_label)

        self.version_label = QLabel(APP_VERSION, self)
        form.addRow("Version", self.version_label)

        layout.addLayout(form)

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

    def _change_database_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Neuen Datenbankpfad waehlen",
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
            "damit die Aenderung wirksam wird.",
        )
