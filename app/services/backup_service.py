from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import Engine

from app.config import AppConfig
from app.db import check_sqlite_integrity
from app.utils.paths import get_backups_dir

BACKUP_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


class RestoreNotConfirmedError(Exception):
    """Wird ausgeloest, wenn ein Restore ohne explizite Bestaetigung angefragt wird."""


def create_backup(config: AppConfig) -> Path:
    """Kopiert die aktuelle SQLite-Datenbank in einen zeitgestempelten Backup-Ordner."""
    if not config.database_path.exists():
        raise FileNotFoundError(f"Keine Datenbank unter '{config.database_path}' gefunden.")

    backups_dir = get_backups_dir(config.project_root)
    timestamp = datetime.now().strftime(BACKUP_TIMESTAMP_FORMAT)
    base_name = f"{config.database_path.stem}_{timestamp}"
    backup_path = backups_dir / f"{base_name}{config.database_path.suffix}"
    # Zwei Backups innerhalb derselben Sekunde duerfen sich niemals gegenseitig ueberschreiben.
    suffix_counter = 1
    while backup_path.exists():
        backup_path = backups_dir / f"{base_name}_{suffix_counter}{config.database_path.suffix}"
        suffix_counter += 1
    shutil.copy2(config.database_path, backup_path)
    return backup_path


def list_backups(config: AppConfig) -> list[Path]:
    backups_dir = get_backups_dir(config.project_root)
    return sorted(backups_dir.glob(f"{config.database_path.stem}_*{config.database_path.suffix}"), reverse=True)


def restore_backup(config: AppConfig, backup_path: Path, *, confirm: bool) -> None:
    """Stellt eine Datenbank aus einem Backup wieder her. Erfordert explizite Bestaetigung durch den Aufrufer (UI-Dialog)."""
    if not confirm:
        raise RestoreNotConfirmedError("Restore muss explizit bestätigt werden.")
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup-Datei '{backup_path}' existiert nicht.")

    # Sicherheitsnetz: aktuellen Stand vor dem Ueberschreiben ebenfalls sichern.
    if config.database_path.exists():
        create_backup(config)

    shutil.copy2(backup_path, config.database_path)


def verify_integrity(engine: Engine) -> tuple[bool, str]:
    result = check_sqlite_integrity(engine)
    return result == "ok", result
