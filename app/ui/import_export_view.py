from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.context import AppContext
from app.services import backup_service, export_service, recipe_service
from app.ui.dialogs import confirm_dialog, error_dialog, info_dialog
from app.ui.widgets import PageHeader


class ImportExportView(QWidget):
    """Datenexport, Backup und Restore."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(PageHeader("Export & Backup", "Datenexport, Backup und Restore"))

        export_group = QGroupBox("Export", self)
        export_layout = QHBoxLayout(export_group)
        export_recipes_button = QPushButton("Rezepte als CSV exportieren", export_group)
        export_recipes_button.clicked.connect(self._export_recipes)
        export_layout.addWidget(export_recipes_button)
        export_layout.addStretch(1)
        layout.addWidget(export_group)

        backup_group = QGroupBox("Backup und Restore", self)
        backup_layout = QVBoxLayout(backup_group)

        self.cloud_mode_hint = QLabel(
            "Im Cloud-Datenbank-Modus (Neon Postgres) gibt es kein lokales Datei-Backup - "
            "Neon sichert automatisch (Point-in-Time-Restore ueber das Neon-Dashboard).",
            backup_group,
        )
        self.cloud_mode_hint.setWordWrap(True)
        self.cloud_mode_hint.hide()
        backup_layout.addWidget(self.cloud_mode_hint)

        backup_row = QHBoxLayout()
        self.backup_button = QPushButton("Backup erstellen", backup_group)
        self.backup_button.clicked.connect(self._create_backup)
        integrity_button = QPushButton("Datenbank prüfen", backup_group)
        integrity_button.clicked.connect(self._check_integrity)
        backup_row.addWidget(self.backup_button)
        backup_row.addWidget(integrity_button)
        backup_row.addStretch(1)
        backup_layout.addLayout(backup_row)

        restore_row = QHBoxLayout()
        self.backup_combo = QComboBox(backup_group)
        self.restore_button = QPushButton("Aus Backup wiederherstellen", backup_group)
        self.restore_button.clicked.connect(self._restore_backup)
        restore_row.addWidget(self.backup_combo)
        restore_row.addWidget(self.restore_button)
        backup_layout.addLayout(restore_row)

        layout.addWidget(backup_group)
        layout.addStretch(1)

    def refresh(self) -> None:
        is_sqlite = self.context.config.is_sqlite
        self.cloud_mode_hint.setVisible(not is_sqlite)
        self.backup_button.setEnabled(is_sqlite)
        self.backup_combo.setEnabled(is_sqlite)
        self.restore_button.setEnabled(is_sqlite)
        self._reload_backup_combo()

    def _reload_backup_combo(self) -> None:
        self.backup_combo.clear()
        for backup_path in backup_service.list_backups(self.context.config):
            self.backup_combo.addItem(backup_path.name, str(backup_path))

    def _export_recipes(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Rezepte exportieren", "rezepte.csv", "CSV-Dateien (*.csv)")
        if not path:
            return
        with self.context.session() as session:
            recipes = recipe_service.search_recipes(session, active_only=False)
            export_service.export_recipes_to_csv(recipes, Path(path))
        info_dialog(self, f"Rezepte exportiert nach:\n{path}")

    def _create_backup(self) -> None:
        try:
            backup_path = backup_service.create_backup(self.context.config)
        except FileNotFoundError as exc:
            error_dialog(self, str(exc))
            return
        info_dialog(self, f"Backup erstellt:\n{backup_path}")
        self._reload_backup_combo()

    def _restore_backup(self) -> None:
        backup_path_text = self.backup_combo.currentData()
        if not backup_path_text:
            error_dialog(self, "Es ist kein Backup ausgewählt.")
            return
        if not confirm_dialog(
            self,
            "Backup wiederherstellen",
            "Die aktuelle Datenbank wird durch das ausgewählte Backup ersetzt. "
            "Der aktuelle Stand wird vorher automatisch gesichert. Fortfahren?",
        ):
            return
        try:
            backup_service.restore_backup(self.context.config, Path(backup_path_text), confirm=True)
        except (FileNotFoundError, backup_service.RestoreNotConfirmedError) as exc:
            error_dialog(self, str(exc))
            return
        info_dialog(self, "Wiederherstellung abgeschlossen. Bitte die Anwendung neu starten.")
        self._reload_backup_combo()

    def _check_integrity(self) -> None:
        ok, result = backup_service.verify_integrity(self.context.engine, self.context.config)
        if ok:
            info_dialog(self, "Datenbankintegrität: OK")
        else:
            error_dialog(self, f"Datenbankintegrität fehlgeschlagen: {result}")
