from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.context import AppContext
from app.services import backup_service, export_service, import_service, recipe_service
from app.ui.dialogs import confirm_dialog, error_dialog, info_dialog
from app.ui.widgets import PageHeader


class ImportExportView(QWidget):
    """Excel-Import, Datenexport, Backup und Restore."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(PageHeader("Import/Export", "Excel-Import, Datenexport, Backup und Restore"))

        import_group = QGroupBox("Excel-Import", self)
        import_layout = QVBoxLayout(import_group)
        import_button = QPushButton("Excel-Datei importieren", import_group)
        import_button.clicked.connect(self._run_import)
        self.import_report_text = QPlainTextEdit(import_group)
        self.import_report_text.setReadOnly(True)
        self.import_report_text.setFixedHeight(140)
        import_layout.addWidget(import_button)
        import_layout.addWidget(self.import_report_text)
        layout.addWidget(import_group)

        export_group = QGroupBox("Export", self)
        export_layout = QHBoxLayout(export_group)
        export_recipes_button = QPushButton("Rezepte als CSV exportieren", export_group)
        export_recipes_button.clicked.connect(self._export_recipes)
        export_layout.addWidget(export_recipes_button)
        export_layout.addStretch(1)
        layout.addWidget(export_group)

        backup_group = QGroupBox("Backup und Restore", self)
        backup_layout = QVBoxLayout(backup_group)

        backup_row = QHBoxLayout()
        backup_button = QPushButton("Backup erstellen", backup_group)
        backup_button.clicked.connect(self._create_backup)
        integrity_button = QPushButton("Datenbank pruefen", backup_group)
        integrity_button.clicked.connect(self._check_integrity)
        backup_row.addWidget(backup_button)
        backup_row.addWidget(integrity_button)
        backup_row.addStretch(1)
        backup_layout.addLayout(backup_row)

        restore_row = QHBoxLayout()
        self.backup_combo = QComboBox(backup_group)
        restore_button = QPushButton("Aus Backup wiederherstellen", backup_group)
        restore_button.clicked.connect(self._restore_backup)
        restore_row.addWidget(self.backup_combo)
        restore_row.addWidget(restore_button)
        backup_layout.addLayout(restore_row)

        layout.addWidget(backup_group)
        layout.addStretch(1)

    def refresh(self) -> None:
        report = import_service.get_last_import_report(self.context.config)
        if report:
            self._render_report(report)
        self._reload_backup_combo()

    def _render_report(self, report: dict) -> None:
        lines = [f"Quelle: {report.get('source_file', '-')}", f"Import am: {report.get('generated_at', '-')}", ""]
        for key, value in report.get("counters", {}).items():
            lines.append(f"{key}: {value}")
        issues = report.get("issues", [])
        lines.append("")
        lines.append(f"Issues: {len(issues)}")
        self.import_report_text.setPlainText("\n".join(lines))

    def _reload_backup_combo(self) -> None:
        self.backup_combo.clear()
        for backup_path in backup_service.list_backups(self.context.config):
            self.backup_combo.addItem(backup_path.name, str(backup_path))

    def _run_import(self) -> None:
        if not confirm_dialog(
            self,
            "Excel importieren",
            "Der Import liest die Excel-Datei erneut ein und ergaenzt die Datenbank. "
            "Bestehende Daten werden dabei nicht ueberschrieben. Fortfahren?",
        ):
            return
        try:
            counters, issues, excel_path = import_service.run_excel_import(self.context.config)
        except FileNotFoundError as exc:
            error_dialog(self, str(exc))
            return
        lines = [f"Quelle: {excel_path}", ""]
        for key, value in vars(counters).items():
            lines.append(f"{key}: {value}")
        lines.append("")
        lines.append(f"Issues: {len(issues)}")
        self.import_report_text.setPlainText("\n".join(lines))
        info_dialog(self, "Import abgeschlossen. Details siehe Bericht.")

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
            error_dialog(self, "Es ist kein Backup ausgewaehlt.")
            return
        if not confirm_dialog(
            self,
            "Backup wiederherstellen",
            "Die aktuelle Datenbank wird durch das ausgewaehlte Backup ersetzt. "
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
        ok, result = backup_service.verify_integrity(self.context.engine)
        if ok:
            info_dialog(self, "Datenbankintegritaet: OK")
        else:
            error_dialog(self, f"Datenbankintegritaet fehlgeschlagen: {result}")
