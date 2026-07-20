from __future__ import annotations

import os
from pathlib import Path

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
