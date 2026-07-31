"""Entscheidet beim App-Start, welche Datenbank-Engine benutzt wird, wenn eine Cloud-Verbindung
konfiguriert ist: direkt die Cloud, oder - falls sie gerade nicht erreichbar ist bzw. noch
ungesyncte Offline-Aenderungen vorliegen - der lokale Offline-Cache (siehe sync_service).

Der rein lokale SQLite-Modus (keine Cloud konfiguriert) bleibt unveraendert in main.py, da er
keine dieser Entscheidungen braucht.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import AppConfig
from app.db import check_connectivity, create_engine_from_config
from app.services import sync_service
from app.utils.paths import get_offline_cache_path, get_offline_sync_state_path

# Toleranz zwischen dem Schreiben der Cache-Datei und dem Schreiben von last_synced_at bei
# refresh_local_cache_from_cloud() - beides passiert dort praktisch zeitgleich (derselbe
# Funktionsaufruf), eine echte spaetere Offline-Bearbeitung liegt real spuerbar dahinter.
_STALE_CACHE_TOLERANCE = timedelta(seconds=2)


class OfflineWithoutCacheError(Exception):
    """Cloud nicht erreichbar und es existiert noch keine lokale Offline-Kopie - kann nur
    behoben werden, indem die App einmal mit Internetverbindung gestartet wird."""


@dataclass(slots=True)
class DatabaseSelection:
    config: AppConfig
    target_description: str
    is_offline_mode: bool
    cloud_database_url: str | None


def _cache_has_pending_local_changes(cache_path: Path, sync_state_path: Path) -> bool:
    """Guenstige, rein lokale Naeherung ohne Netzwerkzugriff: wurde die Cache-Datei NACH dem
    letzten Sync/Priming noch einmal beschrieben? SQLite aktualisiert den Datei-Zeitstempel bei
    jedem Schreibzugriff. Vermeidet einen teuren Zeilen-fuer-Zeilen-Vergleich mit der Cloud bei
    jedem App-Start (siehe sync_service.analyze(), das bleibt der explizite "Jetzt
    synchronisieren"-Aktion in den Einstellungen vorbehalten)."""
    if not cache_path.exists():
        return False
    last_synced_at = sync_service.read_last_synced_at(sync_state_path)
    if last_synced_at is None:
        return True
    cache_modified_at = datetime.fromtimestamp(cache_path.stat().st_mtime, tz=timezone.utc)
    return cache_modified_at > last_synced_at + _STALE_CACHE_TOLERANCE


def resolve_cloud_or_offline_mode(project_root: Path, saved_url: str) -> DatabaseSelection:
    cloud_config = AppConfig.load(project_root=project_root, database_url=saved_url)
    cloud_engine = create_engine_from_config(cloud_config)
    cloud_reachable = check_connectivity(cloud_engine) == "ok"

    offline_cache_path = get_offline_cache_path()
    sync_state_path = get_offline_sync_state_path()

    if cloud_reachable:
        if _cache_has_pending_local_changes(offline_cache_path, sync_state_path):
            return DatabaseSelection(
                config=AppConfig.load(project_root=project_root, database_path=offline_cache_path),
                target_description="Offline-Modus (ungesyncte Änderungen vorhanden)",
                is_offline_mode=True,
                cloud_database_url=saved_url,
            )
        # Kein Hinweis auf lokale Aenderungen - der Cache ist bestenfalls ein veralteter
        # Spiegel, sicher loeschbar (kein offener Handle in diesem Prozess).
        offline_cache_path.unlink(missing_ok=True)
        sync_state_path.unlink(missing_ok=True)
        return DatabaseSelection(
            config=cloud_config,
            target_description="Cloud-Datenbank (Neon Postgres)",
            is_offline_mode=False,
            cloud_database_url=saved_url,
        )

    if offline_cache_path.exists():
        return DatabaseSelection(
            config=AppConfig.load(project_root=project_root, database_path=offline_cache_path),
            target_description="Offline-Modus (keine Internetverbindung)",
            is_offline_mode=True,
            cloud_database_url=saved_url,
        )

    raise OfflineWithoutCacheError(
        "Die Cloud-Datenbank ist nicht erreichbar und es liegt noch keine lokale Offline-Kopie "
        "vor. Bitte die Anwendung einmal mit Internetverbindung starten."
    )
