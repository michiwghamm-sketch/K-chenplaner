from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

APP_DIR_NAME = "ZelaKueche"
USER_SETTINGS_FILENAME = "settings.json"


def get_user_config_dir() -> Path:
    """Return the per-user config directory (Windows: %APPDATA%, sonst Home)."""
    appdata = os.getenv("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".config"
    config_dir = base / APP_DIR_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_user_settings_path() -> Path:
    return get_user_config_dir() / USER_SETTINGS_FILENAME


def get_backups_dir(project_root: Path) -> Path:
    backups_dir = project_root / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    return backups_dir


def get_logs_dir(project_root: Path) -> Path:
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_user_settings() -> dict[str, Any]:
    """Liest settings.json (Datenbankpfad/-URL etc.). Liefert {} wenn nicht vorhanden/kaputt."""
    settings_path = get_user_settings_path()
    if not settings_path.exists():
        return {}
    try:
        return json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_user_settings(updates: dict[str, Any]) -> None:
    """Merged `updates` in die bestehende settings.json, statt sie zu ueberschreiben - `database_path`
    und `database_url` sind unabhaengige Schluessel, die beide erhalten bleiben muessen."""
    settings = load_user_settings()
    settings.update(updates)
    get_user_settings_path().write_text(json.dumps(settings, indent=2), encoding="utf-8")


def clear_user_setting(key: str) -> None:
    settings = load_user_settings()
    if key in settings:
        del settings[key]
        get_user_settings_path().write_text(json.dumps(settings, indent=2), encoding="utf-8")


def get_offline_cache_path() -> Path:
    """Lokale Zwischenkopie der Cloud-Datenbank fuer den Offline-Modus (siehe sync_service) -
    lebt bewusst im Nutzerprofil statt im Installationsordner, damit sie auch bei einer
    Installation in einem schreibgeschuetzten Ordner funktioniert."""
    return get_user_config_dir() / "offline_cache.sqlite3"


def get_offline_sync_state_path() -> Path:
    return get_user_config_dir() / "offline_sync_state.json"


def get_assets_dir() -> Path:
    """Liefert app/assets - im PyInstaller-Bundle liegen die Daten unter sys._MEIPASS,
    nicht relativ zu __file__ (dort sind Module in ein Archiv gepackt, __file__ ist dann
    kein echter Dateisystempfad mehr)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "app" / "assets"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent / "assets"
