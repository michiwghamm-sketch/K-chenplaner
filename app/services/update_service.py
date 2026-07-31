"""Prueft gegen die GitHub-Releases-API, ob eine neuere Version verfuegbar ist.

Bewusst kein Silent-Self-Update (Ersetzen der laufenden .exe): das ist fehleranfaellig und
bei einem Fehlschlag kann eine nicht-technische Person die App dann nicht mehr reparieren.
Stattdessen wird nur auf die neue Version hingewiesen, mit Link zur GitHub-Release-Seite.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

GITHUB_REPO = "michiwghamm-sketch/K-chenplaner"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
REQUEST_TIMEOUT_SECONDS = 5


@dataclass(slots=True)
class UpdateInfo:
    latest_version: str
    download_url: str


def _parse_version(version: str) -> tuple[int, ...]:
    cleaned = version.strip().lstrip("vV")
    parts = re.findall(r"\d+", cleaned)
    return tuple(int(part) for part in parts) or (0,)


def check_for_update(current_version: str) -> UpdateInfo | None:
    """Liefert UpdateInfo, wenn die neueste GitHub-Release neuer ist als `current_version`.

    Liefert None bei fehlendem Internet, fehlender Release oder gleicher/aelterer Version -
    ein fehlgeschlagener Check soll den App-Start nie blockieren oder abbrechen.
    """
    try:
        request = urllib.request.Request(
            RELEASES_API_URL,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "ZelaKueche-UpdateCheck"},
        )
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None

    latest_tag = data.get("tag_name")
    download_url = data.get("html_url")
    if not latest_tag or not download_url:
        return None

    if _parse_version(latest_tag) <= _parse_version(current_version):
        return None

    return UpdateInfo(latest_version=latest_tag, download_url=download_url)
