from __future__ import annotations

import ctypes
from pathlib import Path

SYNCED_DRIVE_MARKERS = (
    "onedrive",
    "dropbox",
    "google drive",
    "googledrive",
    "icloud",
    "icloud drive",
)

# Windows GetDriveTypeW: 4 = DRIVE_REMOTE (Netzlaufwerk)
DRIVE_REMOTE = 4


def _windows_drive_type(drive_root: str) -> int | None:
    try:
        return ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive_root))
    except (AttributeError, OSError):
        return None


def is_network_drive(path: Path) -> bool:
    if path.drive:
        drive_root = f"{path.drive}\\"
        drive_type = _windows_drive_type(drive_root)
        if drive_type == DRIVE_REMOTE:
            return True
    return str(path).startswith("\\\\")


def detect_synced_folder(path: Path) -> str | None:
    lowered = str(path).lower()
    for marker in SYNCED_DRIVE_MARKERS:
        if marker in lowered:
            return marker
    return None


def get_drive_warning(path: Path) -> str | None:
    """Liefert eine Warnmeldung, wenn der Pfad auf einem Cloud-Sync- oder Netzlaufwerk liegt."""
    resolved = path.resolve()
    synced_marker = detect_synced_folder(resolved)
    if synced_marker:
        return (
            f"Der Datenbankpfad liegt anscheinend in einem synchronisierten Cloud-Ordner "
            f"({synced_marker.title()}). Gleichzeitige Synchronisation kann die SQLite-Datei "
            "beschaedigen. Bitte einen lokalen, nicht synchronisierten Ordner verwenden oder "
            "vorsichtig sein, dass die App nicht auf zwei Geraeten gleichzeitig laeuft."
        )
    if is_network_drive(resolved):
        return (
            "Der Datenbankpfad liegt auf einem Netzlaufwerk. SQLite unterstuetzt keine "
            "zuverlaessige Mehrbenutzer-Gleichzeitigkeit ueber Netzlaufwerke. Bitte einen "
            "lokalen Pfad verwenden oder Datenverlust-Risiken bewusst in Kauf nehmen."
        )
    return None
