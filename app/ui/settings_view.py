from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
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

from app import __version__
from app.config import AppConfig
from app.context import AppContext
from app.db import check_connectivity, create_engine_from_config
from app.models import Unit
from app.services import sync_service, unit_service
from app.services.update_service import UpdateInfo
from app.ui.dialogs import SyncConflictDialog, confirm_dialog, error_dialog, info_dialog, prompt_text
from app.ui.update_check import run_update_check_async
from app.ui.widgets import PageHeader, StatusBadge
from app.utils.drive_detection import get_drive_warning
from app.utils.paths import clear_user_setting, get_offline_sync_state_path, save_user_settings

APP_VERSION = __version__


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
        delete_button.setProperty("role", "danger")
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
        self.db_mode_label = QLabel(self)
        form.addRow("Datenbank-Modus", self.db_mode_label)

        self.db_path_edit = QLineEdit(self)
        self.db_path_edit.setReadOnly(True)
        change_row = QHBoxLayout()
        change_row.addWidget(self.db_path_edit)
        self.change_path_button = QPushButton("Ändern...", self)
        self.change_path_button.clicked.connect(self._change_database_path)
        change_row.addWidget(self.change_path_button)
        form.addRow("Datenbankpfad", change_row)

        self.backups_dir_label = QLabel(self)
        form.addRow("Backup-Ordner", self.backups_dir_label)

        version_row = QHBoxLayout()
        self.version_label = QLabel(APP_VERSION, self)
        version_row.addWidget(self.version_label)
        self.check_update_button = QPushButton("Nach Updates suchen", self)
        self.check_update_button.clicked.connect(self._check_for_update)
        version_row.addWidget(self.check_update_button)
        version_row.addStretch(1)
        form.addRow("Version", version_row)

        layout.addLayout(form)

        cloud_row = QHBoxLayout()
        self.connect_cloud_button = QPushButton("Mit Cloud-Datenbank verbinden...", self)
        self.connect_cloud_button.clicked.connect(self._connect_cloud_database)
        self.disconnect_cloud_button = QPushButton("Zurück zu lokaler Datenbank", self)
        self.disconnect_cloud_button.clicked.connect(self._disconnect_cloud_database)
        self.sync_button = QPushButton("Jetzt synchronisieren", self)
        self.sync_button.clicked.connect(self._sync_now)
        cloud_row.addWidget(self.connect_cloud_button)
        cloud_row.addWidget(self.disconnect_cloud_button)
        cloud_row.addWidget(self.sync_button)
        cloud_row.addStretch(1)
        layout.addLayout(cloud_row)

        self.offline_hint = QLabel(
            "Offline-Modus: die Cloud-Datenbank war beim Start nicht erreichbar oder es liegen "
            "noch ungesyncte Änderungen vor. Mit Internetverbindung auf \"Jetzt synchronisieren\" "
            "klicken, um deine Änderungen mit dem Team zu teilen.",
            self,
        )
        self.offline_hint.setWordWrap(True)
        self.offline_hint.hide()
        layout.addWidget(self.offline_hint)

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
        config = self.context.config
        is_sqlite = config.is_sqlite
        is_offline = self.context.is_offline_mode

        if is_offline:
            self.db_mode_label.setText("Offline (ungesynct)")
        else:
            self.db_mode_label.setText("Lokal (SQLite)" if is_sqlite else "Cloud (Neon Postgres)")
        self.db_path_edit.setText(str(config.database_path) if is_sqlite else "- (Cloud-Datenbank) -")
        self.change_path_button.setEnabled(is_sqlite and not is_offline)
        self.connect_cloud_button.setEnabled(is_sqlite and not is_offline)
        self.disconnect_cloud_button.setEnabled(not is_sqlite or is_offline)
        self.sync_button.setVisible(is_offline)
        self.offline_hint.setVisible(is_offline)
        self.backups_dir_label.setText(str(config.project_root / "backups"))

        if is_offline:
            self.drive_warning_badge.hide()
            return

        if not is_sqlite:
            self.drive_warning_badge.setText(
                "Cloud-Datenbank aktiv - lokale Backup-/Laufwerkspruefungen gelten hier nicht "
                "(siehe Export & Backup)."
            )
            self.drive_warning_badge.set_level("info")
            self.drive_warning_badge.show()
            return

        warning = get_drive_warning(config.database_path)
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

        save_user_settings({"database_path": path})
        info_dialog(
            self,
            "Der neue Datenbankpfad wurde gespeichert. Bitte die Anwendung neu starten, "
            "damit die Änderung wirksam wird.",
        )

    def _connect_cloud_database(self) -> None:
        connection_string = prompt_text(
            self,
            "Mit Cloud-Datenbank verbinden",
            "Connection-String der Cloud-Datenbank (z. B. von neon.tech, beginnt mit "
            "'postgresql://'). Wie ein Passwort behandeln - nicht weitergeben außer an "
            "vertraute Team-Mitglieder:",
        )
        if not connection_string:
            return
        if not (connection_string.startswith("postgresql://") or connection_string.startswith("postgres://")):
            error_dialog(self, "Der Connection-String muss mit 'postgresql://' beginnen.")
            return

        # Nur das Praefix zu pruefen sagt nichts darueber aus, ob die Verbindung tatsaechlich
        # funktioniert (Tippfehler im Host/Passwort, falscher Datenbankname, Firewall, ...) -
        # ohne echten Verbindungstest faellt das fuer technische Laien erst nach dem Neustart
        # auf, wenn die App unerklaert im Offline-Modus landet. Gleiches Muster wie _sync_now().
        self.connect_cloud_button.setEnabled(False)
        self.connect_cloud_button.setText("Verbindung wird geprüft...")
        try:
            test_config = AppConfig.load(project_root=self.context.config.project_root, database_url=connection_string)
            test_engine = create_engine_from_config(test_config)
            status = check_connectivity(test_engine)
        finally:
            self.connect_cloud_button.setEnabled(True)
            self.connect_cloud_button.setText("Mit Cloud-Datenbank verbinden...")

        if status != "ok":
            error_dialog(
                self,
                "Die Cloud-Datenbank ist mit diesem Connection-String nicht erreichbar "
                f"(Status: {status}). Bitte String, Netzwerk und Firewall prüfen - "
                "gespeichert wird nichts.",
            )
            return

        save_user_settings({"database_url": connection_string})
        info_dialog(
            self,
            "Verbindung erfolgreich getestet und gespeichert. Bitte die Anwendung neu starten, "
            "damit die Änderung wirksam wird.",
        )

    def _disconnect_cloud_database(self) -> None:
        if not confirm_dialog(
            self,
            "Zurück zu lokaler Datenbank",
            "Die App verwendet nach dem Neustart wieder die zuletzt genutzte lokale "
            "SQLite-Datei statt der Cloud-Datenbank. Fortfahren?",
        ):
            return
        clear_user_setting("database_url")
        info_dialog(self, "Cloud-Verbindung entfernt. Bitte die Anwendung neu starten.")

    def _sync_now(self) -> None:
        cloud_url = self.context.cloud_database_url
        if not cloud_url:
            return

        self.sync_button.setEnabled(False)
        self.sync_button.setText("Synchronisiere...")
        try:
            cloud_config = AppConfig.load(project_root=self.context.config.project_root, database_url=cloud_url)
            cloud_engine = create_engine_from_config(cloud_config)
            if check_connectivity(cloud_engine) != "ok":
                error_dialog(self, "Die Cloud-Datenbank ist weiterhin nicht erreichbar. Bitte später erneut versuchen.")
                return

            sync_state_path = get_offline_sync_state_path()
            last_synced_at = sync_service.read_last_synced_at(sync_state_path)
            plan = sync_service.analyze(self.context.engine, cloud_engine, last_synced_at)

            resolutions: dict = {}
            if plan.conflicts:
                dialog = SyncConflictDialog(plan.conflicts, self)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    info_dialog(self, "Sync abgebrochen - es wurde nichts verändert.")
                    return
                resolutions = dialog.resolutions()

            report = sync_service.apply(self.context.engine, cloud_engine, plan, resolutions, sync_state_path)
            conflict_text = (
                f" ({report.conflicts_resolved_local} Konflikt(e) zu deinen Gunsten, "
                f"{report.conflicts_resolved_cloud} zugunsten der Cloud entschieden)"
                if plan.conflicts
                else ""
            )
            info_dialog(
                self,
                f"Sync abgeschlossen: {report.pushed_rows} Zeile(n) hochgeladen{conflict_text}.\n\n"
                "Bitte die Anwendung neu starten, um live mit der Cloud weiterzuarbeiten.",
            )
        finally:
            self.sync_button.setEnabled(True)
            self.sync_button.setText("Jetzt synchronisieren")

    def _check_for_update(self) -> None:
        self.check_update_button.setEnabled(False)
        self.check_update_button.setText("Suche läuft...")
        run_update_check_async(self, self._on_update_check_result)

    def _on_update_check_result(self, update_info: UpdateInfo | None) -> None:
        self.check_update_button.setEnabled(True)
        self.check_update_button.setText("Nach Updates suchen")
        if update_info is None:
            info_dialog(self, f"Du hast bereits die neueste Version ({APP_VERSION}).")
            return
        if confirm_dialog(
            self,
            "Update verfügbar",
            f"Eine neuere Version ist verfügbar: {update_info.latest_version}\n\n"
            "Jetzt die Release-Seite zum Herunterladen öffnen?",
        ):
            QDesktopServices.openUrl(QUrl(update_info.download_url))
