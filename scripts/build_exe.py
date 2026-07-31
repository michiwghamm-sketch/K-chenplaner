"""Baut die Windows-Anwendung mit PyInstaller (onedir-Build unter dist/ZelaKueche/).

Aufruf:
    .venv\\Scripts\\python.exe scripts\\build_exe.py

Das Ergebnis liegt unter dist/ZelaKueche/ZelaKueche.exe und wird von
installer/zelakueche.iss zu einem Setup.exe verpackt.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENTRY_POINT = PROJECT_ROOT / "app" / "main.py"
ASSETS_DIR = PROJECT_ROOT / "app" / "assets"
ICON_PATH = ASSETS_DIR / "app_icon.ico"


def build() -> None:
    from PyInstaller.__main__ import run as pyinstaller_run

    add_data_separator = ";" if sys.platform.startswith("win") else ":"
    args = [
        str(ENTRY_POINT),
        "--name=ZelaKueche",
        "--windowed",
        "--onedir",
        "--noconfirm",
        f"--distpath={PROJECT_ROOT / 'dist'}",
        f"--workpath={PROJECT_ROOT / 'build'}",
        f"--specpath={PROJECT_ROOT}",
        f"--add-data={ASSETS_DIR}{add_data_separator}app/assets",
        f"--icon={ICON_PATH}",
    ]
    pyinstaller_run(args)


if __name__ == "__main__":
    build()
