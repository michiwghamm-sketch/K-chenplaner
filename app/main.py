from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from app.config import AppConfig  # noqa: E402
from app.context import AppContext  # noqa: E402
from app.db import initialize_database  # noqa: E402
from app.services.backup_service import verify_integrity  # noqa: E402
from app.ui.app import MainWindow  # noqa: E402
from app.utils.drive_detection import get_drive_warning  # noqa: E402
from app.utils.logging_config import get_logger, setup_logging  # noqa: E402
from app.utils.paths import get_logs_dir, get_user_settings_path  # noqa: E402


def load_saved_database_path() -> Path | None:
    settings_path = get_user_settings_path()
    if not settings_path.exists():
        return None
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    raw_path = data.get("database_path")
    return Path(raw_path) if raw_path else None


def save_database_path(path: Path) -> None:
    settings_path = get_user_settings_path()
    settings_path.write_text(json.dumps({"database_path": str(path)}, indent=2), encoding="utf-8")


def choose_database_path_first_run(default_path: Path) -> Path | None:
    """Fragt beim allerersten Start den Datenbankpfad ab. Gibt None zurueck, wenn der Nutzer abbricht."""
    QMessageBox.information(
        None,
        "Willkommen",
        "Beim ersten Start wird ein Speicherort fuer die Datenbank benoetigt.\n\n"
        f"Vorgeschlagener Standardpfad:\n{default_path}\n\n"
        "Im naechsten Dialog kann dieser Pfad uebernommen oder ein anderer Ort gewaehlt werden.",
    )
    path, _ = QFileDialog.getSaveFileName(
        None,
        "Datenbankpfad waehlen",
        str(default_path),
        "SQLite-Datenbank (*.sqlite3)",
    )
    if not path:
        return None

    resolved = Path(path)
    warning = get_drive_warning(resolved)
    if warning:
        result = QMessageBox.warning(
            None,
            "Warnung: Speicherort",
            f"{warning}\n\nTrotzdem an diesem Ort speichern?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return None
    return resolved


def main() -> int:
    app = QApplication(sys.argv)

    default_config = AppConfig.load(project_root=PROJECT_ROOT)
    setup_logging(get_logs_dir(PROJECT_ROOT))
    logger = get_logger("main")

    saved_path = load_saved_database_path()
    if saved_path is None:
        chosen_path = choose_database_path_first_run(default_config.database_path)
        if chosen_path is None:
            logger.info("Ersteinrichtung abgebrochen: kein Datenbankpfad gewaehlt.")
            return 0
        save_database_path(chosen_path)
        saved_path = chosen_path

    try:
        config = AppConfig.load(project_root=PROJECT_ROOT, database_path=saved_path)
        config, engine, session_factory = initialize_database(config)
    except Exception as exc:  # noqa: BLE001 - Nicht-Entwickler sollen eine verstaendliche Meldung sehen
        logger.exception("Datenbank konnte nicht initialisiert werden.")
        QMessageBox.critical(
            None,
            "Datenbankfehler",
            f"Die Datenbank unter\n{saved_path}\nkonnte nicht geoeffnet werden.\n\nDetails: {exc}",
        )
        return 1

    ok, integrity_result = verify_integrity(engine)
    if not ok:
        logger.error("Datenbankintegritaetspruefung fehlgeschlagen: %s", integrity_result)
        QMessageBox.warning(
            None,
            "Datenbankintegritaet",
            f"Die Integritaetspruefung der Datenbank meldet ein Problem:\n{integrity_result}\n\n"
            "Ein Restore aus einem Backup wird empfohlen (Import/Export > Wiederherstellen).",
        )

    context = AppContext(config=config, engine=engine, session_factory=session_factory)
    window = MainWindow(context)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
